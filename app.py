import ctypes
import json
import math
import os
import queue
import random
import subprocess
import tempfile
import threading
import time
import urllib.request
import winreg
from ctypes import wintypes
from pathlib import Path

import cv2
import dxcam
import numpy as np
from PySide6.QtCore import Qt, QThread, Signal, QSize
from PySide6.QtGui import QColor, QPainter, QPen, QBrush, QFont
from PySide6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, QGridLayout,
    QLabel, QPushButton, QFrame, QSlider, QLineEdit, QComboBox, QColorDialog,
    QTabWidget, QButtonGroup, QAbstractButton, QMessageBox, QScrollArea,
    QSpinBox, QDoubleSpinBox
)

APP_NAME = "AFK Controller"
APP_VERSION = "1.0.0"
APP_DIR = Path(os.getenv("APPDATA", str(Path.home()))) / "AFKController"
CONFIG_PATH = APP_DIR / "settings.json"
PROFILES_DIR = APP_DIR / "profiles"

VIGEM_URL = "https://github.com/nefarius/ViGEmBus/releases/download/v1.22.0/ViGEmBus_1.22.0_x64_x86_arm64.exe"
HIDHIDE_URL = "https://github.com/nefarius/HidHide/releases/download/v1.5.230.0/HidHide_1.5.230_x64.exe"

DEFAULTS = {
    "enable_aim_assist": True,
    "enable_controller_input": True,
    "enable_virtual_controller": True,
    "ds4_output": False,
    "human_movement": False,
    "human_strength": 0.30,
    "target_color": "#E600FF",
    "color_tolerance": 20,
    "aim_trigger": "L2 + R2",
    "aim_bone": "Chest",
    "controller_slot": "Auto",
    "fov": 180,
    "aim_strength": 0.26,
    "smoothing": 0.42,
    "max_correction": 7500,
    "sticky_aim": True,
    "sticky_time_ms": 140,
    "sticky_strength": 0.55,
    "anti_recoil": True,
    "recoil_vertical": 20,
    "recoil_horizontal": 0,
    "hair_triggers": True,
    "auto_hold_breath": True,
    "auto_ping": False,
    "bunny_hop": True,
    "slide_cancel": True,
    "rapid_fire_rps": 0,
    "yy_spam_ms": 22,
    "fire_button": "R2",
    "block_vibration": True,
    "hide_controller_mode": "Auto",
    "capture_fps": 120,
}

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


class XINPUT_GAMEPAD(ctypes.Structure):
    _fields_ = [
        ("wButtons", wintypes.WORD),
        ("bLeftTrigger", wintypes.BYTE),
        ("bRightTrigger", wintypes.BYTE),
        ("sThumbLX", wintypes.SHORT),
        ("sThumbLY", wintypes.SHORT),
        ("sThumbRX", wintypes.SHORT),
        ("sThumbRY", wintypes.SHORT),
    ]


class XINPUT_STATE(ctypes.Structure):
    _fields_ = [("dwPacketNumber", wintypes.DWORD), ("Gamepad", XINPUT_GAMEPAD)]


def clamp(v, lo, hi):
    return max(lo, min(hi, v))


def normalize_hex(value: str) -> str:
    value = value.strip().upper()
    if not value.startswith("#"):
        value = "#" + value
    if len(value) != 7:
        raise ValueError("Hex color must be #RRGGBB")
    int(value[1:], 16)
    return value


def hex_to_rgb(value: str):
    value = normalize_hex(value)
    return tuple(int(value[i:i + 2], 16) for i in (1, 3, 5))


def atomic_save_json(path: Path, data: dict):
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    os.replace(tmp, path)


def load_settings() -> dict:
    APP_DIR.mkdir(parents=True, exist_ok=True)
    PROFILES_DIR.mkdir(parents=True, exist_ok=True)
    data = dict(DEFAULTS)
    try:
        if CONFIG_PATH.exists():
            data.update(json.loads(CONFIG_PATH.read_text(encoding="utf-8")))
    except Exception:
        pass
    return data


