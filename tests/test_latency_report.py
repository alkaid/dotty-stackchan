import importlib.util
from pathlib import Path
import unittest


_PATH = Path(__file__).parents[1] / "scripts" / "latency_report.py"
_SPEC = importlib.util.spec_from_file_location("latency_report", _PATH)
assert _SPEC is not None and _SPEC.loader is not None
latency_report = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(latency_report)


class TestLatencyReport(unittest.TestCase):
    def test_parse_and_summarise_privacy_safe_events(self):
        lines = [
            "svc | DOTTY_LATENCY component=role_tts turn=a phase=answer_first_opus elapsed_ms=2100",
            "svc | DOTTY_LATENCY component=role_tts turn=b phase=answer_first_opus elapsed_ms=1200",
            "svc | DOTTY_LATENCY component=dotty_pi turn=a phase=pi_tool_end elapsed_ms=900 tool=think_hard",
            "svc | DOTTY_LATENCY component=role_tts turn=a phase=filler_start elapsed_ms=1201",
            "svc | user text must be ignored",
        ]

        phases, flags = latency_report.summarise(lines)

        self.assertEqual(phases["answer_first_opus"], [2100, 1200])
        self.assertEqual(flags["a"], {"tool:think_hard", "filler"})
        self.assertNotIn("user", str(phases))

    def test_percentile_uses_nearest_rank(self):
        values = list(range(1, 21))

        self.assertEqual(latency_report.percentile(values, 0.50), 10)
        self.assertEqual(latency_report.percentile(values, 0.95), 19)


if __name__ == "__main__":
    unittest.main()
