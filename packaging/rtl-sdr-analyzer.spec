# PyInstaller spec for the standalone rtl-sdr-analyzer build (one folder, console app).
#
#   pip install ".[bundle]"
#   pyinstaller packaging/rtl-sdr-analyzer.spec --noconfirm
#
# Windows: set RTLSDR_NATIVE_DIR to a folder holding rtlsdr.dll (+ pthreadVC2.dll,
# msvcr100.dll) so the dongle works without installing anything else.
# macOS / Linux: librtlsdr is taken from the system (brew / apt), so the build stays
# portable across distro versions and udev / kernel-driver setup keeps working.

import os
from pathlib import Path

from PyInstaller.utils.hooks import collect_data_files, collect_submodules

SPEC_DIR = Path(SPECPATH)  # noqa: F821 - injected by PyInstaller

binaries = []
native_dir = os.environ.get("RTLSDR_NATIVE_DIR")
if native_dir:
    for entry in sorted(Path(native_dir).iterdir()):
        name = entry.name.lower()
        if name.endswith((".dll", ".dylib", ".so")) or ".so." in name:
            binaries.append((str(entry), "."))
    if not any(b[0].lower().endswith(("rtlsdr.dll", ".dylib", ".so")) or ".so." in b[0] for b in binaries):
        raise SystemExit(f"RTLSDR_NATIVE_DIR={native_dir} contains no librtlsdr library")

datas = collect_data_files("rtl_sdr_analyzer")  # web UI (HTML/JS/CSS/fonts), py.typed

hiddenimports = []
for package in ("uvicorn", "websockets", "httptools"):
    try:
        hiddenimports += collect_submodules(package)
    except Exception:  # noqa: BLE001 - optional uvicorn[standard] extras
        pass

a = Analysis(  # noqa: F821
    [str(SPEC_DIR / "entry.py")],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    excludes=["tkinter", "matplotlib", "scipy", "pytest", "IPython"],
    noarchive=False,
)
pyz = PYZ(a.pure)  # noqa: F821
exe = EXE(  # noqa: F821
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="rtl-sdr-analyzer",
    console=True,  # logs + Ctrl+C to quit; closing the window stops the server
    upx=False,
)
coll = COLLECT(  # noqa: F821
    exe,
    a.binaries,
    a.datas,
    name="rtl-sdr-analyzer",
    upx=False,
)
