# SR-B20A Remote

[中文](#中文)

A local Bluetooth Low Energy controller for the Yamaha SR-B20A soundbar, with Windows and Linux desktop interfaces. This is an independent project and is not affiliated with Yamaha.

## Windows

Download the Chinese or English EXE from Releases and run it. On first launch the application scans for nearby `YamahaAV` devices; one match is selected automatically, multiple matches require selection, and a manual address can be entered if discovery fails. The address is saved locally in `%APPDATA%\srb20a-remote\address.txt` and is not uploaded.

Local Bluetooth is the default. The optional SSH gateway mode expects an SSH alias `mbp` and a Linux gateway installed at `~/Tool/codex/sr-b20a`. Linux and Windows GUI controls include volume, subwoofer, input, power, sound modes, 3D surround, Clear Voice, Bass Extension and indicator brightness. Commands are confirmed by fresh status where possible; a lost connection after sending a command leaves the result uncertain.

## Linux gateway and GUI

Requires Python 3 with `venv`, systemd user services, a BLE adapter supported by BlueZ, and GTK 4 with Python GObject bindings. Extract the Linux source bundle to `~/Tool/codex/sr-b20a`, run `./install-linux.sh` from that directory, then open **SR-B20A Remote** from the application menu. The installer scans for the device and stores its address under `~/.config/srb20a-remote/`; it refuses to replace an existing `bluetooth-gateway.service`. The GUI language follows the system locale at installation. It sends requests to the private local gateway socket, which serializes operations and records request IDs.

If discovery fails, create `~/.config/srb20a-remote/address.txt` containing the colon-separated Bluetooth address, then run the installer. The project was tested with one SR-B20A; results may vary with adapters and firmware. Input switching and standby wake were tested on Windows direct Bluetooth; Linux standby wake remains unverified. Advanced remote long-press settings are not implemented over BLE.

## Build and test

Windows: install Python with Tkinter, `bleak==3.0.2` and PyInstaller, then run `./build-windows.ps1`. The script builds Chinese and English one-file applications.

Linux: `python make_english.py`, then run `.venv/bin/python -m unittest test_soundbar_status test_soundbar_control test_gateway test_gateway_fast`. The protocol code is licensed under AGPL-3.0; see [LICENSE](LICENSE) and [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md).

## 中文

这是 Yamaha SR-B20A 的本地蓝牙控制工具，提供 Windows 和 Linux 图形界面，与 Yamaha 官方无关联。

Windows 用户从 Release 下载中文版或英文版 EXE。首次启动会自动扫描音箱：只有一台时自动选择，多台时让用户选择；找不到时可以手动输入地址。地址仅保存在本机 `%APPDATA%\srb20a-remote\address.txt`。默认使用本机蓝牙，也可切换至 SSH 网关。

Linux 需要 Python 3、venv、BlueZ、用户级 systemd 和 GTK 4 Python 绑定。将 Linux 源码包解压到 `~/Tool/codex/sr-b20a`，在该目录执行 `./install-linux.sh`，然后从应用菜单打开 SR-B20A Remote。安装器不会覆盖已有同名网关服务；界面语言随安装时系统语言选择。

软件支持音量、低音炮、输入、电源、声音模式、3D 环绕、人声增强、低音增强和指示灯。写入后以音箱状态确认；写入后断线时应先刷新，避免盲目重试。部分遥控器长按高级设置没有找到 BLE 命令，不支持在程序中直接设置。
