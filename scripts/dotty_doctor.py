#!/usr/bin/env python3
"""dotty doctor - health-check CLI for the Dotty/StackChan stack.

Runs the same checks as `make doctor` but as a portable Python script
that can be invoked on any host (workstation, Docker host, CI) without make.

Usage:
    python scripts/dotty_doctor.py [options]

Options:
    --config PATH     Path to .config.yaml (default: auto-discovered)
    --env PATH        Path to .env (default: auto-discovered)
    --host HOST       Override the client-visible/service host
    --http-port N     Override legacy public xiaozhi HTTP/OTA port
    --ws-port N       Override the public xiaozhi WebSocket port
    --bridge-port N   Override published dashboard port
    --behaviour-port N Override published dotty-behaviour port
    --bridge-url U    Override dashboard (bridge.py :8081) health URL
    --server-url U    Override xiaozhi server OTA URL
    --behaviour-url U Override dotty-behaviour (:8090) health URL
    --timeout N       HTTP timeout in seconds (default: 5)
    --json          Output results as JSON to stdout
"""
from __future__ import annotations

import argparse
import json
import os
import re
import socket
import sys
import urllib.error
import urllib.request
from pathlib import Path
from typing import Optional
from urllib.parse import urlsplit


# ── ANSI colour helpers ───────────────────────────────────────────────────────

def _supports_color() -> bool:
    return (
        hasattr(sys.stdout, "isatty")
        and sys.stdout.isatty()
        and os.getenv("NO_COLOR") is None
    )


_COLOR = _supports_color()
GREEN  = "\033[0;32m" if _COLOR else ""
RED    = "\033[0;31m" if _COLOR else ""
YELLOW = "\033[0;33m" if _COLOR else ""
BOLD   = "\033[1m"    if _COLOR else ""
RESET  = "\033[0m"    if _COLOR else ""


# ── Result type ───────────────────────────────────────────────────────────────

class Result:
    __slots__ = ("label", "status", "detail")

    def __init__(self, label: str, status: str, detail: str = "") -> None:
        assert status in ("pass", "fail", "skip", "warn")
        self.label = label
        self.status = status
        self.detail = detail

    def print_line(self) -> None:
        tag = {
            "pass": f"{GREEN}PASS{RESET}",
            "fail": f"{RED}FAIL{RESET}",
            "skip": f"{YELLOW}SKIP{RESET}",
            "warn": f"{YELLOW}WARN{RESET}",
        }[self.status]
        suffix = f"  ({self.detail})" if self.detail else ""
        print(f"  {tag}  {self.label}{suffix}")

    def to_dict(self) -> dict:
        return {"label": self.label, "status": self.status, "detail": self.detail}


# ── Config discovery ──────────────────────────────────────────────────────────

def _find_config(hint: Optional[str] = None) -> Optional[Path]:
    if hint:
        p = Path(hint).expanduser()
        return p if p.exists() else None
    for candidate in [Path.cwd(), *Path.cwd().parents]:
        # New: setup wizard renders to data/.config.yaml (matches the
        # compose.yml bind mount). Legacy: pre-template root copy.
        for rel in ("data/.config.yaml", ".config.yaml"):
            p = candidate / rel
            if p.exists():
                return p
    return None


def _find_env(hint: Optional[str] = None) -> Optional[Path]:
    if hint:
        p = Path(hint).expanduser()
        return p if p.exists() else None
    for candidate in [Path.cwd(), *Path.cwd().parents]:
        p = candidate / ".env"
        if p.exists():
            return p
    return None


def _read_env(path: Optional[Path]) -> dict[str, str]:
    if path is None:
        return {}
    out: dict[str, str] = {}
    for raw in path.read_text().splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        value = value.strip().strip('"').strip("'")
        out[key.strip()] = value
    return out


def _extract_yaml_url(config_text: str, key: str) -> Optional[str]:
    m = re.search(rf"^\s*{re.escape(key)}:\s*['\"]?([^'\"\s]+)", config_text, re.M)
    return m.group(1) if m else None


