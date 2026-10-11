import base64
import copy
import json
import unittest
import asyncio
import time
import threading
import httpx
from unittest.mock import patch

from studio.adapters.yue2 import YuE2Adapter, YuE2Params
from studio.adapters.yue2_score import inspect, fit, ScoreError
from studio.params import GenerationParams
from tests.test_models import ModelFixtures, tiny_audio


def score(vocal=None, instrumental=None, tempo=120, unit=16, meter="4/4"):
    vocal = vocal or ["Z"] * 8 + ["C16"] * 4 + ["Z"] * 8
    instrumental = instrumental or ["C16"] * len(vocal)
    header = ["X:1", "T:", f"M:{meter}", f"L:1/{unit}", f"Q:1/4={tempo}",
              'V: Vocal clef=treble name="Vocal Melody" snm="Vocal"',
              'V: Ins clef=treble name="Ins Melody" snm="Inst."', "K:C"]
    for v, i in zip(vocal, instrumental):
        header.extend(["V: Vocal", v + "|", "V: Ins", i + "|"])
    return "\n".join(header) + "\n"


def artifact(text, truncated="false", ident="score"):
    return {"id": ident, "payload": base64.b64encode(text.encode()).decode(), "meta": {"truncated": truncated}}


class DurationAnalysisTests(unittest.TestCase):
    def test_automatic_analysis_checks_tempo_and_reuses_exact_plan_without_replanning(self):
        adapter, calls = YuE2Adapter(), []
        planned = score(["C16"] * 94, tempo=73, unit=32, meter="2/4")
        def run(request):
            calls.append(copy.deepcopy(request))
            if request["options"].get("stop_after") == "abc":
                return {"artifacts": [artifact(planned)]}
            return {"audio": tiny_audio(), "artifacts": [artifact(json.dumps([1] * 2820), ident="semantic")]}
        params = GenerationParams(style="English, pop, 100 BPM", lyrics="Synthetic song", model_options={"cot": "full"})
        result = adapter.analyze_duration(params, run)
        summary = result["analysis"]
        self.assertEqual((summary["status"], summary["planned_duration_s"], summary["recommended_target_s"]), ("ready", 112.8, 115))
        self.assertEqual(len(calls), 1)
        params.target_duration_s = 115
        data = adapter.generate(params, run, prepared=result["prepared"])
        self.assertEqual(len(calls), 3)  # one plan, one semantic pass, one render
        self.assertEqual(calls[1]["options"]["abc"], result["prepared"]["score"])
        self.assertTrue(data["generation"]["planning"]["analysis_reused"])
        self.assertEqual(data["generation"]["planning"]["planner_bpm"], 73)

    def test_short_target_returns_a_usable_recommendation_from_best_candidate(self):
        plans = iter([score(["C16"] * n, tempo=100) for n in (57, 70, 80)])
        adapter = YuE2Adapter()
        params = GenerationParams(style="Pop", lyrics="Synthetic song", target_duration_s=120)
        result = adapter.analyze_duration(params, lambda _: {"artifacts": [artifact(next(plans))]})
        self.assertEqual(result["analysis"]["status"], "too_short")
        self.assertEqual(result["analysis"]["recommended_target_s"], 140)
        params.target_duration_s = 140
        chosen, info = adapter.reuse_plan(params, result["prepared"])
        self.assertAlmostEqual(inspect(chosen).duration_s, 136.8)
        self.assertEqual(info["seed"], 1234)

    def test_over_limit_and_supplied_scores_are_explained_without_audio(self):
        adapter = YuE2Adapter()
        long = adapter.analyze_duration(GenerationParams(style="Pop"),
            lambda _: {"artifacts": [artifact(score(["C16"] * 200))]})
        self.assertEqual(long["analysis"]["status"], "too_long")
        self.assertIsNone(long["analysis"]["recommended_target_s"])
        supplied = score()
        result = adapter.analyze_duration(GenerationParams(style="100 BPM", target_duration_s=30,
            model_options={"abc": supplied, "cot": "full"}), lambda _: self.fail("Supplied score must not use inference"))
        self.assertEqual(result["analysis"]["recommended_target_s"], 40)
        self.assertEqual(result["prepared"]["score"], supplied)
        self.assertEqual(result["analysis"]["bpm"], 120)

    def test_truncated_or_invalid_plans_produce_no_false_estimate(self):
        for art in (artifact(score(), "true"), artifact("not a score")):
            with self.assertRaises(ScoreError):
                YuE2Adapter().analyze_duration(GenerationParams(style="Pop"), lambda _: {"artifacts": [art]})


