import asyncio
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import gateway_server as gw


class GatewayTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.base = Path(self.temporary.name)
        self.patch = patch.object(gw, "BASE", self.base)
        self.patch.start()
        self.calls = 0
        self.active = 0
        self.maximum_active = 0
        async def run(args):
            self.calls += 1
            self.active += 1
            self.maximum_active = max(self.maximum_active, self.active)
            await asyncio.sleep(0.01)
            self.active -= 1
            return {"ok": True, "command": args.command}
        self.runner = run
        self.gateway = gw.Gateway(self.base / "evidence", run)

    async def asyncTearDown(self):
        self.patch.stop()
        self.temporary.cleanup()

    def request(self, identifier, **extra):
        return {"command": "status", "request_id": identifier, **extra}

    async def test_requests_are_serialized_and_results_are_saved(self):
        results = await asyncio.gather(self.gateway.handle(self.request("one")),
                                       self.gateway.handle(self.request("two")))
        self.assertTrue(all(item["ok"] for item in results))
        self.assertEqual(self.maximum_active, 1)
        self.assertEqual(self.calls, 2)
        self.assertTrue(json.loads((self.base / "evidence/one.json").read_text())["complete"])

    async def test_request_replay_survives_gateway_restart_and_never_sends_twice(self):
        request = self.request("once", command="volume", value=20)
        first = await self.gateway.handle(request)
        replacement = gw.Gateway(self.base / "evidence", self.runner)
        second = await replacement.handle(request)
        self.assertFalse(first["gateway"]["replayed"])
        self.assertTrue(second["gateway"]["replayed"])
        self.assertEqual(self.calls, 1)
        conflict = await replacement.handle(self.request("once", command="volume", value=21))
        self.assertEqual(conflict["error"]["code"], "request_id_conflict")
        self.assertEqual(self.calls, 1)

    async def test_incomplete_request_is_not_reexecuted(self):
        request = gw.validate(self.request("interrupted", command="mute", value="on"))
        (self.base / "evidence/interrupted.json").write_text(json.dumps({"request": request, "complete": False}))
        result = await self.gateway.handle(request)
        self.assertEqual(result["error"]["code"], "request_incomplete")
        self.assertEqual(self.calls, 0)

    async def test_invalid_device_path_boolean_and_address_are_rejected(self):
        for extra in ({"device": "mesh"}, {"request_id": "../../escape"},
                      {"command": "volume", "value": True}, {"address": "other"},
                      {"command": "power", "value": "on; echo x"}):
            result = await self.gateway.handle(self.request("invalid", **extra))
            self.assertEqual(result["error"]["code"], "invalid_request")
        self.assertEqual(self.calls, 0)

    async def test_external_cli_lock_prevents_gateway_ble_operation(self):
        with (self.base / ".ble.lock").open("a") as lock:
            gw.fcntl.flock(lock, gw.fcntl.LOCK_EX | gw.fcntl.LOCK_NB)
            result = await self.gateway.handle(self.request("busy"))
        self.assertEqual(result["error"]["code"], "busy")
        self.assertEqual(self.calls, 0)

    async def test_full_queue_rejects_another_request_without_running_it(self):
        started, release = asyncio.Event(), asyncio.Event()
        calls = []
        async def waiting(args):
            calls.append(args.command)
            started.set()
            await release.wait()
            return {"ok": True}
        gateway = gw.Gateway(self.base / "bounded", waiting)
        first = asyncio.create_task(gateway.handle(self.request("first")))
        await started.wait()
        second = asyncio.create_task(gateway.handle(self.request("second")))
        await asyncio.sleep(0)
        rejected = await gateway.handle(self.request("third"))
        self.assertEqual(rejected["error"]["code"], "busy")
        release.set()
        await asyncio.gather(first, second)
        self.assertEqual(len(calls), 2)


if __name__ == "__main__":
    unittest.main()
