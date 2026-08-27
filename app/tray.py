"""System tray icon for the launcher (Windows Shell_NotifyIcon via ctypes).

Zero-dependency tray: a hidden message window owns the icon and a popup menu
(打开主界面 / 启动服务器 / 停止服务器 / 退出). Menu clicks and left-clicks
push commands into a thread-safe queue; the shell UI polls ``poll_tray`` on
the bridge (which runs on the JS api thread) so every window operation stays
on a thread pywebview already uses for window calls.
"""

from __future__ import annotations

import collections
import ctypes
import logging
import os
import threading
from ctypes import wintypes

log = logging.getLogger("tray")

WM_COMMAND = 0x0111
WM_DESTROY = 0x0002
WM_USER = 0x0400
WM_TRAYICON = WM_USER + 20
WM_LBUTTONUP = 0x0202
WM_RBUTTONUP = 0x0205

NIM_ADD = 0
NIM_MODIFY = 1
NIM_DELETE = 2
NIF_MESSAGE = 0x1
NIF_ICON = 0x2
NIF_TIP = 0x4

MF_STRING = 0x0000
MF_SEPARATOR = 0x0800
TPM_RETURNCMD = 0x0100
TPM_RIGHTBUTTON = 0x0002

IMAGE_ICON = 1
LR_LOADFROMFILE = 0x0010
LR_DEFAULTSIZE = 0x0040
LR_SHARED = 0x8000

IDM_OPEN = 1001
IDM_START = 1002
IDM_STOP = 1003
IDM_QUIT = 1004


class NOTIFYICONDATA(ctypes.Structure):
    _fields_ = [
        ("cbSize", wintypes.DWORD),
        ("hWnd", wintypes.HWND),
        ("uID", wintypes.UINT),
        ("uFlags", wintypes.UINT),
        ("uCallbackMessage", wintypes.UINT),
        ("hIcon", wintypes.HICON),
        ("szTip", wintypes.WCHAR * 128),
    ]


class POINT(ctypes.Structure):
    _fields_ = [("x", wintypes.LONG), ("y", wintypes.LONG)]


_wndproc_type = ctypes.WINFUNCTYPE(
    ctypes.c_long, wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM)


class WNDCLASSW(ctypes.Structure):
    _fields_ = [
        ("style", wintypes.UINT),
        ("lpfnWndProc", _wndproc_type),
        ("cbClsExtra", ctypes.c_int),
        ("cbWndExtra", ctypes.c_int),
        ("hInstance", wintypes.HINSTANCE),
        ("hIcon", wintypes.HICON),
        ("hCursor", wintypes.HANDLE),
        ("hbrBackground", wintypes.HBRUSH),
        ("lpszMenuName", wintypes.LPCWSTR),
        ("lpszClassName", wintypes.LPCWSTR),
    ]