class DurationAnalysisApiTests(ModelFixtures):
    def request(self, path, body=None, method="POST"):
        from studio.app import app
        async def send():
            async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://studio.test") as client:
                return await client.request(method, path, json=body)
        return asyncio.run(send())

    def wait(self, job):
        from studio import app as api
        deadline = time.monotonic() + 5
        while api.jobs[job["id"]]["status"] in {"queued", "running"} and time.monotonic() < deadline:
            time.sleep(0.01)
        self.assertNotIn(api.jobs[job["id"]]["status"], {"queued", "running"})
        return api.jobs[job["id"]]

    def test_analysis_queue_reuses_plan_and_refuses_changed_inputs_profile_and_expiry(self):
        self.setup_profile()
        from studio import app as api
        adapter, calls = YuE2Adapter(), []
        def run(profile, request, cancel=None):
            calls.append(copy.deepcopy(request))
            if request["options"].get("stop_after") == "abc":
                return {"artifacts": [artifact(score())]}
            return {"audio": tiny_audio(), "artifacts": [artifact(json.dumps([1] * 1000), ident="semantic")]}
        body = {"style": "English, piano", "lyrics": "Synthetic song", "model_options": {"cot": "full"}}
        with patch.object(self.provider, "adapter", return_value=adapter), patch.object(self.provider, "run", side_effect=run):
            response = self.request("/api/duration-analysis", body)
            self.assertEqual(response.status_code, 200)
            job = self.wait(response.json())
            self.addCleanup(api.jobs.pop, job["id"], None)
            self.addCleanup(api._plans.pop, job["id"], None)
            self.assertEqual(job["status"], "done", job.get("error"))
            self.assertFalse(list(self.root.glob("outputs/*")), "Analysis must not write songs")
            generate = {**body, "target_duration_s": 40, "analysis_id": job["id"]}
            self.assertEqual(self.request("/api/generate", {**generate, "lyrics": "Changed synthetic text"}).status_code, 409)
            self.assertEqual(self.request("/api/generate", {**generate, "target_duration_s": 10}).status_code, 422)
            response = self.request("/api/generate", {**generate, "seed": 1235})
            self.assertEqual(response.status_code, 200, response.text)
            self.assertNotIn("_prepared", response.json())
            finished = self.wait(response.json())
            self.addCleanup(api.jobs.pop, finished["id"], None)
            self.assertEqual(finished["status"], "done", finished.get("error"))
            self.assertEqual(len(calls), 3)
            self.assertTrue(finished["result"]["generation"]["planning"]["analysis_reused"])
            self.assertEqual(finished["result"]["generation"]["planning"]["seed"], 1234)
            self.assertEqual(finished["result"]["params"]["seed"], 1235)
            self.assertNotIn("_prepared", next(j for j in self.request("/api/jobs", method="GET").json() if j["id"] == finished["id"]))
            self.setup_profile("bf16", "f32")
            self.assertEqual(self.request("/api/generate", generate).status_code, 409)
            api._plans[job["id"]]["created"] -= api.PLAN_TTL_S + 1
            self.assertIn("expired", self.request("/api/generate", generate).json()["detail"])

    def test_fresh_install_and_unsupported_provider_cannot_start_analysis(self):
        self.assertEqual(self.request("/api/duration-analysis", {"style": "Piano"}).status_code, 409)
        self.assertFalse(self.requests)
        self.setup_profile()
        self.assertEqual(self.request("/api/duration-analysis", {"style": "Piano"}).status_code, 422)

    def test_running_analysis_can_be_cancelled_without_a_plan_or_song(self):
        self.setup_profile()
        from studio import app as api
        self.provider.hold_run = threading.Event()
        with patch.object(self.provider, "adapter", return_value=YuE2Adapter()):
            job = self.request("/api/duration-analysis", {"style": "Piano"}).json()
            self.addCleanup(api.jobs.pop, job["id"], None)
            deadline = time.monotonic() + 5
            while not self.provider.calls and time.monotonic() < deadline:
                time.sleep(0.01)
            self.assertTrue(self.provider.calls)
            self.assertEqual(self.request(f"/api/jobs/{job['id']}/cancel").status_code, 200)
            self.assertEqual(self.wait(job)["status"], "cancelled")
            self.assertNotIn(job["id"], api._plans)
            self.assertFalse(list(self.root.glob("outputs/*")))


