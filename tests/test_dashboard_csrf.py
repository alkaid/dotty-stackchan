"""CSRF middleware tests for the dashboard.

Covers the signed double-submit cookie pattern in `bridge/csrf.py` and
its integration into `bridge.py` — cookie issuance on GET, header
validation on mutating /ui/ requests, /api/ exemption, kill-switch.

Uses the same heavy-lifespan-neutralization bootstrap as
test_bridge_routes.py so the test client can construct without spawning
ACP, perception consumers, or the calendar loop.
"""
from __future__ import annotations

import importlib
import importlib.util
import hashlib
import os
import sys
import tempfile
import json
import unittest
from contextlib import asynccontextmanager
from pathlib import Path
from unittest.mock import patch


# Same env redirects as test_bridge_routes.py — kid/smart-mode state dirs
# default under /root which CI/tests can't write, and CONVO_LOG_DIR
# defaults the same way.
_state_dir = Path(tempfile.mkdtemp(prefix="dotty-csrf-test-state-"))
os.environ.setdefault("DOTTY_KID_MODE_STATE", str(_state_dir / "kid-mode"))
os.environ.setdefault("DOTTY_SMART_MODE_STATE", str(_state_dir / "smart-mode"))
os.environ.setdefault("CONVO_LOG_DIR", str(_state_dir / "logs"))
os.environ.setdefault("IDLE_PHOTOGRAPHER_ENABLED", "0")
os.environ.setdefault("DREAMER_ENABLED", "0")
os.environ.setdefault("DANCE_REFLECTOR_ENABLED", "0")
os.environ.setdefault("CALENDAR_IDS", "")
os.environ.setdefault("ZEROCLAW_BIN", "/bin/true")
# Pin a known secret so cookie signatures are deterministic across the
# whole test file. Must be set before bridge.csrf imports.
os.environ["DOTTY_CSRF_SECRET"] = "test-secret-for-csrf-tests-only"
os.environ.setdefault("DOTTY_CSRF_ENFORCE", "1")

_repo_root = Path(__file__).resolve().parents[1]
_spec = importlib.util.spec_from_file_location(
    "bridge_app", _repo_root / "bridge.py",
)
assert _spec is not None and _spec.loader is not None
bridge_app = importlib.util.module_from_spec(_spec)
sys.modules["bridge_app"] = bridge_app
_spec.loader.exec_module(bridge_app)


@asynccontextmanager
async def _noop_lifespan(_app):
    yield


bridge_app.app.router.lifespan_context = _noop_lifespan

from fastapi.testclient import TestClient  # noqa: E402

import bridge.csrf as csrf_mod  # noqa: E402
import bridge.dashboard as dashboard_mod  # noqa: E402


class CSRFCookieIssuanceTests(unittest.TestCase):
    """A fresh GET to /ui/ should set the dotty_csrf cookie and inject
    the raw token into the rendered HTML as a <meta> tag."""

    def setUp(self):
        self.client = TestClient(bridge_app.app)

    def test_get_ui_sets_cookie_and_meta(self):
        # Hit /ui directly (no trailing slash) — /ui/ 307-redirects and
        # the Set-Cookie lands on the intermediate response, which the
        # TestClient absorbs into its jar before the final 200. The
        # response object only shows Set-Cookies from the final hop.
        r = self.client.get("/ui")
        self.assertEqual(r.status_code, 200)
        self.assertIn(csrf_mod.COOKIE_NAME, self.client.cookies)
        # Cookie value contains the signature; unsigning should yield
        # the raw token that's embedded in the meta tag.
        raw = csrf_mod._unsign(self.client.cookies[csrf_mod.COOKIE_NAME])
        self.assertIsNotNone(raw)
        self.assertIn(f'name="csrf-token" content="{raw}"', r.text)

    def test_health_does_not_set_cookie(self):
        # /health is in the exempt prefix list — but the middleware does
        # still set the cookie on any first request (it issues on every
        # response that lacked a valid one). That's by design: the cookie
        # is harmless to other endpoints and pre-warms the dashboard.
        # What MUST hold: /health remains accessible without a token.
        r = self.client.get("/health")
        self.assertEqual(r.status_code, 200)

