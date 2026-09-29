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
        self.virtual.right_trigger(value=int(rt))
        self.virtual.left_joystick_float(x_value_float=clamp(lx / 32767.0, -1, 1), y_value_float=clamp(-ly / 32767.0, -1, 1))
        self.virtual.right_joystick_float(x_value_float=clamp(rx / 32767.0, -1, 1), y_value_float=clamp(-ry / 32767.0, -1, 1))
        self.virtual.update()

    def run(self):
        try:
            ctypes.windll.user32.SetProcessDPIAware()
        except Exception:
            pass
        try:
            self.xinput = xinput_dll()
            self.status.emit("Engine: Starting")
            frame_count = 0
            fps = 0.0
            fps_start = time.perf_counter()
            while not self._stop.is_set():
                settings = self._snapshot()
                requested = settings.get("controller_slot", "Auto")
                if self.slot is None or requested != "Auto" and self.slot != int(requested):
                    self.slot = self._find_slot(requested)
                state = self._read_state(self.slot)
                if state is None:
                    self.slot = self._find_slot(requested)
                    state = self._read_state(self.slot)

                virtual_ready = False
                try:
                    virtual_ready = self._ensure_virtual(settings)
                except Exception as e:
                    self.status.emit("Engine: Driver Required")
                    self.error.emit(str(e))
                    self._reset_virtual()
                    time.sleep(0.8)
                    continue

                if state is None:
                    self.telemetry.emit({
                        "controller": False, "slot": None, "target": False, "confidence": 0,
                        "fps": fps, "virtual": virtual_ready, "rx": 0, "ry": 0,
                    })
                    time.sleep(0.12)
                    continue

                aim_active = self._trigger_active(state, settings["aim_trigger"])
                fire_active = self._fire_active(state, settings)
                ox = oy = conf = 0
                target_found = False
                if aim_active and settings["enable_aim_assist"]:
                    ox, oy, conf, target_found = self._screen_target(settings)

                # Anti-recoil from the supplied GPC: only while firing.
                if settings["anti_recoil"] and fire_active:
                    ox += int(settings["recoil_horizontal"] * 327)
                    oy += int(settings["recoil_vertical"] * 327)

                gp = state.Gamepad
                buttons = int(gp.wButtons) if settings["enable_controller_input"] else 0
                lt = int(gp.bLeftTrigger) if settings["enable_controller_input"] else 0
                rt = int(gp.bRightTrigger) if settings["enable_controller_input"] else 0
                lx = int(gp.sThumbLX) if settings["enable_controller_input"] else 0
                ly = int(gp.sThumbLY) if settings["enable_controller_input"] else 0
                rx = int(gp.sThumbRX) if settings["enable_controller_input"] else 0
                ry = int(gp.sThumbRY) if settings["enable_controller_input"] else 0

                now = time.monotonic()
                buttons, lt, rt = self._apply_macros(state, settings, buttons, lt, rt, now, aim_active, fire_active)
                rx = int(clamp(rx + ox, -32768, 32767))
                ry = int(clamp(ry + oy, -32768, 32767))

                if virtual_ready:
                    if self.is_ds4:
                        self._output_ds4(buttons, lt, rt, lx, ly, rx, ry)
                    else:
                        self._output_x360(buttons, lt, rt, lx, ly, rx, ry)

                frame_count += 1
                now_perf = time.perf_counter()
                if now_perf - fps_start >= 0.5:
                    fps = frame_count / (now_perf - fps_start)
                    frame_count = 0
                    fps_start = now_perf
                    self.telemetry.emit({
                        "controller": True, "slot": self.slot, "target": target_found,
                        "confidence": conf, "fps": fps, "virtual": virtual_ready,
                        "rx": rx, "ry": ry,
                    })
                    self.status.emit("Engine: Running")

                time.sleep(1 / max(120, int(settings.get("capture_fps", 120)) * 3))
        except Exception as e:
            self.error.emit(str(e))
            self.status.emit("Engine: Error")
        finally:
            self._reset_virtual()
            self.status.emit("Engine: Stopped")


