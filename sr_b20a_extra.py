"""Additional SR-B20A commands identified from Yamaha Sound Bar Remote 2.40."""
import asyncio
from bleak import BleakClient, BleakScanner
from soundbar_control import ADDRESS, Session, packet

PROGRAMS = {'stereo': ('407850', 1, None), 'standard': ('407ef1', 0, 10),
            'movie': ('4078d9', 0, 3), 'game': ('4078dc', 0, 12)}


def extra_state(state):
    raw = bytes.fromhex(state['raw_hex'])
    mode, program = raw[13], raw[14]
    state['program'] = 'stereo' if mode == 1 else ({10: 'standard', 3: 'movie', 12: 'game'}.get(program) if mode == 0 else None)
    state['three_d'] = bool(raw[15] & 0x40)
    return state


class ExtendedSession(Session):
    async def status(self):
        return extra_state(await super().status())


async def run_extended(command, value, stop_before_connect=False):
    result = {'ok': False, 'command': command, 'writes': [], 'frames': [], 'setter_attempted': False, 'attempt_history': []}
    try:
        async with BleakScanner() as scanner:
            async with asyncio.timeout(15):
                async for device, advertisement in scanner.advertisement_data():
                    if device.address.upper() == ADDRESS:
                        break
            if stop_before_connect:
                await scanner.stop()
            async with BleakClient(device, timeout=8 if stop_before_connect else 20, pair=False) as client:
                session = ExtendedSession(client, result)
                await client.start_notify(session.notify, session.received)
                try:
                    await session.identify()
                    before = await session.status()
                    result['before'] = before
                    if command == 'subwoofer':
                        current = before['subwoofer_raw']
                        if current not in range(0, 33, 4) or value not in ('up', 'down'):
                            raise ValueError('低音炮数值不在已知范围')
                        expected = current + (4 if value == 'up' else -4)
                        if not 0 <= expected <= 32:
                            result['after'] = before
                        else:
                            await session.set_verified(packet(bytes.fromhex('40784c' if value == 'up' else '40784d')), 'subwoofer_raw', expected)
                    elif command == 'program':
                        data, _, _ = PROGRAMS[value]
                        if before['program'] == value:
                            result['after'] = before
                        else:
                            await session.set_verified(packet(bytes.fromhex(data)), 'program', value)
                    elif command == 'three-d':
                        expected = {'on': True, 'off': False}[value]
                        if before['program'] == 'stereo':
                            raise ValueError('立体声模式下请先选择标准、电影或游戏模式')
                        if before['three_d'] == expected:
                            result['after'] = before
                        else:
                            await session.set_verified(packet(bytes.fromhex('4078c9' if expected else '4078b4')), 'three_d', expected)
                    else:
                        raise ValueError('不支持的命令')
                finally:
                    await client.stop_notify(session.notify)
        result['ok'] = True
    except Exception as exc:
        result['attempt_history'].append({'error': {'message': str(exc) or repr(exc)}})
        if result['setter_attempted']:
            result['uncertain_after_write'] = True
    return result
