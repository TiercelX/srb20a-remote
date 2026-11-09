#!/usr/bin/python3
"""Native GTK controller for the local SR-B20A gateway on MBP."""
import json
import os
import socket
import threading
import uuid
from pathlib import Path
import gi
gi.require_version('Gtk', '4.0')
from gi.repository import Gtk, GLib

SOCKET = Path(os.environ.get('XDG_RUNTIME_DIR', '/run/user/' + str(os.getuid()))) / 'bluetooth-gateway/control.sock'


def request(command, value=None):
    data = {'version': 1, 'device': 'sr-b20a', 'command': command, 'request_id': str(uuid.uuid4())}
    if value is not None:
        data['value'] = str(value)
    sent = False
    try:
        with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as client:
            client.settimeout(330)
            client.connect(str(SOCKET))
            sent = True
            client.sendall((json.dumps(data) + '\n').encode())
            with client.makefile('rb') as stream:
                line = stream.readline(262145)
                if not line or len(line) > 262144:
                    raise ValueError('网关返回结果为空或过长')
                result = json.loads(line)
        if not result.get('ok'):
            error = result.get('error') or ((result.get('attempt_history') or [{}])[-1].get('error') or {})
            message = error.get('message') or '操作未确认'
            if result.get('setter_attempted') or result.get('uncertain_after_write') or result.get('uncertain_completion'):
                message += '；命令可能已发出，请先刷新状态'
            return None, message
        return result, None
    except Exception as exc:
        return None, str(exc) + ('；结果可能未知，请先刷新状态' if sent else '')


def decorate(state):
    raw = bytes.fromhex(state['raw_hex'])
    state['program'] = 'stereo' if raw[13] == 1 else ({10: 'standard', 3: 'movie', 12: 'game'}.get(raw[14]) if raw[13] == 0 else None)
    state['three_d'] = bool(raw[15] & 0x40)
    return state


class Window(Gtk.ApplicationWindow):
    def __init__(self, app):
        super().__init__(application=app, title='SR-B20A 控制')
        self.set_default_size(560, 590)
        self.state = None
        self.busy = False
        self.widgets = []
        outer = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12)
        outer.set_margin_top(20); outer.set_margin_bottom(20); outer.set_margin_start(20); outer.set_margin_end(20)
        self.set_child(outer)
        top = Gtk.Box(spacing=8); outer.append(top)
        title = Gtk.Label(label='SR-B20A', xalign=0); title.add_css_class('title-1'); title.set_hexpand(True); top.append(title)
        self.refresh = Gtk.Button(label='刷新状态'); self.refresh.connect('clicked', lambda *_: self.execute('status')); top.append(self.refresh)
        self.info = Gtk.Label(label='正在读取状态…', xalign=0); outer.append(self.info)
        grid = Gtk.Grid(column_spacing=8, row_spacing=10); outer.append(grid)
        def row(n, title):
            label = Gtk.Label(label=title, xalign=0); label.set_hexpand(True); grid.attach(label, 0, n, 1, 1)
        def button(n, col, label, command, value):
            b = Gtk.Button(label=label); b.connect('clicked', lambda *_: self.execute(command, value)); grid.attach(b, col, n, 1, 1); self.widgets.append(b); return b
        row(0,'电源'); self.on = button(0,1,'开机','power','on'); button(0,2,'待机','power','off')
        row(1,'输入'); button(1,1,'电视','input','tv'); button(1,2,'光纤','input','optical'); button(1,3,'蓝牙','input','bluetooth')
        row(2,'音量'); self.volume = Gtk.SpinButton.new_with_range(0,50,1); grid.attach(self.volume,1,2,1,1); self.widgets.append(self.volume)
        apply = Gtk.Button(label='设置'); apply.connect('clicked',lambda *_:self.execute('volume',str(self.volume.get_value_as_int()))); grid.attach(apply,2,2,1,1); self.widgets.append(apply)
        row(3,'低音炮'); self.sub = Gtk.Label(label='--'); grid.attach(self.sub,1,3,1,1); button(3,2,'−','subwoofer','down'); button(3,3,'＋','subwoofer','up')
        row(4,'声音模式');
        for i,(label,value) in enumerate((('立体声','stereo'),('标准','standard'),('电影','movie'),('游戏','game')),1): button(4,i,label,'program',value)
        self.toggle_buttons = {}
        for n,(key,label) in enumerate((('three-d','3D 环绕'),('mute','静音'),('clear-voice','Clear Voice'),('bass-extension','Bass Extension')),5):
            row(n,label); b=Gtk.Button(label='--'); b.connect('clicked',lambda _,k=key:self.toggle(k)); grid.attach(b,1,n,1,1); self.widgets.append(b); self.toggle_buttons[key]=b
        row(9,'指示灯'); button(9,1,'关','dimmer','off'); button(9,2,'暗','dimmer','dim'); button(9,3,'亮','dimmer','bright')
        self.message=Gtk.Label(label='通过本机蓝牙网关连接',xalign=0,wrap=True); outer.append(self.message)
        GLib.idle_add(self.execute,'status')

    def toggle(self, command):
        if self.state is None: return
        field={'three-d':'three_d','mute':'mute','clear-voice':'clear_voice_bit','bass-extension':'bass_extension_bit'}[command]
        self.execute(command,'off' if self.state[field] else 'on')

    def set_busy(self,busy):
        self.busy=busy
        for widget in self.widgets: widget.set_sensitive(not busy and self.state is not None)
        self.on.set_sensitive(not busy)
        self.refresh.set_sensitive(not busy)
        if self.state and self.state.get('program')=='stereo': self.toggle_buttons['three-d'].set_sensitive(False)

    def execute(self,command,value=None):
        if self.busy: return False
        self.set_busy(True); self.message.set_text('正在连接音箱，请稍候…')
        def work():
            result,error=request(command,value)
            GLib.idle_add(self.finish,command,result,error)
        threading.Thread(target=work,daemon=True).start()
        return False

    def finish(self,command,result,error):
        if error:
            self.state=None; self.info.set_text('状态未知'); self.message.set_text('操作未确认：'+error+'。请先刷新状态。')
        else:
            self.state=decorate(result.get('after') or result['before'])
            s=self.state
            names={'stereo':'立体声','standard':'标准','movie':'电影','game':'游戏'}
            self.info.set_text(('开机' if s['power'] else '待机')+'  ·  输入：'+str(s.get('input') or '未知')+'  ·  模式：'+names.get(s['program'],'未知')+'  ·  指示灯：'+str(s.get('dimmer') or '未知'))
            self.volume.set_value(s['volume_raw']); sub=s['subwoofer_raw']; self.sub.set_text(str((sub-16)//4) if sub in range(0,33,4) else str(sub))
            for key,field in (('three-d','three_d'),('mute','mute'),('clear-voice','clear_voice_bit'),('bass-extension','bass_extension_bit')):
                self.toggle_buttons[key].set_label('开启' if s[field] else '关闭')
            self.message.set_text(('状态已更新' if command=='status' else '操作已确认')+' · 请求 ID：'+result.get('gateway',{}).get('request_id','--'))
        self.set_busy(False)
        return False


class App(Gtk.Application):
    def __init__(self): super().__init__(application_id='local.srb20a.Controller')
    def do_activate(self):
        window=self.props.active_window or Window(self)
        window.present()

if __name__=='__main__':
    App().run(None)
