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