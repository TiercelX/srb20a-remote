"""SR-B20A BLE control with model checks and fresh status verification.

Command payloads: Sound Bar Remote 2.40, jc/d.java and ec/a2.java.
Uses the existing AGPL status/framing implementation. No audio streaming.
"""
import argparse
import asyncio
import json
from pathlib import Path
import sys

from soundbar_status import (FrameBuffer, IDENTITY_QUERY, STATUS_QUERY,
                             decode_status, describe, now, select_channels)

from srb20a_config import get_address
try:
    ADDRESS = get_address()
except ValueError:
    ADDRESS = None
COMMANDS = {
    "power": {"on": ("40787e", "power", True), "off": ("40787f", "power", False)},
    "mute": {"on": ("407ea2", "mute", True), "off": ("407ea3", "mute", False)},
    "input": {"tv": ("4078df", "input_code", 7),
              "optical": ("407849", "input_code", 10),
              "bluetooth": ("407829", "input_code", 5)},
    "clear-voice": {"on": ("407e80", "clear_voice_bit", True),
                    "off": ("407e82", "clear_voice_bit", False)},
    "bass-extension": {"on": ("40786e", "bass_extension_bit", True),
                       "off": ("40786f", "bass_extension_bit", False)},
    "dimmer": {"bright": ("5100", "dimmer_code", 0),
               "dim": ("5101", "dimmer_code", 1), "off": ("5102", "dimmer_code", 2)},
}


def packet(payload):
    body = bytes([len(payload)]) + payload
    return b"\xcc\xaa" + body + bytes([-sum(body) & 255])


def command_spec(command, value):
    if command == "volume":
        try:
            number = int(value)
        except (TypeError, ValueError):
            raise ValueError("Volume must be an integer from 0 to 50") from None
        if not 0 <= number <= 50:
            raise ValueError("Volume must be from 0 to 50 (raw units, not percent)")
        return packet(bytes([0x41, number])), "volume_raw", number
    try:
        payload, field, expected = COMMANDS[command][value]
    except KeyError:
        raise ValueError(f"Unsupported command/value: {command} {value}") from None
    return packet(bytes.fromhex(payload)), field, expected


class Session:
    def __init__(self, client, result):
        self.client, self.result = client, result
        self.queue = asyncio.Queue(maxsize=64)
        self.buffer = FrameBuffer()
        self.notify, self.writer = select_channels(client.services)

    def received(self, _sender, data):
        for frame in self.buffer.feed(data):
            if not self.queue.full():
                self.queue.put_nowait((now(), frame))

    async def send(self, data):
        self.result["writes"].append({"at": now(), "hex": data.hex()})
        await self.client.write_gatt_char(
            self.writer, data, response="write" in self.writer.properties)

    async def request(self, data, predicate):
        while not self.queue.empty():
            self.queue.get_nowait()
        await self.send(data)
        async with asyncio.timeout(8):
            while True:
                at, frame = await self.queue.get()
                self.result["frames"].append({"at": at, "hex": frame.hex()})
                if predicate(frame):
                    return frame

    async def identify(self):
        frame = await self.request(IDENTITY_QUERY,
                                   lambda f: len(f) >= 12 and f[3:5] == b"\x04\x00")
        if frame[7] != 0x23:
            raise RuntimeError(f"Refusing control of model code {frame[7]}")
        self.result["model"] = "SR-B20A"

    async def status(self):
        frame = await self.request(STATUS_QUERY,
                                   lambda f: len(f) == 18 and f[3:5] == b"\x05\x00")
        return decode_status(frame)

    async def set_verified(self, data, field, expected):
        # Mark uncertainty BEFORE transmission; never replay a setter on reconnect.
        self.result["setter_attempted"] = True
        await self.send(data)
        for _ in range(3):
            await asyncio.sleep(0.35)
            state = await self.status()
            self.result["after"] = state
            if state[field] == expected:
                return state
        raise RuntimeError(f"Fresh status did not confirm {field}={expected!r}")


async def round_trip(session, result, command, target, original, baseline):
    data, field, expected = command_spec(command, target)
    restore_data, _, restore_expected = command_spec(command, original)
    record = {"command": command, "field": field, "before": baseline[field],
              "target": expected, "change_verified": False, "restored": False}
    result.setdefault("control_tests", []).append(record)
    try:
        record["changed_state"] = await session.set_verified(data, field, expected)
        record["change_verified"] = True
    finally:
        record["restore_attempted"] = True
        restored = await session.set_verified(restore_data, field, restore_expected)
        record["restored_state"] = restored
        record["restored"] = restored[field] == restore_expected
        record["full_status_restored"] = restored["raw_hex"] == baseline["raw_hex"]
    if not record["full_status_restored"]:
        raise RuntimeError("Another status field changed during test; suite stopped")


