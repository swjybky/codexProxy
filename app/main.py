from __future__ import annotations

import argparse
import os
import signal
import sys
import threading
import webbrowser
from typing import Any

from .runtime_paths import app_icon_path
from .server import start_server
from .storage import AppStore


def patch_pywebview_qt6_permissions(qt_module: Any | None = None) -> bool:
    """Fix pywebview 6.2.1 passing raw ints to Qt 6 permission APIs."""
    if qt_module is None:
        requested_gui = os.environ.get("PYWEBVIEW_GUI", "").strip().lower()
        if requested_gui and requested_gui not in {"qt", "qt6"}:
            return False
        try:
            from webview.platforms import qt as qt_module
        except (ImportError, ModuleNotFoundError):
            return False

    page_type = getattr(qt_module, "QWebPage", None)
    browser_view = getattr(qt_module, "BrowserView", None)
    if not getattr(qt_module, "_qt6", False) or page_type is None or browser_view is None:
        return False
    if not hasattr(page_type, "PermissionPolicy") or not hasattr(page_type, "Feature"):
        return False

    web_page = browser_view.WebPage
    if getattr(web_page, "_codex_proxy_permission_patch", False):
        return True

    feature_type = page_type.Feature
    policy_type = page_type.PermissionPolicy
    media_features = {
        feature
        for feature in (
            getattr(feature_type, "MediaAudioCapture", None),
            getattr(feature_type, "MediaVideoCapture", None),
            getattr(feature_type, "MediaAudioVideoCapture", None),
        )
        if feature is not None
    }
    clipboard_feature = getattr(feature_type, "ClipboardReadWrite", None)

    def on_feature_permission_requested(self: Any, url: Any, feature: Any) -> None:
        trusted_local_page = str(url.host()).lower() in {"127.0.0.1", "localhost", "::1"}
        allow = feature in media_features or (trusted_local_page and feature == clipboard_feature)
        policy = (
            policy_type.PermissionGrantedByUser
            if allow
            else policy_type.PermissionDeniedByUser
        )
        self.setFeaturePermission(url, feature, policy)

    web_page.onFeaturePermissionRequested = on_feature_permission_requested
    web_page._codex_proxy_permission_patch = True
    return True


def main() -> None:
    parser = argparse.ArgumentParser(description="Codex Proxy desktop application")
    parser.add_argument("--browser", action="store_true", help="在系统浏览器中打开，不启动 pywebview")
    parser.add_argument("--port", type=int, default=None, help="临时覆盖本地监听端口")
    args = parser.parse_args()

    store = AppStore()
    try:
        server = start_server(store, port=args.port)
    except OSError as error:
        raise SystemExit(f"无法启动本地服务：{error}") from error

    base_url = f"http://127.0.0.1:{server.server_port}/"
    admin_token = store.get_settings()["admin_token"]
    window_url = f"{base_url}#admin_token={admin_token}"
    print(f"Codex Proxy is running at {base_url}")

    if args.browser:
        webbrowser.open(window_url)
        stop = threading.Event()
        signal.signal(signal.SIGINT, lambda *_: stop.set())
        signal.signal(signal.SIGTERM, lambda *_: stop.set())
        stop.wait()
        server.shutdown()
        return

    if sys.platform.startswith("linux"):
        # QtPy otherwise picks whichever Qt binding happens to be installed
        # first. The Linux bundle ships PySide6 because it includes WebEngine.
        os.environ.setdefault("QT_API", "pyside6")
        os.environ.setdefault("PYWEBVIEW_GUI", "qt")

    try:
        import webview
    except ImportError as error:
        server.shutdown()
        raise SystemExit("缺少 pywebview，请先运行 pip install -r requirements.txt，或使用 --browser") from error

    patch_pywebview_qt6_permissions()
    webview.create_window(
        "Codex Proxy",
        window_url,
        width=1120,
        height=760,
        min_size=(900, 640),
        background_color="#F3F5F7",
    )
    try:
        webview.start(icon=str(app_icon_path()))
    finally:
        server.shutdown()
        server.server_close()


if __name__ == "__main__":
    main()
