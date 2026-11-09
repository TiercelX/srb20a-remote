"""Bounded Yamaha BLE status reader. No power/volume/input setters exist here.

Protocol adapted from MichaelObst/yamaha-sr-c20a (AGPL-3.0).
GATT and status layout cross-checked against Sound Bar Remote 2.40 APK.
No physical/listening verification is implied by decoded device reports.
"""
from __future__ import annotations

import argparse
import asyncio
from datetime import datetime, timezone
import json
from pathlib import Path
import sys

NOTIFY_UUID = "5cafe9de-e7b0-4e0b-8fb9-2da91a7ae3ed"
SERVICE_UUID = "945ca2b0-852c-4ab8-b654-354df41c2795"
WRITE_UUID = "0c50e7fa-594c-408b-ae0d-b53b884b7c08"
STATUS_QUERY = bytes.fromhex("ccaa020305f6")
_identity_body = b"\x09\x01HTS Cont"
IDENTITY_QUERY = b"\xcc\xaa" + _identity_body + bytes([-sum(_identity_body) & 255])


def now():
    return datetime.now(timezone.utc).isoformat()


def decode_status(frame: bytes) -> dict:
    """Reject invalid/unknown frames, preserve raw values and unknown enums."""
    if len(frame) < 4 or frame[:2] != b"\xcc\xaa":
        raise ValueError("Invalid frame header")
    if len(frame) != frame[2] + 4:
        raise ValueError("Invalid frame length")
    if sum(frame[2:]) % 256:
        raise ValueError("Invalid checksum")
    if frame[2] != 14 or frame[3:5] != b"\x05\x00":
        raise ValueError("Not a supported full status response")
    return {
        "mapping": "sound-bar-remote-2.40-static-crosscheck",
        "power": bool(frame[5] & 1),
        "input_code": frame[6],
        "input": {5: "bluetooth", 7: "tv", 10: "optical", 12: "analog"}.get(frame[6]),
        "mute": frame[7] != 0,
        "volume_raw": frame[8],
        "subwoofer_raw": frame[9],
        "surround_bit": bool(frame[13] & 1),
        "sound_mode_raw": frame[12:16].hex(),
        "sound_mode_code": frame[14],
        "sound_mode": None,
        "sound_mode_reference": {3: "movie", 10: "standard", 12: "game"}.get(frame[14]),
        "sound_mode_mapping_verified": False,
        "clear_voice_bit": bool(frame[15] & 4),
        "bass_extension_bit": bool(frame[15] & 32),
        "dimmer_code": frame[16] & 3,
        "dimmer": {0: "bright", 1: "dim", 2: "off"}.get(frame[16] & 3),
        "raw_hex": frame.hex(),
    }


class FrameBuffer:
    """Handle fragmented/coalesced notifications; keep memory bounded."""

    def __init__(self):
        self.buffer = bytearray()

    def feed(self, data):
        self.buffer.extend(data)
        frames = []
        while self.buffer:
            start = self.buffer.find(b"\xcc\xaa")
            if start < 0:
                self.buffer[:] = self.buffer[-1:] if self.buffer[-1] == 0xcc else b""
                break
            del self.buffer[:start]
            if len(self.buffer) < 3:
                break
            if self.buffer[2] > 124:
                del self.buffer[0]
                continue
            size = self.buffer[2] + 4
            if len(self.buffer) < size:
                break
            frame = bytes(self.buffer[:size])
            if sum(frame[2:]) % 256:
                del self.buffer[0]
                continue
            frames.append(frame)
            del self.buffer[:size]
        return frames


def candidate(device, advertisement):
    name = advertisement.local_name or device.name or ""
    uuids = [u.lower() for u in advertisement.service_uuids]
    return ("yamaha" in name.lower() or "sr-b20" in name.lower()
            or SERVICE_UUID in uuids or NOTIFY_UUID in uuids)


async def discover(seconds):
    from bleak import BleakScanner
    results = await asyncio.wait_for(
        BleakScanner.discover(timeout=seconds, return_adv=True), seconds + 15)
    return list(results.values())