class Card(QFrame):
    def __init__(self, title: str, parent=None):
        super().__init__(parent)
        self.setObjectName("card")
        self.layout = QVBoxLayout(self)
        self.layout.setContentsMargins(26, 24, 26, 24)
        self.layout.setSpacing(16)
        label = QLabel(title)
        label.setObjectName("cardTitle")
        self.layout.addWidget(label)


class MainWindow(QMainWindow):
    driver_message = Signal(str)
    driver_error = Signal(str)

    def __init__(self):
        super().__init__()
        self.settings = load_settings()
        self.engine = None
        self.controls = {}
        self.setWindowTitle(f"{APP_NAME} {APP_VERSION}")
        self.setMinimumSize(1100, 780)
        self.resize(1180, 840)
        self._build_ui()
        self.driver_message.connect(self.engine_label_set_safe)
        self.driver_error.connect(self.on_error)
        self._apply_style()
        self._load_to_ui()
        self._update_driver_status()

    def _apply_style(self):
        self.setStyleSheet("""
        QMainWindow, QWidget#root {
            background: qlineargradient(x1:0,y1:0,x2:1,y2:1, stop:0 #041936, stop:0.52 #072b58, stop:1 #061b3f);
            color: #EAF7FF;
            font-family: 'Segoe UI';
            font-size: 14px;
        }
        QLabel { color: #D7EBFF; }
        QLabel#brand { font-size: 22px; font-weight: 800; color: white; }
        QLabel#subtle { color: #79A7D0; font-size: 12px; }
        QLabel#engine { color: #56F5C4; font-size: 15px; font-weight: 700; }
        QLabel#cardTitle { color: #FFFFFF; font-size: 19px; font-weight: 800; }
        QFrame#topbar, QFrame#card {
            background-color: rgba(6, 43, 92, 220);
            border: 1px solid #167BC0;
            border-radius: 20px;
        }
        QFrame#topbar { border-radius: 16px; }
        QPushButton {
            background-color: #0B5FA4;
            border: 1px solid #158ED1;
            border-radius: 13px;
            color: #EAF8FF;
            padding: 10px 18px;
            font-weight: 650;
        }
        QPushButton:hover { background-color: #1178C1; border-color: #23CFF4; }
        QPushButton:pressed { background-color: #0A4F8D; }
        QPushButton[primary="true"] {
            background-color: #20CFEA;
            color: #032343;
            border-color: #41ECFF;
        }
        QPushButton[choice="true"] {
            min-height: 44px;
             background-color: #0A5195;
            border-color: #157CC0;
            border-radius: 15px;
        }
        QPushButton[choice="true"]:checked {
            background-color: #19D3E9;
            color: #04253F;
            border: 2px solid #63F7FF;
        }
        QComboBox, QLineEdit, QSpinBox, QDoubleSpinBox {
            background-color: #0B4E8C;
            border: 1px solid #177FC1;
            border-radius: 12px;
            min-height: 38px;
            padding: 4px 12px;
            color: white;
        }
        QComboBox::drop-down { border: 0; width: 34px; }
        QSlider::groove:horizontal {
            height: 7px; border-radius: 4px; background: #1C66AA;
        }
        QSlider::sub-page:horizontal { background: #22D7EF; border-radius: 4px; }
        QSlider::handle:horizontal {
            background: white; border: 2px solid #D9FFFF; width: 22px; margin: -8px 0; border-radius: 12px;
        }
        QTabWidget::pane { border: 0; background: transparent; }
        QTabBar::tab {
            background: #082D59; color: #8FB7DA; padding: 12px 24px; margin-right: 6px;
            border-top-left-radius: 10px; border-top-right-radius: 10px;
        }
        QTabBar::tab:selected { background: #0D5E9E; color: white; }
        QScrollArea { border: 0; background: transparent; }
        QScrollArea > QWidget > QWidget { background: transparent; }
        """)

    def _build_ui(self):
        root = QWidget()
        root.setObjectName("root")
        self.setCentralWidget(root)
        outer = QVBoxLayout(root)
        outer.setContentsMargins(22, 20, 22, 20)
        outer.setSpacing(16)

        header = QHBoxLayout()
        brand_box = QVBoxLayout()
        brand = QLabel("AFK CONTROLLER")
        brand.setObjectName("brand")
        brand_box.addWidget(brand)
        sub = QLabel("Screen Vision + Controller Engine")
        sub.setObjectName("subtle")
        brand_box.addWidget(sub)
        header.addLayout(brand_box)
        header.addStretch()
        self.driver_label = QLabel("Drivers: checking...")
        self.driver_label.setObjectName("subtle")
        header.addWidget(self.driver_label)
        outer.addLayout(header)

        topbar = QFrame()
        topbar.setObjectName("topbar")
        top = QHBoxLayout(topbar)
        top.setContentsMargins(18, 12, 18, 12)
        top.addWidget(QLabel("Config:"))
        self.profile_combo = QComboBox()
        self.profile_combo.addItems(["settings"])
        self.profile_combo.setMinimumWidth(260)
        top.addWidget(self.profile_combo)
        reload_btn = QPushButton("Reload")
        reload_btn.clicked.connect(self.reload_settings)
        top.addWidget(reload_btn)
        save_btn = QPushButton("Save")
        save_btn.setProperty("primary", True)
        save_btn.clicked.connect(self.save_settings)
        top.addWidget(save_btn)
        top.addStretch()
        self.engine_label = QLabel("Engine: Stopped")
        self.engine_label.setObjectName("engine")
        top.addWidget(self.engine_label)
        self.start_btn = QPushButton("START")
        self.start_btn.setProperty("primary", True)
        self.start_btn.clicked.connect(self.start_engine)
        top.addWidget(self.start_btn)
        self.stop_btn = QPushButton("STOP")
        self.stop_btn.setEnabled(False)
        self.stop_btn.clicked.connect(self.stop_engine)
        top.addWidget(self.stop_btn)
        outer.addWidget(topbar)

        self.tabs = QTabWidget()
        outer.addWidget(self.tabs, 1)
        self.tabs.addTab(self._build_controller_tab(), "Controller Settings")
        self.tabs.addTab(self._build_script_tab(), "AFK Script")
        self.tabs.addTab(self._build_diagnostics_tab(), "Diagnostics")

    def _switch_row(self, layout, row, text, key):
        label = QLabel(text)
        sw = Switch()
        self.controls[key] = sw
        layout.addWidget(label, row, 0)
        layout.addWidget(sw, row, 1, alignment=Qt.AlignRight)

    def _slider_row(self, layout, row, text, key, minimum, maximum, suffix="", scale=1):
        label = QLabel(text)
        slider = QSlider(Qt.Horizontal)
        slider.setRange(minimum, maximum)
        value = QLabel()
        value.setMinimumWidth(64)
        value.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        self.controls[key] = (slider, scale)
        def update(v):
            shown = v / scale
            value.setText(f"{shown:.2f}{suffix}" if scale != 1 else f"{v}{suffix}")
        slider.valueChanged.connect(update)
        update(slider.value())
        layout.addWidget(label, row, 0)
        box = QHBoxLayout()
        box.addWidget(slider, 1)
        box.addWidget(value)
        layout.addLayout(box, row, 1)

    def _build_controller_tab(self):
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        content = QWidget()
        wrap = QVBoxLayout(content)
        wrap.setContentsMargins(6, 12, 6, 12)
        wrap.setSpacing(16)

        card = Card("Controller Settings")
        grid = QGridLayout()
        grid.setHorizontalSpacing(30)
        grid.setVerticalSpacing(17)
        grid.setColumnStretch(0, 1)
        grid.setColumnStretch(1, 3)
        self._switch_row(grid, 0, "Enable Aim Assist", "enable_aim_assist")
        self._switch_row(grid, 1, "Enable Controller Input", "enable_controller_input")
        self._switch_row(grid, 2, "Enable Virtual Controller", "enable_virtual_controller")
        self._switch_row(grid, 3, "DS4 Output (off = Xbox 360)", "ds4_output")
        self._switch_row(grid, 4, "Human Movement", "human_movement")
        self._slider_row(grid, 5, "Human Strength", "human_strength", 0, 100, scale=100)

        grid.addWidget(QLabel("Target Color"), 6, 0)
        color_row = QHBoxLayout()
        self.color_button = QPushButton(" ")
        self.color_button.setFixedSize(44, 40)
        self.color_button.clicked.connect(self.pick_color)
        self.color_hex = QLineEdit()
        self.color_hex.setAlignment(Qt.AlignCenter)
        self.color_hex.editingFinished.connect(self.validate_color)
        color_row.addWidget(self.color_button)
        color_row.addWidget(self.color_hex, 1)
        grid.addLayout(color_row, 6, 1)
        self.controls["target_color"] = self.color_hex

        self._slider_row(grid, 7, "Color Tolerance", "color_tolerance", 0, 100)

        grid.addWidget(QLabel("Aim Trigger"), 8, 0, 1, 2)
        self.aim_trigger = ChoiceButtons(["L2", "R2", "L2 + R2", "L1", "R1", "L1 + R1"], columns=3)
        self.controls["aim_trigger"] = self.aim_trigger
        grid.addWidget(self.aim_trigger, 9, 0, 1, 2)

        grid.addWidget(QLabel("Aim Bone"), 10, 0, 1, 2)
        self.aim_bone = ChoiceButtons(["Head", "Chest", "Random"], columns=3)
        self.controls["aim_bone"] = self.aim_bone
        grid.addWidget(self.aim_bone, 11, 0, 1, 2)

        grid.addWidget(QLabel("Controller Input"), 12, 0)
        controller_row = QHBoxLayout()
        self.controller_slot = QComboBox()
        self.controller_slot.addItems(["Auto", "0", "1", "2", "3"])
        self.controls["controller_slot"] = self.controller_slot
        self.controller_status = QLabel("Auto: waiting for controller")
        self.controller_status.setObjectName("subtle")
        controller_row.addWidget(self.controller_slot)
        controller_row.addWidget(self.controller_status, 1)
        grid.addLayout(controller_row, 12, 1)

        grid.addWidget(QLabel("Hide Controller"), 13, 0)
        hide_row = QHBoxLayout()
        self.hide_combo = QComboBox()
        self.hide_combo.addItems(["Auto", "Off"])
        self.controls["hide_controller_mode"] = self.hide_combo
        hide_row.addWidget(self.hide_combo)
        hide_btn = QPushButton("Open HidHide")
        hide_btn.clicked.connect(self.open_hidhide_clicked)
        hide_row.addWidget(hide_btn)
        grid.addLayout(hide_row, 13, 1)

        card.layout.addLayout(grid)
        wrap.addWidget(card)

        vision = Card("Vision Response")
        vg = QGridLayout()
        vg.setHorizontalSpacing(30)
        vg.setVerticalSpacing(16)
        vg.setColumnStretch(0, 1)
        vg.setColumnStretch(1, 3)
        self._slider_row(vg, 0, "FOV Radius", "fov", 50, 500)
        self._slider_row(vg, 1, "Aim Strength", "aim_strength", 1, 100, scale=100)
        self._slider_row(vg, 2, "Smoothing", "smoothing", 1, 100, scale=100)
        self._slider_row(vg, 3, "Max Correction", "max_correction", 500, 15000)
        self._switch_row(vg, 4, "Sticky Aim", "sticky_aim")
        self._slider_row(vg, 5, "Sticky Time", "sticky_time_ms", 20, 500, suffix=" ms")
        self._slider_row(vg, 6, "Sticky Strength", "sticky_strength", 1, 100, scale=100)
        vision.layout.addLayout(vg)
        wrap.addWidget(vision)
        wrap.addStretch()
        scroll.setWidget(content)
        return scroll

    def _build_script_tab(self):
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        content = QWidget()
        wrap = QVBoxLayout(content)
        wrap.setContentsMargins(6, 12, 6, 12)
        wrap.setSpacing(16)

        card = Card("AFK Script Logic")
        grid = QGridLayout()
        grid.setHorizontalSpacing(30)
        grid.setVerticalSpacing(16)
        grid.setColumnStretch(0, 1)
        grid.setColumnStretch(1, 3)
        self._switch_row(grid, 0, "Anti-Recoil", "anti_recoil")
        self._slider_row(grid, 1, "Vertical Recoil", "recoil_vertical", 0, 100)
        self._slider_row(grid, 2, "Horizontal Recoil", "recoil_horizontal", -100, 100)
        self._switch_row(grid, 3, "Hair Triggers", "hair_triggers")
        self._switch_row(grid, 4, "Auto Hold Breath", "auto_hold_breath")
        self._switch_row(grid, 5, "Auto Ping", "auto_ping")
        self._switch_row(grid, 6, "Bunny Hop", "bunny_hop")
        self._switch_row(grid, 7, "Slide Cancel", "slide_cancel")
        self._slider_row(grid, 8, "Rapid Fire", "rapid_fire_rps", 0, 10, suffix=" RPS")
        self._slider_row(grid, 9, "YY Spam Delay", "yy_spam_ms", 0, 100, suffix=" ms")
        grid.addWidget(QLabel("Fire Button"), 10, 0)
        fire = ChoiceButtons(["R2", "R1"], selected="R2", columns=2)
        self.controls["fire_button"] = fire
        grid.addWidget(fire, 10, 1)
        card.layout.addLayout(grid)
        wrap.addWidget(card)
        wrap.addStretch()
        scroll.setWidget(content)
        return scroll

    def _build_diagnostics_tab(self):
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(6, 12, 6, 12)
        card = Card("Live Diagnostics")
        self.diag = QLabel("Engine stopped")
        self.diag.setWordWrap(True)
        self.diag.setStyleSheet("font-family: Consolas; font-size: 14px; line-height: 1.4;")
        card.layout.addWidget(self.diag)
        buttons = QHBoxLayout()
        driver_btn = QPushButton("Install / Repair Drivers")
        driver_btn.setProperty("primary", True)
        driver_btn.clicked.connect(self.install_drivers)
        buttons.addWidget(driver_btn)
        open_data = QPushButton("Open Data Folder")
        open_data.clicked.connect(lambda: (APP_DIR.mkdir(parents=True, exist_ok=True), os.startfile(APP_DIR)))
        buttons.addWidget(open_data)
        buttons.addStretch()
        card.layout.addLayout(buttons)
        layout.addWidget(card)
        layout.addStretch()
        return page

    def _load_to_ui(self):
        for key, widget in self.controls.items():
            value = self.settings.get(key, DEFAULTS.get(key))
            if isinstance(widget, Switch):
                widget.setChecked(bool(value))
            elif isinstance(widget, tuple):
                slider, scale = widget
                slider.setValue(int(round(float(value) * scale)))
            elif isinstance(widget, ChoiceButtons):
                widget.set_value(str(value))
            elif isinstance(widget, QComboBox):
                idx = widget.findText(str(value))
                if idx >= 0:
                    widget.setCurrentIndex(idx)
            elif isinstance(widget, QLineEdit):
                widget.setText(str(value))
        self._refresh_color_button()

    def _collect_ui(self):
        data = dict(self.settings)
        for key, widget in self.controls.items():
            if isinstance(widget, Switch):
                data[key] = widget.isChecked()
            elif isinstance(widget, tuple):
                slider, scale = widget
                data[key] = slider.value() / scale if scale != 1 else slider.value()
            elif isinstance(widget, ChoiceButtons):
                data[key] = widget.value()
            elif isinstance(widget, QComboBox):
                data[key] = widget.currentText()
            elif isinstance(widget, QLineEdit):
                data[key] = widget.text().strip()
        data["target_color"] = normalize_hex(data["target_color"])
        return data

    def save_settings(self):
        try:
            self.settings = self._collect_ui()
            atomic_save_json(CONFIG_PATH, self.settings)
            if self.engine and self.engine.isRunning():
                self.engine.update_settings(self.settings)
            self.engine_label.setText("Engine: Settings Saved" if not self.engine or not self.engine.isRunning() else "Engine: Running")
        except Exception as e:
            QMessageBox.critical(self, APP_NAME, str(e))

    def reload_settings(self):
        self.settings = load_settings()
        self._load_to_ui()
        if self.engine and self.engine.isRunning():
            self.engine.update_settings(self.settings)

    def pick_color(self):
        current = QColor(self.color_hex.text())
        color = QColorDialog.getColor(current if current.isValid() else QColor("#E600FF"), self, "Target Color")
        if color.isValid():
            self.color_hex.setText(color.name().upper())
            self._refresh_color_button()
            self.save_settings()

    def validate_color(self):
        try:
            self.color_hex