"""Relay one CLI/JSON request to the local gateway; invoke this relay over SSH."""
import argparse
import json
import os
from pathlib import Path
import socket
import sys
import uuid


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command")
    parser.add_argument("value", nargs="?")
    parser.add_argument("--request-id", default=None)
    args = parser.parse_args()
    request = {"version": 1, "device": "sr-b20a", "command": args.command,
               "request_id": args.request_id or str(uuid.uuid4())}
    if args.value is not None:
        request["value"] = args.value
    sent = False
    try:
        if args.command == "request":
            payload = sys.stdin.buffer.read(4097)
            if len(payload) > 4096:
                raise ValueError("Request exceeds 4096 bytes")
            request = json.loads(payload)
            if not isinstance(request, dict):
                raise ValueError("Expected a JSON object")
            request.setdefault("request_id", args.request_id or str(uuid.uuid4()))
        path = Path(os.environ.get("XDG_RUNTIME_DIR", f"/run/user/{os.getuid()}")) / "bluetooth-gateway/control.sock"
        with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as connection:
            connection.settimeout(330)
            connection.connect(str(path))
            sent = True
            connection.sendall(json.dumps(request).encode() + b"\n")
            with connection.makefile("rb") as stream:
                line = stream.readline(262145)
                if not line or len(line) > 262144:
                    raise ValueError("Missing or oversized gateway response")
                response = json.loads(line)
    except Exception as exc:
        response = {"ok": False, "gateway": {"request_id": request.get("request_id")},
                    "error": {"code": "relay_error", "message": str(exc)},
                    "uncertain_completion": sent,
                    "note": ("Completion may be uncertain after disconnect; query status before retrying a setter."
                             if sent else "Request was not sent to the gateway.")}
    print(json.dumps(response, ensure_ascii=False, indent=2))
    return 0 if response.get("ok") else 1


if __name__ == "__main__":
    sys.exit(main())
