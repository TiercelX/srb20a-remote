import unittest
import copy
from types import SimpleNamespace
from unittest.mock import patch

import soundbar_control as ctl
from test_soundbar_status import packet, services
from soundbar_status import IDENTITY_QUERY, STATUS_QUERY


class ControlTests(unittest.IsolatedAsyncioTestCase):
    async def test_round_trip_restores_after_rejected_change(self):
        baseline = {"volume_raw": 20, "raw_hex": "original"}
        class Session:
            async def set_verified(self, data, field, expected):
                if expected == 19:
                    raise RuntimeError("No confirmation")
                return dict(baseline)
        result = {}
        with self.assertRaisesRegex(RuntimeError, "No confirmation"):
            await ctl.round_trip(Session(), result, "volume", "19", "20", baseline)
        test = result["control_tests"][0]
        self.assertFalse(test["change_verified"])
        self.assertTrue(test["restored"])
        self.assertTrue(test["full_status_restored"])

    async def test_suite_restores_every_field_and_never_tests_input_or_power(self):
        from soundbar_status import decode_status
        baseline = decode_status(packet([5, 0, 1, 7, 0, 20, 8, 32, 32, 0, 1, 10, 36, 2]))
        state = copy.deepcopy(baseline)
        calls = []
        class Session:
            async def status(self):
                return dict(state)
            async def set_verified(self, data, field, expected):
                calls.append((field, expected))
                state[field] = expected
                # Synthetic fixture marker models complete status equality.
                state["raw_hex"] = "original" if all(
                    state[k] == v for k, v in baseline.items() if k != "raw_hex") else "changed"
                return dict(state)
        baseline["raw_hex"] = state["raw_hex"] = "original"
        result = {"before": baseline}
        await ctl.test_controls(Session(), result)
        self.assertTrue(result["all_tests_restored"])
        self.assertTrue(result["final_state_matches_initial"])
        self.assertEqual(calls[:2], [("volume_raw", 19), ("volume_raw", 20)])
        self.assertEqual(len(result["control_tests"]), 5)
        self.assertFalse(any(field in ("power", "input_code") for field, _ in calls))

    def test_reject_invalid_commands_before_transport(self):
        for command, value in (("volume", "-1"), ("volume", "51"),
                               ("volume", "bad"), ("mute", None),
                               ("input", "analog"), ("raw", "ffff")):
            with self.subTest(command=command, value=value), self.assertRaises(ValueError):
                ctl.command_spec(command, value)
        self.assertEqual(ctl.command_spec("volume", "20")[0], bytes.fromhex("ccaa024114a9"))

    async def exercise(self, model=35, fail_change=False):
        class FakeClient:
            def __init__(self):
                self.services = services()
                self.dimmer = 2
                self.writes = []

            async def start_notify(self, _notify, callback):
                self.callback = callback

            async def stop_notify(self, _notify):
                pass

            async def write_gatt_char(self, _writer, data, response):
                self.writes.append(data)
                if data == IDENTITY_QUERY:
                    reply = packet([4, 0, 1, 0, model, 1, 0, 0])
                elif data == STATUS_QUERY:
                    reply = packet([5, 0, 1, 7, 0, 20, 8, 32, 32, 0, 1, 10, 36, self.dimmer])
                else:
                    if not fail_change or data[4] == 2:
                        self.dimmer = data[4]
                    return
                self.callback(None, reply)

        client = FakeClient()
        result = {"frames": [], "writes": [], "setter_attempted": False}
        args = SimpleNamespace(command="test-dimmer", value=None)

        async def no_delay(_):
            pass

        with patch.object(ctl.asyncio, "sleep", no_delay):
            try:
                await ctl.operate(client, args, result)
            except RuntimeError:
                return client, result, True
        return client, result, False

    async def test_change_confirmed_and_original_restored(self):
        client, result, failed = await self.exercise()
        self.assertFalse(failed)
        self.assertTrue(result["change_verified"])
        self.assertTrue(result["restored"])
        self.assertEqual(client.dimmer, 2)

    async def test_wrong_model_never_receives_setter(self):
        client, result, failed = await self.exercise(model=37)
        self.assertTrue(failed)
        self.assertEqual(client.writes, [IDENTITY_QUERY])
        self.assertFalse(result["setter_attempted"])

    async def test_no_false_success_and_restore_on_verification_failure(self):
        client, result, failed = await self.exercise(fail_change=True)
        self.assertTrue(failed)
        self.assertNotIn("change_verified", result)
        self.assertTrue(result["restored"])
        self.assertEqual(client.dimmer, 2)


if __name__ == "__main__":
    unittest.main()
