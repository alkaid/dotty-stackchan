from __future__ import annotations

import importlib.util
import json
import tempfile
import unittest
from pathlib import Path


_PATH = (
    Path(__file__).resolve().parents[1]
    / "custom-providers" / "role_tts" / "profile_state.py"
)
_SPEC = importlib.util.spec_from_file_location("role_tts_profile_state", _PATH)
assert _SPEC is not None and _SPEC.loader is not None
profile_state = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(profile_state)


class VoiceProfileStateTests(unittest.TestCase):
    def test_active_role_resolves_assigned_voice(self) -> None:
        with tempfile.TemporaryDirectory(prefix="dotty-profile-") as tmp:
            root = Path(tmp)
            roles = root / "roles.json"
            voices = root / "voices.json"
            roles.write_text(json.dumps({
                "active_role_id": "guide",
                "roles": [{"id": "guide", "voice_id": "edge-au"}],
            }))
            voices.write_text(json.dumps({
                "voices": [{
                    "id": "edge-au", "name": "AU", "provider": "edge",
                    "config": {"voice": "en-AU-NatashaNeural"},
                }],
            }))
            voice = profile_state.load_active_voice(str(roles), str(voices))
            self.assertEqual(voice["id"], "edge-au")

    def test_missing_role_store_uses_saved_default_voice(self) -> None:
        with tempfile.TemporaryDirectory(prefix="dotty-profile-") as tmp:
            root = Path(tmp)
            voices = root / "voices.json"
            voices.write_text(json.dumps({
                "voices": [{
                    "id": "default",
                    "name": "Louder Xiaoxiao",
                    "provider": "edge",
                    "config": {
                        "voice": "zh-CN-XiaoxiaoNeural",
                        "volume": "+40%",
                    },
                }],
            }))

            voice = profile_state.load_active_voice(
                str(root / "missing-roles.json"), str(voices),
            )

            self.assertEqual(voice["name"], "Louder Xiaoxiao")
            self.assertEqual(voice["config"]["volume"], "+40%")

    def test_missing_assigned_voice_uses_saved_default_voice(self) -> None:
        with tempfile.TemporaryDirectory(prefix="dotty-profile-") as tmp:
            root = Path(tmp)
            roles = root / "roles.json"
            voices = root / "voices.json"
            roles.write_text(json.dumps({
                "active_role_id": "guide",
                "roles": [{"id": "guide", "voice_id": "deleted-voice"}],
            }))
            voices.write_text(json.dumps({
                "voices": [{
                    "id": "default",
                    "name": "Saved default",
                    "provider": "edge",
                    "config": {"volume": "+40%"},
                }],
            }))

            voice = profile_state.load_active_voice(str(roles), str(voices))

            self.assertEqual(voice["id"], "default")
            self.assertEqual(voice["config"]["volume"], "+40%")

    def test_missing_or_invalid_state_uses_default(self) -> None:
        voice = profile_state.load_active_voice("/missing/roles", "/missing/voices")
        self.assertEqual(voice["id"], "default")
        self.assertEqual(voice["provider"], "edge")
        self.assertEqual(voice["config"]["voice"], "zh-CN-XiaoxiaoNeural")


if __name__ == "__main__":
    unittest.main()