def service_exists(name: str) -> bool:
    try:
        with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, rf"SYSTEM\CurrentControlSet\Services\{name}"):
            return True
    except OSError:
        return False


def xinput_dll():
    for dll_name in ("xinput1_4.dll", "xinput9_1_0.dll", "xinput1_3.dll"):
        try:
            dll = ctypes.WinDLL(dll_name)
            dll.XInputGetState.argtypes = [wintypes.DWORD, ctypes.POINTER(XINPUT_STATE)]
            dll.XInputGetState.restype = wintypes.DWORD
            return dll
        except Exception:
            pass
    raise RuntimeError("XInput is not available on this Windows installation")


def run_as_admin(exe: Path, args: str = ""):
    return ctypes.windll.shell32.ShellExecuteW(None, "runas", str(exe), args, None, 1) > 32


def download_file(url: str, target: Path):
    req = urllib.request.Request(url, headers={"User-Agent": f"{APP_NAME}/{APP_VERSION}"})
    with urllib.request.urlopen(req, timeout=90) as response, open(target, "wb") as out:
        while True:
            chunk = response.read(262144)
            if not chunk:
                break
            out.write(chunk)


def open_hidhide():
    candidates = [
        Path(os.getenv("ProgramFiles", r"C:\Program Files")) / "Nefarius Software Solutions" / "HidHide" / "HidHideClient.exe",
        Path(os.getenv("ProgramFiles", r"C:\Program Files")) / "Nefarius Software Solutions e.U" / "HidHide" / "HidHideClient.exe",
    ]
    for path in candidates:
        if path.exists():
            subprocess.Popen([str(path)])
            return True
    return False


class Switch(QAbstractButton):
    def __init__(self, checked=False, parent=None):
        super().__init__(parent)
        self.setCheckable(True)
        self.setChecked(checked)
        self.setCursor(Qt.PointingHandCursor)
        self.setFixedSize(60, 32)

    def sizeHint(self):
        return QSize(60, 32)

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        bg = QColor("#20DDF2") if self.isChecked() else QColor("#173C67")
        p.setPen(Qt.NoPen)
        p.setBrush(QBrush(bg))
        p.drawRoundedRect(0, 0, self.width(), self.height(), 16, 16)
        knob = QColor("#FFFFFF")
        p.setBrush(QBrush(knob))
        diameter = 24
        x = self.width() - diameter - 4 if self.isChecked() else 4
        p.drawEllipse(x, 4, diameter, diameter)


