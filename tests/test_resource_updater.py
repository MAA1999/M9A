import hashlib
from types import SimpleNamespace
from typing import Any

import pytest
import requests

from agent.utils import resource_updater


class FakeResponse:
    def __init__(self, *, json_data: Any = None, content: bytes = b"") -> None:
        self._json_data = json_data
        self.content = content

    def raise_for_status(self) -> None:
        return None

    def json(self) -> Any:
        return self._json_data


class FakeSession:
    """按 URL 返回预设响应；自动忽略重试时附加的查询串。"""

    def __init__(self, responses: dict[str, FakeResponse]) -> None:
        self.responses = responses
        self.requests: list[str] = []

    def get(self, url: str, timeout: int, **kwargs: Any) -> FakeResponse:
        del timeout, kwargs
        self.requests.append(url)
        base_url = url.split("?")[0]
        if base_url not in self.responses:
            raise AssertionError(f"unexpected request: {url}")
        return self.responses[base_url]


class FakeHttpError(requests.HTTPError):
    def __init__(self, status_code: int) -> None:
        super().__init__(f"HTTP {status_code}")
        self.response = SimpleNamespace(status_code=status_code)


def sha256(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


def test_full_fallback_starts_from_root_manifest(monkeypatch: Any) -> None:
    api_base = "https://example.test/api"
    fake_session = FakeSession(
        {
            f"{api_base}/manifest.json": FakeResponse(
                json_data={
                    "directories": [
                        {"manifest": "data/manifest.json"},
                        {"manifest": "resource/manifest.json"},
                        {"manifest": "images/manifest.json"},
                    ]
                }
            ),
            f"{api_base}/data/manifest.json": FakeResponse(
                json_data={"directories": [{"manifest": "data/activity/manifest.json"}]}
            ),
            f"{api_base}/data/activity/manifest.json": FakeResponse(json_data={"files": [{"path": "data/a.json"}]}),
            f"{api_base}/resource/manifest.json": FakeResponse(
                json_data={
                    "directories": [
                        {"manifest": "resource/base/manifest.json"},
                        {"manifest": "resource/data/manifest.json"},
                    ]
                }
            ),
            f"{api_base}/resource/base/manifest.json": FakeResponse(
                json_data={"files": [{"path": "resource/base/a.json"}]}
            ),
        }
    )
    monkeypatch.setattr(resource_updater, "session", fake_session)

    manifests = resource_updater.get_all_manifests(api_base, "manifest.json", timeout=5)

    assert manifests == ["data/activity/manifest.json", "resource/base/manifest.json"]


@pytest.mark.parametrize("unsafe_path", ["../outside.txt", "/absolute.txt", "C:/outside.txt", "..\\outside.txt"])
def test_rejects_file_path_outside_work_root(monkeypatch: Any, tmp_path: Any, unsafe_path: str) -> None:
    api_base = "https://example.test/api"
    work_root = tmp_path / "project"
    work_root.mkdir()
    monkeypatch.setattr(resource_updater, "get_runtime_paths", lambda: SimpleNamespace(work_root=work_root))
    monkeypatch.setattr(
        resource_updater,
        "session",
        FakeSession(
            {
                f"{api_base}/resource/manifest.json": FakeResponse(
                    json_data={"files": [{"path": unsafe_path, "hash": sha256(b"unsafe")}]}
                )
            }
        ),
    )

    result = resource_updater.check_and_update_resources(
        api_base_url=api_base,
        resource_manifests=["resource/manifest.json"],
    )

    assert result["success"] is False
    assert "unexpected request" not in result["error"]
    assert result["updated_files"] == []
    assert not (tmp_path / "outside.txt").exists()


def test_hash_failure_does_not_commit_other_staged_files(monkeypatch: Any, tmp_path: Any) -> None:
    api_base = "https://example.test/api"
    work_root = tmp_path / "project"
    good_path = work_root / "data" / "good.txt"
    good_path.parent.mkdir(parents=True)
    good_path.write_bytes(b"old")
    good_content = b"new-good"
    expected_bad_content = b"expected-bad"

    monkeypatch.setattr(resource_updater, "get_runtime_paths", lambda: SimpleNamespace(work_root=work_root))
    monkeypatch.setattr(
        resource_updater,
        "session",
        FakeSession(
            {
                f"{api_base}/data/test/manifest.json": FakeResponse(
                    json_data={
                        "files": [
                            {"path": "data/good.txt", "hash": sha256(good_content)},
                            {"path": "data/bad.txt", "hash": sha256(expected_bad_content)},
                        ]
                    }
                ),
                f"{api_base}/data/good.txt": FakeResponse(content=good_content),
                f"{api_base}/data/bad.txt": FakeResponse(content=b"tampered"),
            }
        ),
    )

    result = resource_updater.check_and_update_resources(
        api_base_url=api_base,
        resource_manifests=["data/test/manifest.json"],
    )

    assert result["success"] is False
    assert result["failed_files"] == ["data/bad.txt"]
    assert good_path.read_bytes() == b"old"
    assert not (work_root / "data" / "bad.txt").exists()
    assert list((work_root / "data").glob(".*.tmp")) == []


def test_commits_files_after_all_downloads_are_verified(monkeypatch: Any, tmp_path: Any) -> None:
    api_base = "https://example.test/api"
    work_root = tmp_path / "project"
    content = b"verified"
    monkeypatch.setattr(resource_updater, "get_runtime_paths", lambda: SimpleNamespace(work_root=work_root))
    monkeypatch.setattr(
        resource_updater,
        "session",
        FakeSession(
            {
                f"{api_base}/data/test/manifest.json": FakeResponse(
                    json_data={"files": [{"path": "data/value.txt", "hash": sha256(content)}]}
                ),
                f"{api_base}/data/value.txt": FakeResponse(content=content),
            }
        ),
    )

    result = resource_updater.check_and_update_resources(
        api_base_url=api_base,
        resource_manifests=["data/test/manifest.json"],
    )

    assert result["success"] is True
    assert result["updated_files"] == ["data/value.txt"]
    assert (work_root / "data" / "value.txt").read_bytes() == content


def test_invalid_manifest_path_returns_failure(monkeypatch: Any, tmp_path: Any) -> None:
    """manifest 路径非法时应返回失败结果，而不是把异常抛给 agent 启动流程。"""
    work_root = tmp_path / "project"
    work_root.mkdir()
    monkeypatch.setattr(resource_updater, "get_runtime_paths", lambda: SimpleNamespace(work_root=work_root))

    result = resource_updater.check_and_update_resources(
        api_base_url="https://example.test/api",
        resource_manifests=["../evil.json"],
    )

    assert result["success"] is False
    assert result["failed_manifests"] == ["../evil.json"]


def test_other_manifest_still_commits_when_one_manifest_fails(monkeypatch: Any, tmp_path: Any) -> None:
    """回归：某个 manifest 失败不应该拖住其它 manifest 已校验通过的文件。"""
    api_base = "https://example.test/api"
    work_root = tmp_path / "project"
    work_root.mkdir()
    good_content = b"good"

    monkeypatch.setattr(resource_updater, "get_runtime_paths", lambda: SimpleNamespace(work_root=work_root))
    monkeypatch.setattr(
        resource_updater,
        "session",
        FakeSession(
            {
                f"{api_base}/data/bad/manifest.json": FakeResponse(
                    json_data={"files": [{"path": "data/bad.txt", "hash": sha256(b"wanted")}]}
                ),
                f"{api_base}/data/bad.txt": FakeResponse(content=b"tampered"),
                f"{api_base}/data/good/manifest.json": FakeResponse(
                    json_data={"files": [{"path": "data/good.txt", "hash": sha256(good_content)}]}
                ),
                f"{api_base}/data/good.txt": FakeResponse(content=good_content),
            }
        ),
    )
    monkeypatch.setattr(resource_updater, "RETRY_BACKOFF_SECONDS", 0)

    result = resource_updater.check_and_update_resources(
        api_base_url=api_base,
        resource_manifests=["data/bad/manifest.json", "data/good/manifest.json"],
    )

    assert result["success"] is False
    assert result["failed_manifests"] == ["data/bad/manifest.json"]
    assert result["updated_files"] == ["data/good.txt"]
    assert (work_root / "data" / "good.txt").read_bytes() == good_content
    assert not (work_root / "data" / "bad.txt").exists()


def test_hash_failure_reports_both_hashes(monkeypatch: Any, tmp_path: Any) -> None:
    """失败信息要带上双方哈希与响应特征，便于判断是服务端还是链路问题。"""
    api_base = "https://example.test/api"
    work_root = tmp_path / "project"
    work_root.mkdir()
    expected_content = b"expected"
    actual_content = b"tampered"

    monkeypatch.setattr(resource_updater, "get_runtime_paths", lambda: SimpleNamespace(work_root=work_root))
    monkeypatch.setattr(
        resource_updater,
        "session",
        FakeSession(
            {
                f"{api_base}/data/test/manifest.json": FakeResponse(
                    json_data={"files": [{"path": "data/value.txt", "hash": sha256(expected_content)}]}
                ),
                f"{api_base}/data/value.txt": FakeResponse(content=actual_content),
            }
        ),
    )
    monkeypatch.setattr(resource_updater, "RETRY_BACKOFF_SECONDS", 0)

    result = resource_updater.check_and_update_resources(
        api_base_url=api_base,
        resource_manifests=["data/test/manifest.json"],
    )

    assert result["success"] is False
    assert sha256(expected_content)[:16] in result["error"]
    assert sha256(actual_content)[:16] in result["error"]
    assert f"大小 {len(actual_content)} 字节" in result["error"]


def test_hash_retry_bypasses_cdn_cache(monkeypatch: Any, tmp_path: Any) -> None:
    """首次拿到旧副本，重试（带 m9a_retry 参数）后拿到正确内容。"""
    api_base = "https://example.test/api"
    work_root = tmp_path / "project"
    work_root.mkdir()
    content = b"fresh"
    file_urls: list[str] = []

    class RetrySession:
        def get(self, url: str, timeout: int, **kwargs: Any) -> FakeResponse:
            del timeout, kwargs
            if url.endswith("manifest.json"):
                return FakeResponse(json_data={"files": [{"path": "data/value.txt", "hash": sha256(content)}]})
            file_urls.append(url)
            return FakeResponse(content=b"stale" if len(file_urls) == 1 else content)

    monkeypatch.setattr(resource_updater, "get_runtime_paths", lambda: SimpleNamespace(work_root=work_root))
    monkeypatch.setattr(resource_updater, "session", RetrySession())
    monkeypatch.setattr(resource_updater, "RETRY_BACKOFF_SECONDS", 0)

    result = resource_updater.check_and_update_resources(
        api_base_url=api_base,
        resource_manifests=["data/test/manifest.json"],
    )

    assert result["success"] is True
    assert (work_root / "data" / "value.txt").read_bytes() == content
    assert len(file_urls) == 2
    assert "m9a_retry=" in file_urls[1]


def test_http_4xx_is_not_retried(monkeypatch: Any, tmp_path: Any) -> None:
    """回归：404 这类响应重试不可能成功，只应尝试一次。"""
    api_base = "https://example.test/api"
    work_root = tmp_path / "project"
    work_root.mkdir()
    content = b"data"
    file_requests: list[str] = []

    class NotFoundSession:
        def get(self, url: str, timeout: int, **kwargs: Any) -> FakeResponse:
            del timeout, kwargs
            if url.endswith("manifest.json"):
                return FakeResponse(json_data={"files": [{"path": "data/value.txt", "hash": sha256(content)}]})
            file_requests.append(url)
            raise FakeHttpError(404)

    monkeypatch.setattr(resource_updater, "get_runtime_paths", lambda: SimpleNamespace(work_root=work_root))
    monkeypatch.setattr(resource_updater, "session", NotFoundSession())
    monkeypatch.setattr(resource_updater, "RETRY_BACKOFF_SECONDS", 0)

    result = resource_updater.check_and_update_resources(
        api_base_url=api_base,
        resource_manifests=["data/test/manifest.json"],
    )

    assert result["success"] is False
    assert result["failed_manifests"] == ["data/test/manifest.json"]
    assert len(file_requests) == 1


def test_error_field_keeps_every_failed_manifest(monkeypatch: Any, tmp_path: Any) -> None:
    """回归：多个清单失败时 error 不应只剩最后一条。"""
    api_base = "https://example.test/api"
    work_root = tmp_path / "project"
    work_root.mkdir()

    monkeypatch.setattr(resource_updater, "get_runtime_paths", lambda: SimpleNamespace(work_root=work_root))
    monkeypatch.setattr(
        resource_updater,
        "session",
        FakeSession(
            {
                f"{api_base}/data/a/manifest.json": FakeResponse(
                    json_data={"files": [{"path": "data/a.txt", "hash": sha256(b"want-a")}]}
                ),
                f"{api_base}/data/a.txt": FakeResponse(content=b"bad-a"),
                f"{api_base}/data/b/manifest.json": FakeResponse(
                    json_data={"files": [{"path": "data/b.txt", "hash": sha256(b"want-b")}]}
                ),
                f"{api_base}/data/b.txt": FakeResponse(content=b"bad-b"),
            }
        ),
    )
    monkeypatch.setattr(resource_updater, "RETRY_BACKOFF_SECONDS", 0)

    result = resource_updater.check_and_update_resources(
        api_base_url=api_base,
        resource_manifests=["data/a/manifest.json", "data/b/manifest.json"],
    )

    assert result["success"] is False
    assert result["failed_manifests"] == ["data/a/manifest.json", "data/b/manifest.json"]
    assert "data/a.txt" in result["error"]
    assert "data/b.txt" in result["error"]
