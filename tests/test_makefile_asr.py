from __future__ import annotations

import os
import importlib.util
import shutil
import stat
import subprocess
import sys
import types
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
        f"printf '%s\\n' \"$*\" >> '{tmp_path}/docker-calls.log'\n"
        "if [ \"$1\" = compose ] && [ \"$2\" = version ]; then exit 0; fi\n"
        f"if [ \"$1\" = info ]; then printf '%s\\n' '{runtimes}'; exit 0; fi\n"
        "if [ \"$1\" = compose ] && [ \"$2\" = run ]; then "
        "printf '%s' \"$*\" | grep -Eq 'torch\\.ones\\(1, device=\"cuda\"\\)|ctranslate2' || exit 97; "
        f"exit {0 if gpu_probe_ok else 1}; fi\n"
        "if [ \"$1\" = compose ]; then exit 0; fi\n"
        "if [ \"$1\" = image ] && [ \"$2\" = inspect ]; then exit 1; fi\n"
        "if [ \"$1\" = pull ]; then exit 0; fi\n"
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
    assert env["ASR_COMPUTE_TYPE"] == "float32"
    assert env["XIAOZHI_CONTAINER_RUNTIME"] == "runc"
    assert env["NVIDIA_VISIBLE_DEVICES"] == "void"
    config = yaml.safe_load((tmp_path / "data/.config.yaml").read_text())
    assert config["selected_module"]["ASR"] == "FunASR"
    assert config["ASR"]["FunASR"]["device"] == "cpu"
    assert config["ASR"]["FunASR"]["language"] == "auto"
    assert env["ASR_LANGUAGE"] == "auto"


def test_setup_builds_xiaozhi_base_before_application_images(tmp_path: Path) -> None:
    result = _run_setup(tmp_path, has_cuda=False, asr_lines=["ASR_ACCELERATION=auto"])
    assert result.returncode == 0, result.stdout + result.stderr
    calls = (tmp_path / "docker-calls.log").read_text().splitlines()
    base_build = calls.index("compose --profile build-only build xiaozhi-base")
    application_build = calls.index("compose build")
    assert base_build < application_build


def test_setup_pulls_configured_xiaozhi_base_instead_of_building_it(tmp_path: Path) -> None:
    image = "registry.example.test/dotty/xiaozhi-base:cu128"
    result = _run_setup(
        tmp_path,
        has_cuda=False,
        asr_lines=["ASR_ACCELERATION=auto", f"XIAOZHI_BASE_IMAGE={image}"],
    )
    assert result.returncode == 0, result.stdout + result.stderr
    calls = (tmp_path / "docker-calls.log").read_text().splitlines()
    assert f"pull {image}" in calls
    assert "compose --profile build-only build xiaozhi-base" not in calls


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
    assert env["ASR_MODULE"] == "FunASR"
    assert env["ASR_DEVICE"] == "cuda"
    assert env["ASR_COMPUTE_TYPE"] == "float32"
    assert env["XIAOZHI_CONTAINER_RUNTIME"] == "nvidia"
    assert env["NVIDIA_VISIBLE_DEVICES"] == "all"
    config = yaml.safe_load((tmp_path / "data/.config.yaml").read_text())
    assert config["selected_module"]["ASR"] == "FunASR"
    assert config["ASR"]["FunASR"]["device"] == "cuda"
    assert config["ASR"]["FunASR"]["language"] == "auto"
    assert "FunASR CUDA support verified" in result.stdout


def test_forced_cpu_wins_when_nvidia_runtime_exists(tmp_path: Path) -> None:
    result = _run_setup(tmp_path, has_cuda=True, asr_lines=["ASR_ACCELERATION=cpu"])
    assert result.returncode == 0, result.stdout + result.stderr
    env = _read_env(tmp_path / ".env")
    assert env["ASR_MODULE"] == "FunASR"
    assert env["ASR_DEVICE"] == "cpu"
    assert env["XIAOZHI_CONTAINER_RUNTIME"] == "runc"
    assert env["NVIDIA_VISIBLE_DEVICES"] == "void"


