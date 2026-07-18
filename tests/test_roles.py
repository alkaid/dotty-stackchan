from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from bridge.roles import (
    RoleError,
    activate_role,
    create_role,
    delete_role,
    read_roles,
    update_role,
)


class RoleStoreTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory(prefix="dotty-roles-")
        self.root = Path(self.tmp.name)
        self.path = self.root / "roles.json"
        self.seed = self.root / "default.md"
        self.seed.write_text("You are the default role.\n", encoding="utf-8")
        self.env = patch.dict(
            "os.environ", {
                "DOTTY_DEFAULT_ROLE_FILE": str(self.seed),
                "ROBOT_NAME": "Mochi",
            },
        )
        self.env.start()

    def tearDown(self) -> None:
        self.env.stop()
        self.tmp.cleanup()

    def test_missing_store_uses_default_role_without_writing(self) -> None:
        state = read_roles(self.path)
        self.assertEqual(state["active_role_id"], "default")
        self.assertEqual(state["roles"][0]["name"], "Mochi")
        self.assertFalse(self.path.exists())

    def test_legacy_default_dotty_role_follows_robot_name(self) -> None:
        self.path.write_text(json.dumps({
            "version": 1,
            "active_role_id": "default",
            "roles": [{
                "id": "default",
                "name": "Dotty",
                "prompt": "You are Dotty, a small robot.",
                "voice_id": "default",
            }],
        }), encoding="utf-8")

        role = read_roles(self.path)["roles"][0]
        self.assertEqual(role["name"], "Mochi")
        self.assertEqual(role["prompt"], "You are Mochi, a small robot.")

    def test_renaming_role_rebinds_identity_line(self) -> None:
        state = create_role(
            "Guide", "You are Guide, a patient museum guide.", path=self.path,
        )
        guide = state["roles"][1]
        state = update_role(
            guide["id"], "Curator", guide["prompt"], path=self.path,
        )
        self.assertEqual(
            state["roles"][1]["prompt"],
            "You are Curator, a patient museum guide.",
        )

    def test_crud_and_activation_round_trip(self) -> None:
        state = create_role("Guide", "You are a patient guide.", path=self.path)
        guide = state["roles"][1]
        state = update_role(
            guide["id"], "Museum Guide", "Explain every exhibit.", path=self.path,
        )
        self.assertEqual(state["roles"][1]["name"], "Museum Guide")
        state = activate_role(guide["id"], self.path)
        self.assertEqual(state["active_role_id"], guide["id"])
        state = activate_role("default", self.path)
        state = delete_role(guide["id"], self.path)
        self.assertEqual([role["id"] for role in state["roles"]], ["default"])
        self.assertEqual(json.loads(self.path.read_text()), state)

    def test_active_role_cannot_be_deleted(self) -> None:
        with self.assertRaisesRegex(RoleError, "Activate another role"):
            delete_role("default", self.path)

    def test_invalid_store_is_not_silently_overwritten(self) -> None:
        self.path.write_text("not json", encoding="utf-8")
        with self.assertRaisesRegex(RoleError, "Unable to read"):
            create_role("Guide", "Prompt", path=self.path)

    def test_role_limits_are_validated(self) -> None:
        with self.assertRaisesRegex(RoleError, "name"):
            create_role("", "Prompt", path=self.path)
        with self.assertRaisesRegex(RoleError, "prompt"):
            create_role("Guide", "", path=self.path)


if __name__ == "__main__":
    unittest.main()