class TrayController:
    """Owns the tray icon; callbacks only enqueue commands."""

    def __init__(self, app_dir: str, icon_name: str = "dsh.ico") -> None:
        self._app_dir = app_dir
        self._icon_path = self._find_icon(icon_name)
        self._queue: collections.deque[str] = collections.deque()
        self._lock = threading.Lock()
        self._thread: threading.Thread | None = None
        self._hwnd: int = 0
        self._nid: NOTIFYICONDATA | None = None
        self._stop = threading.Event()
        self._wndproc = _wndproc_type(self._wnd_proc)

    def _find_icon(self, name: str) -> str:
        for root in (self._app_dir,
                     os.path.join(self._app_dir, "_internal"),
                     os.path.dirname(self._app_dir)):
            path = os.path.join(root, name)
            if os.path.isfile(path):
                return path
        return ""

    # ------------------------------------------------------------- queue

    def push(self, cmd: str) -> None:
        with self._lock:
            self._queue.append(cmd)

    def pop(self) -> str:
        with self._lock:
            return self._queue.popleft() if self._queue else ""

    # ------------------------------------------------------------- icon

    def start(self) -> bool:
        if self._thread is not None:
            return True
        self._stop.clear()
        self._thread = threading.Thread(
            target=self._run, name="tray-icon", daemon=True)
        self._thread.start()
        return True

    def stop(self) -> None:
        self._stop.set()
        if self._hwnd:
            ctypes.windll.user32.PostMessageW(self._hwnd, WM_DESTROY, 0, 0)

    def update_tooltip(self, text: str) -> None:
        if not self._nid:
            return
        self._nid.szTip = text[:127]
        self._nid.uFlags = NIF_TIP
        ctypes.windll.shell32.Shell_NotifyIconW(NIM_MODIFY,
                                                ctypes.byref(self._nid))

    # ------------------------------------------------------------- loop

    def _run(self) -> None:
        try:
            self._message_loop()
        except Exception:  # tray must never kill the app
            log.exception("tray loop crashed")

    def _message_loop(self) -> None:
        user32 = ctypes.windll.user32
        shell32 = ctypes.windll.shell32
        kernel32 = ctypes.windll.kernel32
        hinst = kernel32.GetModuleHandleW(None)
        # Default ctypes argtypes are 32-bit ints; 64-bit message params
        # (packed pointers/coords in LPARAM) would overflow.
        user32.DefWindowProcW.argtypes = [wintypes.HWND, wintypes.UINT,
                                          wintypes.WPARAM, wintypes.LPARAM]
        user32.DefWindowProcW.restype = wintypes.LPARAM

        wndclass = WNDCLASSW()
        wndclass.lpfnWndProc = self._wndproc
        wndclass.hInstance = hinst
        wndclass.lpszClassName = "DSHTrayWindow"
        if not user32.RegisterClassW(ctypes.byref(wndclass)):
            log.error("RegisterClassW failed: %s", ctypes.get_last_error())
            return
        self._hwnd = user32.CreateWindowExW(
            0, "DSHTrayWindow", "DSHTray", 0, 0, 0, 0, 0,
            None, None, hinst, None)
        if not self._hwnd:
            log.error("tray window creation failed: %s", ctypes.get_last_error())
            return

        hicon = 0
        if self._icon_path:
            hicon = user32.LoadImageW(None, self._icon_path, IMAGE_ICON,
                                      0, 0, LR_LOADFROMFILE | LR_DEFAULTSIZE)

        nid = NOTIFYICONDATA()
        nid.cbSize = ctypes.sizeof(NOTIFYICONDATA)
        nid.hWnd = self._hwnd
        nid.uID = 1
        nid.uFlags = NIF_MESSAGE | NIF_ICON | NIF_TIP
        nid.uCallbackMessage = WM_TRAYICON
        nid.hIcon = hicon
        nid.szTip = "DeepSeek Harness"
        if not shell32.Shell_NotifyIconW(NIM_ADD, ctypes.byref(nid)):
            log.warning("Shell_NotifyIconW ADD failed: %s", ctypes.get_last_error())
        self._nid = nid

        msg = wintypes.MSG()
        while not self._stop.is_set():
            got = user32.GetMessageW(ctypes.byref(msg), None, 0, 0)
            if got <= 0:
                break
            user32.TranslateMessage(ctypes.byref(msg))
            user32.DispatchMessageW(ctypes.byref(msg))

        if self._nid is not None:
            shell32.Shell_NotifyIconW(NIM_DELETE, ctypes.byref(self._nid))
            self._nid = None
        if self._hwnd:
            user32.DestroyWindow(self._hwnd)
            self._hwnd = 0

    # ------------------------------------------------------------- wndproc

    def _wnd_proc(self, hwnd, msg, wparam, lparam) -> int:
        user32 = ctypes.windll.user32
        if msg == WM_TRAYICON:
            if lparam == WM_LBUTTONUP:
                self.push("show")
            elif lparam == WM_RBUTTONUP:
                self._show_menu()
            return 0
        if msg == WM_COMMAND:
            cmd_id = wparam & 0xFFFF
            mapping = {IDM_OPEN: "show", IDM_START: "start",
                       IDM_STOP: "stop", IDM_QUIT: "quit"}
            if cmd_id in mapping:
                self.push(mapping[cmd_id])
            return 0
        if msg == WM_DESTROY:
            user32.PostQuitMessage(0)
            return 0
        return user32.DefWindowProcW(hwnd, msg, wparam, lparam)

    def _show_menu(self) -> None:
        user32 = ctypes.windll.user32
        kernel32 = ctypes.windll.kernel32
        menu = user32.CreatePopupMenu()
        try:
            user32.AppendMenuW(menu, MF_STRING, IDM_OPEN, "打开主界面")
            user32.AppendMenuW(menu, MF_SEPARATOR, 0, "")
            user32.AppendMenuW(menu, MF_STRING, IDM_START, "启动服务器")
            user32.AppendMenuW(menu, MF_STRING, IDM_STOP, "停止服务器")
            user32.AppendMenuW(menu, MF_SEPARATOR, 0, "")
            user32.AppendMenuW(menu, MF_STRING, IDM_QUIT, "退出")
            pt = POINT()
            user32.GetCursorPos(ctypes.byref(pt))
            # Make the menu appear even when the tray window lacks focus.
            user32.SetForegroundWindow(self._hwnd)
            cmd = user32.TrackPopupMenu(
                menu, TPM_RETURNCMD | TPM_RIGHTBUTTON, pt.x, pt.y, 0,
                self._hwnd, None)
            if cmd in (IDM_OPEN, IDM_START, IDM_STOP, IDM_QUIT):
                user32.PostMessageW(self._hwnd, WM_COMMAND, cmd, 0)
        finally:
            user32.DestroyMenu(menu)
        kernel32.GetLastError()
