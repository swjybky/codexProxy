from pathlib import Path
import sys

from PyInstaller.utils.hooks import collect_all


root = Path(SPECPATH).parent
icons = root / "packaging" / "icons"
webview_datas, webview_binaries, webview_hiddenimports = collect_all("webview")
exe_options = {}
if sys.platform == "win32":
    exe_options["icon"] = str(icons / "app-icon.ico")

a = Analysis(
    [str(root / "run.py")],
    pathex=[str(root)],
    binaries=webview_binaries,
    datas=webview_datas
    + [
        (str(root / "web" / "dist"), "web/dist"),
        (str(icons / "app-icon.png"), "packaging/icons"),
        (str(icons / "app-icon.ico"), "packaging/icons"),
    ],
    hiddenimports=webview_hiddenimports,
    hookspath=[],
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
)
pyz = PYZ(a.pure)
exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="CodexProxy",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=False,
    **exe_options,
)
coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=True,
    name="CodexProxy",
)

if sys.platform == "darwin":
    app = BUNDLE(
        coll,
        name="CodexProxy.app",
        icon=str(icons / "app-icon.icns"),
        bundle_identifier="com.codexproxy.desktop",
        info_plist={
            "CFBundleDisplayName": "Codex Proxy",
            "NSHighResolutionCapable": True,
        },
    )