def test_funasr_language_can_be_pinned(tmp_path: Path) -> None:
    result = _run_setup(
        tmp_path,
        has_cuda=False,
        asr_lines=["ASR_ACCELERATION=cpu", "ASR_LANGUAGE=zh"],
    )
    assert result.returncode == 0, result.stdout + result.stderr
    config = yaml.safe_load((tmp_path / "data/.config.yaml").read_text())
    assert config["ASR"]["FunASR"]["language"] == "zh"
    assert _read_env(tmp_path / ".env")["ASR_LANGUAGE"] == "zh"


def test_rejects_unknown_asr_language(tmp_path: Path) -> None:
    result = _run_setup(
        tmp_path,
        has_cuda=False,
        asr_lines=["ASR_ACCELERATION=cpu", "ASR_LANGUAGE=english"],
    )
    assert result.returncode != 0
    assert "ASR_LANGUAGE must be" in result.stdout


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


def test_manual_funasr_defaults_to_auto_language_and_float32(tmp_path: Path) -> None:
    result = _run_setup(
        tmp_path,
        has_cuda=False,
        asr_lines=["ASR_ACCELERATION=manual", "ASR_MODULE=FunASR"],
    )
    assert result.returncode == 0, result.stdout + result.stderr
    env = _read_env(tmp_path / ".env")
    config = yaml.safe_load((tmp_path / "data/.config.yaml").read_text())
    assert env["ASR_LANGUAGE"] == "auto"
    assert config["ASR"]["FunASR"] == {
        "type": "fun_local",
        "model_dir": "models/SenseVoiceSmall",
        "output_dir": "tmp/",
        "language": "auto",
        "device": "cpu",
    }


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
    assert "cannot run FunASR on CUDA" in result.stdout


def test_funasr_provider_passes_configured_cuda_device(monkeypatch) -> None:
    calls: list[dict] = []

    class FakeAutoModel:
        def __init__(self, **kwargs):
            calls.append(kwargs)

    class FakeLogger:
        def bind(self, **_kwargs):
            return self

        def __getattr__(self, _name):
            return lambda *_args, **_kwargs: None

    modules = {
        "funasr": types.SimpleNamespace(AutoModel=FakeAutoModel),
        "psutil": types.SimpleNamespace(
            virtual_memory=lambda: types.SimpleNamespace(total=8 * 1024**3)
        ),
        "config": types.ModuleType("config"),
        "config.logger": types.SimpleNamespace(setup_logging=lambda: FakeLogger()),
        "core": types.ModuleType("core"),
        "core.providers": types.ModuleType("core.providers"),
        "core.providers.asr": types.ModuleType("core.providers.asr"),
        "core.providers.asr.utils": types.SimpleNamespace(lang_tag_filter=lambda value: value),
        "core.providers.asr.base": types.SimpleNamespace(ASRProviderBase=object),
        "core.providers.asr.dto": types.ModuleType("core.providers.asr.dto"),
        "core.providers.asr.dto.dto": types.SimpleNamespace(
            InterfaceType=types.SimpleNamespace(LOCAL="local")
        ),
    }
    for name, module in modules.items():
        monkeypatch.setitem(sys.modules, name, module)

    path = ROOT / "custom-providers/asr/fun_local.py"
    spec = importlib.util.spec_from_file_location("fun_local_under_test", path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)

    provider = module.ASRProvider(
        {
            "model_dir": "models/SenseVoiceSmall",
            "output_dir": "tmp",
            "device": "cuda",
        },
        delete_audio_file=True,
    )
    assert provider.device == "cuda:0"
    assert provider.language == "auto"
    assert calls == [
        {
            "model": "models/SenseVoiceSmall",
            "vad_kwargs": {"max_single_segment_time": 30000},
            "disable_update": True,
            "hub": "hf",
            "device": "cuda:0",
        }
    ]
