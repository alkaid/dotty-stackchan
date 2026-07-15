from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from bridge.runtime_config import effective_config, read_overrides, write_overrides


class RuntimeConfigTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory(prefix="dotty-runtime-unit-")
        self.path = Path(self.tmp.name) / "runtime-config.json"

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def test_round_trip_and_allowlist(self) -> None:
        write_overrides(
            {
                "DOTTY_PI_MODEL": "model-a",
                "DOTTY_PI_SIMPLE_REASONING": "true",
                "DOTTY_ADMIN_TOKEN": "must-not-be-written",
            },
            self.path,
        )
        self.assertEqual(read_overrides(self.path), {
            "DOTTY_PI_MODEL": "model-a",
            "DOTTY_PI_SIMPLE_REASONING": "true",
        })
        self.assertNotIn(
            "DOTTY_ADMIN_TOKEN", self.path.read_text(encoding="utf-8"),
        )

    def test_overrides_startup_defaults(self) -> None:
        self.path.write_text(
            json.dumps({"DOTTY_PI_MODEL": "persisted"}), encoding="utf-8",
        )
        values = effective_config({"DOTTY_PI_MODEL": "from-env"}, self.path)
        self.assertEqual(values["DOTTY_PI_MODEL"], "persisted")

    def test_invalid_config_falls_back_to_defaults(self) -> None:
        self.path.write_text("not-json", encoding="utf-8")
        value = effective_config({"DOTTY_PI_MODEL": "from-env"}, self.path)[
            "DOTTY_PI_MODEL"
        ]
        self.assertEqual(value, "from-env")


if __name__ == "__main__":
    unittest.main()