def _parse_url_endpoint(
    value: Optional[str], allowed_schemes: set[str]
) -> tuple[Optional[str], Optional[int]]:
    if not value:
        return None, None
    try:
        parsed = urlsplit(value)
        if parsed.scheme not in allowed_schemes or not parsed.hostname:
            return None, None
        default_port = 443 if parsed.scheme in {"https", "wss"} else 80
        return parsed.hostname, parsed.port or default_port
    except ValueError:
        return None, None


def _extract_websocket_endpoint(config_text: str) -> tuple[Optional[str], Optional[int]]:
    return _parse_url_endpoint(
        _extract_yaml_url(config_text, "websocket"), {"ws", "wss"}
    )


def _env_int(env: dict[str, str], key: str, fallback: int) -> int:
    raw = env.get(key, "").strip()
    if not raw:
        return fallback
    try:
        return int(raw)
    except ValueError:
        return fallback


def _project_root(config_path: Optional[Path]) -> Path:
    """Resolve the directory that contains `models/`.

    Models are bind-mounted from the repo root (`./models/...` in
    compose.yml), but in a standard deploy the config lives at
    `<root>/data/.config.yaml` (and at `<root>/.config.yaml` in the legacy
    layout). Anchoring naively to `config_path.parent` therefore looks for
    `data/models/...` and FALSE-FAILs a healthy install. Prefer whichever
    candidate actually has a `models/` dir; otherwise return the most likely
    root so the "missing" message still points at the right place.
    """
    if config_path is None:
        return Path.cwd()
    parent = config_path.parent
    # If config is under a `data/` dir, the repo root is one level up.
    candidates = (
        [parent.parent, parent] if parent.name == "data" else [parent, parent.parent]
    )
    for base in candidates:
        if (base / "models").is_dir():
            return base
    return candidates[0]


# ── Individual checks ─────────────────────────────────────────────────────────

def check_config_exists(config_path: Optional[Path]) -> Result:
    label = ".config.yaml exists"
    if config_path is None:
        return Result(label, "fail", "not found - run `make setup`")
    return Result(label, "pass", str(config_path))


def check_no_placeholders(config_path: Optional[Path]) -> Result:
    label = ".config.yaml - no unsubstituted placeholders"
    if config_path is None:
        return Result(label, "skip", "config not found")
    wizard_placeholders = {
        "<XIAOZHI_WS_PORT>",
        "<XIAOZHI_HTTP_PORT>",
        "<XIAOZHI_PUBLIC_WS_BASE_URL>",
        "<XIAOZHI_PUBLIC_OTA_BASE_URL>",
        "<ROBOT_NAME>",
        "<YOUR_NAME>",
        "<TZ_VALUE>",
        "<ASR_MODULE>",
        "<ASR_DEVICE>",
        "<ASR_COMPUTE_TYPE>",
    }
    found = [
        token
        for token in re.findall(r"<[A-Z][A-Z0-9_]+>", config_path.read_text())
        if token in wizard_placeholders
    ]
    if found:
        unique = sorted(set(found))
        return Result(label, "fail", "placeholders present: " + ", ".join(unique))
    return Result(label, "pass")


# Required SenseVoiceSmall assets and a sane minimum byte size for each. The size
# floors catch corrupt/partial downloads - notably the 15-byte "Entry not found"
# stubs that the pre-#124 `make fetch-models` saved silently when a filename 404'd
# (which crash-looped the ASR container with `sentencepiece … bpemodel=None`).
SENSEVOICE_REQUIRED = {
    "model.pt": 200_000_000,                          # ~900 MB
    "config.yaml": 500,
    "configuration.json": 100,
    "am.mvn": 1_000,
    "chn_jpn_yue_eng_ko_spectok.bpe.model": 1_000,    # the BPE/sentencepiece tokenizer
}


