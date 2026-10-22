# Third-party components

ImageFlow source is MIT licensed. The following components retain their own licenses.

- Python 3.12: PSF License, https://docs.python.org/3/license.html
- PySide6 / Shiboken6 / Qt: LGPLv3 / GPLv3 or commercial licensing, https://doc.qt.io/qtforpython-6/licenses.html and https://www.qt.io/licensing/open-source-lgpl-obligations
- Pillow: HPND-style license and included codec licenses, https://github.com/python-pillow/Pillow/blob/main/LICENSE
- PyInstaller: GPL with the bootloader distribution exception, https://pyinstaller.org/en/stable/license.html
- pytest (development only): MIT, https://github.com/pytest-dev/pytest/blob/main/LICENSE

The directory build dynamically loads the Qt DLLs shipped under `_internal`; it does not statically link Qt. Users may replace compatible shared libraries and debug modified versions. This project imposes no restriction on reverse engineering for debugging such modifications. The build script copies available dependency license texts into `licenses/`; Python's license is also included by PyInstaller. Corresponding upstream sources are available from https://download.qt.io/official_releases/QtForPython/ and https://download.qt.io/official_releases/qt/ (match the shipped version). Check distribution obligations when redistributing a modified binary.

FFmpeg is **not bundled**. A user-selected FFmpeg distribution has its own build-dependent LGPL/GPL licensing. No FFmpeg binary is copied into the application distribution.

The optional one-click configuration downloads a separate Gyan essentials FFmpeg build only on user request, from https://www.gyan.dev/ffmpeg/builds/. Downloaded executables and their upstream license are stored in the user's configuration tools directory, which is excluded from ImageFlow release archives. Upstream build configuration and corresponding source information are available from that provider and https://ffmpeg.org/download.html.
