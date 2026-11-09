#!/usr/bin/env bash
set -euo pipefail
base="$HOME/Tool/codex/sr-b20a"
here=$(cd -- "$(dirname -- "$0")" && pwd)
if [[ "$here" != "$base" ]]; then
  printf 'Extract this package to %s and run the installer there.\n' "$base" >&2
  exit 1
fi
unit="$HOME/.config/systemd/user/bluetooth-gateway.service"
if [[ -e "$unit" ]]; then
  printf 'A Bluetooth gateway service already exists: %s\nPlease review it before replacing it.\n' "$unit" >&2
  exit 1
fi
python3 make_english.py
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements.txt
if [[ ! -f "$HOME/.config/srb20a-remote/address.txt" ]]; then .venv/bin/python setup_address.py; fi
mkdir -p "$HOME/.config/systemd/user" "$HOME/.local/share/applications"
cat > "$unit" <<'EOF'
[Unit]
Description=SR-B20A Bluetooth gateway
[Service]
Type=notify
NotifyAccess=main
WorkingDirectory=%h/Tool/codex/sr-b20a
ExecStart=%h/Tool/codex/sr-b20a/.venv/bin/python %h/Tool/codex/sr-b20a/gateway_extended.py
RuntimeDirectory=bluetooth-gateway
RuntimeDirectoryMode=0700
UMask=0077
Restart=on-failure
RestartSec=3
TimeoutStopSec=330
NoNewPrivileges=yes
RestrictAddressFamilies=AF_UNIX
[Install]
WantedBy=default.target
EOF
case "${LANG:-}" in zh*) app=mbp_gui.py;; *) app=mbp_gui_en.py;; esac
cat > "$HOME/.local/share/applications/srb20a-remote.desktop" <<EOF
[Desktop Entry]
Type=Application
Name=SR-B20A Remote
Exec=/usr/bin/python3 $base/$app
Icon=audio-speakers
Terminal=false
Categories=AudioVideo;Audio;
EOF
chmod +x mbp-gateway.sh srctl
systemctl --user daemon-reload
systemctl --user enable --now bluetooth-gateway.service
printf 'Installed. Start SR-B20A Remote from the application menu.\n'
