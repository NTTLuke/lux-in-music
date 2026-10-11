import asyncio
import subprocess
import sys
import tomllib
import unittest
from pathlib import Path
from unittest.mock import patch

import httpx
from pydantic import ValidationError

from studio.adapters.yue2 import YuE2Params as GenerationParams

ROOT = Path(__file__).resolve().parents[1]


class ProductIdentityTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from studio.app import app
        cls.app = app

    def get(self, path):
        async def request():
            async with httpx.AsyncClient(transport=httpx.ASGITransport(app=self.app), base_url="http://studio.test") as client:
                return await client.get(path)
        return asyncio.run(request())

    def test_browser_and_api_names_match_the_product(self):
        page = self.get("/")
        schema = self.get("/openapi.json")
        self.assertEqual(page.status_code, 200)
        self.assertIn("<title>Lux In Music</title>", page.text)
        self.assertEqual(schema.json()["info"]["title"], "Lux In Music")

    def test_project_and_lock_package_identity_match(self):
        project = tomllib.loads((ROOT / "pyproject.toml").read_text())["project"]
        lock = tomllib.loads((ROOT / "uv.lock").read_text())
        editable = next(p for p in lock["package"] if p.get("source") == {"editable": "."})
        self.assertEqual(project["name"], "lux-in-music")
        self.assertEqual(editable["name"], project["name"])
        self.assertEqual(editable["version"], project["version"])

    def test_generation_cli_help_needs_no_engine(self):
        result = subprocess.run([sys.executable, "-m", "studio.cli", "--help"], cwd=ROOT, capture_output=True, text=True, timeout=15)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("--lyrics", result.stdout)
        self.assertNotIn("--max-duration", result.stdout)
        self.assertNotIn("--target-duration", result.stdout)

    def test_create_page_has_no_manual_duration_or_separate_check(self):
        page = self.get("/")
        self.assertEqual(page.status_code, 200)
        self.assertIn('id="duration-hint"', page.text)
        self.assertNotIn('id="duration-mode"', page.text)
        self.assertNotIn('id="len"', page.text)
        self.assertNotIn("Analyze duration", page.text)
        self.assertNotIn("duration.js", page.text)
        script = self.get("/static/app.js")
        self.assertEqual(script.status_code, 200)
        self.assertNotIn("/api/duration-analysis", script.text)
        self.assertIn("variations: state.variations", script.text)

    def test_generation_api_schema_does_not_advertise_duration_controls(self):
        schema = self.get("/openapi.json").json()
        ref = schema["paths"]["/api/generate"]["post"]["requestBody"]["content"]["application/json"]["schema"]["$ref"]
        fields = schema["components"]["schemas"][ref.rsplit("/", 1)[-1]]["properties"]
        self.assertIn("variations", fields)
        self.assertNotIn("target_duration_s", fields)
        self.assertNotIn("max_duration_s", fields)
        self.assertNotIn("semantic_max_tokens", fields)

    def test_cli_rejects_duration_fields_in_generic_model_options(self):
        result = subprocess.run([sys.executable, "-m", "studio.cli", "--style", "Piano",
            "--model-options", '{"target_duration_s":120}'], cwd=ROOT, capture_output=True, text=True, timeout=15)
        self.assertEqual(result.returncode, 2)
        self.assertIn("Song length is inferred", result.stderr)

    def test_engine_offline_health_remains_a_valid_ui_response(self):
        with patch("studio.engine.health", side_effect=RuntimeError("engine unavailable")):
            response = self.get("/api/health")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["engine"], "down")


class RequestBoundaryTests(unittest.TestCase):
    def params(self, **changes):
        return GenerationParams(lyrics="[Verse]\nA song", style="English, pop", **changes)

    def test_duration_cap_maps_to_codec_budget_not_a_false_completion_flag(self):
        request = self.params(max_duration_s=180).to_request()
        self.assertEqual(request["options"]["semantic_max_tokens"], "4500")
        self.assertNotIn("max_duration_s", request["options"])
        self.assertNotIn("completed", request)

    def test_short_cap_does_not_conflict_with_engine_default_minimum(self):
        request = self.params(max_duration_s=4).to_request()
        self.assertEqual(request["options"]["semantic_min_tokens"], "100")
        self.assertEqual(request["options"]["semantic_max_tokens"], "100")

    def test_lyrics_are_optional_and_instrumental_sends_the_upstream_tag(self):
        self.assertEqual(GenerationParams(style="Piano").to_request()["lyrics"], "")
        request = self.params(instrumental=True).to_request()
        self.assertEqual(request["lyrics"], "[instrumental]")
        self.assertNotIn("instrumental", request["options"])

    def test_conflicting_token_limits_and_unsupported_score_route_fail(self):
        with self.assertRaises(ValidationError):
            self.params(semantic_min_tokens=201, semantic_max_tokens=200)
        with self.assertRaises(ValidationError):
            self.params(abc="X:1\nK:C\nC4|", cot="off")


class LaunchHostTests(unittest.TestCase):
    def launch(self, *argv):
        import contextlib, io
        from studio import launch
        out = io.StringIO()
        with patch.object(sys, "argv", ["launch", "--no-open", *argv]), patch("uvicorn.run") as run, \
                contextlib.redirect_stdout(out):
            launch.main()
        return run.call_args.kwargs["host"], out.getvalue()

    def test_local_by_default_and_warns_when_listening_elsewhere(self):
        host, out = self.launch()
        self.assertEqual(host, "127.0.0.1")
        self.assertIn("http://127.0.0.1:8000", out)
        self.assertNotIn("WARNING", out)
        for given, shown in [("0.0.0.0", "http://127.0.0.1:8000"), ("192.168.1.20", "http://192.168.1.20:8000"),
                             ("fd7a::1", "http://[fd7a::1]:8000")]:
            with self.subTest(host=given):
                host, out = self.launch("--host", given)
                self.assertEqual(host, given)
                self.assertIn(shown, out)
                self.assertIn("no login", out)
