from pathlib import Path

import yaml


ROOT = Path(__file__).resolve().parents[1]


def test_firmware_wake_phrase_does_not_start_an_llm_greeting() -> None:
    config = yaml.safe_load((ROOT / ".config.yaml.template").read_text())

    assert config["wakeup_words"] == ["HiESP"]
    assert config["enable_greeting"] is False
