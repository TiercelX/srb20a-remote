import asyncio
import sys
from types import SimpleNamespace
import unittest
from unittest.mock import patch

import soundbar_status as sb


def packet(payload):
    body = bytes([len(payload)]) + bytes(payload)
    return b"\xcc\xaa" + body + bytes([-sum(body) & 255])


# Synthetic protocol fixture, NOT a capture from a real SR-B20A.
STATUS = packet([5, 0, 1, 7, 0, 20, 8, 32, 32, 0, 1, 10, 36, 1])


class ProtocolTests(unittest.TestCase):
    def test_decode_synthetic_known_status(self):
        state = sb.decode_status(STATUS)
        self.assertTrue(state["power"])
        self.assertEqual(state["input"], "tv")
        self.assertFalse(state["mute"])
        self.assertEqual(state["volume_raw"], 20)
        self.assertEqual(state["subwoofer_raw"], 8)
        self.assertTrue(state["surround_bit"])
        self.assertIsNone(state["sound_mode"])
        self.assertEqual(state["sound_mode_reference"], "standard")
        self.assertTrue(state["clear_voice_bit"])
        self.assertTrue(state["bass_extension_bit"])
        self.assertEqual(state["dimmer"], "dim")

    def test_invalid_and_nonstatus_packets_rejected(self):
        for value in (b"", b"bad", STATUS[:-1], STATUS + b"\x00",
                      STATUS[:-1] + bytes([STATUS[-1] ^ 1]),
                      packet([16, 17]), packet([6] + [0] * 13)):
            with self.subTest(value=value), self.assertRaises(ValueError):
                sb.decode_status(value)

    def test_unknown_enums_preserve_values_without_inventing_names(self):
        payload = list(STATUS[3:-1])
        payload[3], payload[11], payload[13] = 255, 254, 3
        state = sb.decode_status(packet(payload))
        self.assertIsNone(state["input"])
        self.assertIsNone(state["sound_mode"])
        self.assertIsNone(state["dimmer"])
        self.assertEqual(state["input_code"], 255)

    def test_all_fragment_boundaries_and_multiple_frames(self):
        for split in range(len(STATUS) + 1):
            buffer = sb.FrameBuffer()
            self.assertEqual(buffer.feed(STATUS[:split]) + buffer.feed(STATUS[split:]),
                             [STATUS])
        buffer = sb.FrameBuffer()
        self.assertEqual(buffer.feed(b"noise" + STATUS + STATUS), [STATUS, STATUS])

    def test_corruption_resync_and_bounded_garbage(self):
        buffer = sb.FrameBuffer()
        damaged = STATUS[:-1] + bytes([STATUS[-1] ^ 1])
        self.assertEqual(buffer.feed(damaged + STATUS), [STATUS])
        buffer.feed(b"x" * 10000)
        self.assertLessEqual(len(buffer.buffer), 1)


def services(extra_writer=False):
    notify = SimpleNamespace(uuid=sb.NOTIFY_UUID, service_uuid=sb.SERVICE_UUID,
                             properties=["notify"], handle=8)
    writer = SimpleNamespace(uuid=sb.WRITE_UUID, service_uuid=sb.SERVICE_UUID,
                             properties=["write"], handle=6)
    chars = [notify, writer] + ([writer] if extra_writer else [])
    return [SimpleNamespace(uuid=sb.SERVICE_UUID, characteristics=chars)]


class TransportTests(unittest.IsolatedAsyncioTestCase):
    async def test_three_fresh_queries_only_and_disconnect(self):
        class FakeClient:
            def __init__(self, *args, **kwargs):
                self.services = services()
                self.writes = []
                self.is_connected = True
                self.stopped = False

            async def __aenter__(self):
                return self

            async def __aexit__(self, *args):
                self.is_connected = False

            async def start_notify(self, _char, callback):
                self.callback = callback

            async def stop_notify(self, _char):
                self.stopped = True

            async def write_gatt_char(self, _char, data, response):
                self.writes.append(data)
                response_frame = (packet([4, 0, 1, 0, 35, 1, 0, 0])
                                  if data == sb.IDENTITY_QUERY else STATUS)
                self.callback(None, response_frame[:7])
                self.callback(None, response_frame[7:])

        client = FakeClient()
        result = {"queries_sent": 0, "samples": [], "frames": []}
        args = SimpleNamespace(connect_timeout=1, samples=3, response_timeout=1,
                               interval=0, identify=True)
        with patch.dict(sys.modules, {"bleak": SimpleNamespace(BleakClient=lambda *a, **k: client)}):
            await sb.query(object(), args, result)
        self.assertEqual(client.writes, [sb.IDENTITY_QUERY] + [bytes.fromhex("ccaa020305f6")] * 3)
        self.assertEqual(result["identity"]["model"], "SR-B20A")
        self.assertEqual(len(result["samples"]), 3)
        self.assertTrue(client.stopped)
        self.assertFalse(client.is_connected)

    async def test_no_target_never_connects_or_returns_cached_success(self):
        async def empty(_seconds):
            return []
        args = SimpleNamespace(command="status", scan_seconds=1, address=None,
                               attempts=1, retry_delay=0)
        with patch.object(sb, "discover", empty):
            result = await sb.run(args)
        self.assertFalse(result["ok"])
        self.assertFalse(result["connected"])
        self.assertEqual(result["queries_sent"], 0)
        self.assertEqual(result["samples"], [])

    async def test_bounded_retry_records_failures_and_does_not_reuse_old_samples(self):
        args = SimpleNamespace(command="status", attempts=3, retry_delay=0)
        outputs = [
            {"ok": False, "started_at": "1", "finished_at": "2",
             "queries_sent": 0, "samples": [], "error": {"message": "scan failed"}},
            {"ok": True, "started_at": "3", "finished_at": "4",
             "queries_sent": 1, "samples": [{"fresh": True}]}]

        async def once(_args):
            return outputs.pop(0)

        with patch.object(sb, "run_once", once):
            result = await sb.run(args)
        self.assertTrue(result["ok"])
        self.assertEqual(result["samples"], [{"fresh": True}])
        self.assertEqual([h["ok"] for h in result["attempt_history"]], [False, True])

    async def test_all_retries_exhausted_is_failure(self):
        async def empty(_seconds):
            return []
        args = SimpleNamespace(command="status", scan_seconds=1, address=None,
                               attempts=2, retry_delay=0)
        with patch.object(sb, "discover", empty):
            result = await sb.run(args)
        self.assertFalse(result["ok"])
        self.assertEqual(len(result["attempt_history"]), 2)
        self.assertEqual(result["samples"], [])

    def test_unknown_or_ambiguous_gatt_refused(self):
        for value in ([], services(extra_writer=True)):
            with self.assertRaises(RuntimeError):
                sb.select_channels(value)


if __name__ == "__main__":
    unittest.main()
