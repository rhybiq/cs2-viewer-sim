# PyInstaller spec for the CS2 Viewer Sim desktop app.
# Build from the repo root with: pyinstaller packaging/app.spec
#
# Bundles ffmpeg.exe alongside the exe so end users don't need it on PATH.
# viewer_sim.ffmpeg_bin() resolves it via sys._MEIPASS at runtime.
#
# EasyOCR (text overlay quality) is bundled only if it's installed in the
# build environment -- see requirements-ocr.txt. It still downloads its
# recognition model from the internet on first use at runtime; that model
# itself is not bundled here.

import os

from PyInstaller.utils.hooks import collect_data_files

block_cipher = None
repo_root = os.path.dirname(os.path.abspath(SPECPATH))
ffmpeg_src = os.environ.get("FFMPEG_EXE_PATH")

binaries = []
if ffmpeg_src and os.path.exists(ffmpeg_src):
    binaries.append((ffmpeg_src, "."))

hiddenimports = ["scenedetect", "pyloudnorm"]
datas = []
try:
    import easyocr  # noqa: F401
    hiddenimports.append("easyocr")
    datas += collect_data_files("easyocr")
except ImportError:
    pass

a = Analysis(
    [os.path.join(repo_root, "run_app.py")],
    pathex=[repo_root],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    runtime_hooks=[],
    excludes=[],
    cipher=block_cipher,
    noarchive=False,
)
pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.zipfiles,
    a.datas,
    [],
    name="CS2ViewerSim",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,
    disable_windowed_traceback=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)