def describe(device, advertisement):
    return {"address": device.address, "name": advertisement.local_name or device.name,
            "rssi": advertisement.rssi, "service_uuids": advertisement.service_uuids}


def select_channels(services):
    """Never fall back to writing an arbitrary handle on an unknown device."""
    notifications = [c for s in services if s.uuid == SERVICE_UUID for c in s.characteristics
                     if c.uuid.lower() == NOTIFY_UUID and "notify" in c.properties]
    if len(notifications) != 1:
        raise RuntimeError("Expected Yamaha notification characteristic is missing or ambiguous")
    notify = notifications[0]
    service = next(s for s in services if s.uuid == notify.service_uuid)
    writers = [c for c in service.characteristics if c.uuid.lower() == WRITE_UUID
               and ("write" in c.properties or "write-without-response" in c.properties)]
    if len(writers) != 1:
        raise RuntimeError("Expected exactly one writable characteristic in Yamaha service")
    return notify, writers[0]


async def query(device, args, result):
    from bleak import BleakClient
    async with BleakClient(device, timeout=args.connect_timeout, pair=False) as client:
        result["connected"] = True
        result["phase"] = "gatt_discovery_complete"
        result["gatt"] = [{"uuid": s.uuid, "characteristics": [
            {"uuid": c.uuid, "handle": c.handle, "properties": c.properties}
            for c in s.characteristics]} for s in client.services]
        notify, writer = select_channels(client.services)
        result["phase"] = "subscribe"
        queue = asyncio.Queue(maxsize=64)
        buffer = FrameBuffer()

        def received(_sender, data):
            for frame in buffer.feed(data):
                if not queue.full():
                    queue.put_nowait((now(), frame))

        await client.start_notify(notify, received)
        result["notifications_subscribed"] = True
        if args.identify:
            result["phase"] = "identity_query"
            await client.write_gatt_char(writer, IDENTITY_QUERY,
                                         response="write" in writer.properties)
            result["identity_query_sent"] = True
            deadline = asyncio.get_running_loop().time() + args.response_timeout
            while asyncio.get_running_loop().time() < deadline:
                try:
                    at, frame = await asyncio.wait_for(
                        queue.get(), deadline - asyncio.get_running_loop().time())
                except TimeoutError:
                    result["identity_warning"] = "No identity response; continuing with status query"
                    break
                result["frames"].append({"received_at": at, "hex": frame.hex()})
                if len(frame) >= 12 and frame[3:5] == b"\x04\x00":
                    code = frame[7]
                    result["identity"] = {"model_code": code, "model": {
                        35: "SR-B20A", 36: "ATS-B200", 37: "SR-C20A",
                        38: "ATS-C200", 39: "SR-C30A"}.get(code), "raw_hex": frame.hex()}
                    break
        result["phase"] = "status_query"
        for _ in range(args.samples):
            # Drop unsolicited/previous-query frames; only accept fresh responses.
            while not queue.empty():
                queue.get_nowait()
            await client.write_gatt_char(writer, STATUS_QUERY,
                                         response="write" in writer.properties)
            result["queries_sent"] += 1
            deadline = asyncio.get_running_loop().time() + args.response_timeout
            while True:
                remaining = deadline - asyncio.get_running_loop().time()
                if remaining <= 0:
                    raise TimeoutError("No valid full status response before deadline")
                at, frame = await asyncio.wait_for(queue.get(), remaining)
                result["frames"].append({"received_at": at, "hex": frame.hex()})
                try:
                    status = decode_status(frame)
                except ValueError:
                    continue
                result["samples"].append({"received_at": at, "status": status})
                break
            if len(result["samples"]) < args.samples:
                await asyncio.sleep(args.interval)
        await client.stop_notify(notify)
    result["disconnected"] = True


