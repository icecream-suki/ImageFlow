# -*- mode: python ; coding: utf-8 -*-
from pathlib import Path
import os
import sys

root = Path(SPECPATH)
a = Analysis(
    [str(root / 'run.py')],
    pathex=[str(root)],
    binaries=[],
    datas=[(str(root / 'README.md'), '.'), (str(root / 'THIRD_PARTY_NOTICES.md'), '.')],
    hiddenimports=[],
    hookspath=[],
    excludes=['tkinter', 'numpy', 'pytest', 'PySide6.QtQml', 'PySide6.QtQuick',
              'PySide6.QtWebEngineCore', 'PySide6.QtWebEngineWidgets', 'PySide6.QtMultimedia',
              'PySide6.QtPdf', 'PySide6.QtNetwork', 'PySide6.QtTest'],
    noarchive=False,
)
# Qt Widgets does not need QML, virtual keyboard, PDF or network plugins.
# Qt 6.12 uses Windows' unsuffixed ICU API. Never ship an unrelated ICU picked
# from another tool's PATH (e.g. Poppler exports suffixed ICU symbols instead).
unneeded_qt = ('qt6qml', 'qt6quick', 'qt6virtualkeyboard', 'qt6pdf', 'qt6network', 'qt6opengl')
def keep_binary(entry):
    destination = entry[0].replace('\\', '/').lower()
    name = destination.rsplit('/', 1)[-1]
    if name.startswith(('icu', 'api-ms-win-')) or name == 'ucrtbase.dll':
        return False  # supported Windows 10/11 supplies these system components
    if name.startswith(unneeded_qt):
        return False
    if '/platforminputcontexts/' in destination or name == 'qpdf.dll':
        return False
    return True
a.binaries = [entry for entry in a.binaries if keep_binary(entry)]
a.datas = [entry for entry in a.datas if '/translations/' not in entry[0].replace('\\', '/').lower()
           or entry[0].endswith('qtbase_zh_CN.qm')]
allowed = [Path(sys.prefix).resolve(), Path(sys.base_prefix).resolve(), Path(os.environ['WINDIR']).resolve()]
for destination, source, kind in a.binaries:
    if not any(Path(source).resolve().is_relative_to(parent) for parent in allowed):
        raise SystemExit(f'Refusing dependency from outside Python / Windows: {source}')
pyz = PYZ(a.pure)
exe = EXE(pyz, a.scripts, [], exclude_binaries=True, name='ImageFlow',
          debug=False, bootloader_ignore_signals=False, strip=False, upx=False,
          console=False, disable_windowed_traceback=False)
coll = COLLECT(exe, a.binaries, a.datas, strip=False, upx=False, name='ImageFlow')
