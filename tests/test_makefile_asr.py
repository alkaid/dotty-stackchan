from __future__ import annotations

import os
import shutil
import stat
import subprocess
from pathlib import Path

import pytest
import yaml


ROOT = Path(__file__).resolve().parents[1]
MAKE = shutil.which("make")


def _read_env(path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    for line in path.read_text().splitlines():
        if line and not line.startswith("#") and "=" in line:
            key, value = line.split("=", 1)
            values[key] = value
    return values


def _run_setup(
    tmp_path: Path,
    *,
    has_cuda: bool,
    asr_lines: list[str],
    gpu_probe_ok: bool = True,
    public_ws_base: str = "wss://voice.example.test:5443/",
    public_ota_base: str = "https://ota.example.test:5444/",
) -> subprocess.CompletedProcess[str]:
    if MAKE is None:
        pytest.skip("make is not installed")

    shutil.copy(ROOT / "Makefile", tmp_path / "Makefile")
    shutil.copy(ROOT / ".config.yaml.template", tmp_path / ".config.yaml.template")

    env_lines = [
        "TZ=UTC",
        "XIAOZHI_WS_PORT=5001",
        "XIAOZHI_HTTP_PORT=5002",
        "DOTTY_ADMIN_TOKEN=0123456789abcdef0123456789abcdef",
        "DOTTY_PI_BASE_URL=https://sub2api.example/v1",
        "DOTTY_PI_API_KEY=test-key",
        "DOTTY_PI_PROVIDER=sub2api",
        "DOTTY_PI_MODEL=dotty-simple",
        "VOICE_THINKER_MODEL=dotty-think",
        *asr_lines,
    ]
    env_lines.extend(
        [
            f"XIAOZHI_PUBLIC_WS_BASE_URL={public_ws_base}",
            f"XIAOZHI_PUBLIC_OTA_BASE_URL={public_ota_base}",
        ]
    )
    (tmp_path / ".env").write_text("\n".join(env_lines) + "\n")

    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    runtimes = '{"runc":{},"nvidia":{}}' if has_cuda else '{"runc":{}}'
    docker = fake_bin / "docker"
    docker.write_text(
        "#!/bin/sh\n"
        "if [ \"$1\" = compose ] && [ \"$2\" = version ]; then exit 0; fi\n"
        f"if [ \"$1\" = info ]; then printf '%s\\n' '{runtimes}'; exit 0; fi\n"
        "if [ \"$1\" = compose ] && [ \"$2\" = run ]; then "
        f"exit {0 if gpu_probe_ok else 1}; fi\n"
        "if [ \"$1\" = compose ]; then exit 0; fi\n"
        "exit 1\n"
    )
    docker.chmod(docker.stat().st_mode | stat.S_IXUSR)

    recursive_make = fake_bin / "make"
    recursive_make.write_text("#!/bin/sh\nexit 0\n")
    recursive_make.chmod(recursive_make.stat().st_mode | stat.S_IXUSR)

    env = os.environ.copy()
    env["PATH"] = f"{fake_bin}:{env['PATH']}"
    return subprocess.run(
        [MAKE, "setup"],
        cwd=tmp_path,
        env=env,
        text=True,
        capture_output=True,
        timeout=15,
    )


def test_auto_falls_back_to_cpu_without_nvidia_runtime(tmp_path: Path) -> None:
    result = _run_setup(tmp_path, has_cuda=False, asr_lines=["ASR_ACCELERATION=auto"])
    assert result.returncode == 0, result.stdout + result.stderr
    env = _read_env(tmp_path / ".env")
    assert env["ASR_MODULE"] == "FunASR"
    assert env["ASR_DEVICE"] == "cpu"
    assert env["ASR_COMPUTE_TYPE"] == "int8"
    assert env["XIAOZHI_CONTAINER_RUNTIME"] == "runc"
    assert env["NVIDIA_VISIBLE_DEVICES"] == "void"
    assert "ASR: FunASR" in (tmp_path / "data/.config.yaml").read_text()


def test_render_separates_internal_and_client_ports(tmp_path: Path) -> None:
    result = _run_setup(tmp_path, has_cuda=False, asr_lines=["ASR_ACCELERATION=auto"])
    assert result.returncode == 0, result.stdout + result.stderr
    config = yaml.safe_load((tmp_path / "data/.config.yaml").read_text())
    server = config["server"]
    assert server["port"] == 8000
    assert server["http_port"] == 8003
    assert server["websocket"] == "wss://voice.example.test:5443/xiaozhi/v1/"
    assert server["ota_base_url"] == "https://ota.example.test:5444"


def test_rejects_public_base_urls_with_paths(tmp_path: Path) -> None:
    result = _run_setup(
        tmp_path,
        has_cuda=False,
        asr_lines=["ASR_ACCELERATION=auto"],
        public_ws_base="wss://voice.example.test:5443/gateway",
        public_ota_base="https://ota.example.test:5444/gateway",
    )
    assert result.returncode != 0
    assert "XIAOZHI_PUBLIC_WS_BASE_URL" in result.stdout
    assert "XIAOZHI_PUBLIC_OTA_BASE_URL" in result.stdout


def test_requires_both_public_base_urls(tmp_path: Path) -> None:
    result = _run_setup(
        tmp_path,
        has_cuda=False,
        asr_lines=["ASR_ACCELERATION=auto"],
        public_ws_base="",
        public_ota_base="",
    )
    assert result.returncode != 0
    assert "Missing required keys:" in result.stdout
    assert "XIAOZHI_PUBLIC_WS_BASE_URL" in result.stdout
    assert "XIAOZHI_PUBLIC_OTA_BASE_URL" in result.stdout


def test_auto_enables_cuda_when_nvidia_runtime_exists(tmp_path: Path) -> None:
    result = _run_setup(tmp_path, has_cuda=True, asr_lines=["ASR_ACCELERATION=auto"])
    assert result.returncode == 0, result.stdout + result.stderr
    env = _read_env(tmp_path / ".env")
    assert env["ASR_MODULE"] == "WhisperLocal"
    assert env["ASR_DEVICE"] == "cuda"
    assert env["ASR_COMPUTE_TYPE"] == "float16"
    assert env["XIAOZHI_CONTAINER_RUNTIME"] == "nvidia"
    assert env["NVIDIA_VISIBLE_DEVICES"] == "all"
    assert "ASR: WhisperLocal" in (tmp_path / "data/.config.yaml").read_text()


def test_forced_cpu_wins_when_nvidia_runtime_exists(tmp_path: Path) -> None:
    result = _run_setup(tmp_path, has_cuda=True, asr_lines=["ASR_ACCELERATION=cpu"])
    assert result.returncode == 0, result.stdout + result.stderr
    env = _read_env(tmp_path / ".env")
    assert env["ASR_MODULE"] == "FunASR"
    assert env["ASR_DEVICE"] == "cpu"
    assert env["XIAOZHI_CONTAINER_RUNTIME"] == "runc"
    assert env["NVIDIA_VISIBLE_DEVICES"] == "void"


def test_existing_explicit_settings_default_to_manual(tmp_path: Path) -> None:
    result = _run_setup(
        tmp_path,
        has_cuda=True,
        asr_lines=[
            "ASR_MODULE=WhisperLocal",
            "ASR_DEVICE=cuda",
            "ASR_COMPUTE_TYPE=int8_float16",
            "XIAOZHI_CONTAINER_RUNTIME=nvidia",
            "NVIDIA_VISIBLE_DEVICES=2",
        ],
    )
    assert result.returncode == 0, result.stdout + result.stderr
    env = _read_env(tmp_path / ".env")
    assert env["ASR_ACCELERATION"] == "manual"
    assert env["ASR_COMPUTE_TYPE"] == "int8_float16"
    assert env["NVIDIA_VISIBLE_DEVICES"] == "2"


def test_manual_whisper_cpu_does_not_require_nvidia_runtime(tmp_path: Path) -> None:
    result = _run_setup(
        tmp_path,
        has_cuda=False,
        asr_lines=[
            "ASR_ACCELERATION=manual",
            "ASR_MODULE=WhisperLocal",
            "ASR_DEVICE=cpu",
            "ASR_COMPUTE_TYPE=int8",
            "XIAOZHI_CONTAINER_RUNTIME=runc",
            "NVIDIA_VISIBLE_DEVICES=void",
        ],
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert "Validating xiaozhi CUDA passthrough" not in result.stdout


def test_forced_cuda_fails_without_nvidia_runtime(tmp_path: Path) -> None:
    result = _run_setup(tmp_path, has_cuda=False, asr_lines=["ASR_ACCELERATION=cuda"])
    assert result.returncode != 0
    assert "requires the NVIDIA Docker runtime" in result.stdout


def test_auto_falls_back_to_cpu_when_container_cuda_probe_fails(tmp_path: Path) -> None:
    result = _run_setup(
        tmp_path,
        has_cuda=True,
        asr_lines=["ASR_ACCELERATION=auto"],
        gpu_probe_ok=False,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    env = _read_env(tmp_path / ".env")
    assert env["ASR_MODULE"] == "FunASR"
    assert env["ASR_DEVICE"] == "cpu"
    assert env["XIAOZHI_CONTAINER_RUNTIME"] == "runc"
    assert "CUDA probe failed" in result.stdout
    assert "ASR: FunASR" in (tmp_path / "data/.config.yaml").read_text()


def test_forced_cuda_fails_when_container_cuda_probe_fails(tmp_path: Path) -> None:
    result = _run_setup(
        tmp_path,
        has_cuda=True,
        asr_lines=["ASR_ACCELERATION=cuda"],
        gpu_probe_ok=False,
    )
    assert result.returncode != 0
    assert "cannot access CUDA with float16" in result.stdout
