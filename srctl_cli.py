"""Host-local SR-B20A CLI with tvctl-style flag aliases and verified readback."""
import argparse
import json
from pathlib import Path
import subprocess
import sys

from soundbar_control import COMMANDS, command_spec

OPERATIONS = ["health", "diagnostics", "status", "volume", *COMMANDS, "test-controls", "test-dimmer"]
ALIASES = {"--" + name: name for name in OPERATIONS}


def on_off(value):
    return "on" if value else "off"


def main():
    arguments = [ALIASES.get(argument, argument) for argument in sys.argv[1:]]
    if arguments == ["help"]:
        arguments = ["--help"]
    parser = argparse.ArgumentParser(
        prog="srctl", description="Control SR-B20A through the local MBP Bluetooth gateway.",
        epilog="Aliases: --status, --volume 35, --mute on, --clear-voice on, --bass-extension off, --dimmer dim. Volume is raw 0-50, not percent. Input/power are not yet hardware-verified.")
    parser.add_argument("command", choices=OPERATIONS)
    parser.add_argument("value", nargs="?")
    parser.add_argument("--json", action="store_true", help="Return the full gateway JSON")
    args = parser.parse_args(arguments)
    try:
        if args.command in ("health", "diagnostics", "status", "test-controls", "test-dimmer"):
            if args.value is not None:
                raise ValueError("This command does not accept a value")
        else:
            command_spec(args.command, args.value)
    except ValueError as exc:
        parser.error(str(exc))
    relay = [str(Path(__file__).with_name("mbp-gateway.sh")), args.command]
    if args.value is not None:
        relay.append(args.value)
    try:
        completed = subprocess.run(relay, capture_output=True, text=True, timeout=340)
        result = json.loads(completed.stdout)
    except (OSError, subprocess.TimeoutExpired, ValueError) as exc:
        print(f"srctl: no confirmed result: {exc}. Query status before retrying a setter.", file=sys.stderr)
        return 1
    if args.json:
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0 if result.get("ok") and completed.returncode == 0 else 1
    if not result.get("ok") or completed.returncode:
        error = result.get("error") or (result.get("attempt_history") or [{}])[-1].get("error") or {}
        print(f"srctl: not confirmed: {error.get('message', 'Unknown error')}", file=sys.stderr)
        print(f"request_id={result.get('gateway', {}).get('request_id')} evidence={result.get('evidence_file')}", file=sys.stderr)
        return 1
    if args.command == "health":
        print(f"gateway=ready compat_loaded={on_off(result['bluetooth_compat_loaded'])} "
              f"compat_version={result['bluetooth_compat_version']} "
              f"pending={result['gateway']['pending']} soundbar_online=unchecked")
    elif args.command == "diagnostics":
        data = result["diagnostics"]
        counts = data.get("counters", {})
        print(f"compat_version={data.get('module_version')} corrected={counts.get('corrected_reports')} "
              f"invalid={counts.get('invalid_packets')} skipped={counts.get('skipped_shared')}")
        for item in data.get("channels", []):
            if item["reports"]:
                print(f"channel={item['interpretation']} reports={item['reports']} "
                      f"RSSI_mean={item['rssi_mean_dbm']}dBm range={item['rssi_min_dbm']}..{item['rssi_max_dbm']}dBm")
        print(" ".join(f"{key}={value}" for key, value in data.get("metadata_counts", {}).items() if key.startswith("ad_")))
        print("Counts are received reports, not unique devices or packet loss.")
    else:
        state = result.get("after") or result["before"]
        print(f"SR-B20A power={on_off(state['power'])} input={state['input']} "
              f"volume={state['volume_raw']}/50 mute={on_off(state['mute'])} "
              f"clear_voice={on_off(state['clear_voice_bit'])} "
              f"bass_extension={on_off(state['bass_extension_bit'])} dimmer={state['dimmer']} verified")
        if args.command == "test-controls":
            print(f"tests={len(result.get('control_tests', []))} all_restored={result.get('all_tests_restored')}")
        elif args.command == "test-dimmer":
            print(f"change_verified={result.get('change_verified')} restored={result.get('restored')}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
