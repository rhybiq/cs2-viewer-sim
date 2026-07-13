# PyInstaller spec for the CS2 Demo Highlights desktop app.
# Build from the repo root with: pyinstaller packaging/demo_highlights_app.spec
#
# A separate onefile exe from app.spec (not a second EXE() block in that same
# spec) -- PyInstaller's multi-output MERGE() sharing is designed for
# onedir/COLLECT builds, not onefile ones (neither spec uses COLLECT), so two
# independent specs is simpler and keeps each build's dependency scope
# cleanly isolated: this app.spec's own build can't accidentally pick up
# awpy/scipy/pyarrow just because a sibling spec needs them.
#
# excludes matplotlib/scipy: awpy's __init__.py eagerly imports Nav (which
# eagerly imports networkx -- cannot be excluded, it's unconditionally
# loaded), but matplotlib/scipy are only reachable through awpy/plot/*.py,
# which nothing in the Demo/Nav/Spawns import chain touches -- confirmed via
# direct grep of the installed awpy source, not guessed. Trims ~139MB.
# pyarrow is left bundled: it's a stated hard dependency of demoparser2
# itself (not an optional plotting extra like matplotlib/scipy), and
# demoparser2 is a compiled Rust extension whose internal calls into pyarrow
# (if any) wouldn't show up in a static grep of its thin Python wrapper --
# not confident enough to exclude it without much deeper verification than
# a plain grep gives.
#
# excludes torch/torchvision/sympy: a real first build (not guessed --
# actually measured) came out at 311MB, traced to polars.ml.torch, an
# optional PyTorch-interop submodule of polars that only exists to convert
# DataFrames to/from torch tensors. demo_highlights never touches it, but
# PyInstaller's static analysis found the conditional `import torch` inside
# it and, because torch happens to be installed in this dev environment
# (pulled in by requirements-stt.txt/-ocr.txt for the *other* app), resolved
# and bundled the entire torch/torchvision/sympy tree -- by far the largest
# single contributor, dwarfing scipy/pyarrow. Confirmed via the build's own
# warn-*.txt (`torch.memory_format - imported by torch (conditional),
# polars.ml.torch (conditional)`) and Analysis-00.toc, not assumed.

import os

repo_root = os.path.dirname(os.path.abspath(SPECPATH))

block_cipher = None

# app/ui/qss_loader.py reads dark_theme.qss relative to its own location at
# runtime -- same non-.py-resource bundling requirement as app.spec.
datas = [(os.path.join(repo_root, "app", "ui", "dark_theme.qss"), os.path.join("app", "ui"))]

a = Analysis(
    [os.path.join(repo_root, "run_demo_highlights.py")],
    pathex=[repo_root],
    binaries=[],
    datas=datas,
    hiddenimports=[],
    hookspath=[],
    runtime_hooks=[],
    excludes=["matplotlib", "scipy", "torch", "torchvision", "sympy"],
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
    name="CS2DemoHighlights",
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