async def test_controls(session, result):
    baseline = result["before"]
    if not baseline["power"]:
        raise RuntimeError("Control tests require the soundbar to be on; no setter sent")
    volume = baseline["volume_raw"]
    dimmer = baseline["dimmer"]
    if not 0 <= volume <= 50 or dimmer not in COMMANDS["dimmer"]:
        raise RuntimeError("Unknown original value; cannot safely restore")
    plan = []
    if volume:
        plan.append(("volume", str(volume - 1), str(volume)))
    else:
        result["volume_test_skipped"] = "Already at zero; test never raises volume above original"
    for command, field in (("mute", "mute"), ("clear-voice", "clear_voice_bit"),
                           ("bass-extension", "bass_extension_bit")):
        original = "on" if baseline[field] else "off"
        plan.append((command, "off" if baseline[field] else "on", original))
    plan.append(("dimmer", "dim" if dimmer != "dim" else "bright", dimmer))
    try:
        for command, target, original in plan:
            current = await session.status()
            if current["raw_hex"] != baseline["raw_hex"]:
                raise RuntimeError("State changed outside the suite; no further test sent")
            await round_trip(session, result, command, target, original, current)
    finally:
        tests = result.get("control_tests", [])
        result["all_tests_restored"] = bool(tests) and all(
            test["restored"] and test.get("full_status_restored", False) for test in tests)
    result["after"] = await session.status()
    result["final_state_matches_initial"] = result["after"]["raw_hex"] == baseline["raw_hex"]
    if not result["final_state_matches_initial"]:
        raise RuntimeError("Final state differs from initial status")


async def operate(client, args, result):
    session = Session(client, result)
    await client.start_notify(session.notify, session.received)
    try:
        await session.identify()
        result["before"] = await session.status()
        if args.command == "status":
            return
        if args.command == "test-controls":
            await test_controls(session, result)
            return
        if args.command == "test-dimmer":
            # A visible, reversible control test; restore even if verification fails.
            original = result["before"]["dimmer_code"]
            if original not in (0, 1, 2):
                raise RuntimeError("Unknown dimmer state; no change made")
            target = 1 if original != 1 else 0
            result["test_target"] = target
            try:
                await session.set_verified(packet(bytes([0x51, target])), "dimmer_code", target)
                result["change_verified"] = True
            finally:
                result["restore_attempted"] = True
                restored = await session.set_verified(
                    packet(bytes([0x51, original])), "dimmer_code", original)
                result["restored"] = restored["dimmer_code"] == original
            return
        data, field, expected = command_spec(args.command, args.value)
        if result["before"][field] == expected:
            result["already_set"] = True
            result["after"] = result["before"]
            return
        await session.set_verified(data, field, expected)
        result["change_verified"] = True
    finally:
        await client.stop_notify(session.notify)


async def run(args):
    from bleak import BleakClient, BleakScanner
    result = {"started_at": now(), "ok": False, "command": args.command,
              "value": args.value, "writes": [], "frames": [],
              "setter_attempted": False, "attempt_history": []}
    for attempt in range(args.attempts):
        record = {"attempt": attempt + 1, "started_at": now(), "phase": "scan"}
        result["attempt_history"].append(record)
        try:
            async with BleakScanner() as scanner:
                async with asyncio.timeout(args.scan_seconds):
                    async for device, advertisement in scanner.advertisement_data():
                        if device.address.upper() == args.address.upper():
                            result["target"] = describe(device, advertisement)
                            break
                record["phase"] = "connect"
                async with BleakClient(device, timeout=args.connect_timeout, pair=False) as client:
                    record["phase"] = "operate"
                    async with asyncio.timeout(65):
                        await operate(client, args, result)
                result["disconnected"] = True
            result["ok"] = True
            record["phase"] = "complete"
            break
        except Exception as exc:
            record["error"] = {"type": type(exc).__name__, "message": str(exc) or repr(exc)}
            if result["setter_attempted"]:
                result["uncertain_after_write"] = True
                break
            if attempt + 1 < args.attempts:
                await asyncio.sleep(2)
        finally:
            record["finished_at"] = now()
    result["finished_at"] = now()
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=["status", "test-dimmer", "test-controls", "volume", *COMMANDS])
    parser.add_argument("value", nargs="?")
    parser.add_argument("--address", default=ADDRESS)
    parser.add_argument("--attempts", type=int, default=2)
    parser.add_argument("--scan-seconds", type=float, default=60)
    parser.add_argument("--connect-timeout", type=float, default=45)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    if not (1 <= args.attempts <= 3 and 1 <= args.scan_seconds <= 60
            and 1 <= args.connect_timeout <= 60):
        parser.error("Timing/attempt values outside limits")
    try:
        if args.command not in ("status", "test-dimmer", "test-controls"):
            command_spec(args.command, args.value)
        elif args.value is not None:
            raise ValueError("This command takes no value")
    except ValueError as exc:
        parser.error(str(exc))
    # Serialize with the status wrapper on Linux, including over separate SSH calls.
    import fcntl
    with Path(__file__).with_name(".ble.lock").open("a") as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            parser.exit(1, "Another soundbar operation is active\n")
        result = asyncio.run(run(args))
    content = json.dumps(result, ensure_ascii=False, indent=2)
    if args.output:
        args.output.write_text(content + "\n", encoding="utf-8")
    print(content)
    return 0 if result["ok"] else 1


if __name__ == "__main__":
    sys.exit(main())
