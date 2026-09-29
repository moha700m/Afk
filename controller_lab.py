import ctypes
import math
from ctypes import wintypes

from PySide6.QtCore import Qt, QTimer, Signal
from PySide6.QtGui import QColor, QPainter, QPen, QBrush
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QGridLayout, QLabel, QPushButton,
    QComboBox, QFrame, QSlider, QProgressBar
)

JOY_RETURNALL = 0x000000FF
JOYERR_NOERROR = 0
MAXPNAMELEN = 32
MAX_JOYSTICKOEMVXDNAME = 260

XINPUT_GAMEPAD_DPAD_UP = 0x0001
XINPUT_GAMEPAD_DPAD_DOWN = 0x0002
XINPUT_GAMEPAD_DPAD_LEFT = 0x0004
XINPUT_GAMEPAD_DPAD_RIGHT = 0x0008
XINPUT_GAMEPAD_START = 0x0010
XINPUT_GAMEPAD_BACK = 0x0020
XINPUT_GAMEPAD_LEFT_THUMB = 0x0040
XINPUT_GAMEPAD_RIGHT_THUMB = 0x0080
XINPUT_GAMEPAD_LEFT_SHOULDER = 0x0100
XINPUT_GAMEPAD_RIGHT_SHOULDER = 0x0200
XINPUT_GAMEPAD_A = 0x1000
XINPUT_GAMEPAD_B = 0x2000
XINPUT_GAMEPAD_X = 0x4000
XINPUT_GAMEPAD_Y = 0x8000


class JOYCAPSW(ctypes.Structure):
    _fields_ = [
        ("wMid", wintypes.WORD), ("wPid", wintypes.WORD),
        ("szPname", wintypes.WCHAR * MAXPNAMELEN),
        ("wXmin", wintypes.UINT), ("wXmax", wintypes.UINT),
        ("wYmin", wintypes.UINT), ("wYmax", wintypes.UINT),
        ("wZmin", wintypes.UINT), ("wZmax", wintypes.UINT),
        ("wNumButtons", wintypes.UINT),
        ("wPeriodMin", wintypes.UINT), ("wPeriodMax", wintypes.UINT),
        ("wRmin", wintypes.UINT), ("wRmax", wintypes.UINT),
        ("wUmin", wintypes.UINT), ("wUmax", wintypes.UINT),
        ("wVmin", wintypes.UINT), ("wVmax", wintypes.UINT),
        ("wCaps", wintypes.UINT), ("wMaxAxes", wintypes.UINT),
        ("wNumAxes", wintypes.UINT), ("wMaxButtons", wintypes.UINT),
        ("szRegKey", wintypes.WCHAR * 32),
        ("szOEMVxD", wintypes.WCHAR * MAX_JOYSTICKOEMVXDNAME),
    ]


class JOYINFOEX(ctypes.Structure):
    _fields_ = [
        ("dwSize", wintypes.DWORD), ("dwFlags", wintypes.DWORD),
        ("dwXpos", wintypes.DWORD), ("dwYpos", wintypes.DWORD),
        ("dwZpos", wintypes.DWORD), ("dwRpos", wintypes.DWORD),
        ("dwUpos", wintypes.DWORD), ("dwVpos", wintypes.DWORD),
        ("dwButtons", wintypes.DWORD), ("dwButtonNumber", wintypes.DWORD),
        ("dwPOV", wintypes.DWORD), ("dwReserved1", wintypes.DWORD),
        ("dwReserved2", wintypes.DWORD),
    ]


class XINPUT_GAMEPAD(ctypes.Structure):
    _fields_ = [
        ("wButtons", wintypes.WORD),
        ("bLeftTrigger", wintypes.BYTE),
        ("bRightTrigger", wintypes.BYTE),
        ("sThumbLX", wintypes.SHORT), ("sThumbLY", wintypes.SHORT),
        ("sThumbRX", wintypes.SHORT), ("sThumbRY", wintypes.SHORT),
    ]


class XINPUT_STATE(ctypes.Structure):
    _fields_ = [("dwPacketNumber", wintypes.DWORD), ("Gamepad", XINPUT_GAMEPAD)]


def _xinput():
    for dll_name in ("xinput1_4.dll", "xinput9_1_0.dll", "xinput1_3.dll"):
        try:
            dll = ctypes.WinDLL(dll_name)
            dll.XInputGetState.argtypes = [wintypes.DWORD, ctypes.POINTER(XINPUT_STATE)]
            dll.XInputGetState.restype = wintypes.DWORD
            return dll
        except Exception:
            pass
    return None


