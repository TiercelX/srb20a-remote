"""Extend the existing MBP gateway while preserving its queue and replay log."""
import asyncio
import gateway_server as base
from sr_b20a_extra import run_extended

EXTENDED = {'subwoofer': {'up', 'down'}, 'program': {'stereo', 'standard', 'movie', 'game'},
            'three-d': {'on', 'off'}}
original_validate = base.validate
original_gateway = base.Gateway


def validate(request):
    if not isinstance(request, dict) or not isinstance(request.get('command'), str) or request.get('command') not in EXTENDED:
        return original_validate(request)
    command = request['command']
    value = request.get('value')
    if not isinstance(value, str) or value not in EXTENDED[command]:
        raise ValueError('Unsupported extended command value')
    # Apply all existing envelope, device and request-id checks without weakening them.
    checked = original_validate({**request, 'command': 'mute', 'value': 'on'})
    checked.update(command=command, value=value)
    return checked


async def fast_standard(args):
    """Stop discovery before connecting; no command is replayed after a write."""
    from bleak import BleakClient, BleakScanner
    engine = base.engine
    result = {"started_at": engine.now(), "ok": False, "command": args.command,
              "value": args.value, "writes": [], "frames": [],
              "setter_attempted": False, "attempt_history": []}
    record = {"attempt": 1, "started_at": engine.now(), "phase": "scan", "strategy": "scan_then_connect"}
    result['attempt_history'].append(record)
    try:
        async with BleakScanner() as scanner:
            async with asyncio.timeout(args.scan_seconds):
                async for device, advertisement in scanner.advertisement_data():
                    if device.address.upper() == args.address.upper():
                        result['target'] = engine.describe(device, advertisement)
                        break
            await scanner.stop()
            record['phase'] = 'connect'
            async with BleakClient(device, timeout=8, pair=False) as client:
                record['phase'] = 'operate'
                async with asyncio.timeout(65):
                    await engine.operate(client, args, result)
            result['disconnected'] = True
        result['ok'] = True
        record['phase'] = 'complete'
    except Exception as exc:
        record['error'] = {'type': type(exc).__name__, 'message': str(exc) or repr(exc)}
        if result['setter_attempted']:
            result['uncertain_after_write'] = True
    finally:
        record['finished_at'] = engine.now()
        result['finished_at'] = engine.now()
    return result


async def dispatch(args):
    if args.command in EXTENDED:
        first = await run_extended(args.command, args.value, stop_before_connect=True)
        if first['ok'] or first.get('setter_attempted'):
            return first
        second = await run_extended(args.command, args.value)
    else:
        first = await fast_standard(args)
        if first['ok'] or first.get('setter_attempted'):
            return first
        second = await base.engine.run(args)
    second['fast_attempt'] = first
    return second


class ExtendedGateway(original_gateway):
    def __init__(self, evidence=None, runner=None):
        super().__init__(evidence=evidence, runner=runner or dispatch)

    @staticmethod
    def health():
        data = original_gateway.health()
        data['devices'][0]['extended_controls'] = sorted(EXTENDED)
        return data


if __name__ == '__main__':
    base.validate = validate
    base.Gateway = ExtendedGateway
    asyncio.run(base.serve())