def check_models_sensevoice(config_path: Optional[Path]) -> Result:
    label = "SenseVoiceSmall model files present"
    root = _project_root(config_path)
    model_dir = root / "models" / "SenseVoiceSmall"
    if not model_dir.is_dir():
        return Result(label, "fail", f"{model_dir} missing - run `make fetch-models`")
    problems = []
    for name, min_size in SENSEVOICE_REQUIRED.items():
        f = model_dir / name
        if not f.is_file():
            problems.append(f"{name} missing")
        elif f.stat().st_size < min_size:
            problems.append(f"{name} only {f.stat().st_size} B (corrupt download?)")
    if problems:
        return Result(label, "fail", "; ".join(problems) + " - re-run `make fetch-models`")
    return Result(label, "pass", f"{len(SENSEVOICE_REQUIRED)} required files OK")


def check_models_piper(config_path: Optional[Path]) -> Result:
    label = "Piper TTS model (*.onnx) present"
    root = _project_root(config_path)
    piper_dir = root / "models" / "piper"
    if not piper_dir.is_dir():
        return Result(label, "fail", f"{piper_dir} missing - run `make fetch-models`")
    onnx_files = list(piper_dir.glob("*.onnx"))
    if not onnx_files:
        return Result(label, "fail", "no .onnx files in models/piper/")
    return Result(label, "pass", onnx_files[0].name)


def check_http(label: str, url: str, timeout: int) -> Result:
    try:
        with urllib.request.urlopen(url, timeout=timeout) as resp:
            status = resp.status
    except urllib.error.HTTPError as e:
        status = e.code
    except Exception as exc:
        return Result(label, "fail", f"{url} unreachable - {str(exc)[:80]}")
    if status < 500:
        return Result(label, "pass", f"{url} HTTP {status}")
    return Result(label, "fail", f"{url} HTTP {status}")


def check_tcp(label: str, host: str, port: int, timeout: int) -> Result:
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return Result(label, "pass", f"{host}:{port}")
    except Exception as exc:
        return Result(label, "fail", f"{host}:{port} unreachable - {str(exc)[:80]}")


# ── Orchestration ─────────────────────────────────────────────────────────────

def run_checks(
    config_path: Optional[Path],
    env_path: Optional[Path],
    host: Optional[str],
    http_port: Optional[int],
    ws_port: Optional[int],
    bridge_port: Optional[int],
    behaviour_port: Optional[int],
    bridge_url: Optional[str],
    server_url: Optional[str],
    behaviour_url: Optional[str],
    timeout: int,
) -> list[Result]:
    results: list[Result] = []

    results.append(check_config_exists(config_path))
    results.append(check_no_placeholders(config_path))
    results.append(check_models_sensevoice(config_path))
    results.append(check_models_piper(config_path))

    env = _read_env(env_path)
    config_text = config_path.read_text() if config_path else ""
    public_ws_base = env.get("XIAOZHI_PUBLIC_WS_BASE_URL")
    public_ota_base = (
        env.get("XIAOZHI_PUBLIC_OTA_BASE_URL")
        or _extract_yaml_url(config_text, "ota_base_url")
    )
    config_host, config_ws_port = _parse_url_endpoint(
        public_ws_base, {"ws", "wss"}
    )
    if not config_host:
        config_host, config_ws_port = _extract_websocket_endpoint(config_text)
    xiaozhi_host = host or config_host
    service_host = host
    published_ws_port = (
        ws_port
        or config_ws_port
        or _env_int(env, "XIAOZHI_WS_PORT", 8000)
    )
    published_bridge_port = bridge_port or _env_int(env, "DOTTY_BRIDGE_PORT", 8081)
    published_behaviour_port = behaviour_port or _env_int(env, "DOTTY_BEHAVIOUR_PORT", 8090)

    if server_url is None and public_ota_base:
        server_url = public_ota_base.rstrip("/") + "/xiaozhi/ota/"
    elif server_url is None and xiaozhi_host:
        published_http_port = http_port or _env_int(env, "XIAOZHI_HTTP_PORT", 8003)
        server_url = f"http://{xiaozhi_host}:{published_http_port}/xiaozhi/ota/"
    if server_url:
        results.append(check_http("Xiaozhi OTA endpoint reachable", server_url, timeout))
    else:
        results.append(Result(
            "Xiaozhi OTA endpoint reachable", "skip",
            "set XIAOZHI_PUBLIC_OTA_BASE_URL or pass --server-url",
        ))

    if xiaozhi_host:
        results.append(check_tcp("Xiaozhi WebSocket port reachable", xiaozhi_host, published_ws_port, timeout))
    else:
        results.append(Result(
            "Xiaozhi WebSocket port reachable", "skip",
            "set XIAOZHI_PUBLIC_WS_BASE_URL or pass --host/--ws-port",
        ))

    if bridge_url is None and service_host:
        bridge_url = f"http://{service_host}:{published_bridge_port}/health"
    if bridge_url:
        results.append(check_http("Dashboard /health reachable", bridge_url, timeout))
    else:
        results.append(Result(
            "Dashboard /health reachable", "skip",
            "pass --bridge-url or --host",
        ))

    if behaviour_url is None and service_host:
        behaviour_url = f"http://{service_host}:{published_behaviour_port}/health"
    if behaviour_url:
        results.append(check_http("dotty-behaviour /health reachable", behaviour_url, timeout))
    else:
        results.append(Result(
            "dotty-behaviour /health reachable", "skip",
            "pass --behaviour-url or --host",
        ))

    return results


