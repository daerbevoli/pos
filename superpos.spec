# superpos.spec
# Build with: pyinstaller superpos.spec  ->  dist/SuperPOS/SuperPOS.exe
#
# One-folder build: SuperPOS.exe plus an _internal/ folder with Python, Qt and
# the bundled resources. The Inno Setup installer copies this whole folder into
# Program Files. (A one-file exe would unpack itself to a temp folder on every
# launch: slower to start and far more likely to be flagged by antivirus.)

import os
import re

from PyInstaller.building.build_main import Analysis, PYZ, EXE, COLLECT
from PyInstaller.utils.hooks import collect_data_files, collect_submodules, copy_metadata
from PyInstaller.utils.win32.versioninfo import (
    VSVersionInfo, FixedFileInfo, StringFileInfo, StringTable, StringStruct,
    VarFileInfo, VarStruct,
)

ROOT = SPECPATH  # folder holding this spec, so the build works from any cwd

# Read the version as text rather than importing the app package.
with open(os.path.join(ROOT, 'app', '__version__.py'), encoding='utf-8') as f:
    VERSION = re.search(r'__version__\s*=\s*"([^"]+)"', f.read()).group(1)
_v = tuple(int(n) for n in VERSION.split('.')) + (0,)  # Windows wants 4 numbers

# Shown in the exe's Properties -> Details tab.
version_info = VSVersionInfo(
    ffi=FixedFileInfo(filevers=_v, prodvers=_v),
    kids=[
        StringFileInfo([StringTable('040904B0', [
            StringStruct('CompanyName', 'SKBC bv'),
            StringStruct('FileDescription', 'SuperPOS'),
            StringStruct('FileVersion', VERSION),
            StringStruct('InternalName', 'SuperPOS'),
            StringStruct('OriginalFilename', 'SuperPOS.exe'),
            StringStruct('ProductName', 'SuperPOS'),
            StringStruct('ProductVersion', VERSION),
        ])]),
        VarFileInfo([VarStruct('Translation', [0x0409, 1200])]),
    ],
)

a = Analysis(
    [os.path.join(ROOT, 'main.py')],
    pathex=[ROOT],
    binaries=[],
    datas=[
        (os.path.join(ROOT, 'resources'), 'resources'),   # styles, icons
        # escpos reads capabilities.json at print time; without it the exe
        # starts fine but crashes on the first receipt.
        *collect_data_files('escpos'),
        # libusb: libusb.cfg and the per-arch libusb-1.0.dll that
        # receipt_service._get_backend() looks up under the package folder.
        *collect_data_files('libusb', include_py_files=False),
        # libusb and its helper packages (pkg_about, py-utlx, ...) each read
        # their own version from their installed-package metadata on import;
        # recursive=True bundles it for every package in libusb's dependency tree.
        *copy_metadata('libusb', recursive=True),
    ],
    hiddenimports=[
        'sqlalchemy.dialects.sqlite',
        *collect_submodules('escpos'),
        # libusb loads pkg_about through __import__("pkg_about"), invisible to
        # PyInstaller: the first print / drawer kick would crash without it.
        *collect_submodules('libusb', filter=lambda name: not name.startswith(
            ('libusb._platform.macos', 'libusb._platform.linux'))),
        *collect_submodules('pkg_about'),
        # reportlab imports its barcode types through exec() strings, which
        # PyInstaller can't see: the exe would crash at startup without these.
        *collect_submodules('reportlab.graphics.barcode'),
    ],
    hookspath=[],
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
)

pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    exclude_binaries=True,   # one-folder: DLLs/data go into COLLECT below
    name='SuperPOS',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,               # UPX-packed DLLs trigger antivirus and can break Qt
    console=False,           # no console window on Windows
    icon=os.path.join(ROOT, 'resources', 'icons', 'kassa.ico'),
    version=version_info,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    name='SuperPOS',
)
