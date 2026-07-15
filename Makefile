SHELL := /bin/bash
.DEFAULT_GOAL := help

# ── Model URLs ───────────────────────────────────────────────────────
SENSEVOICE_REPO  := https://huggingface.co/FunAudioLLM/SenseVoiceSmall
PIPER_BASE       := https://huggingface.co/rhasspy/piper-voices/resolve/main/en/en_GB/cori/medium
PIPER_ONNX       := en_GB-cori-medium.onnx
PIPER_JSON       := en_GB-cori-medium.onnx.json
WHISPER_REPO     := https://huggingface.co/Systran/faster-whisper-small.en
WHISPER_DIR      := models/whisper-small.en-ct2
WHISPER_FILES    := config.json model.bin tokenizer.json vocabulary.txt

# ── Colours ──────────────────────────────────────────────────────────
GREEN  := \033[0;32m
RED    := \033[0;31m
YELLOW := \033[0;33m
BOLD   := \033[1m
RESET  := \033[0m

# ── Robust download helper (issue #124) ──────────────────────────────
# Shell function injected at the head of each fetch block as `dl_file <url> <dest>`.
# `-f` turns any HTTP >=400 into a non-zero exit (and suppresses saving the error
# body), `--retry` rides out transient HF hiccups, the size floor rejects the
# 15-byte "Entry not found" stubs that the old bare `curl -o` saved silently, and
# every failure `rm`s the partial so the skip-if-exists guard can't "succeed" on it.
DL_FILE = dl_file() { if curl -fL --retry 3 --retry-delay 1 --progress-bar -o "$$2" "$$1"; then _sz=$$(wc -c < "$$2" 2>/dev/null || echo 0); if [ "$$_sz" -lt 100 ]; then echo -e "  $(RED)$$2: only $$_sz bytes — treating as a failed download$(RESET)"; rm -f "$$2"; return 1; fi; else echo -e "  $(RED)Failed to download $$1$(RESET)"; rm -f "$$2"; return 1; fi; }

# ── Targets ──────────────────────────────────────────────────────────
.PHONY: help setup xiaozhi-base fetch-models doctor up simulator simulator-only down logs status voice-list voice-install sbom verify-firmware test test-node lint check _preflight-compose _preflight-rendered

# ─────────────────────────────────────────────────────────────────────
# _preflight-compose — fail fast if Docker Compose v2 plugin is missing
#
# Issue #6: on Ubuntu 24.04 with the distro `docker.io` package, only
# the legacy v1 `docker-compose` (Python, separate binary) is shipped.
# `docker compose <subcmd>` either errors with "is not a docker
# command" or routes args into a parser that rejects flags like `-d`
# with "unknown shorthand flag". Either way the user sees a cryptic
# failure inside whatever target they invoked. Catch it up front with
# install guidance instead.
# ─────────────────────────────────────────────────────────────────────
_preflight-rendered:
	@if [ ! -f data/.config.yaml ]; then \
	  echo ""; \
	  echo -e "$(RED)Error: data/.config.yaml not found.$(RESET)"; \
	  echo "Run 'make setup' to render the xiaozhi config."; \
	  echo "Run:  make setup"; \
	  echo ""; \
	  exit 1; \
	fi

_preflight-compose:
	@if ! docker compose version >/dev/null 2>&1; then \
	  echo ""; \
	  echo -e "$(RED)Error: Docker Compose v2 plugin is not available.$(RESET)"; \
	  echo ""; \
	  echo "This Makefile requires the v2 plugin (the 'docker compose'"; \
	  echo "subcommand, no hyphen). The legacy 'docker-compose' binary"; \
	  echo "is not supported."; \
	  echo ""; \
	  echo "Install on Debian/Ubuntu:"; \
	  echo "    sudo apt install docker-compose-plugin"; \
	  echo ""; \
	  echo "Other distros / manual install:"; \
	  echo "    https://docs.docker.com/compose/install/linux/"; \
	  echo ""; \
	  exit 1; \
	fi

help: ## Show this help
	@echo ""
	@echo -e "$(BOLD)Dotty$(RESET) — your self-hosted StackChan robot assistant"
	@echo ""
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | \
		awk 'BEGIN {FS = ":.*?## "}; {printf "  $(BOLD)%-15s$(RESET) %s\n", $$1, $$2}'
	@echo ""

xiaozhi-base: _preflight-compose ## Build the low-churn Xiaozhi CUDA/PyTorch base image
	docker compose --profile build-only build xiaozhi-base

# ─────────────────────────────────────────────────────────────────────
# Dev-loop targets — same test split and coverage gate as CI.
# Assumes a venv with `pytest pytest-cov ruff` available on PATH. If
# you use a project venv, run e.g.  `source .venv/bin/activate && make check`.
# ─────────────────────────────────────────────────────────────────────
test: ## Run Python unit tests with coverage gate
	pytest tests/ custom-providers/pi_voice/tests/ \
		--cov --cov-report=
	pytest dotty-behaviour/tests/ \
		--cov --cov-append --cov-report=term --cov-fail-under=56

test-node: ## Run dotty-pi extension and RPC tests
	cd dotty-pi-ext && npm test
	node --test dotty-pi/tests/*.test.mjs

lint: ## Run ruff lint over the repo
	ruff check .

check: lint test test-node ## Run lint + Python/Node tests

# ─────────────────────────────────────────────────────────────────────
# setup — validate .env, render config, fetch models, start compose
#
# Idempotent: validates .env, resolves ASR acceleration, renders
# data/.config.yaml, fetches local models, and starts compose.yml.
# ─────────────────────────────────────────────────────────────────────
setup: _preflight-compose ## Validate .env, render config, fetch models, build and start containers
	@echo ""
	@echo -e "$(BOLD)Dotty setup$(RESET)"
	@echo "Validates .env, resolves ASR settings, renders config, and starts compose.yml."
	@echo ""
	@set -e; \
	 if [ ! -f .env ]; then \
	   echo -e "$(RED)Error: .env not found.$(RESET)"; \
	   echo "Create it from the example and fill the required values first:"; \
	   echo "  cp .env.example .env"; \
	   echo "  $$EDITOR .env"; \
	   echo ""; \
	   exit 1; \
	 fi; \
	 env_value() { \
	   awk -v key="$$1" 'BEGIN { FS = "=" } $$1 == key { sub(/^[^=]*=/, ""); value = $$0 } END { print value }' .env | \
	     sed -e 's/\r$$//' -e 's/^\"//' -e 's/\"$$//' -e "s/^'//" -e "s/'$$//"; \
	 }; \
	 set_env_value() { \
	   local name="$$1" value="$$2"; \
	   if grep -q "^$${name}=" .env; then \
	     sed -i "s|^$${name}=.*|$${name}=$${value}|" .env; \
	   else \
	     printf '%s=%s\n' "$$name" "$$value" >> .env; \
	   fi; \
	 }; \
	 is_placeholder() { \
	   case "$$2" in \
	     *PLACEHOLDER*|CHANGE_ME|CHANGE_ME_*|changeme|TODO|todo|sk-...) return 0 ;; \
	   esac; \
	   return 1; \
	 }; \
	 missing=""; invalid=""; \
	 require() { \
	   local name="$$1" val; \
	   val="$$(env_value "$$name")"; \
	   if [ -z "$$val" ]; then missing="$$missing $$name"; \
	   elif is_placeholder "$$name" "$$val"; then invalid="$$invalid $$name"; fi; \
	 }; \
	 require_port() { \
	   local name="$$1" val; \
	   val="$$(env_value "$$name")"; \
	   if [ -z "$$val" ]; then missing="$$missing $$name"; \
	   elif ! [[ "$$val" =~ ^[0-9]+$$ ]] || [ "$$val" -lt 1 ] || [ "$$val" -gt 65535 ]; then invalid="$$invalid $$name"; fi; \
	 }; \
	 optional_port() { \
	   local name="$$1" val; \
	   val="$$(env_value "$$name")"; \
	   if [ -n "$$val" ] && { ! [[ "$$val" =~ ^[0-9]+$$ ]] || [ "$$val" -lt 1 ] || [ "$$val" -gt 65535 ]; }; then \
	     invalid="$$invalid $$name"; \
	   fi; \
	 }; \
	 trim_base_url() { \
	   local value="$$1"; \
	   while [ "$${value%/}" != "$$value" ]; do value="$${value%/}"; done; \
	   printf '%s' "$$value"; \
	 }; \
	 for name in \
	   TZ DOTTY_ADMIN_TOKEN \
	   DOTTY_PI_BASE_URL DOTTY_PI_API_KEY \
	   DOTTY_PI_PROVIDER DOTTY_PI_MODEL \
	   VOICE_THINKER_MODEL; do \
	   require "$$name"; \
	 done; \
	 for name in XIAOZHI_WS_PORT XIAOZHI_HTTP_PORT; do \
	   require_port "$$name"; \
	 done; \
	 for name in DOTTY_BEHAVIOUR_PORT DOTTY_BRIDGE_PORT; do optional_port "$$name"; done; \
	 XIAOZHI_WS_PORT="$$(env_value XIAOZHI_WS_PORT)"; \
	 XIAOZHI_HTTP_PORT="$$(env_value XIAOZHI_HTTP_PORT)"; \
	 XIAOZHI_PUBLIC_WS_BASE_URL="$$(env_value XIAOZHI_PUBLIC_WS_BASE_URL)"; \
	 XIAOZHI_PUBLIC_OTA_BASE_URL="$$(env_value XIAOZHI_PUBLIC_OTA_BASE_URL)"; \
	 if [ -z "$$XIAOZHI_PUBLIC_WS_BASE_URL" ]; then missing="$$missing XIAOZHI_PUBLIC_WS_BASE_URL"; \
	 elif is_placeholder XIAOZHI_PUBLIC_WS_BASE_URL "$$XIAOZHI_PUBLIC_WS_BASE_URL"; then invalid="$$invalid XIAOZHI_PUBLIC_WS_BASE_URL"; \
	 else XIAOZHI_PUBLIC_WS_BASE_URL="$$(trim_base_url "$$XIAOZHI_PUBLIC_WS_BASE_URL")"; fi; \
	 if [ -z "$$XIAOZHI_PUBLIC_OTA_BASE_URL" ]; then missing="$$missing XIAOZHI_PUBLIC_OTA_BASE_URL"; \
	 elif is_placeholder XIAOZHI_PUBLIC_OTA_BASE_URL "$$XIAOZHI_PUBLIC_OTA_BASE_URL"; then invalid="$$invalid XIAOZHI_PUBLIC_OTA_BASE_URL"; \
	 else XIAOZHI_PUBLIC_OTA_BASE_URL="$$(trim_base_url "$$XIAOZHI_PUBLIC_OTA_BASE_URL")"; fi; \
	 if [ -n "$$XIAOZHI_PUBLIC_WS_BASE_URL" ] && \
	    ! [[ "$$XIAOZHI_PUBLIC_WS_BASE_URL" =~ ^wss?://[^/?#[:space:]]+$$ ]]; then \
	   invalid="$$invalid XIAOZHI_PUBLIC_WS_BASE_URL"; \
	 fi; \
	 if [ -n "$$XIAOZHI_PUBLIC_OTA_BASE_URL" ] && \
	    ! [[ "$$XIAOZHI_PUBLIC_OTA_BASE_URL" =~ ^https?://[^/?#[:space:]]+$$ ]]; then \
	   invalid="$$invalid XIAOZHI_PUBLIC_OTA_BASE_URL"; \
	 fi; \
	 ADMIN_TOKEN="$$(env_value DOTTY_ADMIN_TOKEN)"; \
	 if [ "$${#ADMIN_TOKEN}" -lt 32 ]; then invalid="$$invalid DOTTY_ADMIN_TOKEN"; fi; \
	 case "$$(env_value DOTTY_PI_BASE_URL)" in http://*|https://*) ;; *) invalid="$$invalid DOTTY_PI_BASE_URL" ;; esac; \
	 if [ -n "$$missing" ] || [ -n "$$invalid" ]; then \
	   echo -e "$(RED)Error: .env is incomplete.$(RESET)"; \
	   if [ -n "$$missing" ]; then echo "Missing required keys:$$missing"; fi; \
	   if [ -n "$$invalid" ]; then echo "Unset placeholder or invalid values:$$invalid"; fi; \
	   echo ""; \
	   echo "Edit .env, then run 'make setup' again."; \
	   echo ""; \
	   exit 1; \
	 fi; \
	 TZ_VALUE="$$(env_value TZ)"; \
	 ROBOT_NAME="$$(env_value ROBOT_NAME)"; [ -n "$$ROBOT_NAME" ] || ROBOT_NAME=Dotty; \
	 YOUR_NAME="$$(env_value YOUR_NAME)"; [ -n "$$YOUR_NAME" ] || YOUR_NAME=household; \
	 echo -e "$(BOLD)Detecting NVIDIA Docker runtime...$(RESET)"; \
	 if docker info --format '{{json .Runtimes}}' 2>/dev/null | grep -qi '"nvidia"'; then \
	   HAS_CUDA=1; \
	   echo -e "  $(GREEN)Found NVIDIA runtime.$(RESET)"; \
	 else \
	   HAS_CUDA=0; \
	   echo -e "  $(YELLOW)NVIDIA runtime not found.$(RESET)"; \
	 fi; \
	 ASR_ACCELERATION="$$(env_value ASR_ACCELERATION)"; \
	 ASR_LANGUAGE="$$(env_value ASR_LANGUAGE)"; \
	 [ -n "$$ASR_LANGUAGE" ] || ASR_LANGUAGE=auto; \
	 case "$$ASR_LANGUAGE" in auto|zh|en|yue|ja|ko|nospeech) ;; *) \
	   echo -e "$(RED)Error: ASR_LANGUAGE must be auto, zh, en, yue, ja, ko, or nospeech.$(RESET)"; exit 1 ;; \
	 esac; \
	 if [ -z "$$ASR_ACCELERATION" ]; then \
	   if [ -n "$$(env_value ASR_MODULE)$$(env_value ASR_DEVICE)$$(env_value ASR_COMPUTE_TYPE)$$(env_value XIAOZHI_CONTAINER_RUNTIME)$$(env_value NVIDIA_VISIBLE_DEVICES)" ]; then \
	     ASR_ACCELERATION=manual; \
	   else \
	     ASR_ACCELERATION=auto; \
	   fi; \
	 fi; \
	 case "$$ASR_ACCELERATION" in \
	   auto) \
	     if [ "$$HAS_CUDA" = "1" ]; then RESOLVED_ACCELERATION=cuda; else RESOLVED_ACCELERATION=cpu; fi ;; \
	   cpu) RESOLVED_ACCELERATION=cpu ;; \
	   cuda) \
	     if [ "$$HAS_CUDA" != "1" ]; then \
	       echo -e "$(RED)Error: ASR_ACCELERATION=cuda requires the NVIDIA Docker runtime.$(RESET)"; exit 1; \
	     fi; \
	     RESOLVED_ACCELERATION=cuda ;; \
	   manual) RESOLVED_ACCELERATION=manual ;; \
	   *) \
	     echo -e "$(RED)Error: ASR_ACCELERATION must be auto, cpu, cuda, or manual.$(RESET)"; exit 1 ;; \
	 esac; \
	 if [ "$$RESOLVED_ACCELERATION" = "cuda" ]; then \
	   ASR_MODULE=FunASR; ASR_DEVICE=cuda; ASR_COMPUTE_TYPE=float32; \
	   CONTAINER_RUNTIME=nvidia; NVIDIA_VISIBLE_DEVICES_VALUE=all; \
	 elif [ "$$RESOLVED_ACCELERATION" = "cpu" ]; then \
	   ASR_MODULE=FunASR; ASR_DEVICE=cpu; ASR_COMPUTE_TYPE=float32; \
	   CONTAINER_RUNTIME=runc; NVIDIA_VISIBLE_DEVICES_VALUE=void; \
	 else \
	   ASR_MODULE="$$(env_value ASR_MODULE)"; [ -n "$$ASR_MODULE" ] || ASR_MODULE=FunASR; \
	   ASR_DEVICE="$$(env_value ASR_DEVICE)"; [ -n "$$ASR_DEVICE" ] || ASR_DEVICE=cpu; \
	   ASR_COMPUTE_TYPE="$$(env_value ASR_COMPUTE_TYPE)"; \
	   if [ -z "$$ASR_COMPUTE_TYPE" ]; then \
	     if [ "$$ASR_MODULE" = "FunASR" ]; then ASR_COMPUTE_TYPE=float32; else ASR_COMPUTE_TYPE=int8; fi; \
	   fi; \
	   CONTAINER_RUNTIME="$$(env_value XIAOZHI_CONTAINER_RUNTIME)"; [ -n "$$CONTAINER_RUNTIME" ] || CONTAINER_RUNTIME=runc; \
	   NVIDIA_VISIBLE_DEVICES_VALUE="$$(env_value NVIDIA_VISIBLE_DEVICES)"; \
	   [ -n "$$NVIDIA_VISIBLE_DEVICES_VALUE" ] || NVIDIA_VISIBLE_DEVICES_VALUE=void; \
	 fi; \
	 case "$$CONTAINER_RUNTIME" in runc|nvidia) ;; *) \
	   echo -e "$(RED)Error: XIAOZHI_CONTAINER_RUNTIME must be runc or nvidia.$(RESET)"; exit 1 ;; \
	 esac; \
	 NEED_CUDA=0; \
	 case "$$ASR_DEVICE" in cuda|cuda:*) NEED_CUDA=1 ;; esac; \
	 if [ "$$NEED_CUDA" = "1" ] && [ "$$CONTAINER_RUNTIME" != "nvidia" ]; then \
	   echo -e "$(RED)Error: CUDA ASR requires XIAOZHI_CONTAINER_RUNTIME=nvidia.$(RESET)"; \
	   exit 1; \
	 fi; \
	 if [ "$$CONTAINER_RUNTIME" = "nvidia" ] && [ "$$HAS_CUDA" != "1" ]; then \
	   echo -e "$(RED)Error: Docker does not provide the NVIDIA runtime.$(RESET)"; exit 1; \
	 fi; \
	 set_env_value ASR_ACCELERATION "$$ASR_ACCELERATION"; \
	 set_env_value ASR_LANGUAGE "$$ASR_LANGUAGE"; \
	 if [ "$$ASR_ACCELERATION" != "manual" ]; then \
	   set_env_value ASR_MODULE "$$ASR_MODULE"; \
	   set_env_value ASR_DEVICE "$$ASR_DEVICE"; \
	   set_env_value ASR_COMPUTE_TYPE "$$ASR_COMPUTE_TYPE"; \
	   set_env_value XIAOZHI_CONTAINER_RUNTIME "$$CONTAINER_RUNTIME"; \
	   set_env_value NVIDIA_VISIBLE_DEVICES "$$NVIDIA_VISIBLE_DEVICES_VALUE"; \
	   echo "  resolved ASR settings written to .env"; \
	 fi; \
	 echo -e "$(GREEN).env validation passed.$(RESET)"; \
	 echo -e "$(BOLD)Using ASR: $$ASR_MODULE / $$ASR_DEVICE / $$ASR_COMPUTE_TYPE; runtime=$$CONTAINER_RUNTIME (mode=$$ASR_ACCELERATION).$(RESET)"; \
	 echo ""; \
	 echo -e "$(BOLD)Rendering xiaozhi config...$(RESET)"; \
	 mkdir -p data/bin tmp; \
	 sed_escape() { printf '%s' "$$1" | sed -e 's/[\\&|]/\\&/g'; }; \
	 e_XIAOZHI_PUBLIC_WS_BASE_URL=$$(sed_escape "$$XIAOZHI_PUBLIC_WS_BASE_URL"); \
	 e_XIAOZHI_PUBLIC_OTA_BASE_URL=$$(sed_escape "$$XIAOZHI_PUBLIC_OTA_BASE_URL"); \
	 e_ROBOT_NAME=$$(sed_escape     "$$ROBOT_NAME"); \
	 e_YOUR_NAME=$$(sed_escape      "$$YOUR_NAME"); \
	 e_TZ_VALUE=$$(sed_escape       "$$TZ_VALUE"); \
	 render_xiaozhi_config() { \
	   sed \
	       -e "s|<XIAOZHI_PUBLIC_WS_BASE_URL>|$$e_XIAOZHI_PUBLIC_WS_BASE_URL|g" \
	       -e "s|<XIAOZHI_PUBLIC_OTA_BASE_URL>|$$e_XIAOZHI_PUBLIC_OTA_BASE_URL|g" \
	       -e "s|<ROBOT_NAME>|$$e_ROBOT_NAME|g" \
	       -e "s|You are Dotty,|You are $$e_ROBOT_NAME,|g" \
	       -e "s|<YOUR_NAME>|$$e_YOUR_NAME|g" \
	       -e "s|<TZ_VALUE>|$$e_TZ_VALUE|g" \
	       -e "s|<ASR_MODULE>|$$ASR_MODULE|g" \
	       -e "s|<ASR_LANGUAGE>|$$ASR_LANGUAGE|g" \
	       -e "s|<ASR_DEVICE>|$$ASR_DEVICE|g" \
	       -e "s|<ASR_COMPUTE_TYPE>|$$ASR_COMPUTE_TYPE|g" \
	       .config.yaml.template > data/.config.yaml.tmp; \
	   mv data/.config.yaml.tmp data/.config.yaml; \
	 }; \
	 render_xiaozhi_config; \
	 echo "  .config.yaml.template → data/.config.yaml"; \
	 docker compose config --quiet; \
	 echo ""; \
	 make --no-print-directory fetch-models; \
	 echo ""; \
	 BRIDGE_VERSION_VALUE="$${BRIDGE_VERSION:-$$(git rev-parse --short HEAD 2>/dev/null || echo unknown)}"; \
	 echo -e "$(BOLD)Ensuring Xiaozhi base image...$(RESET)"; \
	 XIAOZHI_BASE_IMAGE_VALUE="$$(env_value XIAOZHI_BASE_IMAGE)"; \
	 if [ -n "$$XIAOZHI_BASE_IMAGE_VALUE" ]; then \
	   if docker image inspect "$$XIAOZHI_BASE_IMAGE_VALUE" >/dev/null 2>&1; then \
	     echo "  using local $$XIAOZHI_BASE_IMAGE_VALUE"; \
	   else \
	     echo "  pulling $$XIAOZHI_BASE_IMAGE_VALUE"; \
	     docker pull "$$XIAOZHI_BASE_IMAGE_VALUE"; \
	   fi; \
	 else \
	   docker compose --profile build-only build xiaozhi-base; \
	 fi; \
	 echo ""; \
	 echo -e "$(BOLD)Building application images...$(RESET)"; \
	 BRIDGE_VERSION="$$BRIDGE_VERSION_VALUE" docker compose build; \
	 if [ "$$NEED_CUDA" = "1" ]; then \
	   echo ""; \
	   echo -e "$(BOLD)Validating xiaozhi CUDA passthrough...$(RESET)"; \
	   if [ "$$ASR_MODULE" = "FunASR" ]; then \
	     GPU_PROBE='import torch; available = torch.cuda.is_available(); count = torch.cuda.device_count() if available else 0; probe = torch.ones(1, device="cuda").mul_(2) if available and count else None; torch.cuda.synchronize() if probe is not None else None; value = probe.cpu().item() if probe is not None else None; print(f"FunASR torch CUDA available={available}, devices={count}, kernel={value}"); raise SystemExit(0 if value == 2 else 1)'; \
	   else \
	     GPU_PROBE='import os, ctranslate2; required = os.environ["DOTTY_CUDA_COMPUTE_TYPE"]; count = ctranslate2.get_cuda_device_count(); types = ctranslate2.get_supported_compute_types("cuda", 0) if count else set(); print(f"Whisper CUDA devices={count}, compute_types={sorted(types)}, required={required}"); raise SystemExit(0 if count > 0 and required in types else 1)'; \
	   fi; \
	   if docker compose run --rm --no-deps --entrypoint python \
	       -e DOTTY_CUDA_COMPUTE_TYPE="$$ASR_COMPUTE_TYPE" xiaozhi-esp32-server \
	       -c "$$GPU_PROBE"; then \
	     echo -e "  $(GREEN)$$ASR_MODULE CUDA support verified.$(RESET)"; \
	   elif [ "$$ASR_ACCELERATION" = "auto" ]; then \
	     echo -e "  $(YELLOW)CUDA probe failed; falling back to FunASR on CPU.$(RESET)"; \
	     ASR_MODULE=FunASR; ASR_DEVICE=cpu; ASR_COMPUTE_TYPE=float32; \
	     CONTAINER_RUNTIME=runc; NVIDIA_VISIBLE_DEVICES_VALUE=void; NEED_CUDA=0; \
	     set_env_value ASR_MODULE "$$ASR_MODULE"; \
	     set_env_value ASR_DEVICE "$$ASR_DEVICE"; \
	     set_env_value ASR_COMPUTE_TYPE "$$ASR_COMPUTE_TYPE"; \
	     set_env_value XIAOZHI_CONTAINER_RUNTIME "$$CONTAINER_RUNTIME"; \
	     set_env_value NVIDIA_VISIBLE_DEVICES "$$NVIDIA_VISIBLE_DEVICES_VALUE"; \
	     render_xiaozhi_config; \
	     docker compose config --quiet; \
	   else \
	     echo -e "$(RED)Error: xiaozhi cannot run $$ASR_MODULE on CUDA through Compose.$(RESET)"; \
	     echo "Check the NVIDIA driver and Container Toolkit, or set ASR_ACCELERATION=cpu."; \
	     exit 1; \
	   fi; \
	 fi; \
	 echo ""; \
	 echo -e "$(BOLD)Starting containers...$(RESET)"; \
	 BRIDGE_VERSION="$$BRIDGE_VERSION_VALUE" docker compose up -d; \
	 echo ""; \
	 echo -e "$(GREEN)$(BOLD)Setup complete.$(RESET)"; \
	 echo ""; \
	 echo "Next steps:"; \
	 echo "  1. Flash the StackChan firmware (see SETUP.md or m5stack/StackChan repo)."; \
	 echo "  2. In the device's Advanced Options, set the OTA URL to:"; \
	 echo "       $$XIAOZHI_PUBLIC_OTA_BASE_URL/xiaozhi/ota/"; \
	 echo "  3. Run 'make doctor' to verify everything is healthy."; \
	 echo ""

# ─────────────────────────────────────────────────────────────────────
# fetch-models — download ASR + TTS model files
# ─────────────────────────────────────────────────────────────────────
SENSEVOICE_FILES := model.pt config.yaml configuration.json am.mvn chn_jpn_yue_eng_ko_spectok.bpe.model
# Stale filenames shipped before the #124 fix: `tokens.json` and
# `chn_jpn_yue_eng_ko_spectral.fbank.conf.yaml` never existed in the HF repo and
# downloaded as 15-byte "Entry not found" stubs. Removed on existing installs below.
SENSEVOICE_STALE := tokens.json chn_jpn_yue_eng_ko_spectral.fbank.conf.yaml
SENSEVOICE_DIR   := models/SenseVoiceSmall
PIPER_DIR        := models/piper

fetch-models: ## Download SenseVoiceSmall + Piper voice models
	@echo ""
	@echo -e "$(BOLD)Fetching models...$(RESET)"
	@echo ""
	@# ── SenseVoiceSmall ──
	@mkdir -p $(SENSEVOICE_DIR)
	@echo -e "$(BOLD)[SenseVoiceSmall]$(RESET)"
	@# Purge pre-#124 stale stubs so the skip-if-exists guard re-fetches cleanly.
	@for f in $(SENSEVOICE_STALE); do rm -f "$(SENSEVOICE_DIR)/$$f"; done
	@$(DL_FILE); for f in $(SENSEVOICE_FILES); do \
	  if [ -f "$(SENSEVOICE_DIR)/$$f" ]; then \
	    echo -e "  $(GREEN)$$f — already exists, skipping$(RESET)"; \
	  else \
	    echo "  Downloading $$f ..."; \
	    dl_file "$(SENSEVOICE_REPO)/resolve/main/$$f" "$(SENSEVOICE_DIR)/$$f" || exit 1; \
	  fi; \
	done
	@echo ""
	@# ── Piper voice ──
	@mkdir -p $(PIPER_DIR)
	@echo -e "$(BOLD)[Piper TTS — $(PIPER_ONNX)]$(RESET)"
	@$(DL_FILE); for f in $(PIPER_ONNX) $(PIPER_JSON); do \
	  if [ -f "$(PIPER_DIR)/$$f" ]; then \
	    echo -e "  $(GREEN)$$f — already exists, skipping$(RESET)"; \
	  else \
	    echo "  Downloading $$f ..."; \
	    dl_file "$(PIPER_BASE)/$$f" "$(PIPER_DIR)/$$f" || exit 1; \
	  fi; \
	done
	@echo ""
	@# ── faster-whisper small.en (CTranslate2) ──
	@mkdir -p $(WHISPER_DIR)
	@echo -e "$(BOLD)[faster-whisper small.en]$(RESET)"
	@$(DL_FILE); for f in $(WHISPER_FILES); do \
	  if [ -f "$(WHISPER_DIR)/$$f" ]; then \
	    echo -e "  $(GREEN)$$f — already exists, skipping$(RESET)"; \
	  else \
	    echo "  Downloading $$f ..."; \
	    dl_file "$(WHISPER_REPO)/resolve/main/$$f" "$(WHISPER_DIR)/$$f" || exit 1; \
	  fi; \
	done
	@echo ""
	@echo -e "$(GREEN)All models ready.$(RESET)"

# ─────────────────────────────────────────────────────────────────────
# sbom — generate a component+license inventory (sbom.json at repo root)
# ─────────────────────────────────────────────────────────────────────
sbom: ## Generate Software Bill of Materials (sbom.json)
	@./scripts/generate-sbom.sh

doctor: ## Run health checks on config, models, and services
	python3 scripts/dotty_doctor.py

# ─────────────────────────────────────────────────────────────────────
# Docker shortcuts
# ─────────────────────────────────────────────────────────────────────
up: _preflight-compose _preflight-rendered ## Start containers (docker compose up -d)
	docker compose up -d

simulator: _preflight-compose _preflight-rendered ## Build and start the optional StackChan simulator
	docker compose --profile simulator up -d --build stackchan-simulator

simulator-only: _preflight-compose _preflight-rendered ## Rebuild only the simulator without touching dependencies
	docker compose --profile simulator up -d --build --no-deps stackchan-simulator

down: _preflight-compose _preflight-rendered ## Stop containers (docker compose down)
	docker compose down

logs: _preflight-compose _preflight-rendered ## Tail container logs (docker compose logs -f)
	docker compose logs -f

voice-list: ## List curated Piper voices (see docs/voice-catalog.md)
	@./scripts/voice-install.sh --list

voice-install: ## Install a curated Piper voice (VOICE=<key> [APPLY=1])
	@if [ -z "$(VOICE)" ]; then \
	  echo -e "$(RED)Error: VOICE is required.$(RESET)  Example: make voice-install VOICE=en_US-kristin-medium"; \
	  echo "Run 'make voice-list' to see the catalog."; \
	  exit 2; \
	fi
	@if [ -n "$(APPLY)" ]; then \
	  ./scripts/voice-install.sh "$(VOICE)" --apply; \
	else \
	  ./scripts/voice-install.sh "$(VOICE)"; \
	fi

# ─────────────────────────────────────────────────────────────────────
# verify-firmware — build + checksum, optionally diff against published
# ─────────────────────────────────────────────────────────────────────
verify-firmware: ## Build firmware in IDF container and compute SHA256 checksums
	@echo ""
	@echo -e "$(BOLD)Firmware reproducibility check$(RESET)"
	@echo ""
	@if ! command -v docker >/dev/null 2>&1; then \
	  echo -e "$(RED)Error: docker is required.$(RESET)"; exit 1; \
	fi
	@if [ ! -f firmware/firmware/CMakeLists.txt ]; then \
	  echo -e "$(RED)Error: firmware submodule not initialised.$(RESET)"; \
	  echo "Run: git submodule update --init --recursive"; \
	  exit 1; \
	fi
	@echo -e "$(BOLD)Fetching firmware deps...$(RESET)"
	docker run --rm -v "$(PWD)/firmware/firmware:/project" -w /project \
	  espressif/idf:v5.5.4 \
	  bash -lc 'git config --global --add safe.directory "*" && python fetch_repos.py'
	@echo -e "$(BOLD)Building firmware...$(RESET)"
	docker run --rm -v "$(PWD)/firmware/firmware:/project" -w /project \
	  espressif/idf:v5.5.4 \
	  bash -lc 'git config --global --add safe.directory "*" && idf.py build'
	@echo -e "$(BOLD)Computing checksums...$(RESET)"
	@sha256sum \
	  firmware/firmware/build/stack-chan.bin \
	  firmware/firmware/build/ota_data_initial.bin \
	  firmware/firmware/build/generated_assets.bin \
	  | tee firmware/firmware/build/SHA256SUMS.txt
	@echo ""
	@if [ -f firmware/firmware/build/SHA256SUMS.published ]; then \
	  echo -e "$(BOLD)Comparing against published checksums...$(RESET)"; \
	  if diff -q firmware/firmware/build/SHA256SUMS.published \
	             firmware/firmware/build/SHA256SUMS.txt >/dev/null 2>&1; then \
	    echo -e "$(GREEN)PASS$(RESET)  Build is reproducible."; \
	  else \
	    echo -e "$(RED)FAIL$(RESET)  Checksums differ:"; \
	    diff firmware/firmware/build/SHA256SUMS.published \
	         firmware/firmware/build/SHA256SUMS.txt; \
	    exit 1; \
	  fi; \
	else \
	  echo -e "$(YELLOW)NOTE$(RESET)  No published SHA256SUMS.published to compare against."; \
	  echo "  To verify a release, download SHA256SUMS.txt from GitHub Releases,"; \
	  echo "  save it as firmware/firmware/build/SHA256SUMS.published, and re-run."; \
	fi
	@echo ""

status: _preflight-compose _preflight-rendered ## Show container status + bridge / dotty-behaviour health
	@docker compose ps
	@echo ""
	@python3 scripts/dotty_doctor.py
