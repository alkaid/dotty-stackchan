"""Active Role name resolution shared by autonomous mode prompts."""

from __future__ import annotations

import json

from role_identity import active_role_name, wake_phrase


def test_active_role_name_and_wake_phrase_follow_selected_role(tmp_path) -> None:
    path = tmp_path / "roles.json"
    path.write_text(json.dumps({
        "active_role_id": "guide",
        "roles": [
            {"id": "default", "name": "Dotty"},
            {"id": "guide", "name": "Mochi"},
        ],
    }), encoding="utf-8")

    assert active_role_name(path) == "Mochi"
    assert wake_phrase(path) == "hi, Mochi"


def test_legacy_default_role_follows_robot_name(tmp_path, monkeypatch) -> None:
    path = tmp_path / "roles.json"
    path.write_text(json.dumps({
        "active_role_id": "default",
        "roles": [{"id": "default", "name": "Dotty"}],
    }), encoding="utf-8")
    monkeypatch.setenv("ROBOT_NAME", "Mochi")

    assert active_role_name(path) == "Mochi"
