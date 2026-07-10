import hashlib
from types import SimpleNamespace
from typing import Any

import pytest

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
    def __init__(self, responses: dict[str, FakeResponse]) -> None:
        self.responses = responses

    def get(self, url: str, timeout: int) -> FakeResponse:
        del timeout
        if url not in self.responses:
            raise AssertionError(f"unexpected request: {url}")
        return self.responses[url]


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