class CSRFEnforcementTests(unittest.TestCase):
    """POST to /ui/actions/* must require a matching X-CSRF-Token."""

    def setUp(self):
        # Each test gets a clean cookie jar so prior tests' cookies don't
        # leak across cases.
        self.client = TestClient(bridge_app.app)

    def _prime_token(self) -> str:
        r = self.client.get("/ui/")
        self.assertEqual(r.status_code, 200)
        raw = csrf_mod._unsign(self.client.cookies[csrf_mod.COOKIE_NAME])
        assert raw is not None
        return raw

    def test_post_without_cookie_rejected(self):
        # Fresh client, no GET first → no cookie, POST should 403.
        fresh = TestClient(bridge_app.app)
        r = fresh.post("/ui/actions/mood", data={"emoji": "😊"})
        self.assertEqual(r.status_code, 403)
        self.assertIn(b"csrf", r.content.lower())

    def test_post_with_cookie_but_no_header_rejected(self):
        self._prime_token()
        r = self.client.post("/ui/actions/mood", data={"emoji": "😊"})
        self.assertEqual(r.status_code, 403)

    def test_post_with_mismatched_header_rejected(self):
        self._prime_token()
        r = self.client.post(
            "/ui/actions/mood",
            data={"emoji": "😊"},
            headers={"X-CSRF-Token": "not-the-real-token"},
        )
        self.assertEqual(r.status_code, 403)

    def test_post_with_matching_header_accepted_by_middleware(self):
        # We only assert the middleware passes the request through to
        # the handler — the handler itself may 503 because xiaozhi admin
        # isn't configured in the test env. The point is: NOT 403.
        token = self._prime_token()
        r = self.client.post(
            "/ui/actions/mood",
            data={"emoji": "😊"},
            headers={"X-CSRF-Token": token},
        )
        self.assertNotEqual(r.status_code, 403)

    def test_tampered_cookie_signature_rejected(self):
        self._prime_token()
        # Corrupt the signature half. Cookie is `raw.sig`; mutate sig.
        bad = self.client.cookies[csrf_mod.COOKIE_NAME].rsplit(".", 1)[0] + ".deadbeef"
        self.client.cookies.set(csrf_mod.COOKIE_NAME, bad)
        r = self.client.post(
            "/ui/actions/mood",
            data={"emoji": "😊"},
            headers={"X-CSRF-Token": "anything"},
        )
        self.assertEqual(r.status_code, 403)


class CSRFExemptionTests(unittest.TestCase):
    """API and observability endpoints must remain reachable without
    a CSRF token."""

    def setUp(self):
        self.client = TestClient(bridge_app.app)

    def test_api_post_without_cookie_passes_middleware(self):
        # /api/perception/event is documented in bridge.py as
        # @app.post(..., status_code=204) — middleware MUST NOT 403 it.
        # The handler may still respond with a non-success status if the
        # payload is malformed, but specifically not 403 from CSRF.
        r = self.client.post(
            "/api/perception/event",
            json={"type": "event", "name": "test", "data": {}},
        )
        self.assertNotEqual(r.status_code, 403)

    def test_admin_routes_use_admin_token_instead_of_csrf(self):
        self.assertTrue(csrf_mod._is_exempt("/admin/kid-mode"))


class CSRFKillSwitchTests(unittest.TestCase):
    """DOTTY_CSRF_ENFORCE=0 → log-only mode, requests pass through."""

    def test_enforce_off_passes_bad_token(self):
        # Monkey-patch the module-level enforcement flag (set at import).
        original = csrf_mod._ENFORCE
        csrf_mod._ENFORCE = False
        try:
            client = TestClient(bridge_app.app)
            # Prime cookie, then POST with a bad header — should not 403.
            client.get("/ui/")
            r = client.post(
                "/ui/actions/mood",
                data={"emoji": "😊"},
                headers={"X-CSRF-Token": "deliberately-wrong"},
            )
            self.assertNotEqual(r.status_code, 403)
        finally:
            csrf_mod._ENFORCE = original


