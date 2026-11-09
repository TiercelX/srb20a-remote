"""SSH-accessible MBP Bluetooth gateway; private Unix socket, serialized BLE jobs."""
import asyncio
from datetime import datetime, timezone
import fcntl
import importlib.util
import json
import os
from pathlib import Path
import re
import signal
import socket
from types import SimpleNamespace
import uuid

import soundbar_control as engine

BASE = Path(__file__).resolve().parent
SOCKET = Path(os.environ.get("XDG_RUNTIME_DIR", f"/run/user/{os.getuid()}")) / "bluetooth-gateway/control.sock"
COMMANDS = {"status", "test-controls", "test-dimmer", "volume", *engine.COMMANDS}
NO_VALUE = {"status", "test-controls", "test-dimmer", "health", "diagnostics"}


def now():
    return datetime.now(timezone.utc).isoformat()


def validate(request):
    if not isinstance(request, dict) or set(request) - {"version", "device", "command", "value", "request_id"}:
        raise ValueError("Expected version/device/command/value/request_id only")
    if type(request.get("version", 1)) is not int or request.get("version", 1) != 1:
        raise ValueError("Unsupported protocol version")
    if request.get("device", "sr-b20a") != "sr-b20a":
        raise ValueError("Unknown device; Mesh backend is not implemented")
    command = request.get("command")
    if not isinstance(command, str) or command not in COMMANDS | NO_VALUE:
        raise ValueError("Unsupported command")
    value = request.get("value")
    if command in NO_VALUE:
        if value is not None:
            raise ValueError("This command does not accept a value")
    else:
        if type(value) not in (str, int):
            raise ValueError("Command value must be a string or integer")
        engine.command_spec(command, str(value))
        value = str(value)
    request_id = request.get("request_id", str(uuid.uuid4()))
    if not isinstance(request_id, str) or not re.fullmatch(r"[A-Za-z0-9_-]{1,64}", request_id):
        raise ValueError("Invalid request_id")
    return {"version": 1, "device": "sr-b20a", "command": command,
            "value": value, "request_id": request_id}


def failure(code, message, request_id=None):
    return {"ok": False, "gateway": {"protocol_version": 1, "request_id": request_id},
            "error": {"code": code, "message": message}}


class Gateway:
    def __init__(self, evidence=None, runner=None):
        self.evidence = evidence or BASE / "evidence/gateway"
        self.evidence.mkdir(parents=True, exist_ok=True, mode=0o700)
        self.lock = asyncio.Lock()
        self.pending = 0
        self.runner = runner or engine.run

    @staticmethod
    def health():
        module = Path("/sys/module/bcm_legacy_adv_fix")
        version = module / "version"
        return {"ok": True, "command": "health", "gateway": {"protocol_version": 1,
                "transport": "SSH + private Unix socket", "pending_limit": 2},
                "bluetooth_compat_loaded": module.exists(),
                "bluetooth_compat_version": version.read_text().strip() if version.exists() else None,
                "devices": [{"id": "sr-b20a", "model": "SR-B20A", "backend": "yamaha-ble",
                             "verified_controls": ["volume", "mute", "clear-voice", "bass-extension", "dimmer"],
                             "unverified_controls": ["input", "power"]}],
                "soundbar_online_checked": False}

    def save(self, path, data):
        temporary = path.with_suffix(".tmp")
        with temporary.open("w", encoding="utf-8") as handle:
            json.dump(data, handle, ensure_ascii=False, indent=2)
            handle.flush()
            os.fsync(handle.fileno())
        temporary.replace(path)
        directory = os.open(path.parent, os.O_DIRECTORY)
        try:
            os.fsync(directory)
        finally:
            os.close(directory)

    async def handle(self, incoming):
        try:
            request = validate(incoming)
        except ValueError as exc:
            return failure("invalid_request", str(exc))
        request_id = request["request_id"]
        if request["command"] == "health":
            data = self.health()
            data["gateway"].update(request_id=request_id, pending=self.pending)
            return data
        if request["command"] == "diagnostics":
            path = Path("/usr/local/lib/bcm-legacy-adv/bt_diagnostics.py")
            spec = importlib.util.spec_from_file_location("gateway_diagnostics", path)
            module = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(module)
            return {"ok": True, "command": "diagnostics", "gateway": {
                    "protocol_version": 1, "request_id": request_id}, "diagnostics": module.snapshot()}
        if self.pending >= 2:
            return failure("busy", "Gateway queue is full; no operation started", request_id)
        self.pending += 1
        received_at = now()
        try:
            async with self.lock:
                evidence = self.evidence / f"{request_id}.json"
                if evidence.exists():
                    previous = json.loads(evidence.read_text(encoding="utf-8"))
                    if previous["request"] != request:
                        return failure("request_id_conflict", "request_id already belongs to another request", request_id)
                    if not previous.get("complete"):
                        return failure("request_incomplete", "Previous execution did not finish logging; query status before another setter", request_id)
                    response = previous["response"]
                    response["gateway"]["replayed"] = True
                    return response
                with (BASE / ".ble.lock").open("a") as lock:
                    try:
                        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
                    except BlockingIOError:
                        return failure("busy", "Another Bluetooth operation holds the device lock", request_id)
                    self.save(evidence, {"request": request, "received_at": received_at,
                                         "complete": False, "accepted_at": now()})
                    args = SimpleNamespace(command=request["command"], value=request["value"],
                                           address=engine.ADDRESS, scan_seconds=15,
                                           connect_timeout=20, attempts=1)
                    try:
                        response = await asyncio.wait_for(self.runner(args), timeout=150)
                    except Exception as exc:
                        response = failure("execution_error", str(exc) or repr(exc), request_id)
                        response["uncertain_completion"] = True
                    response["gateway"] = {"protocol_version": 1, "request_id": request_id,
                                           "received_at": received_at, "finished_at": now(),
                                           "replayed": False}
                    response["evidence_file"] = str(evidence)
                    try:
                        self.save(evidence, {"request": request, "complete": True, "response": response})
                    except OSError as exc:
                        response = failure("evidence_write_error", str(exc), request_id)
                        response["uncertain_completion"] = True
                    return response
        finally:
            self.pending -= 1


