import importlib.util
from pathlib import Path
import tempfile
import unittest


_PATH = Path(__file__).parents[1] / "scripts" / "bump_firmware_version.py"
_SPEC = importlib.util.spec_from_file_location("bump_firmware_version", _PATH)
assert _SPEC is not None and _SPEC.loader is not None
bump_firmware_version = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(bump_firmware_version)


class TestFirmwareVersionBump(unittest.TestCase):
    def _cmake_file(self, version: str) -> tuple[tempfile.TemporaryDirectory, Path]:
        directory = tempfile.TemporaryDirectory()
        path = Path(directory.name) / "CMakeLists.txt"
        path.write_text(
            f'cmake_minimum_required(VERSION 3.16)\nset(PROJECT_VER "{version}")\n',
            encoding="utf-8",
        )
        return directory, path

    def test_default_bumps_patch_version(self):
        directory, path = self._cmake_file("1.3.5")
        with directory:
            version = bump_firmware_version.bump_project_version(path)
            self.assertEqual(version, "1.3.6")
            self.assertIn('set(PROJECT_VER "1.3.6")', path.read_text())

    def test_explicit_version_must_increase(self):
        directory, path = self._cmake_file("1.3.5")
        with directory:
            version = bump_firmware_version.bump_project_version(path, "1.4.0")
            self.assertEqual(version, "1.4.0")

        directory, path = self._cmake_file("1.3.5")
        with directory:
            with self.assertRaisesRegex(ValueError, "must exceed"):
                bump_firmware_version.bump_project_version(path, "1.3.5")


if __name__ == "__main__":
    unittest.main()
