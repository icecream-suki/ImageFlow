"""Check the known Qt/ICU packaging regression without launching a GUI dialog."""
from pathlib import Path
import ctypes
import os
import sys
import pefile

directory = Path(sys.argv[1]).resolve()
internal = directory / '_internal'
assert (directory / 'ImageFlow.exe').is_file()
assert (internal / 'PySide6' / 'plugins' / 'platforms' / 'qwindows.dll').is_file()
assert not list(internal.glob('icu*.dll')), 'Qt must load the Windows ICU API, not another application\'s ICU'
assert not list(directory.rglob('ffmpeg.exe')), 'FFmpeg must not be bundled'
assert not list(directory.rglob('ffprobe.exe')), 'FFprobe must not be bundled'
qt = pefile.PE(str(internal / 'PySide6' / 'Qt6Core.dll'), fast_load=True)
qt.parse_data_directories(directories=[pefile.DIRECTORY_ENTRY['IMAGE_DIRECTORY_ENTRY_IMPORT']])
directories = [os.add_dll_directory(str(path)) for path in [internal, internal / 'PySide6', internal / 'shiboken6']]
try:
    for name in ['Qt6Core.dll', 'Qt6Gui.dll', 'Qt6Widgets.dll', 'QtWidgets.pyd']:
        ctypes.WinDLL(str(internal / 'PySide6' / name))
finally:
    for handle in directories:
        handle.close()
print('Qt DLL loading preflight passed; no foreign ICU or FFmpeg executable is bundled.')
