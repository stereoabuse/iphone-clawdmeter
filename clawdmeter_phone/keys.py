"""Press keys and type text into whatever window has focus (Windows SendInput)."""

import ctypes
from ctypes import wintypes

INPUT_KEYBOARD = 1
KEYEVENTF_KEYUP = 0x0002
KEYEVENTF_UNICODE = 0x0004

VK = {"enter": 0x0D, "esc": 0x1B}

ULONG_PTR = ctypes.c_size_t


class KEYBDINPUT(ctypes.Structure):
    _fields_ = [("wVk", wintypes.WORD), ("wScan", wintypes.WORD), ("dwFlags", wintypes.DWORD),
                ("time", wintypes.DWORD), ("dwExtraInfo", ULONG_PTR)]


class MOUSEINPUT(ctypes.Structure):
    _fields_ = [("dx", wintypes.LONG), ("dy", wintypes.LONG), ("mouseData", wintypes.DWORD),
                ("dwFlags", wintypes.DWORD), ("time", wintypes.DWORD), ("dwExtraInfo", ULONG_PTR)]


class _U(ctypes.Union):
    _fields_ = [("ki", KEYBDINPUT), ("mi", MOUSEINPUT)]


class INPUT(ctypes.Structure):
    _fields_ = [("type", wintypes.DWORD), ("u", _U)]


def _send(inputs: list[INPUT]) -> bool:
    """False when Windows refused the input (PC locked, or an elevated window has focus)."""
    arr = (INPUT * len(inputs))(*inputs)
    return ctypes.windll.user32.SendInput(len(inputs), arr, ctypes.sizeof(INPUT)) == len(inputs)


def _key(vk: int, up: bool) -> INPUT:
    return INPUT(INPUT_KEYBOARD, _U(ki=KEYBDINPUT(vk, 0, KEYEVENTF_KEYUP if up else 0, 0, 0)))


def press(combo: str) -> bool:
    """press('enter'); a combo like 'ctrl+enter' works once its keys are in VK."""
    vks = [VK[k] for k in combo.lower().split("+")]
    return _send([_key(v, False) for v in vks] + [_key(v, True) for v in reversed(vks)])


def type_text(text: str) -> bool:
    inputs = []
    for ch in text.replace("\r\n", "\n"):
        if ch == "\n":
            continue
        code = ord(ch)
        units = [code] if code < 0x10000 else [0xD800 + ((code - 0x10000) >> 10), 0xDC00 + ((code - 0x10000) & 0x3FF)]
        for u in units:
            inputs.append(INPUT(INPUT_KEYBOARD, _U(ki=KEYBDINPUT(0, u, KEYEVENTF_UNICODE, 0, 0))))
            inputs.append(INPUT(INPUT_KEYBOARD, _U(ki=KEYBDINPUT(0, u, KEYEVENTF_UNICODE | KEYEVENTF_KEYUP, 0, 0))))
    return not inputs or _send(inputs)


# What each phone button does.
ACTIONS = {
    "send": "enter",      # submit the prompt
    "accept": "enter",    # Claude Code highlights "Yes" in permission prompts
    "reject": "esc",      # deny a prompt, or interrupt Claude mid-turn
}
