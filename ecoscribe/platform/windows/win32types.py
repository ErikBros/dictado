"""ctypes declarations shared by the hook and SendInput code.

Every function gets explicit argtypes/restype: on 64-bit Windows the ctypes
default (int) truncates pointers and LPARAMs, which crashes hooks at random.
"""
import ctypes
from ctypes import wintypes as w

user32 = ctypes.WinDLL("user32", use_last_error=True)
kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)

LRESULT = ctypes.c_ssize_t
ULONG_PTR = ctypes.c_size_t
HOOKPROC = ctypes.WINFUNCTYPE(LRESULT, ctypes.c_int, w.WPARAM, w.LPARAM)


class KBDLLHOOKSTRUCT(ctypes.Structure):
    _fields_ = [("vkCode", w.DWORD), ("scanCode", w.DWORD), ("flags", w.DWORD),
                ("time", w.DWORD), ("dwExtraInfo", ULONG_PTR)]


class MSLLHOOKSTRUCT(ctypes.Structure):
    _fields_ = [("pt", w.POINT), ("mouseData", w.DWORD), ("flags", w.DWORD),
                ("time", w.DWORD), ("dwExtraInfo", ULONG_PTR)]


class MOUSEINPUT(ctypes.Structure):
    _fields_ = [("dx", w.LONG), ("dy", w.LONG), ("mouseData", w.DWORD), ("dwFlags", w.DWORD),
                ("time", w.DWORD), ("dwExtraInfo", ULONG_PTR)]


class KEYBDINPUT(ctypes.Structure):
    _fields_ = [("wVk", w.WORD), ("wScan", w.WORD), ("dwFlags", w.DWORD),
                ("time", w.DWORD), ("dwExtraInfo", ULONG_PTR)]


class _INPUTUNION(ctypes.Union):
    _fields_ = [("mi", MOUSEINPUT), ("ki", KEYBDINPUT)]


class INPUT(ctypes.Structure):
    _fields_ = [("type", w.DWORD), ("u", _INPUTUNION)]


user32.SetWindowsHookExW.argtypes = (ctypes.c_int, HOOKPROC, w.HINSTANCE, w.DWORD)
user32.SetWindowsHookExW.restype = w.HHOOK
user32.UnhookWindowsHookEx.argtypes = (w.HHOOK,)
user32.UnhookWindowsHookEx.restype = w.BOOL
user32.CallNextHookEx.argtypes = (w.HHOOK, ctypes.c_int, w.WPARAM, w.LPARAM)
user32.CallNextHookEx.restype = LRESULT
user32.GetMessageW.argtypes = (ctypes.POINTER(w.MSG), w.HWND, w.UINT, w.UINT)
user32.GetMessageW.restype = w.BOOL
user32.PostThreadMessageW.argtypes = (w.DWORD, w.UINT, w.WPARAM, w.LPARAM)
user32.PostThreadMessageW.restype = w.BOOL
user32.PeekMessageW.argtypes = (ctypes.POINTER(w.MSG), w.HWND, w.UINT, w.UINT, w.UINT)
user32.PeekMessageW.restype = w.BOOL
user32.SetTimer.argtypes = (w.HWND, ULONG_PTR, w.UINT, ctypes.c_void_p)
user32.SetTimer.restype = ULONG_PTR
user32.KillTimer.argtypes = (w.HWND, ULONG_PTR)
user32.SendInput.argtypes = (w.UINT, ctypes.POINTER(INPUT), ctypes.c_int)
user32.SendInput.restype = w.UINT
user32.MapVirtualKeyW.argtypes = (w.UINT, w.UINT)
user32.MapVirtualKeyW.restype = w.UINT
user32.GetAsyncKeyState.argtypes = (ctypes.c_int,)
user32.GetAsyncKeyState.restype = ctypes.c_short
user32.GetForegroundWindow.restype = w.HWND
user32.GetWindowThreadProcessId.argtypes = (w.HWND, ctypes.POINTER(w.DWORD))
user32.GetWindowThreadProcessId.restype = w.DWORD
kernel32.GetModuleHandleW.argtypes = (w.LPCWSTR,)
kernel32.GetModuleHandleW.restype = w.HMODULE

WH_KEYBOARD_LL, WH_MOUSE_LL = 13, 14
WM_KEYDOWN, WM_KEYUP, WM_SYSKEYDOWN, WM_SYSKEYUP = 0x100, 0x101, 0x104, 0x105
WM_TIMER, WM_QUIT = 0x113, 0x12
MOUSE_PRESS_MSGS = {0x201, 0x204, 0x207, 0x20A, 0x20B, 0x20E}
LLKHF_INJECTED, LLMHF_INJECTED = 0x10, 0x01
LLKHF_EXTENDED = 0x01  # e.g. the numpad's Enter (same vk as the main Enter)
VK_RETURN = 0x0D
INPUT_MOUSE, INPUT_KEYBOARD = 0, 1
KEYEVENTF_EXTENDEDKEY, KEYEVENTF_KEYUP = 0x1, 0x2
MOUSEEVENTF_WHEEL = 0x0800
