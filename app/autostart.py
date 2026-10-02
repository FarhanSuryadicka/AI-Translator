"""Mulai bersama Windows (HKCU\\...\\Run), diminimalkan ke system tray."""

import os
import sys

RUN_KEY = r"Software\Microsoft\Windows\CurrentVersion\Run"
NAME = "AI Translator"


def _command():
    if getattr(sys, "frozen", False):
        return '"{}" --tray'.format(sys.executable)
    main = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "main.py")
    pythonw = os.path.join(os.path.dirname(sys.executable), "pythonw.exe")
    return '"{}" "{}" --tray'.format(pythonw if os.path.exists(pythonw) else sys.executable, main)


def set_enabled(on):
    import winreg

    with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY, 0, winreg.KEY_SET_VALUE) as key:
        if on:
            winreg.SetValueEx(key, NAME, 0, winreg.REG_SZ, _command())
        else:
            try:
                winreg.DeleteValue(key, NAME)
            except FileNotFoundError:
                pass


def is_enabled():
    import winreg

    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY) as key:
            winreg.QueryValueEx(key, NAME)
            return True
    except OSError:
        return False