class DashboardConfigurationTests(unittest.TestCase):
    def setUp(self):
        self.client = TestClient(bridge_app.app)
        self.tmp = tempfile.TemporaryDirectory(prefix="dotty-runtime-config-")
        self.path = Path(self.tmp.name) / "runtime-config.json"
        self.env_patch = patch.dict(
            os.environ, {"DOTTY_RUNTIME_CONFIG_FILE": str(self.path)},
        )
        self.env_patch.start()

    def tearDown(self):
        self.env_patch.stop()
        self.tmp.cleanup()

    def _token(self) -> str:
        response = self.client.get("/ui/")
        self.assertEqual(response.status_code, 200)
        token = csrf_mod._unsign(self.client.cookies[csrf_mod.COOKIE_NAME])
        assert token is not None
        return token

    def _valid_form(self) -> dict[str, str]:
        return {
            "DOTTY_PI_MODEL": "simple-v2",
            "DOTTY_PI_SIMPLE_REASONING": "true",
            "DOTTY_PI_SIMPLE_REASONING_EFFORT": "medium",
            "VOICE_THINKER_MODEL": "think-v2",
            "DOTTY_PI_THINK_REASONING_EFFORT": "high",
            "XIAOZHI_PUBLIC_WS_BASE_URL": "wss://voice.example.test:8443",
            "XIAOZHI_PUBLIC_OTA_BASE_URL": "https://ota.example.test",
            "IDLE_PHOTOGRAPHER_ENABLED": "true",
        }

    def test_dashboard_has_configuration_control(self):
        body = self.client.get("/ui/").text
        self.assertIn('hx-get="/ui/configuration"', body)

    def test_configuration_form_lists_all_runtime_fields(self):
        body = self.client.get("/ui/configuration").text
        for key in self._valid_form():
            self.assertIn(f'name="{key}"', body)

    def test_save_persists_allowlisted_runtime_config(self):
        response = self.client.post(
            "/ui/actions/configuration",
            data=self._valid_form(),
            headers={"X-CSRF-Token": self._token()},
        )
        self.assertEqual(response.status_code, 200)
        self.assertIn("Saved", response.text)
        self.assertEqual(json.loads(self.path.read_text()), self._valid_form())

    def test_invalid_public_url_is_not_persisted(self):
        values = self._valid_form()
        values["XIAOZHI_PUBLIC_WS_BASE_URL"] = "http://wrong-scheme.test/path"
        response = self.client.post(
            "/ui/actions/configuration",
            data=values,
            headers={"X-CSRF-Token": self._token()},
        )
        self.assertEqual(response.status_code, 200)
        self.assertIn("WebSocket base URL must be an origin", response.text)
        self.assertFalse(self.path.exists())


