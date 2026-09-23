# -*- mode: python ; coding: utf-8 -*-
"""
PyInstaller build spec for the AbinDebugger desktop app.

Build from the project root:

    pyinstaller frontend/AbinDebugger.spec --noconfirm

Produces dist/AbinDebugger.app on macOS, dist/AbinDebugger/AbinDebugger.exe
(inside a folder -- zip the whole folder to hand it to someone) on Windows.
Must be built separately on each target OS; see
.github/workflows/build-desktop.yml for automated builds of both.
"""
import sys
from pathlib import Path

from PyInstaller.utils.hooks import collect_all

PROJECT_ROOT = Path(SPECPATH).parent  # noqa: F821 -- SPECPATH is injected by PyInstaller

datas = [
    (str(PROJECT_ROOT / "frontend" / "templates"), "frontend/templates"),
    (str(PROJECT_ROOT / "benchmarks"), "benchmarks"),
    # The mined bug-fix pattern DB HypothesisGenerator reads from (read-only
    # at debug time) -- without it, the search finds zero candidate
    # hypotheses and every run silently degrades to "UNABLE TO REPAIR".
    (str(PROJECT_ROOT / "patterns.db"), "."),
]
binaries = []
hiddenimports = [
    "model.core.ModelTester",
    "model.core.AbinDebugger",
    "model.FaultLocalizator",
    "model.HypothesisTester",
    "model.HypothesisGenerator",
    "model.HypothesisRefinement",
    "model.SearchSchema",
    "model.EvaluationEngine",
    "model.abstractor.NodeMapper",
    "model.misc.generate_test_cases",
]

# pandas/anthropic/pydantic all do dynamic/optional imports PyInstaller's
# static analysis can miss -- collect them fully rather than debug missing
# submodules one at a time.
for pkg in ("pandas", "anthropic", "pydantic", "pydantic_core"):
    pkg_datas, pkg_binaries, pkg_hiddenimports = collect_all(pkg)
    datas += pkg_datas
    binaries += pkg_binaries
    hiddenimports += pkg_hiddenimports

a = Analysis(  # noqa: F821
    [str(PROJECT_ROOT / "frontend" / "desktop.py")],
    pathex=[str(PROJECT_ROOT), str(PROJECT_ROOT / "frontend")],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
)
pyz = PYZ(a.pure)  # noqa: F821

exe = EXE(  # noqa: F821
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="AbinDebugger",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,  # no terminal window -- this is the whole point
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)

coll = COLLECT(  # noqa: F821
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    upx_exclude=[],
    name="AbinDebugger",
)

if sys.platform == "darwin":
    app = BUNDLE(  # noqa: F821
        coll,
        name="AbinDebugger.app",
        icon=None,
        bundle_identifier="com.abindebugger.app",
        info_plist={"NSHighResolutionCapable": "True"},
    )