def _norm_short(value):
    return max(-1.0, min(1.0, value / (32767.0 if value >= 0 else 32768.0)))


class StickView(QWidget):
    def __init__(self, title, parent=None):
        super().__init__(parent)
        self.title = title
        self.x = 0.0
        self.y = 0.0
        self.deadzone = 0.12
        self.setMinimumSize(220, 245)

    def set_value(self, x, y, deadzone=None):
        self.x = max(-1.0, min(1.0, float(x)))
        self.y = max(-1.0, min(1.0, float(y)))
        if deadzone is not None:
            self.deadzone = max(0.0, min(0.5, float(deadzone)))
        self.update()

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        p.setPen(QColor("#DDF8FF"))
        font = p.font()
        font.setPointSize(11)
        font.setBold(True)
        p.setFont(font)
        p.drawText(self.rect().adjusted(0, 2, 0, 0), Qt.AlignTop | Qt.AlignHCenter, self.title)

        size = min(self.width() - 34, self.height() - 62)
        cx = self.width() / 2
        cy = 40 + size / 2
        radius = size / 2

        p.setPen(QPen(QColor("#1B7FBC"), 2))
        p.setBrush(QBrush(QColor(5, 34, 72, 190)))
        p.drawEllipse(int(cx - radius), int(cy - radius), int(size), int(size))

        dz = radius * self.deadzone
        p.setPen(QPen(QColor("#2ACEE8"), 1, Qt.DashLine))
        p.setBrush(Qt.NoBrush)
        p.drawEllipse(int(cx - dz), int(cy - dz), int(dz * 2), int(dz * 2))

        p.setPen(QPen(QColor("#174E79"), 1))
        p.drawLine(int(cx - radius), int(cy), int(cx + radius), int(cy))
        p.drawLine(int(cx), int(cy - radius), int(cx), int(cy + radius))

        px = cx + self.x * radius * 0.88
        py = cy - self.y * radius * 0.88
        p.setPen(QPen(QColor("#CFFFFF"), 3))
        p.setBrush(QBrush(QColor("#21E1F3")))
        p.drawEllipse(int(px - 10), int(py - 10), 20, 20)

        p.setPen(QColor("#8DB9D8"))
        p.drawText(0, self.height() - 28, self.width(), 20,
                   Qt.AlignHCenter, f"X {self.x:+.3f}   Y {self.y:+.3f}")


class StatusPill(QLabel):
    def __init__(self, text="", good=False, parent=None):
        super().__init__(text, parent)
        self.setAlignment(Qt.AlignCenter)
        self.setMinimumHeight(34)
        self.set_status(text, good)

    def set_status(self, text, good=False, warn=False):
        self.setText(text)
        if good:
            bg, border, fg = "#0B6B67", "#24EACD", "#D8FFF9"
        elif warn:
            bg, border, fg = "#6A4B0A", "#F5BE38", "#FFF2C7"
        else:
            bg, border, fg = "#402B51", "#9B6DD0", "#F0E6FF"
        self.setStyleSheet(
            f"background:{bg};border:1px solid {border};border-radius:11px;"
            f"padding:6px 12px;color:{fg};font-weight:700;"
        )


class ButtonLamp(QLabel):
    def __init__(self, name, parent=None):
        super().__init__(name, parent)
        self.setAlignment(Qt.AlignCenter)
        self.setMinimumSize(58, 38)
        self.set_active(False)

    def set_active(self, active):
        if active:
            self.setStyleSheet(
                "background:#1ED6E9;color:#05213B;border:1px solid #6AFAFF;"
                "border-radius:11px;font-weight:800;"
            )
        else:
            self.setStyleSheet(
                "background:#0A3768;color:#82A9CB;border:1px solid #145A91;"
                "border-radius:11px;font-weight:700;"
            )