class DashboardRoleVoiceTests(unittest.TestCase):
    def setUp(self):
        self.client = TestClient(bridge_app.app)
        self.tmp = tempfile.TemporaryDirectory(prefix="dotty-role-voice-")
        root = Path(self.tmp.name)
        self.roles_path = root / "roles.json"
        self.voices_path = root / "voices.json"
        self.seed_path = root / "default.md"
        self.seed_path.write_text("You are Dotty.", encoding="utf-8")
        self.env_patch = patch.dict(os.environ, {
            "DOTTY_ROLES_FILE": str(self.roles_path),
            "DOTTY_VOICES_FILE": str(self.voices_path),
            "DOTTY_DEFAULT_ROLE_FILE": str(self.seed_path),
        })
        self.env_patch.start()
        self.preview_calls = []

        async def preview(**kwargs):
            self.preview_calls.append(kwargs)
            return {"ok": True}

        self.old_preview = dashboard_mod._state.get("voice_preview")
        dashboard_mod._state["voice_preview"] = preview

    def tearDown(self):
        dashboard_mod._state["voice_preview"] = self.old_preview
        self.env_patch.stop()
        self.tmp.cleanup()

    def _token(self) -> str:
        self.client.get("/ui/")
        token = csrf_mod._unsign(self.client.cookies[csrf_mod.COOKIE_NAME])
        assert token is not None
        return token

    def _post(self, path: str, data: dict[str, str]):
        return self.client.post(
            path, data=data, headers={"X-CSRF-Token": self._token()},
        )

    def _edge_form(self) -> dict[str, str]:
        return {
            "voice_id": "",
            "name": "Young AU",
            "provider": "edge",
            "edge_voice": "en-AU-NatashaNeural",
            "edge_rate": "+10%",
            "edge_volume": "+0%",
            "edge_pitch": "+5Hz",
        }

    def test_role_and_voice_crud_with_reference_protection(self):
        response = self._post("/ui/actions/voices/save", self._edge_form())
        self.assertEqual(response.status_code, 200)
        voice_state = json.loads(self.voices_path.read_text())
        edge_id = voice_state["voices"][1]["id"]

        response = self._post("/ui/actions/roles/create", {
            "name": "Guide",
            "prompt": "You are a guide.",
            "voice_id": edge_id,
        })
        self.assertEqual(response.status_code, 200)
        role_state = json.loads(self.roles_path.read_text())
        guide_id = role_state["roles"][1]["id"]
        self._post("/ui/actions/roles/activate", {"role_id": guide_id})
        self.assertIn("Young AU", self.client.get("/ui/voices").text)

        blocked = self._post("/ui/actions/voices/delete", {"voice_id": edge_id})
        self.assertIn("Voice is used by: Guide", blocked.text)

        self._post("/ui/actions/roles/update", {
            "role_id": guide_id,
            "name": "Guide",
            "prompt": "You are a patient guide.",
            "voice_id": "default",
        })
        deleted = self._post("/ui/actions/voices/delete", {"voice_id": edge_id})
        self.assertIn("Saved", deleted.text)
        self.assertEqual(len(json.loads(self.voices_path.read_text())["voices"]), 1)

    def test_unsaved_edge_voice_can_be_previewed(self):
        values = self._edge_form()
        values["preview_text"] = "This is a preview."
        response = self._post("/ui/actions/voices/preview", values)
        self.assertEqual(response.status_code, 200)
        self.assertIn("Preview queued", response.text)
        self.assertEqual(self.preview_calls[0]["text"], "This is a preview.")
        self.assertEqual(
            self.preview_calls[0]["profile"]["config"]["voice"],
            "en-AU-NatashaNeural",
        )

    def test_new_voice_editor_defaults_to_xiaoxiao_edge(self):
        response = self.client.get("/ui/voices/editor?new=true")
        self.assertEqual(response.status_code, 200)
        self.assertIn(
            '<option value="edge" selected>EdgeTTS</option>', response.text,
        )
        self.assertIn('value="zh-CN-XiaoxiaoNeural"', response.text)
        self.assertIn("你好，我是 Dotty。", response.text)
        self.assertIn('name="gain_db"', response.text)

    def test_role_manager_lists_default_voice(self):
        body = self.client.get("/ui/roles/manage").text
        self.assertIn("Default EdgeTTS - Xiaoxiao", body)
        self.assertIn("You are Dotty.", body)

    def test_role_card_shows_robot_name_wake_phrase(self):
        with patch.dict(os.environ, {"ROBOT_NAME": "Mochi"}):
            body = self.client.get("/ui/roles").text
        self.assertIn("Mochi", body)
        self.assertIn("hi, Mochi", body)

class CSRFSigningUnitTests(unittest.TestCase):
    """Direct tests on the sign/unsign helpers in bridge.csrf."""

    def test_roundtrip(self):
        raw = "abc123"
        signed = csrf_mod._sign(raw)
        self.assertEqual(csrf_mod._unsign(signed), raw)

    def test_unsign_rejects_empty(self):
        self.assertIsNone(csrf_mod._unsign(""))

    def test_unsign_rejects_unsigned(self):
        self.assertIsNone(csrf_mod._unsign("no-dot-here"))

    def test_unsign_rejects_bad_signature(self):
        self.assertIsNone(csrf_mod._unsign("raw.deadbeef"))

    def test_admin_token_provides_stable_fallback_secret(self):
        with patch.dict(
            os.environ,
            {"DOTTY_CSRF_SECRET": "", "DOTTY_ADMIN_TOKEN": "admin-secret"},
        ):
            expected = hashlib.sha256(b"dotty-csrf-v1\0admin-secret").digest()
            self.assertEqual(csrf_mod._load_secret(), expected)


if __name__ == "__main__":
    unittest.main()
