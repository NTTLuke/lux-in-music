"""YuE2 generation parameters.

Mirrors the request options documented in vendor/audio.cpp/docs/models/yue2.md.
Only options the user actually sets are forwarded, so audio.cpp defaults apply
for everything else.
"""

from typing import Literal
import base64
import copy
import json

from pydantic import BaseModel, ConfigDict, Field, model_validator

SEMANTIC_FPS = 25  # semantic codec frames per second of audio


class YuE2Params(BaseModel):
    model_config = ConfigDict(extra="forbid")
    # --- core ---
    title: str | None = Field(None, max_length=80, description="Song title (UI only, not sent to the model)")
    lyrics: str = Field(..., min_length=1, description="Lyrics with [Verse]/[Chorus]/... section tags")
    style: str = Field(..., min_length=1, description="Style prompt: language, genre, instruments, vocal, mix")
    cot: Literal["off", "melody", "full"] = Field("off", description="Symbolic planning route")
    seed: int = Field(1234, ge=0, lt=2**63)
    num_inference_steps: int | None = Field(None, gt=0, description="NAR ODE steps (default 8)")
    guidance_scale: float | None = Field(None, ge=0, le=20)

    # --- ABC conditioning (cot=melody|full) ---
    abc: str | None = Field(None, description="Inline ABC score")

    # --- semantic sampling (controls the song itself, incl. length) ---
    semantic_temperature: float | None = Field(None, ge=0, le=5)
    semantic_top_p: float | None = Field(None, ge=0, le=1)
    semantic_top_k: int | None = Field(None, ge=1)
    semantic_repetition_penalty: float | None = Field(None, gt=0)
    semantic_min_tokens: int | None = Field(None, ge=0)
    semantic_max_tokens: int | None = Field(None, ge=1)

    # --- ABC planner sampling ---
    abc_temperature: float | None = Field(None, ge=0, le=5)
    abc_top_p: float | None = Field(None, ge=0, le=1)
    abc_top_k: int | None = Field(None, ge=1)

    # --- convenience: max length in seconds -> semantic_max_tokens ---
    max_duration_s: float | None = Field(None, gt=0, le=360)
    target_duration_s: float | None = Field(None, ge=30, le=330)

    @model_validator(mode="after")
    def _check(self):
        if self.abc and self.cot == "off":
            raise ValueError("abc requires cot=melody or cot=full")
        if self.target_duration_s:
            if self.cot == "off":
                self.cot = "full"
            cap = min(360, self.target_duration_s + max(15, self.target_duration_s * 0.125))
            if self.max_duration_s is None:
                self.max_duration_s = cap
            if self.max_duration_s < self.target_duration_s:
                raise ValueError("The hard limit must be at least the target duration")
        if self.max_duration_s and self.semantic_max_tokens is None:
            self.semantic_max_tokens = int(self.max_duration_s * SEMANTIC_FPS)
        if self.target_duration_s and self.semantic_max_tokens < int(self.target_duration_s * SEMANTIC_FPS):
            raise ValueError("The semantic token cap must allow the target duration")
        if self.target_duration_s and self.semantic_max_tokens > int(self.max_duration_s * SEMANTIC_FPS):
            raise ValueError("The semantic token cap must not exceed the hard duration limit")
        lo, hi = self.semantic_min_tokens, self.semantic_max_tokens
        if hi is not None and lo is None and hi < 200:
            # audio.cpp default min is 200 tokens (8s); keep the pair valid
            self.semantic_min_tokens = hi
        if lo is not None and hi is not None and hi < lo:
            raise ValueError("semantic_max_tokens must be >= semantic_min_tokens")
        return self

    def to_request(self) -> dict:
        """Build the body for audio.cpp POST /v1/tasks/run (`request` field)."""
        skip = {"title", "lyrics", "seed", "max_duration_s", "target_duration_s"}
        options = {
            k: str(v).lower() if isinstance(v, bool) else str(v)
            for k, v in self.model_dump(exclude_none=True).items()
            if k not in skip
        }
        return {"lyrics": self.lyrics, "seed": self.seed, "options": options}