# ── Entry point ───────────────────────────────────────────────────────────────

def main() -> int:
    parser = argparse.ArgumentParser(
        description="Dotty health-check CLI (portable alternative to `make doctor`)",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("--config", metavar="PATH",
                        help="Path to .config.yaml (auto-discovered if omitted)")
    parser.add_argument("--env", metavar="PATH",
                        help="Path to .env (auto-discovered if omitted)")
    parser.add_argument("--host", metavar="HOST",
                        help="Client-visible host; overrides public URL discovery")
    parser.add_argument("--http-port", metavar="N", type=int,
                        help="Legacy public HTTP/OTA port override")
    parser.add_argument("--ws-port", metavar="N", type=int,
                        help="Public WebSocket port override")
    parser.add_argument("--bridge-port", metavar="N", type=int,
                        help="Published dashboard port (default: .env or 8081)")
    parser.add_argument("--behaviour-port", metavar="N", type=int,
                        help="Published dotty-behaviour port (default: .env or 8090)")
    parser.add_argument("--bridge-url", metavar="URL",
                        help="Dashboard health URL, e.g. http://192.168.1.10:8081/health")
    parser.add_argument("--server-url", metavar="URL",
                        help="Xiaozhi OTA URL, e.g. http://192.168.1.10:8003/xiaozhi/ota/")
    parser.add_argument("--behaviour-url", metavar="URL",
                        help="dotty-behaviour health URL, e.g. http://192.168.1.10:8090/health")
    parser.add_argument("--timeout", metavar="N", type=int, default=5,
                        help="HTTP timeout in seconds (default: 5)")
    parser.add_argument("--json", action="store_true",
                        help="Emit JSON array of results to stdout")
    args = parser.parse_args()

    config_path = _find_config(args.config)
    env_path = _find_env(args.env)

    if not args.json:
        print(f"\n{BOLD}Dotty doctor{RESET}\n")

    results = run_checks(
        config_path=config_path,
        env_path=env_path,
        host=args.host,
        http_port=args.http_port,
        ws_port=args.ws_port,
        bridge_port=args.bridge_port,
        behaviour_port=args.behaviour_port,
        bridge_url=args.bridge_url,
        server_url=args.server_url,
        behaviour_url=args.behaviour_url,
        timeout=args.timeout,
    )

    if args.json:
        print(json.dumps([r.to_dict() for r in results], indent=2))
    else:
        for r in results:
            r.print_line()
        passed  = sum(1 for r in results if r.status == "pass")
        failed  = sum(1 for r in results if r.status == "fail")
        skipped = sum(1 for r in results if r.status in ("skip", "warn"))
        print(f"\n{BOLD}Results: {passed} passed, {failed} failed, {skipped} skipped.{RESET}\n")

    return 1 if any(r.status == "fail" for r in results) else 0


if __name__ == "__main__":
    sys.exit(main())
