from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from bridge.voices import (
    VoiceError,
    create_voice,
    delete_voice,
    read_voices,
    update_voice,
)


class VoiceStoreTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory(prefix="dotty-voices-")
        self.path = Path(self.tmp.name) / "voices.json"

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def test_missing_store_has_default_chattts_voice(self) -> None:
        voice = read_voices(self.path)["voices"][0]
        self.assertEqual(voice["id"], "default")
        self.assertEqual(voice["provider"], "chattts")
        self.assertEqual(voice["config"]["seed"], 42)

    def test_chattts_and_edge_crud(self) -> None:
        state = create_voice(
            "Young AU",
            "edge",
            {
                "voice": "en-AU-NatashaNeural",
                "rate": "+10%",
                "volume": "+0%",
                "pitch": "+5Hz",
            },
            self.path,
        )
        edge = state["voices"][1]
        state = update_voice(
            edge["id"],
            "Fast AU",
            "edge",
            {**edge["config"], "rate": "+20%"},
            self.path,
        )
        self.assertEqual(state["voices"][1]["config"]["rate"], "+20%")
        state = delete_voice(edge["id"], self.path)
        self.assertEqual([voice["id"] for voice in state["voices"]], ["default"])

    def test_invalid_provider_specific_values_are_rejected(self) -> None:
        with self.assertRaisesRegex(VoiceError, "Edge voice"):
            create_voice(
                "Broken", "edge",
                {"voice": "nope", "rate": "+0%", "volume": "+0%", "pitch": "+0Hz"},
                self.path,
            )
        with self.assertRaisesRegex(VoiceError, "Temperature"):
            create_voice(
                "Broken", "chattts",
                {
                    "seed": 1, "temperature": 9, "top_p": 0.7, "top_k": 20,
                    "refine_prompt": "[oral_2]", "code_prompt": "[speed_5]",
                },
                self.path,
            )


if __name__ == "__main__":
    unittest.main()
