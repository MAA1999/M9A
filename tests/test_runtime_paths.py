from pathlib import Path

from agent.utils.runtime_paths import build_runtime_paths


def test_builds_project_and_work_root_paths_separately() -> None:
    paths = build_runtime_paths(
        project_root="/tmp/m9a-project",
        work_root="/tmp/m9a-project",
    )

    assert paths.project_root == Path("/tmp/m9a-project").resolve()
    assert paths.work_root == Path("/tmp/m9a-project").resolve()
    assert paths.config_dir == Path("/tmp/m9a-project/config").resolve()
    assert paths.resource_dir == Path("/tmp/m9a-project/resource").resolve()
    assert paths.manifest_cache_file == Path("/tmp/m9a-project/data/manifest_cache.json").resolve()
