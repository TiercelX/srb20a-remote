"""Create an English GUI from the maintained Chinese source."""
from pathlib import Path
p = Path(__file__).with_name('sr_b20a_gui.py')
s = p.read_text(encoding='utf-8')
start = s.index('ADVANCED_GUIDE = """')
end = s.index('"""', start + len('ADVANCED_GUIDE = """')) + 3
s = s[:start] + '''ADVANCED_GUIDE = """Advanced settings require the physical remote or soundbar controls. They cannot be changed or read via this app.

HDMI control: Turn off the bar, then hold TV on the remote for 5 seconds. TV indicator on means enabled.
Auto standby: With the bar off, hold the input and power buttons on the soundbar for 5 seconds. TV indicator on means disabled.
Child lock: With the bar off, hold INFO on the remote for 5 seconds. TV indicator on means enabled.
Bluetooth standby: With the bar off, hold BLUETOOTH on the remote for 5 seconds. Bluetooth indicator on means enabled. The soundbar turns on after changing the setting.
Bluetooth function: With the bar off, hold DIM on the remote for 5 seconds. Disabling Bluetooth prevents this application from connecting; re-enable it with the physical remote.
Dolby dynamic range: With the bar off, hold STANDARD (maximum), MOVIE (standard), or GAME (no compression) for 5 seconds. Applies to Dolby Digital only.
See the Yamaha user guide for indicator details."""''' + s[end:]
translations = {
'；命令可能已发出，请先刷新状态再操作': '; the command may have been sent. Refresh before retrying',
'网关未确认操作':'Gateway did not confirm the operation','蓝牙未确认操作':'Bluetooth operation not confirmed',
'网关没有返回结果':'No response from gateway', '正在读取音箱状态…':'Reading soundbar status…',
'通过 MBP 蓝牙网关连接':'Connecting through gateway', '等待状态':'Waiting for status',
'本机蓝牙':'Local Bluetooth','MBP 网关':'SSH gateway','SR-B20A 控制':'SR-B20A Control',
'高级设置指南':'Advanced settings', '遥控器与机身高级设置':'Remote advanced settings',
'以下需手动操作；本窗口不读取或更改这些设置。':'Manual operations only; this window does not change settings.',
'打开 Yamaha 官方使用指南':'Open Yamaha user guide', '刷新状态':'Refresh', '连接方式':'Connection',
'低音炮音量':'Subwoofer', '设置音量':'Set volume', '当前模式：':'Sound mode: ',
'声音模式':'Sound mode','立体声':'Stereo','标准':'Standard','电影':'Movie','游戏':'Game',
'3D 环绕':'3D surround','静音':'Mute','指示灯':'Indicators','关闭':'Off','开启':'On',
'待机':'Standby','开机':'Power on','电源':'Power','输入':'Input','蓝牙':'Bluetooth',
'光纤':'Optical','电视':'TV','音量':'Volume','亮':'Bright','暗':'Dim',
'正在连接音箱，请稍候…':'Connecting to soundbar…', '每次操作会读取设备状态并确认结果':'Reading device state and confirming operation',
'操作未确认：':'Operation not confirmed: ', '请先刷新状态，确认结果后再操作。':'Refresh status before retrying.',
'状态已更新':'Status updated','操作已确认':'Operation confirmed','本机蓝牙直连':'Local Bluetooth',
'请求 ID：':'Request ID: ', '状态未知':'Status unknown','未知':'Unknown','原始值 ':'Raw value ',
'音箱地址':'Soundbar address','输入 SR-B20A 蓝牙地址，例如 00:11:22:33:44:55：':'Enter the SR-B20A Bluetooth address, e.g. 00:11:22:33:44:55:',
'地址无效':'Invalid address', '正在搜索音箱':'Searching for soundbars', '正在搜索附近的雅马逊音箱，请稍候…':'Searching for nearby Yamaha soundbars…', '正在搜索附近的雅马哈音箱，请稍候…':'Searching for nearby Yamaha soundbars…', '发现多台设备，请输入序号：':'Multiple devices found; enter a number:', '未找到音箱。请输⼊蓝牙地址，例如 00:11:22:33:44:55：':'No soundbar found. Enter its Bluetooth address, e.g. 00:11:22:33:44:55:', '未找到音箱。请输入蓝牙地址，例如 00:11:22:33:44:55：':'No soundbar found. Enter its Bluetooth address, e.g. 00:11:22:33:44:55:', '选择音箱':'Select soundbar', '请选择有效序号':'Select a valid number', '操作未确认':'Operation not confirmed'
}
for old, new in sorted(translations.items(), key=lambda item: len(item[0]), reverse=True):
    s = s.replace(old, new)
Path(__file__).with_name('sr_b20a_gui_en.py').write_text(s, encoding='utf-8')

# Linux GTK edition uses the same terminology.
source = Path(__file__).with_name('mbp_gui.py').read_text(encoding='utf-8')
linux_translations = {**translations, '通过本机蓝牙网关连接':'Using local Bluetooth gateway', '正在读取状态…':'Reading status…', '操作未确认':'Operation not confirmed', '请先刷新状态':'Refresh status first', '命令可能已发出':'Command may have been sent', '结果可能未知':'Result may be unknown', '连接音箱':'Connecting to soundbar', '低音炮':'Subwoofer', '音箱':'Soundbar', '网关返回结果为空或过长':'Missing or oversized gateway response', '模式：':'Mode: ', '设置':'Set', '\'关\'':'\'Off\'', '无法':'Cannot'}
for old, new in sorted(linux_translations.items(), key=lambda item: len(item[0]), reverse=True):
    source = source.replace(old, new)
Path(__file__).with_name('mbp_gui_en.py').write_text(source, encoding='utf-8')