class ChoiceButtons(QWidget):
    changed = Signal(str)

    def __init__(self, values, selected=None, columns=None, parent=None):
        super().__init__(parent)
        self.group = QButtonGroup(self)
        self.group.setExclusive(True)
        self.buttons = {}
        layout = QGridLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setHorizontalSpacing(12)
        layout.setVerticalSpacing(10)
        columns = columns or len(values)
        for i, value in enumerate(values):
            btn = QPushButton(value)
            btn.setCheckable(True)
            btn.setProperty("choice", True)
            btn.setMinimumHeight(46)
            self.group.addButton(btn)
            self.buttons[value] = btn
            layout.addWidget(btn, i // columns, i % columns)
            if value == selected:
                btn.setChecked(True)
        self.group.buttonClicked.connect(lambda b: self.changed.emit(b.text()))

    def value(self):
        btn = self.group.checkedButton()
        return btn.text() if btn else ""

    def set_value(self, value):
        if value in self.buttons:
            self.buttons[value].setChecked(True)


class EngineThread(QThread):
    telemetry = Signal(dict)
    status = Signal(str)
    error = Signal(str)

    def __init__(self, settings: dict):
        super().__init__()
        self.settings = dict(settings)
        self._lock = threading.Lock()
        self._stop = threading.Event()
        self.xinput = None
        self.slot = None
        self.virtual = None
        self.vg = None
        self.is_ds4 = False
        self.camera = None
        self.smooth_x = 0.0
        self.smooth_y = 0.0
        self.last_target = None
        self.last_target_ts = 0.0
        self.last_fire = False
        self.prev_buttons = 0
        self.ping_until = 0.0
        self.slide_until = 0.0
        self.yy_phase = 0
        self.yy_until = 0.0
        self.hop_phase = False
        self.last_hop_toggle = 0.0
        self.rapid_phase = False
        self.last_rapid_toggle = 0.0
        self.human_phase = 0.0

    def stop(self):
        self._stop.set()

    def update_settings(self, settings: dict):
        with self._lock:
            old_ds4 = self.settings.get("ds4_output")
            old_virtual = self.settings.get("enable_virtual_controller")
            self.settings = dict(settings)
            if old_ds4 != self.settings.get("ds4_output") or old_virtual != self.settings.get("enable_virtual_controller"):
                self._reset_virtual()

    def _snapshot(self):
        with self._lock:
            return dict(self.settings)

    def _find_slot(self, requested):
        if self.xinput is None:
            self.xinput = xinput_dll()
        slots = range(4) if requested == "Auto" else [int(requested)]
        for slot in slots:
            st = XINPUT_STATE()
            if self.xinput.XInputGetState(slot, ctypes.byref(st)) == 0:
                return slot
        return None

    def _read_state(self, slot):
        st = XINPUT_STATE()
        if slot is None or self.xinput.XInputGetState(slot, ctypes.byref(st)) != 0:
            return None
        return st

    def _reset_virtual(self):
        if self.virtual is not None:
            try:
                self.virtual.reset()
                self.virtual.update()
            except Exception:
                pass
        self.virtual = None
        self.vg = None

    def _ensure_virtual(self, settings):
        if not settings["enable_virtual_controller"]:
            self._reset_virtual()
            return False
        if self.virtual is not None and self.is_ds4 == bool(settings["ds4_output"]):
            return True
        if not service_exists("ViGEmBus"):
            raise RuntimeError("ViGEmBus is missing. Install it from the Drivers button, reboot once, then start again.")
        self._reset_virtual()
        try:
            import vgamepad as vg
        except Exception as e:
            if "VIGEM_ERROR_BUS_NOT_FOUND" in str(e):
                raise RuntimeError("ViGEmBus is installed but the bus is not available. Reboot Windows once and try again.") from e
            raise
        self.vg = vg
        self.is_ds4 = bool(settings["ds4_output"])
        self.virtual = vg.VDS4Gamepad() if self.is_ds4 else vg.VX360Gamepad()
        return True

    @staticmethod
    def _button(st, mask):
        return bool(st.Gamepad.wButtons & mask)

    def _trigger_active(self, st, mode):
        lt = st.Gamepad.bLeftTrigger > 45
        rt = st.Gamepad.bRightTrigger > 45
        lb = self._button(st, XINPUT_GAMEPAD_LEFT_SHOULDER)
        rb = self._button(st, XINPUT_GAMEPAD_RIGHT_SHOULDER)
        return {
            "L2": lt, "R2": rt, "L2 + R2": lt and rt,
            "L1": lb, "R1": rb, "L1 + R1": lb and rb,
        }.get(mode, lt)

    def _fire_active(self, st, settings):
        if settings.get("fire_button") == "R1":
            return self._button(st, XINPUT_GAMEPAD_RIGHT_SHOULDER)
        return st.Gamepad.bRightTrigger > 45

    def _screen_target(self, settings):
        if not settings["enable_aim_assist"]:
            return 0, 0, 0, False
        if self.camera is None:
            self.camera = dxcam.create(output_color="BGR")
        user32 = ctypes.windll.user32
        w = user32.GetSystemMetrics(0)
        h = user32.GetSystemMetrics(1)
        fov = int(clamp(settings["fov"], 50, 600))
        cx, cy = w // 2, h // 2
        left, top, right, bottom = max(0, cx - fov), max(0, cy - fov), min(w, cx + fov), min(h, cy + fov)
        frame = self.camera.grab(region=(left, top, right, bottom))
        if frame is None:
            return 0, 0, 0, False

        r, g, b = hex_to_rgb(settings["target_color"])
        target = np.array([b, g, r], dtype=np.int16)
        diff = np.abs(frame.astype(np.int16) - target)
        tol = int(clamp(settings["color_tolerance"], 0, 100))
        mask = (np.max(diff, axis=2) <= tol).astype(np.uint8) * 255
        mask = cv2.morphologyEx(mask, cv2.MORPH_OPEN, np.ones((3, 3), np.uint8))
        count, labels, stats, centroids = cv2.connectedComponentsWithStats(mask, 8)
        if count <= 1:
            return self._sticky_fallback(settings)

        fc_x, fc_y = frame.shape[1] / 2, frame.shape[0] / 2
        best = None
        for i in range(1, count):
            x, y, ww, hh, area = stats[i]
            if area < 4 or area > 18000:
                continue
            tx = x + ww / 2
            bone = settings["aim_bone"]
            if bone == "Head":
                ty = y + hh * 0.20
            elif bone == "Random":
                ty = y + hh * random.uniform(0.20, 0.52)
            else:
                ty = y + hh * 0.45
            dist = math.hypot(tx - fc_x, ty - fc_y)
            if dist > fov:
                continue
            score = dist - min(area, 250) * 0.03
            if best is None or score < best[0]:
                best = (score, tx, ty, dist, area)

        if best is None:
            return self._sticky_fallback(settings)

        _, tx, ty, dist, area = best
        dx, dy = tx - fc_x, ty - fc_y
        smooth = float(clamp(settings["smoothing"], 0.01, 1.0))
        self.smooth_x += (dx - self.smooth_x) * smooth
        self.smooth_y += (dy - self.smooth_y) * smooth
        strength = float(clamp(settings["aim_strength"], 0.01, 1.0))
        max_corr = int(clamp(settings["max_correction"], 500, 20000))
        ox = int(clamp((self.smooth_x / fov) * 32767 * strength, -max_corr, max_corr))
        oy = int(clamp(-(self.smooth_y / fov) * 32767 * strength, -max_corr, max_corr))

        if settings["human_movement"]:
            hs = float(clamp(settings["human_strength"], 0.0, 1.0))
            self.human_phase += 0.13 + hs * 0.08
            ox += int(math.sin(self.human_phase) * max_corr * 0.025 * hs)
            oy += int(math.sin(self.human_phase * 0.77 + 1.2) * max_corr * 0.018 * hs)

        confidence = int(clamp((1 - dist / max(fov, 1)) * 78 + min(1, area / 60) * 22, 0, 100))
        self.last_target = (ox, oy, confidence)
        self.last_target_ts = time.monotonic()
        return ox, oy, confidence, True

    def _sticky_fallback(self, settings):
        if settings.get("sticky_aim") and self.last_target:
            elapsed = (time.monotonic() - self.last_target_ts) * 1000
             max_ms = int(settings.get("sticky_time_ms", 140))
            if elapsed < max_ms:
                decay = (1 - elapsed / max_ms) * float(settings.get("sticky_strength", 0.55))
                return int(self.last_target[0] * decay), int(self.last_target[1] * decay), int(self.last_target[2] * decay), True
        self.smooth_x *= 0.62
        self.smooth_y *= 0.62
        return 0, 0, 0, False

    def _apply_macros(self, st, settings, buttons, lt, rt, now, aim_active, fire_active):
        # Hair triggers
        if settings["hair_triggers"]:
            if lt > 5:
                lt = 255
            if rt > 5:
                rt = 255

        # Auto hold breath: default COD focus is LS in the supplied AFK script.
        if settings["auto_hold_breath"] and aim_active:
            buttons |= XINPUT_GAMEPAD_LEFT_THUMB

        # Auto ping on first fire press while aiming.
        if settings["auto_ping"] and aim_active and fire_active and not self.last_fire:
            self.ping_until = now + 0.055
        if now < self.ping_until:
            buttons |= XINPUT_GAMEPAD_DPAD_UP

        # Bunny hop while jump is held.
        if settings["bunny_hop"] and (st.Gamepad.wButtons & XINPUT_GAMEPAD_A):
            if now - self.last_hop_toggle >= 0.085:
                self.hop_phase = not self.hop_phase
                self.last_hop_toggle = now
            if not self.hop_phase:
                buttons &= ~XINPUT_GAMEPAD_A

        # Slide cancel: after quick B release, pulse sprint.
        was_b = bool(self.prev_buttons & XINPUT_GAMEPAD_B)
        is_b = bool(st.Gamepad.wButtons & XINPUT_GAMEPAD_B)
        if settings["slide_cancel"] and was_b and not is_b and not aim_active and not fire_active:
            self.slide_until = now + 0.11
        if now < self.slide_until:
            buttons |= XINPUT_GAMEPAD_LEFT_THUMB

        # YY spam while sprint is held, mirroring the GPC behavior.
        yy_ms = int(settings.get("yy_spam_ms", 0))
        if yy_ms > 0 and (st.Gamepad.wButtons & XINPUT_GAMEPAD_LEFT_THUMB) and not aim_active and not fire_active:
            period = max(0.03, yy_ms / 1000.0)
            if now >= self.yy_until:
                self.yy_phase = (self.yy_phase + 1) % 4
                self.yy_until = now + period
            if self.yy_phase in (0, 2):
                buttons |= XINPUT_GAMEPAD_Y
            else:
                buttons &= ~XINPUT_GAMEPAD_Y

        # Rapid fire works for the configured primary fire button.
        rps = int(settings.get("rapid_fire_rps", 0))
        if rps > 0 and fire_active:
            half = 0.5 / max(1, rps)
            if now - self.last_rapid_toggle >= half:
                self.rapid_phase = not self.rapid_phase
                self.last_rapid_toggle = now
            if settings.get("fire_button") == "R1":
                if self.rapid_phase:
                    buttons |= XINPUT_GAMEPAD_RIGHT_SHOULDER
                else:
                    buttons &= ~XINPUT_GAMEPAD_RIGHT_SHOULDER
            else:
                rt = 255 if self.rapid_phase else 0

        self.last_fire = fire_active
        self.prev_buttons = st.Gamepad.wButtons
        return buttons, lt, rt

    def _output_x360(self, buttons, lt, rt, lx, ly, rx, ry):
        vg = self.vg
        mapping = [
            (XINPUT_GAMEPAD_DPAD_UP, vg.XUSB_BUTTON.XUSB_GAMEPAD_DPAD_UP),
            (XINPUT_GAMEPAD_DPAD_DOWN, vg.XUSB_BUTTON.XUSB_GAMEPAD_DPAD_DOWN),
            (XINPUT_GAMEPAD_DPAD_LEFT, vg.XUSB_BUTTON.XUSB_GAMEPAD_DPAD_LEFT),
            (XINPUT_GAMEPAD_DPAD_RIGHT, vg.XUSB_BUTTON.XUSB_GAMEPAD_DPAD_RIGHT),
            (XINPUT_GAMEPAD_START, vg.XUSB_BUTTON.XUSB_GAMEPAD_START),
            (XINPUT_GAMEPAD_BACK, vg.XUSB_BUTTON.XUSB_GAMEPAD_BACK),
            (XINPUT_GAMEPAD_LEFT_THUMB, vg.XUSB_BUTTON.XUSB_GAMEPAD_LEFT_THUMB),
            (XINPUT_GAMEPAD_RIGHT_THUMB, vg.XUSB_BUTTON.XUSB_GAMEPAD_RIGHT_THUMB),
            (XINPUT_GAMEPAD_LEFT_SHOULDER, vg.XUSB_BUTTON.XUSB_GAMEPAD_LEFT_SHOULDER),
            (XINPUT_GAMEPAD_RIGHT_SHOULDER, vg.XUSB_BUTTON.XUSB_GAMEPAD_RIGHT_SHOULDER),
            (XINPUT_GAMEPAD_A, vg.XUSB_BUTTON.XUSB_GAMEPAD_A),
            (XINPUT_GAMEPAD_B, vg.XUSB_BUTTON.XUSB_GAMEPAD_B),
            (XINPUT_GAMEPAD_X, vg.XUSB_BUTTON.XUSB_GAMEPAD_X),
            (XINPUT_GAMEPAD_Y, vg.XUSB_BUTTON.XUSB_GAMEPAD_Y),
        ]
        for mask, out_btn in mapping:
            if buttons & mask:
                self.virtual.press_button(button=out_btn)
            else:
                self.virtual.release_button(button=out_btn)
        self.virtual.left_trigger(value=int(lt))
        self.virtual.right_trigger(value=int(rt))
        self.virtual.left_joystick(x_value=int(lx), y_value=int(ly))
        self.virtual.right_joystick(x_value=int(rx), y_value=int(ry))
        self.virtual.update()

    def _output_ds4(self, buttons, lt, rt, lx, ly, rx, ry):
        vg = self.vg
        mapping = [
            (XINPUT_GAMEPAD_START, vg.DS4_BUTTONS.DS4_BUTTON_OPTIONS),
            (XINPUT_GAMEPAD_BACK, vg.DS4_BUTTONS.DS4_BUTTON_SHARE),
            (XINPUT_GAMEPAD_LEFT_THUMB, vg.DS4_BUTTONS.DS4_BUTTON_THUMB_LEFT),
            (XINPUT_GAMEPAD_RIGHT_THUMB, vg.DS4_BUTTONS.DS4_BUTTON_THUMB_RIGHT),
            (XINPUT_GAMEPAD_LEFT_SHOULDER, vg.DS4_BUTTONS.DS4_BUTTON_SHOULDER_LEFT),
            (XINPUT_GAMEPAD_RIGHT_SHOULDER, vg.DS4_BUTTONS.DS4_BUTTON_SHOULDER_RIGHT),
            (XINPUT_GAMEPAD_A, vg.DS4_BUTTONS.DS4_BUTTON_CROSS),
            (XINPUT_GAMEPAD_B, vg.DS4_BUTTONS.DS4_BUTTON_CIRCLE),
            (XINPUT_GAMEPAD_X, vg.DS4_BUTTONS.DS4_BUTTON_SQUARE),
            (XINPUT_GAMEPAD_Y, vg.DS4_BUTTONS.DS4_BUTTON_TRIANGLE),
        ]
        for mask, out_btn in mapping:
            if buttons & mask:
                self.virtual.press_button(button=out_btn)
            else:
                self.virtual.release_button(button=out_btn)

        up, down = bool(buttons & XINPUT_GAMEPAD_DPAD_UP), bool(buttons & XINPUT_GAMEPAD_DPAD_DOWN)
        left, right = bool(buttons & XINPUT_GAMEPAD_DPAD_LEFT), bool(buttons & XINPUT_GAMEPAD_DPAD_RIGHT)
        direction = vg.DS4_DPAD_DIRECTIONS.DS4_BUTTON_DPAD_NONE
        if up and left:
            direction = vg.DS4_DPAD_DIRECTIONS.DS4_BUTTON_DPAD_NORTHWEST
        elif up and right:
            direction = vg.DS4_DPAD_DIRECTIONS.DS4_BUTTON_DPAD_NORTHEAST
        elif down and left:
            direction = vg.DS4_DPAD_DIRECTIONS.DS4_BUTTON_DPAD_SOUTHWEST
        elif down and right:
            direction = vg.DS4_DPAD_DIRECTIONS.DS4_BUTTON_DPAD_SOUTHEAST
        elif up:
            direction = vg.DS4_DPAD_DIRECTIONS.DS4_BUTTON_DPAD_NORTH
        elif down:
            direction = vg.DS4_DPAD_DIRECTIONS.DS4_BUTTON_DPAD_SOUTH
        elif left:
            direction = vg.DS4_DPAD_DIRECTIONS.DS4_BUTTON_DPAD_WEST
        elif right:
            direction = vg.DS4_DPAD_DIRECTIONS.DS4_BUTTON_DPAD_EAST
        self.virtual.directional_pad(direction=direction)
        self.virtual.left_trigger(value=int(lt))
