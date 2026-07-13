from __future__ import annotations

import unittest
from enum import Enum
from pathlib import Path
from types import SimpleNamespace

from app.main import patch_pywebview_qt6_permissions
from app.runtime_paths import app_icon_path


class Feature(Enum):
    MediaAudioCapture = 1
    MediaVideoCapture = 2
    MediaAudioVideoCapture = 3
    ClipboardReadWrite = 4
    Geolocation = 5


class PermissionPolicy(Enum):
    PermissionGrantedByUser = 1
    PermissionDeniedByUser = 2


class FakeWebPage:
    calls: list[tuple[object, object, object]]

    def setFeaturePermission(self, url: object, feature: object, policy: object) -> None:
        self.calls.append((url, feature, policy))


class FakeUrl:
    def __init__(self, host: str) -> None:
        self._host = host

    def host(self) -> str:
        return self._host


class QtPermissionPatchTest(unittest.TestCase):
    def setUp(self) -> None:
        self.qt_module = SimpleNamespace(
            _qt6=True,
            QWebPage=SimpleNamespace(Feature=Feature, PermissionPolicy=PermissionPolicy),
            BrowserView=SimpleNamespace(WebPage=FakeWebPage),
        )
        if hasattr(FakeWebPage, "_codex_proxy_permission_patch"):
            delattr(FakeWebPage, "_codex_proxy_permission_patch")

    def test_uses_qt_enum_instead_of_raw_integer(self) -> None:
        self.assertTrue(patch_pywebview_qt6_permissions(self.qt_module))
        page = FakeWebPage()
        page.calls = []

        page.onFeaturePermissionRequested(FakeUrl("example.com"), Feature.Geolocation)

        self.assertEqual(page.calls[0][2], PermissionPolicy.PermissionDeniedByUser)
        self.assertIsInstance(page.calls[0][2], PermissionPolicy)

    def test_allows_clipboard_only_for_local_desktop_page(self) -> None:
        patch_pywebview_qt6_permissions(self.qt_module)
        page = FakeWebPage()
        page.calls = []

        page.onFeaturePermissionRequested(FakeUrl("127.0.0.1"), Feature.ClipboardReadWrite)
        page.onFeaturePermissionRequested(FakeUrl("example.com"), Feature.ClipboardReadWrite)

        self.assertEqual(page.calls[0][2], PermissionPolicy.PermissionGrantedByUser)
        self.assertEqual(page.calls[1][2], PermissionPolicy.PermissionDeniedByUser)


class AppIconTest(unittest.TestCase):
    def test_desktop_icon_is_available_in_source_tree(self) -> None:
        icon = app_icon_path()

        self.assertEqual(icon.name, "app-icon.png")
        self.assertTrue(Path(icon).is_file())


if __name__ == "__main__":
    unittest.main()