class ScoreDurationTests(unittest.TestCase):
    def test_meter_units_and_compressed_rests_are_timed(self):
        text = score(["C8D8E8"] * 2, ["Z"] * 2, tempo=90, unit=32, meter="3/4")
        self.assertEqual(inspect(text).duration_s, 4)
        compressed = text.replace("C8D8E8|", "Z3|").replace("Z|", "Z3|")
        self.assertEqual(inspect(compressed).duration_s, 12)

    def test_fit_keeps_all_vocal_notes_tempo_and_ending(self):
        original = inspect(score())
        text, info = fit(score(), 30)
        fitted = inspect(text)
        self.assertEqual(max(line.count("|") for line in text.splitlines()), 4)
        self.assertEqual(fitted.duration_s, 30)
        self.assertEqual(fitted.bpm, original.bpm)
        self.assertEqual([b.vocal for b in fitted.bars if b.vocal != "Z"], ["C16"] * 4)
        self.assertEqual(fitted.bars[:2], original.bars[:2])
        self.assertEqual(fitted.bars[-4:], original.bars[-4:])
        self.assertEqual(info["removed_instrumental_bars"], 5)

    def test_shortening_removes_whole_tied_instrumental_phrases(self):
        ins = ["C16", "C16", "D16-", "D16", "E16"] + ["C16"] * 15
        text, _ = fit(score(instrumental=ins), 30)
        bars = inspect(text).bars
        for index, bar in enumerate(bars):
            if bar.instrumental.endswith("-"):
                self.assertEqual(bars[index + 1].instrumental[0], bar.instrumental[0])

    def test_vocal_and_breathing_bars_are_never_cut_to_force_fit(self):
        with self.assertRaisesRegex(ScoreError, "longer duration.*shorten verses"):
            fit(score(["C16", "Z"] * 12), 30)

    def test_unsupported_or_unfinished_notation_fails_closed(self):
        for text in [score().replace("C16|", "C15|"), score().replace("C16|", "(3CCC|"),
                     score()[:-2], score().replace("Q:1/4=120", "Q:120"),
                     score().replace("V: Ins\n", "V: Ins\nM:3/4\n")]:
            with self.subTest(text=text[:30]), self.assertRaises(ScoreError):
                inspect(text)


