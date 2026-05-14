# superpos.spec
# Build with: pyinstaller superpos.spec

from PyInstaller.building.build_main import Analysis, PYZ, EXE, COLLECT

a = Analysis(
    ['main.py'],
    pathex=['.'],
    binaries=[],
    datas=[
        ('resources/', 'resources/'),   # Include styles, icons
    ],
    hiddenimports=[
        'sqlalchemy.dialects.sqlite',
        'escpos',
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
    a.binaries,
    a.datas,
    name='SuperPOS',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=False,         # No console window on Windows
    icon=None,             # Add 'resources/icons/icon.ico' when you have one
)
