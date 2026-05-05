import unittest
from pathlib import Path

from agent.utils.runtime_paths import build_runtime_paths


class RuntimePathsTest(unittest.TestCase):
    def test_builds_project_and_work_root_paths_separately(self):
        paths = build_runtime_paths(
            project_root="/tmp/m9a-project",
            work_root="/tmp/m9a-project/assets",
        )

        self.assertEqual(paths.project_root, Path("/tmp/m9a-project").resolve())
        self.assertEqual(paths.work_root, Path("/tmp/m9a-project/assets").resolve())
        self.assertEqual(paths.deps_dir, Path("/tmp/m9a-project/deps").resolve())
        self.assertEqual(paths.config_dir, Path("/tmp/m9a-project/assets/config").resolve())
        self.assertEqual(paths.resource_dir, Path("/tmp/m9a-project/assets/resource").resolve())
        self.assertEqual(
            paths.manifest_cache_file,
            Path("/tmp/m9a-project/assets/resource/data/manifest_cache.json").resolve(),
        )


if __name__ == "__main__":
    unittest.main()
