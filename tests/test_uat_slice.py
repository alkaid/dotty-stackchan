import importlib.util
import sys
from pathlib import Path
from types import SimpleNamespace


SCRIPT = Path(__file__).parents[1] / "scripts" / "uat-slice.py"


def load_uat_slice():
    spec = importlib.util.spec_from_file_location("uat_slice", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def run_slicer(tmp_path, monkeypatch, capsys, row):
    module = load_uat_slice()
    results = tmp_path / "2026-07-11" / "results.csv"
    results.parent.mkdir()
    results.write_text(
        "check_id,verdict,source,start,end,note\n" + row + "\n",
        encoding="utf-8",
    )
    video = tmp_path / "phone.mov"
    video.touch()
    commands = []

    def fake_run(command):
        commands.append(command)
        return SimpleNamespace(returncode=0)

    monkeypatch.setattr(module.subprocess, "run", fake_run)
    monkeypatch.setattr(
        sys,
        "argv",
        [
            str(SCRIPT),
            str(results),
            "--video",
            f"phone={video}",
            "--sync",
            "phone=00:00:00@19:41:32",
            "--out",
            str(tmp_path / "clips"),
        ],
    )
    return module.main(), commands, capsys.readouterr().out


def test_equal_timestamps_create_pad_only_event_clip(tmp_path, monkeypatch, capsys):
    result, commands, output = run_slicer(
        tmp_path,
        monkeypatch,
        capsys,
        "UT7,FAIL,phone,20:01:31,20:01:31,event marker",
    )

    assert result == 0
    assert len(commands) == 1
    assert commands[0][commands[0].index("-ss") + 1] == "00:19:56.000"
    assert commands[0][commands[0].index("-to") + 1] == "00:20:02.000"
    assert "FAIL    UT7" in output


def test_blank_timestamps_remain_skipped(tmp_path, monkeypatch, capsys):
    result, commands, output = run_slicer(
        tmp_path,
        monkeypatch,
        capsys,
        "US7,FAIL,phone,,,missing observation time",
    )

    assert result == 1
    assert commands == []
    assert "SKIP US7" in output


def test_reversed_timestamps_remain_invalid(tmp_path, monkeypatch, capsys):
    result, commands, output = run_slicer(
        tmp_path,
        monkeypatch,
        capsys,
        "UC1,PASS,phone,19:45:15,19:45:06,reversed window",
    )

    assert result == 1
    assert commands == []
    assert "end 19:45:06 before start 19:45:15" in output