class ControllerLab(QWidget):
    xinput_slot_detected = Signal(str)

    BUTTONS = [
        ("A", XINPUT_GAMEPAD_A), ("B", XINPUT_GAMEPAD_B),
        ("X", XINPUT_GAMEPAD_X), ("Y", XINPUT_GAMEPAD_Y),
        ("LB", XINPUT_GAMEPAD_LEFT_SHOULDER), ("RB", XINPUT_GAMEPAD_RIGHT_SHOULDER),
        ("LS", XINPUT_GAMEPAD_LEFT_THUMB), ("RS", XINPUT_GAMEPAD_RIGHT_THUMB),
        ("BACK", XINPUT_GAMEPAD_BACK), ("START", XINPUT_GAMEPAD_START),
        ("UP", XINPUT_GAMEPAD_DPAD_UP), ("DOWN", XINPUT_GAMEPAD_DPAD_DOWN),
        ("LEFT", XINPUT_GAMEPAD_DPAD_LEFT), ("RIGHT", XINPUT_GAMEPAD_DPAD_RIGHT),
    ]

    def __init__(self, parent=None):
        super().__init__(parent)
        self.xinput = _xinput()
        self.winmm = None
        try:
            self.winmm = ctypes.WinDLL("winmm.dll")
            self.winmm.joyGetNumDevs.restype = wintypes.UINT
            self.winmm.joyGetDevCapsW.argtypes = [
                wintypes.UINT, ctypes.POINTER(JOYCAPSW), wintypes.UINT
            ]
            self.winmm.joyGetDevCapsW.restype = wintypes.UINT
            self.winmm.joyGetPosEx.argtypes = [
                wintypes.UINT, ctypes.POINTER(JOYINFOEX)
            ]
            self.winmm.joyGetPosEx.restype = wintypes.UINT
        except Exception:
            self.winmm = None

        self.devices = []
        self.deadzone = 0.12
        self.last_xinput_slot = None
        self._build_ui()

        self.timer = QTimer(self)
        self.timer.setInterval(33)
        self.timer.timeout.connect(self._poll)
        self.timer.start()
        self.scan_devices()

    def _card(self):
        f = QFrame()
        f.setObjectName("labCard")
        return f

    def _build_ui(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(8, 10, 8, 10)
        root.setSpacing(14)

        hero = self._card()
        hl = QHBoxLayout(hero)
        hl.setContentsMargins(22, 18, 22, 18)
        title_box = QVBoxLayout()
        title = QLabel("CONTROLLER CENTER")
        title.setObjectName("labTitle")
        sub = QLabel("Live device detection • joystick test • drift & deadzone diagnostics")
        sub.setObjectName("labSubtle")
        title_box.addWidget(title)
        title_box.addWidget(sub)
        hl.addLayout(title_box)
        hl.addStretch()
        self.refresh_btn = QPushButton("Re-scan Controllers")
        self.refresh_btn.setProperty("primary", True)
        self.refresh_btn.clicked.connect(self.scan_devices)
        hl.addWidget(self.refresh_btn)
        root.addWidget(hero)

        device_card = self._card()
        dg = QGridLayout(device_card)
        dg.setContentsMargins(22, 18, 22, 18)
        dg.setHorizontalSpacing(18)
        dg.setVerticalSpacing(12)
        dg.addWidget(QLabel("Windows Device"), 0, 0)
        self.device_combo = QComboBox()
        self.device_combo.setMinimumWidth(360)
        dg.addWidget(self.device_combo, 0, 1, 1, 3)
        self.physical_pill = StatusPill("Physical: scanning...")
        self.xinput_pill = StatusPill("XInput: scanning...")
        self.drift_pill = StatusPill("Drift: --")
        dg.addWidget(self.physical_pill, 1, 1)
        dg.addWidget(self.xinput_pill, 1, 2)
        dg.addWidget(self.drift_pill, 1, 3)
        dg.setColumnStretch(1, 1)
        dg.setColumnStretch(2, 1)
        dg.setColumnStretch(3, 1)
        root.addWidget(device_card)

        live = self._card()
        live_grid = QGridLayout(live)
        live_grid.setContentsMargins(22, 18, 22, 18)
        live_grid.setHorizontalSpacing(18)
        live_grid.setVerticalSpacing(14)

        self.left_stick = StickView("LEFT STICK")
        self.right_stick = StickView("RIGHT STICK")
        live_grid.addWidget(self.left_stick, 0, 0, 3, 1)
        live_grid.addWidget(self.right_stick, 0, 1, 3, 1)

        trigger_box = QFrame()
        trigger_layout = QVBoxLayout(trigger_box)
        trigger_layout.setContentsMargins(8, 0, 8, 0)
        trigger_title = QLabel("TRIGGERS")
        trigger_title.setObjectName("labSection")
        trigger_layout.addWidget(trigger_title)
        self.lt_bar = QProgressBar()
        self.lt_bar.setRange(0, 1000)
        self.lt_bar.setFormat("L2  %p%")
        self.rt_bar = QProgressBar()
        self.rt_bar.setRange(0, 1000)
        self.rt_bar.setFormat("R2  %p%")
        trigger_layout.addWidget(self.lt_bar)
        trigger_layout.addWidget(self.rt_bar)

        dz_row = QHBoxLayout()
        dz_row.addWidget(QLabel("Test Deadzone"))
        self.deadzone_slider = QSlider(Qt.Horizontal)
        self.deadzone_slider.setRange(0, 30)
        self.deadzone_slider.setValue(12)
        self.deadzone_value = QLabel("12%")
        self.deadzone_slider.valueChanged.connect(self._deadzone_changed)
        dz_row.addWidget(self.deadzone_slider, 1)
        dz_row.addWidget(self.deadzone_value)
        trigger_layout.addLayout(dz_row)

        self.raw_label = QLabel("Raw input: waiting...")
        self.raw_label.setObjectName("labMono")
        self.raw_label.setWordWrap(True)
        trigger_layout.addWidget(self.raw_label)
        trigger_layout.addStretch()
        live_grid.addWidget(trigger_box, 0, 2, 3, 1)
        live_grid.setColumnStretch(0, 1)
        live_grid.setColumnStretch(1, 1)
        live_grid.setColumnStretch(2, 1)
        root.addWidget(live)

        buttons_card = self._card()
        bl = QVBoxLayout(buttons_card)
        bl.setContentsMargins(22, 18, 22, 18)
        sec = QLabel("LIVE BUTTON TEST")
        sec.setObjectName("labSection")
        bl.addWidget(sec)
        grid = QGridLayout()
        grid.setHorizontalSpacing(10)
        grid.setVerticalSpacing(10)
        self.button_lamps = {}
        for i, (name, mask) in enumerate(self.BUTTONS):
            lamp = ButtonLamp(name)
            self.button_lamps[mask] = lamp
            grid.addWidget(lamp, i // 7, i % 7)
        bl.addLayout(grid)
        self.pov_label = QLabel("POV / D-Pad: CENTER")
        self.pov_label.setObjectName("labSubtle")
        bl.addWidget(self.pov_label)
        root.addWidget(buttons_card)
        root.addStretch()

    def _deadzone_changed(self, value):
        self.deadzone = value / 100.0
        self.deadzone_value.setText(f"{value}%")
        self.left_stick.set_value(self.left_stick.x, self.left_stick.y, self.deadzone)
        self.right_stick.set_value(self.right_stick.x, self.right_stick.y, self.deadzone)

    def scan_devices(self):
        current = self.device_combo.currentText()
        self.devices = []

        if self.winmm is not None:
            count = int(self.winmm.joyGetNumDevs())
            for joy_id in range(min(count, 32)):
                caps = JOYCAPSW()
                rc = self.winmm.joyGetDevCapsW(
                    joy_id, ctypes.byref(caps), ctypes.sizeof(caps)
                )
                if rc != JOYERR_NOERROR:
                    continue
                info = JOYINFOEX()
                info.dwSize = ctypes.sizeof(info)
                info.dwFlags = JOY_RETURNALL
                if self.winmm.joyGetPosEx(joy_id, ctypes.byref(info)) != JOYERR_NOERROR:
                    continue
                name = caps.szPname.strip() or f"Joystick {joy_id}"
                self.devices.append({
                    "id": joy_id,
                    "name": name,
                    "axes": int(caps.wNumAxes),
                    "buttons": int(caps.wNumButtons),
                })

        self.device_combo.blockSignals(True)
        self.device_combo.clear()
        if self.devices:
            for dev in self.devices:
                self.device_combo.addItem(
                    f"{dev['name']}  •  {dev['axes']} axes / {dev['buttons']} buttons",
                    dev["id"]
                )
            idx = self.device_combo.findText(current)
            if idx >= 0:
                self.device_combo.setCurrentIndex(idx)
            self.physical_pill.set_status(
                f"Physical: {len(self.devices)} detected", good=True
            )
        else:
            self.device_combo.addItem("No WinMM device name available")
            self.physical_pill.set_status("Physical: XInput fallback", warn=True)
        self.device_combo.blockSignals(False)
        self._poll()

    def _read_xinput(self):
        if self.xinput is None:
            return None, None
        for slot in range(4):
            state = XINPUT_STATE()
            if self.xinput.XInputGetState(slot, ctypes.byref(state)) == 0:
                return slot, state
        return None, None

    def _read_winmm(self):
        if self.winmm is None or not self.devices:
            return None
        idx = self.device_combo.currentIndex()
        if idx < 0 or idx >= len(self.devices):
            idx = 0
        joy_id = self.devices[idx]["id"]
        info = JOYINFOEX()
        info.dwSize = ctypes.sizeof(info)
        info.dwFlags = JOY_RETURNALL
        if self.winmm.joyGetPosEx(joy_id, ctypes.byref(info)) != JOYERR_NOERROR:
            return None
        return info

    def _poll(self):
        slot, state = self._read_xinput()

        if state is not None:
            if slot != self.last_xinput_slot:
                self.last_xinput_slot = slot
                self.xinput_slot_detected.emit(str(slot))
            gp = state.Gamepad
            lx, ly = _norm_short(gp.sThumbLX), _norm_short(gp.sThumbLY)
            rx, ry = _norm_short(gp.sThumbRX), _norm_short(gp.sThumbRY)
            lt, rt = gp.bLeftTrigger / 255.0, gp.bRightTrigger / 255.0

            self.left_stick.set_value(lx, ly, self.deadzone)
            self.right_stick.set_value(rx, ry, self.deadzone)
            self.lt_bar.setValue(int(lt * 1000))
            self.rt_bar.setValue(int(rt * 1000))

            buttons = int(gp.wButtons)
            for mask, lamp in self.button_lamps.items():
                lamp.set_active(bool(buttons & mask))

            dirs = []
            if buttons & XINPUT_GAMEPAD_DPAD_UP:
                dirs.append("UP")
            if buttons & XINPUT_GAMEPAD_DPAD_DOWN:
                dirs.append("DOWN")
            if buttons & XINPUT_GAMEPAD_DPAD_LEFT:
                dirs.append("LEFT")
            if buttons & XINPUT_GAMEPAD_DPAD_RIGHT:
                dirs.append("RIGHT")
            self.pov_label.setText("POV / D-Pad: " + (" + ".join(dirs) if dirs else "CENTER"))

            lmag = math.hypot(lx, ly)
            rmag = math.hypot(rx, ry)
            mag = max(lmag, rmag)
            if mag <= self.deadzone:
                self.drift_pill.set_status(f"Center: {mag * 100:.1f}% • OK", good=True)
            elif mag <= max(self.deadzone + 0.05, 0.18):
                self.drift_pill.set_status(f"Center: {mag * 100:.1f}% • CHECK", warn=True)
            else:
                self.drift_pill.set_status(f"Input: {mag * 100:.1f}% • MOVING", good=True)

            self.xinput_pill.set_status(f"XInput: Slot {slot}", good=True)
            self.raw_label.setText(
                f"LX {gp.sThumbLX:+6d}   LY {gp.sThumbLY:+6d}\n"
                f"RX {gp.sThumbRX:+6d}   RY {gp.sThumbRY:+6d}\n"
                f"L2 {gp.bLeftTrigger:3d}   R2 {gp.bRightTrigger:3d}"
            )
            return

        self.last_xinput_slot = None
        self.xinput_pill.set_status("XInput: NOT FOUND")
        self.left_stick.set_value(0, 0, self.deadzone)
        self.right_stick.set_value(0, 0, self.deadzone)
        self.lt_bar.setValue(0)
        self.rt_bar.setValue(0)
        for lamp in self.button_lamps.values():
            lamp.set_active(False)

        info = self._read_winmm()
        if info is not None:
            self.raw_label.setText(
                "Windows sees a DirectInput/HID controller, but no XInput slot is active.\n"
                f"Raw X {info.dwXpos}  Y {info.dwYpos}  Z {info.dwZpos}  R {info.dwRpos}"
            )
            self.drift_pill.set_status("DirectInput detected", warn=True)
        else:
            self.raw_label.setText("Connect a controller by USB or Bluetooth, then press Re-scan Controllers.")
            self.drift_pill.set_status("Drift: --")


CONTROLLER_LAB_QSS = """
QFrame#labCard {
    background: qlineargradient(x1:0,y1:0,x2:1,y2:1, stop:0 rgba(6,44,91,235), stop:1 rgba(5,31,69,235));
    border: 1px solid #176FA9;
    border-radius: 18px;
}
QLabel#labTitle {
    color: white;
    font-size: 20px;
    font-weight: 900;
    letter-spacing: 1px;
}
QLabel#labSection {
    color: #E8FBFF;
    font-size: 14px;
    font-weight: 800;
}
QLabel#labSubtle {
    color: #7EAACB;
    font-size: 12px;
}
QLabel#labMono {
    color: #9CCBE7;
    font-family: Consolas;
    font-size: 12px;
}
QProgressBar {
    min-height: 25px;
    background: #082F5E;
    border: 1px solid #145D91;
    border-radius: 9px;
    color: white;
    text-align: center;
    font-weight: 700;
}
QProgressBar::chunk {
    background: #1ED8E9;
    border-radius: 8px;
}
"""