async def run_once(args):
    result = {"schema_version": 1, "started_at": now(), "ok": False,
              "read_only_application_commands": True, "query_hex": STATUS_QUERY.hex(),
              "connected": False, "queries_sent": 0, "frames": [], "samples": []}
    try:
        devices = await discover(args.scan_seconds)
        result["devices_seen"] = len(devices)
        result["phase"] = "scan_complete"
        choices = [(d, a) for d, a in devices if candidate(d, a)]
        result["candidates"] = [describe(d, a) for d, a in choices]
        if args.command == "scan":
            if args.all_devices:
                result["devices"] = [describe(d, a) for d, a in devices]
            result["ok"] = True
        else:
            if args.address:
                choices = [(d, a) for d, a in devices
                           if d.address.lower() == args.address.lower()]
            if len(choices) != 1:
                raise RuntimeError(f"Expected one target, found {len(choices)}. "
                                   "Use scan and an explicit --address if needed; no query sent.")
            device, advertisement = choices[0]
            result["target"] = describe(device, advertisement)
            result["phase"] = "connect"
            # Bound discovery/connect/requests/disconnect, even if BlueZ stalls.
            duration = args.connect_timeout + args.response_timeout + args.samples * (
                args.response_timeout + args.interval + 10) + 15
            if args.keep_scanning:
                # Some Linux adapters need discovery active while establishing LE.
                from bleak import BleakScanner
                async with BleakScanner():
                    await asyncio.wait_for(query(device, args, result), duration)
            else:
                await asyncio.wait_for(query(device, args, result), duration)
            result["ok"] = len(result["samples"]) == args.samples
            result["phase"] = "complete"
    except Exception as exc:
        result["error"] = {"type": type(exc).__name__, "message": str(exc) or repr(exc)}
    result["finished_at"] = now()
    return result


async def run(args):
    invocation_started = now()
    history = []
    attempts = args.attempts if args.command == "status" else 1
    for attempt in range(attempts):
        result = await run_once(args)
        history.append({"attempt": attempt + 1, "ok": result["ok"],
                        "started_at": result["started_at"],
                        "finished_at": result["finished_at"],
                        "phase": result.get("phase"), "error": result.get("error"),
                        "queries_sent": result["queries_sent"],
                        "valid_samples": len(result["samples"])})
        if result["ok"]:
            break
        if attempt + 1 < attempts:
            await asyncio.sleep(args.retry_delay)
    result["invocation_started_at"] = invocation_started
    result["attempt_history"] = history
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=["scan", "status"])
    parser.add_argument("--scan-seconds", type=float, default=15)
    parser.add_argument("--address")
    parser.add_argument("--samples", type=int, default=3)
    parser.add_argument("--interval", type=float, default=2)
    parser.add_argument("--connect-timeout", type=float, default=25)
    parser.add_argument("--response-timeout", type=float, default=8)
    parser.add_argument("--all-devices", action="store_true")
    parser.add_argument("--keep-scanning", action=argparse.BooleanOptionalAction,
                        default=sys.platform.startswith("linux"),
                        help="Keep BLE discovery active during connection (adapter diagnostic)")
    parser.add_argument("--identify", action=argparse.BooleanOptionalAction, default=True,
                        help="Read model identification using the app's session handshake")
    parser.add_argument("--attempts", type=int, default=3,
                        help="Bounded attempts for transient discovery/connection failures")
    parser.add_argument("--retry-delay", type=float, default=3)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    if (not 1 <= args.attempts <= 5 or not 0 <= args.retry_delay <= 30
            or not 1 <= args.samples <= 20 or not 1 <= args.scan_seconds <= 90
            or not 0 <= args.interval <= 30 or not 1 <= args.connect_timeout <= 60
            or not 1 <= args.response_timeout <= 30):
        parser.error("Timing or sample count outside bounded limits")
    try:
        result = asyncio.run(run(args))
    except KeyboardInterrupt:
        return 130
    text = json.dumps(result, ensure_ascii=False, indent=2)
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(text + "\n", encoding="utf-8")
    print(text)
    return 0 if result["ok"] else 1


if __name__ == "__main__":
    sys.exit(main())
