from typing import Any

import requests

from agent.utils import manifest_checker


class FakeResponse:
    def __init__(self, json_data: dict[str, Any]) -> None:
        self._json_data = json_data

    def raise_for_status(self) -> None:
        return None

    def json(self) -> dict[str, Any]:
        return self._json_data


class FailingChildSession:
    def __init__(self) -> None:
        self.headers: list[dict[str, str]] = []

    def get(self, url: str, timeout: int, **kwargs: Any) -> FakeResponse:
        del timeout
        self.headers.append(kwargs.get("headers") or {})
        if url == manifest_checker.MANIFEST_URL:
            return FakeResponse(
                {
                    "updated": 2,
                    "directories": [{"name": "data", "manifest": "data/manifest.json"}],
                }
            )
        if url.endswith("/data/manifest.json"):
            return FakeResponse(
                {
                    "updated": 2,
                    "directories": [{"manifest": "data/activity/manifest.json"}],
                }
            )
        raise requests.ConnectionError("child manifest unavailable")


class LegacyManifestSession:
    def __init__(self) -> None:
        self.headers: list[dict[str, str]] = []

    def get(self, url: str, timeout: int, **kwargs: Any) -> FakeResponse:
        del timeout
        self.headers.append(kwargs.get("headers") or {})
        if url == manifest_checker.MANIFEST_URL:
            return FakeResponse(
                {
                    "updated": 2,
                    "directories": [{"name": "resource", "manifest": "resource/manifest.json"}],
                }
            )
        if url.endswith("/resource/manifest.json"):
            return FakeResponse(
                {
                    "updated": 2,
                    "directories": [{"manifest": "resource/data/manifest.json"}],
                }
            )
        raise AssertionError(f"legacy manifest should be ignored: {url}")


def test_child_manifest_failure_marks_check_as_failed(monkeypatch: Any) -> None:
    monkeypatch.setattr(
        manifest_checker,
        "_load_cache",
        lambda: {
            "root_updated": 1,
            "manifests": {
                "manifest.json": 1,
                "data/manifest.json": 1,
                "data/activity/manifest.json": 1,
            },
        },
    )
    monkeypatch.setattr(manifest_checker, "session", FailingChildSession())

    result = manifest_checker.check_manifest_updates()

    assert result["success"] is False
    assert result["has_any_update"] is True
    assert result["error"] == "部分 manifest 获取失败"


def test_legacy_resource_data_manifest_is_ignored(monkeypatch: Any) -> None:
    monkeypatch.setattr(
        manifest_checker,
        "_load_cache",
        lambda: {
            "root_updated": 1,
            "manifests": {
                "manifest.json": 1,
                "resource/manifest.json": 1,
            },
        },
    )
    monkeypatch.setattr(manifest_checker, "session", LegacyManifestSession())

    result = manifest_checker.check_manifest_updates()

    assert result["success"] is True
    assert result["has_any_update"] is False
    assert result["collected_manifests"]["resource/manifest.json"] == 2


def test_manifest_requests_bypass_cdn_cache(monkeypatch: Any) -> None:
    """回归：manifest 命中 CDN 旧副本会判定"无更新"、静默漏更，必须带 no-cache。"""
    session = LegacyManifestSession()
    monkeypatch.setattr(
        manifest_checker,
        "_load_cache",
        lambda: {"root_updated": 1, "manifests": {"manifest.json": 1}},
    )
    monkeypatch.setattr(manifest_checker, "session", session)

    manifest_checker.check_manifest_updates()

    assert session.headers, "应至少发起一次 manifest 请求"
    assert all(headers.get("Cache-Control") == "no-cache" for headers in session.headers)