async def serve():
    os.umask(0o077)
    SOCKET.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    # Hold an instance lock before removing a stale socket from a prior crash.
    with (SOCKET.parent / "instance.lock").open("a") as instance:
        fcntl.flock(instance, fcntl.LOCK_EX | fcntl.LOCK_NB)
        SOCKET.unlink(missing_ok=True)
        gateway = Gateway()
        connections = set()

        async def connected(reader, writer):
            task = asyncio.current_task()
            connections.add(task)
            try:
                try:
                    line = await asyncio.wait_for(reader.readline(), timeout=5)
                    if not line.endswith(b"\n") or len(line) > 4096:
                        raise ValueError("Expected one JSON line of at most 4096 bytes")
                    response = await gateway.handle(json.loads(line))
                except Exception as exc:
                    response = failure("invalid_request", str(exc) or repr(exc))
                writer.write(json.dumps(response, ensure_ascii=False).encode() + b"\n")
                await writer.drain()
            except (BrokenPipeError, ConnectionResetError):
                # A disconnected client must not cancel an accepted control/restore.
                pass
            finally:
                writer.close()
                try:
                    await writer.wait_closed()
                except (BrokenPipeError, ConnectionResetError):
                    pass
                finally:
                    connections.discard(task)

        server = await asyncio.start_unix_server(connected, path=str(SOCKET), limit=4096)
        os.chmod(SOCKET, 0o600)
        stop = asyncio.Event()
        for sig in (signal.SIGTERM, signal.SIGINT):
            asyncio.get_running_loop().add_signal_handler(sig, stop.set)
        notify = os.environ.get("NOTIFY_SOCKET")
        if notify:
            if notify.startswith("@"):
                notify = "\0" + notify[1:]
            with socket.socket(socket.AF_UNIX, socket.SOCK_DGRAM) as notification:
                notification.sendto(b"READY=1\nSTATUS=Private Bluetooth gateway ready", notify)
        print(json.dumps({"event": "gateway_ready", "socket": str(SOCKET), "at": now()}), flush=True)
        await stop.wait()
        server.close()
        await server.wait_closed()
        if connections:
            await asyncio.gather(*connections, return_exceptions=True)
        SOCKET.unlink(missing_ok=True)


if __name__ == "__main__":
    asyncio.run(serve())