class YuE2Adapter:
    """Translate shared inputs into the native YuE2 request."""
    capabilities = {"planning": ["off", "melody", "full"], "abc": True,
                    "semantic_edit": True, "max_duration_s": 360,
                    "target_duration_s": 330, "min_target_duration_s": 30,
                    "options": ["num_inference_steps", "guidance_scale", "semantic_temperature",
                                "semantic_top_p", "semantic_top_k", "semantic_repetition_penalty"]}

    def normalize(self, params):
        data = params.model_dump(exclude_none=True)
        options = data.pop("model_options", {})
        for key, value in options.items():
            if key in data and data[key] != value:
                raise ValueError(f"Conflicting model option: {key}")
            data[key] = value
        return YuE2Params(**data)

    def request(self, params):
        request = self.normalize(params).to_request()
        request["options"]["export_semantic"] = "true"
        return request

    def smoke_request(self):
        return {"lyrics": "[Verse]\nA quiet light", "seed": 1234,
                "options": {"style": "English, soft piano", "cot": "off",
                            "semantic_min_tokens": "8", "semantic_max_tokens": "16",
                            "num_inference_steps": "1"}}

    def generate(self, params, run, progress=None):
        from .yue2_score import inspect, fit, ScoreError
        p = self.normalize(params)
        request = self.request(p)
        report = {"target_duration_s": p.target_duration_s,
                  "hard_limit_s": p.semantic_max_tokens / SEMANTIC_FPS if p.semantic_max_tokens else 360,
                  "planning_attempts": [], "listening_verified": False}
        artifacts = []
        if p.target_duration_s:
            if p.abc:
                score = inspect(p.abc)
                if score.duration_s > p.target_duration_s:
                    raise ScoreError(f"Your score lasts about {score.duration_s:.0f}s. Choose a longer target or edit the score; supplied scores are never shortened automatically.")
                report["planning"] = {"planned_duration_s": round(score.duration_s, 2), "source": "supplied"}
                chosen = p.abc
            else:
                chosen = None
                for attempt in range(3):
                    if progress:
                        progress(f"Planning arrangement ({attempt + 1}/3)")
                    planning = copy.deepcopy(request)
                    planning["seed"] = (p.seed + attempt) % (2**63)
                    planning["options"]["stop_after"] = "abc"
                    result = run(planning)
                    art = next((a for a in result.get("artifacts", []) if a["id"] == "score"), None)
                    entry = {"seed": planning["seed"]}
                    if art:
                        artifacts.append({**art, "id": f"plan-{attempt + 1}"})
                    try:
                        if not art or str(art.get("meta", {}).get("truncated")).lower() != "false":
                            raise ScoreError("The planner did not return a complete score")
                        text = base64.b64decode(art["payload"]).decode("utf-8")
                        chosen, info = fit(text, p.target_duration_s)
                        entry.update(info)
                        report["planning"] = {**info, "source": "generated", "seed": planning["seed"]}
                    except (ValueError, UnicodeError) as error:
                        entry["error"] = str(error)
                    report["planning_attempts"].append(entry)
                    if chosen is not None:
                        break
                if chosen is None:
                    error = ScoreError("No complete arrangement fits the requested duration after three plans. " + report["planning_attempts"][-1]["error"])
                    error.diagnostics = {"generation": report, "artifacts": artifacts}
                    raise error
            request["options"]["abc"] = chosen
            artifacts.append({"id": "score", "payload": base64.b64encode(chosen.encode()).decode(),
                              "meta": {"truncated": "false", "source": "duration-checked", "format": "abc"}})
            # Compose before acoustic decoding. Never render tokens already
            # known to have hit the cap; retries are deliberately bounded.
            report["semantic_attempts"] = []
            accepted = None
            planned = report["planning"]["planned_duration_s"]
            tolerance = lambda seconds: max(15, seconds * 0.125)
            for attempt in range(2):
                if progress:
                    progress(f"Composing and checking the ending ({attempt + 1}/2)")
                semantic_request = copy.deepcopy(request)
                semantic_request["seed"] = (p.seed + attempt) % (2**63)
                semantic_request["options"]["stop_after"] = "semantic"
                result = run(semantic_request)
                semantic = next((a for a in result.get("artifacts", []) if a["id"] == "semantic"), None)
                ending = self.ending(result)
                entry = {"seed": semantic_request["seed"], **ending}
                if semantic:
                    artifacts.append({**semantic, "id": f"semantic-attempt-{attempt + 1}"})
                    codes = json.loads(base64.b64decode(semantic["payload"]))
                    entry["duration_s"] = len(codes) / SEMANTIC_FPS
                    entry["target_match"] = abs(entry["duration_s"] - p.target_duration_s) <= tolerance(p.target_duration_s)
                    # Planning only shortens, so short lyrics give a short plan. Accept a complete
                    # song that follows its plan; an ending far before the plan dropped sections.
                    entry["shorter_than_target"] = (entry["duration_s"] < p.target_duration_s and not entry["target_match"]
                                                    and abs(entry["duration_s"] - planned) <= tolerance(planned))
                    if ending["status"] == "model_end" and (entry["target_match"] or entry["shorter_than_target"]):
                        accepted = (semantic, codes, entry)
                report["semantic_attempts"].append(entry)
                if accepted:
                    break
            if not accepted:
                report.update(report["semantic_attempts"][-1])
                error = ScoreError("The model did not finish near the requested duration after two attempts. "
                                   "Try shorter verses/repeated choruses, a longer duration, or a more compact style. "
                                   "No unfinished audio was rendered. Planning and semantic diagnostics were saved.")
                error.diagnostics = {"generation": report, "artifacts": artifacts}
                raise error
            semantic, codes, entry = accepted
            report.update(entry)
            report["semantic_seed"] = entry["seed"]
            render = copy.deepcopy(request)
            render["options"].update(semantic_prefix=json.dumps(codes),
                                      semantic_min_tokens=str(len(codes)), semantic_max_tokens=str(len(codes)))
            if progress:
                progress("Rendering the finished composition")
            data = run(render)
            report["render_artifact_meta"] = {a["id"]: a.get("meta", {}) for a in data.get("artifacts", [])}
            # A forced render reports a full window by construction. Preserve
            # this separately from EOS observed at the composing stage.
            data["artifacts"] = [a for a in data.get("artifacts", []) if a["id"] != "semantic"]
            data["artifacts"].append(semantic)
        else:
            data = run(request)
        # Supplied ABC is not exported by the native runtime, so retain our plan.
        data["artifacts"] = artifacts + data.get("artifacts", [])
        report.update(self.ending(data))
        if report.get("shorter_than_target"):
            report["message"] += (f" It is shorter than the {p.target_duration_s:.0f}s target: the arrangement for these"
                                  f" lyrics lasts about {planned:.0f}s. Add sections for a longer song.")
        data["generation"] = report
        return data

    @staticmethod
    def ending(data):
        meta = {a["id"]: a.get("meta", {}) for a in data.get("artifacts", [])}
        semantic = str(meta.get("semantic", {}).get("truncated", "")).lower()
        score = str(meta.get("score", {}).get("truncated", "")).lower()
        status = "truncated" if "true" in (semantic, score) else "model_end" if semantic == "false" else "unknown"
        return {"status": status, "semantic_truncated": {"true": True, "false": False}.get(semantic),
                "score_truncated": {"true": True, "false": False}.get(score),
                "eos_observed": semantic == "false",
                "message": {"truncated": "Stopped at the hard limit. The song may be unfinished. Try a longer duration or shorter lyrics.",
                            "model_end": "The model emitted its end token. Listen to check the musical ending.",
                            "unknown": "The runtime did not report an ending signal."}[status]}

    def runtime_config(self, profile):
        return {"path": profile["root"], "session_options": {
            "yue2.model_gguf": profile["main_file"], "yue2.vae_gguf": profile["vae_file"]}}

    def render_section(self, *args, **kwargs):
        from .yue2_edit import render_section
        return render_section(*args, **kwargs)
