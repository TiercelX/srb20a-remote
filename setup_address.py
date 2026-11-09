"""Select a nearby Yamaha soundbar and save its address for the local gateway."""
import asyncio
from srb20a_config import save_address
from srb20a_discovery import discover_soundbars

found = asyncio.run(discover_soundbars())
if not found:
    raise SystemExit('No Yamaha soundbar found. Set SRB20A_ADDRESS or configure ~/.config/srb20a-remote/address.txt manually.')
if len(found) == 1:
    selected = found[0]
else:
    for i, (address, name) in enumerate(found, 1):
        print(f'{i}: {name} ({address})')
    try:
        choice = int(input('Select a number: '))
        if not 1 <= choice <= len(found):
            raise ValueError()
    except (ValueError, EOFError):
        raise SystemExit('Invalid selection; no address saved.')
    selected = found[choice - 1]
save_address(selected[0])
print('Saved:', selected[1], selected[0])