class EndingGenerationTests(unittest.TestCase):
    def params(self, **changes):
        return GenerationParams(lyrics="[Verse]\nA light\n[Outro]\nGood night", style="English, pop", **changes)

    def test_target_is_separate_from_cap_and_selects_planning(self):
        p = YuE2Adapter().normalize(self.params(target_duration_s=240))
        self.assertEqual(p.cot, "full")
        self.assertEqual(p.max_duration_s, 270)
        self.assertEqual(p.semantic_max_tokens, 6750)
        self.assertNotIn("target_duration_s", p.to_request()["options"])
        with self.assertRaises(ValueError):
            YuE2Adapter().normalize(self.params(target_duration_s=240, max_duration_s=180))
        with self.assertRaises(ValueError):
            YuE2Adapter().normalize(self.params(target_duration_s=240, model_options={"semantic_max_tokens": 9000}))

    def test_plan_is_checked_before_rendering_and_originals_are_retained(self):
        calls = []
        def run(request):
            calls.append(copy.deepcopy(request))
            if request["options"].get("stop_after") == "abc":
                return {"artifacts": [artifact(score())]}
            return {"audio": tiny_audio(), "artifacts": [artifact(json.dumps([1] * 750),
                "false" if request["options"].get("stop_after") == "semantic" else "true", "semantic")]}
        result = YuE2Adapter().generate(self.params(target_duration_s=30), run)
        self.assertEqual(len(calls), 3)
        self.assertEqual(inspect(calls[1]["options"]["abc"]).duration_s, 30)
        self.assertEqual(calls[1]["options"]["semantic_max_tokens"], "1125")
        self.assertEqual(calls[2]["options"]["semantic_min_tokens"], "750")
        self.assertEqual(json.loads(calls[2]["options"]["semantic_prefix"]), [1] * 750)
        self.assertEqual(result["generation"]["status"], "model_end")
        self.assertFalse(result["generation"]["listening_verified"])
        self.assertEqual({a["id"] for a in result["artifacts"]}, {"plan-1", "score", "semantic-attempt-1", "semantic"})
        self.assertEqual(result["generation"]["render_artifact_meta"]["semantic"]["truncated"], "true")
        self.assertEqual(base64.b64decode(result["artifacts"][0]["payload"]).decode(), score())

    def test_explicit_style_tempo_retimes_generated_score_before_fitting(self):
        # Use synthetic text; private user prompts do not belong in repository tests.
        planned = score(["C16"] * 94, tempo=73, unit=32, meter="2/4")
        calls = []

        def run(request):
            calls.append(copy.deepcopy(request))
            if request["options"].get("stop_after") == "abc":
                return {"artifacts": [artifact(planned)]}
            semantic = artifact(json.dumps([1] * 2820), "false", "semantic")
            if request["options"].get("stop_after") == "semantic":
                return {"artifacts": [semantic]}
            return {"audio": tiny_audio(), "artifacts": [semantic]}

        lyrics = "Synthetic verse\nSynthetic chorus\nSynthetic ending"
        style = "Hip hop, melodic rap, 100 BPM, guitar"
        params = GenerationParams(lyrics=lyrics, style=style,
                                 cot="full", seed=1234, target_duration_s=120)
        result = YuE2Adapter().generate(params, run)
        self.assertEqual(len(calls), 3)  # plan, compose with EOS, render
        self.assertEqual(calls[0]["lyrics"], lyrics)
        self.assertEqual(calls[0]["options"]["style"], style)
        checked_score = inspect(calls[1]["options"]["abc"])
        self.assertEqual(checked_score.duration_s, 112.8)
        self.assertEqual(checked_score.bpm, 100)
        self.assertEqual(result["generation"]["target_duration_s"], 120)
        self.assertEqual(result["generation"]["duration_s"], 112.8)
        self.assertTrue(result["generation"]["target_match"])
        self.assertEqual(result["generation"]["status"], "model_end")
        self.assertEqual(result["generation"]["planning"]["planner_bpm"], 73)
        self.assertEqual(result["generation"]["planning"]["requested_bpm"], 100)
        self.assertTrue(result["generation"]["planning"]["tempo_adjusted_to_match_style"])

    def test_style_tempo_override_requires_one_unambiguous_bpm(self):
        self.assertEqual(YuE2Adapter._requested_bpm("indie, 100 BPM, bright guitars"), 100)
        self.assertIsNone(YuE2Adapter._requested_bpm("100-110 BPM, electronic"))
        self.assertIsNone(YuE2Adapter._requested_bpm("90 BPM then 120 BPM"))

    def test_unfittable_plan_error_reports_the_shortest_attempt(self):
        plans = [score(["C16"] * bars, tempo=100) for bars in (57, 70, 80)]
        calls = []

        def run(request):
            calls.append(copy.deepcopy(request))
            return {"artifacts": [artifact(plans[len(calls) - 1])]} \
                if request["options"].get("stop_after") == "abc" else {"artifacts": []}

        with self.assertRaisesRegex(ScoreError, "about 137s at 100 BPM") as caught:
            YuE2Adapter().generate(self.params(target_duration_s=120, seed=10), run)
        attempts = caught.exception.diagnostics["generation"]["planning_attempts"]
        self.assertEqual([a["minimum_duration_s"] for a in attempts], [136.8, 168, 192])
        self.assertEqual(len(caught.exception.diagnostics["artifacts"]), 3)

    def test_invalid_or_truncated_plans_retry_without_audio_then_fail(self):
        for art in [artifact(score(), "true"), artifact(score().replace("C16|", "C15|")),
                    artifact(score(["C16"] * 30))]:
            calls = []
            def run(request):
                calls.append(copy.deepcopy(request))
                return {"artifacts": [art]}
            with self.subTest(art=art["meta"]), self.assertRaisesRegex(ScoreError, "three plans") as caught:
                YuE2Adapter().generate(self.params(target_duration_s=30, seed=42), run)
            self.assertEqual([c["seed"] for c in calls], [42,43,44])
            self.assertTrue(all(c["options"]["stop_after"] == "abc" for c in calls))
            self.assertEqual(len(caught.exception.diagnostics["artifacts"]), 3)

    def test_instrumental_mutes_the_planned_vocal_line_before_rendering(self):
        planned = score(['"Am"C8D8'] + ["Z"] * 3 + ["C16"] * 4)
        calls = []
        def run(request):
            calls.append(copy.deepcopy(request))
            return {"artifacts": [artifact(planned)]} if request["options"].get("stop_after") == "abc" else {"audio": tiny_audio(), "artifacts": []}
        result = YuE2Adapter().generate(self.params(instrumental=True, max_duration_s=30), run)
        self.assertEqual([c["options"].get("stop_after") for c in calls], ["abc", None])
        self.assertEqual((calls[1]["lyrics"], calls[1]["options"]["cot"]), ("[instrumental]", "full"))
        rendered = inspect(calls[1]["options"]["abc"])
        self.assertEqual([b.vocal for b in rendered.bars], ['"Am"z16'] + ["z16"] * 7)
        self.assertEqual([b.instrumental for b in rendered.bars], [b.instrumental for b in inspect(planned).bars])
        saved = next(a for a in result["artifacts"] if a["id"] == "score")
        self.assertEqual(base64.b64decode(saved["payload"]).decode(), calls[1]["options"]["abc"])

    def test_instrumental_target_can_shorten_bars_the_planner_gave_vocals(self):
        calls = []
        def run(request):
            calls.append(copy.deepcopy(request))
            if request["options"].get("stop_after") == "abc":
                return {"artifacts": [artifact(score(["C16", "Z"] * 12))]}  # unfittable with sung bars
            return {"audio": tiny_audio(), "artifacts": [artifact(json.dumps([1] * 750),
                "false" if request["options"].get("stop_after") == "semantic" else "true", "semantic")]}
        YuE2Adapter().generate(self.params(instrumental=True, target_duration_s=30), run)
        rendered = inspect(calls[1]["options"]["abc"])
        self.assertEqual(rendered.duration_s, 30)
        self.assertTrue(all(b.vocal == "z16" for b in rendered.bars))

    def test_supplied_score_is_not_modified_and_skips_planner(self):
        text = score()
        calls = []
        def run(request):
            calls.append(request)
            return {"audio": tiny_audio(), "artifacts": [artifact(json.dumps([1] * 1000), ident="semantic")]}
        YuE2Adapter().generate(self.params(target_duration_s=45, model_options={"abc": text, "cot": "full"}), run)
        self.assertEqual(len(calls), 2)
        self.assertEqual(calls[0]["options"]["abc"], text)
        with self.assertRaisesRegex(ScoreError, "supplied scores are never shortened"):
            YuE2Adapter().generate(self.params(target_duration_s=30, model_options={"abc": text, "cot": "full"}), run)
        self.assertEqual(len(calls), 2)

    def test_capped_or_early_semantics_are_not_rendered_as_target_songs(self):
        for truncated, frames in [("true", 1125), ("false", 25)]:
            calls = []
            def run(request):
                calls.append(copy.deepcopy(request))
                return {"artifacts": [artifact(json.dumps([1] * frames), truncated, "semantic")]}
            with self.subTest(truncated=truncated), self.assertRaisesRegex(ScoreError, "did not finish") as caught:
                YuE2Adapter().generate(self.params(target_duration_s=30,
                    model_options={"abc": score(["C16"] * 10), "cot": "full"}), run)
            self.assertEqual(len(calls), 2)
            self.assertTrue(all(c["options"]["stop_after"] == "semantic" for c in calls))
            self.assertEqual(len(caught.exception.diagnostics["generation"]["semantic_attempts"]), 2)

    def test_complete_song_shorter_than_target_follows_its_plan(self):
        # A 20 s plan for a 60 s target: the model ends near the plan, not the target.
        options = {"abc": score(["C16"] * 10), "cot": "full"}
        for frames, accepted in [(500, True), (450, True), (100, False)]:
            calls = []
            def run(request):
                calls.append(copy.deepcopy(request))
                return {"audio": tiny_audio(), "artifacts": [artifact(json.dumps([1] * frames), ident="semantic")]}
            with self.subTest(seconds=frames / 25):
                if not accepted:
                    with self.assertRaisesRegex(ScoreError, "did not finish"):
                        YuE2Adapter().generate(self.params(target_duration_s=60, model_options=options), run)
                    self.assertEqual(len(calls), 2)
                    continue
                result = YuE2Adapter().generate(self.params(target_duration_s=60, model_options=options), run)
                self.assertEqual(len(calls), 2)  # accepted at the first composing attempt, then rendered
                report = result["generation"]
                self.assertTrue(report["shorter_than_target"])
                self.assertFalse(report["target_match"])
                self.assertEqual(report["status"], "model_end")
                self.assertIn("shorter than the 60s target", report["message"])

    def test_semantic_retry_seed_and_progress_are_recorded(self):
        calls, progress = [], []
        def run(request):
            calls.append(copy.deepcopy(request))
            capped = len(calls) == 1
            return {"audio": tiny_audio(), "artifacts": [artifact(json.dumps([1] * (1125 if capped else 750)),
                "true" if capped else "false", "semantic")]}
        result = YuE2Adapter().generate(self.params(target_duration_s=30, seed=99,
            model_options={"abc": score(["C16"] * 10), "cot": "full"}), run, progress.append)
        self.assertEqual(result["generation"]["semantic_seed"], 100)
        self.assertEqual([c["seed"] for c in calls], [99,100,99])
        self.assertIn("Rendering", progress[-1])
        self.assertEqual(len(result["generation"]["semantic_attempts"]), 2)

    def test_hard_cap_and_missing_ending_signals_are_not_completion(self):
        adapter = YuE2Adapter()
        for value, status in [("true", "truncated"), ("false", "model_end"), (None, "unknown")]:
            data = {"audio": tiny_audio(), "artifacts": [artifact("[]", value, "semantic")]}
            result = adapter.generate(self.params(max_duration_s=180), lambda request: copy.deepcopy(data))
            self.assertEqual(result["generation"]["status"], status)
            self.assertFalse(result["generation"]["listening_verified"])
        data = {"artifacts": [artifact(score(), "true"), artifact("[]", "false", "semantic")]}
        self.assertEqual(adapter.ending(data)["status"], "truncated")


class EndingStorageTests(ModelFixtures):
    def test_existing_verified_profiles_receive_new_capabilities_without_reprobe(self):
        self.setup_profile()
        old = copy.deepcopy(self.manager.state["profiles"])
        adapter = self.provider.adapter({})
        adapter.capabilities = {**adapter.capabilities, "target_duration_s": 330}
        with patch.object(self.provider, "adapter", return_value=adapter):
            self.assertEqual(self.manager.status()["active"]["capabilities"]["target_duration_s"], 330)
            self.assertEqual(self.manager.snapshot()["capabilities"]["target_duration_s"], 330)
        self.assertEqual(self.manager.state["profiles"], old)

    def test_engine_keeps_ending_diagnostics_and_plan_artifacts(self):
        self.setup_profile()
        response = {"audio": tiny_audio(), "artifacts": [artifact(score(), ident="plan-1")],
                    "generation": {"status": "truncated", "eos_observed": False}}
        adapter = self.provider.adapter({})
        adapter.generate = lambda params, run: response
        with patch.object(self.provider, "adapter", return_value=adapter):
            from studio import engine
            result = engine.generate(GenerationParams(lyrics="A song", style="Piano"), "ending-storage")
        meta = json.loads(result.meta_path.read_text())
        self.assertEqual(meta["generation"], response["generation"])
        self.assertTrue(result.artifacts["plan-1"].exists())
        self.assertEqual(meta["artifact_meta"]["plan-1"]["truncated"], "false")

    def test_failed_plan_is_saved_outside_playable_library(self):
        self.setup_profile()
        error = ScoreError("Needs a longer duration")
        error.diagnostics = {"generation": {"planning_attempts": [{"error": "too long"}]}, "artifacts": [artifact(score())]}
        adapter = self.provider.adapter({})
        adapter.generate = lambda params, run: (_ for _ in ()).throw(error)
        from studio import engine
        with patch.object(self.provider, "adapter", return_value=adapter), self.assertRaises(ScoreError):
            engine.generate(GenerationParams(lyrics="A song", style="Piano"), "failed-plan")
        self.assertTrue((engine.OUTPUT_DIR / "failed-plan.failure-report").exists())
        self.assertFalse((engine.OUTPUT_DIR / "failed-plan.wav").exists())
        self.assertFalse((engine.OUTPUT_DIR / "failed-plan.json").exists())

    def test_token_recovery_uses_the_checked_score_and_semantic_retry_seed(self):
        self.setup_profile()
        from studio import engine
        from studio.adapters.yue2_edit import song_tokens
        text = score()
        (engine.OUTPUT_DIR / "recover.abc").write_text(text)
        params = YuE2Params(lyrics="A song", style="English, pop", seed=42, target_duration_s=45)
        (engine.OUTPUT_DIR / "recover.json").write_text(json.dumps({"params": params.model_dump(exclude_none=True),
            "generation": {"target_duration_s": 45, "semantic_seed": 43},
            "duration_s": 40, "artifacts": {"score": "recover.abc"}}))
        with patch("studio.adapters.yue2_edit._run", return_value={"artifacts": [artifact(json.dumps([1] * 1000), ident="semantic")]}) as run:
            self.assertEqual(len(song_tokens("recover", self.manager.snapshot())), 1000)
        args = run.call_args.args
        self.assertEqual(args[1], 43)
        self.assertEqual(args[2]["abc"], text)
