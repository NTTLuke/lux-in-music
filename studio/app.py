"""Web studio: queue generations against audio.cpp and browse the library.

    uv run uvicorn studio.app:app --port 8000
"""

import json
import queue
import threading
import time
import uuid
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from . import edit, engine, separate
from .params import GenerationParams

STATIC = Path(__file__).parent / "static"

app = FastAPI(title="Suno Studio Killer")


@app.middleware("http")
async def _no_cache_ui(request, call_next):
    # The UI changes often during development: always revalidate HTML/JS/CSS.
    response = await call_next(request)
    if request.url.path == "/" or request.url.path.startswith("/static/"):
        response.headers["Cache-Control"] = "no-cache"
    return response

jobs: dict[str, dict] = {}
_queue: queue.Queue[str] = queue.Queue()
# Seconds of compute per second of audio, learned from finished jobs (M4 Max, warm model ~0.45).
_speed = {"ratio": 0.5, "overhead": 8.0}


_sep_speed = {"vocals": 1.1, "4stems": 0.15, "6stems": 0.15, "anything": 1.5}  # seconds per audio second


def _song_duration(song: str) -> float:
    try:
        return json.loads((engine.OUTPUT_DIR / f"{song}.json").read_text())["duration_s"]
    except (OSError, KeyError, json.JSONDecodeError):
        return 60.0


def _estimate(job: dict) -> float:
    params = job["params"]
    if job["kind"] == "separate":
        return 3 + _sep_speed.get(params["mode"], 0.5) * _song_duration(params["song"])
    if job["kind"] == "stemedit":
        dur = _song_duration(params["song"])
        span = params["end_s"] - params["start_s"]
        sep = _sep_speed.get(params.get("mode", "4stems"), 0.5) * (span + 6)
        return 6 + 0.25 * dur + 0.3 * span + sep
    if job["kind"] == "edit":
        dur = _song_duration(params["song"])
        recover = 0 if (engine.OUTPUT_DIR / f"{params['song']}.semantic.json").exists() else 0.25 * dur
        return 4 + recover + 0.25 * dur + 0.3 * (params["end_s"] - params["start_s"])
    target = params.get("max_duration_s") or params.get("semantic_max_tokens", 9000) / 25
    return _speed["overhead"] + _speed["ratio"] * min(target, 360)


def _worker() -> None:
    # audio.cpp runs one generation at a time per model, so a single worker is enough.
    while True:
        job_id = _queue.get()
        job = jobs.get(job_id)
        if job is None:
            continue
        job.update(status="running", started=time.time(), eta_s=_estimate(job))
        try:
            if job["kind"] == "stemedit":
                p = job["params"]
                res = separate.replace_stem(p["song"], p["set_id"], p["stem"], p["start_s"], p["end_s"],
                                            p["seed"], p.get("lyrics"))
                job.update(status="done", result=res)
                continue
            if job["kind"] == "edit":
                p = job["params"]
                res = edit.replace_section(p["song"], p["start_s"], p["end_s"], p["seed"], p.get("lyrics"))
                job.update(status="done", result=res)
                continue
            if job["kind"] == "separate":
                p = job["params"]
                res = separate.separate(p["song"], p["mode"], p.get("prompt"))
                job.update(status="done", result=res)
                _sep_speed[p["mode"]] = res["elapsed_s"] / max(1.0, _song_duration(p["song"]))
                continue
            res = engine.generate(GenerationParams(**job["params"]))
            job.update(status="done", result=json.loads(res.meta_path.read_text()))
            if res.duration_s > 5:
                r = max(0.1, (res.elapsed_s - _speed["overhead"]) / res.duration_s)
                _speed["ratio"] = 0.7 * _speed["ratio"] + 0.3 * r
        except Exception as e:
            job.update(status="error", error=str(e))
        finally:
            job["finished"] = time.time()


threading.Thread(target=_worker, daemon=True).start()


@app.get("/api/health")
def api_health():
    try:
        return {"engine": "ok", **engine.health()}
    except Exception as e:
        return {"engine": "down", "error": str(e), "url": engine.ENGINE_URL}


@app.post("/api/generate")
def api_generate(params: GenerationParams):
    job_id = uuid.uuid4().hex[:8]
    jobs[job_id] = {"id": job_id, "kind": "generate", "status": "queued", "created": time.time(),
                    "params": params.model_dump(exclude_none=True)}
    _queue.put(job_id)
    return jobs[job_id]


@app.get("/api/jobs")
def api_jobs():
    now = time.time()
    out = sorted(jobs.values(), key=lambda j: j["created"], reverse=True)
    return [{**j, "now": now} for j in out]


@app.delete("/api/jobs/{job_id}")
def api_dismiss_job(job_id: str):
    job = jobs.get(job_id)
    if job is None:
        raise HTTPException(404)
    if job["status"] == "running":
        raise HTTPException(409, "job is running")
    del jobs[job_id]
    return {"ok": True}


def _load_meta(meta: Path) -> dict | None:
    try:
        item = json.loads(meta.read_text())
    except json.JSONDecodeError:
        return None
    changed = False
    if "peaks" not in item:  # songs generated before waveforms existed
        wav = meta.with_suffix(".wav")
        if wav.exists():
            item["peaks"] = engine.compute_peaks(wav)
            changed = True
    if "title" not in item or item["title"] == item["name"]:
        item["title"] = item["params"].get("title") or engine.auto_title(item["params"]["lyrics"])
        changed = True
    if changed:
        meta.write_text(json.dumps(item, indent=2))
    return item


@app.get("/api/library")
def api_library():
    items = [m for p in engine.OUTPUT_DIR.glob("*.json")
             if not p.name.endswith(".semantic.json") and (m := _load_meta(p))]
    return sorted(items, key=lambda m: m.get("created", ""), reverse=True)


class SeparateRequest(BaseModel):
    song: str = Field(..., pattern=r"^[\w.-]+$")
    mode: str
    prompt: str | None = Field(None, max_length=120)


@app.get("/api/lux/modes")
def lux_modes():
    return [{"id": m.id, "label": m.label, "stems": m.stems, "prompt": m.prompt} for m in separate.MODES.values()]


@app.post("/api/lux/separate")
def lux_separate(req: SeparateRequest):
    if not (engine.OUTPUT_DIR / f"{req.song}.wav").exists():
        raise HTTPException(404, "song not found")
    mode = separate.MODES.get(req.mode)
    if mode is None:
        raise HTTPException(422, f"unknown mode {req.mode}")
    if mode.prompt and not (req.prompt or "").strip():
        raise HTTPException(422, "describe the sound you want to extract")
    job_id = uuid.uuid4().hex[:8]
    jobs[job_id] = {"id": job_id, "kind": "separate", "status": "queued", "created": time.time(),
                    "params": req.model_dump(exclude_none=True)}
    _queue.put(job_id)
    return jobs[job_id]


class EditRequest(BaseModel):
    song: str = Field(..., pattern=r"^[\w.-]+$")
    start_s: float = Field(..., ge=0)
    end_s: float = Field(..., gt=0)
    seed: int = Field(..., ge=0, lt=2**63)
    lyrics: str | None = None


@app.post("/api/edit/replace")
def edit_replace(req: EditRequest):
    meta_path = engine.OUTPUT_DIR / f"{req.song}.json"
    if not meta_path.exists():
        raise HTTPException(404, "song not found")
    duration = json.loads(meta_path.read_text())["duration_s"]
    if req.end_s - req.start_s < 1 or req.start_s >= duration:
        raise HTTPException(422, "select at least 1 second inside the song")
    job_id = uuid.uuid4().hex[:8]
    jobs[job_id] = {"id": job_id, "kind": "edit", "status": "queued", "created": time.time(),
                    "params": {**req.model_dump(exclude_none=True), "end_s": min(req.end_s, duration)}}
    _queue.put(job_id)
    return jobs[job_id]


class StemEditRequest(EditRequest):
    set_id: str = Field(..., pattern=r"^[\w.-]+$")
    stem: str = Field(..., pattern=r"^[\w-]+$")


@app.post("/api/edit/replace-stem")
def edit_replace_stem(req: StemEditRequest):
    set_meta = separate.STEMS_DIR / req.song / req.set_id / "stems.json"
    if not set_meta.exists():
        raise HTTPException(404, "stem set not found")
    base = json.loads(set_meta.read_text())
    if not any(st["id"] == req.stem for st in base["stems"]):
        raise HTTPException(422, f"no stem {req.stem} in this set")
    duration = _song_duration(req.song)
    if req.end_s - req.start_s < 1 or req.start_s >= duration:
        raise HTTPException(422, "select at least 1 second inside the song")
    job_id = uuid.uuid4().hex[:8]
    jobs[job_id] = {"id": job_id, "kind": "stemedit", "status": "queued", "created": time.time(),
                    "params": {**req.model_dump(exclude_none=True), "end_s": min(req.end_s, duration),
                               "mode": base["mode"]}}
    _queue.put(job_id)
    return jobs[job_id]


@app.get("/api/lux/{song}")
def lux_song(song: str):
    if "/" in song or song.startswith("."):
        raise HTTPException(400)
    return separate.list_stem_sets(song)


engine.OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
app.mount("/outputs", StaticFiles(directory=engine.OUTPUT_DIR), name="outputs")
app.mount("/static", StaticFiles(directory=STATIC), name="static")


@app.get("/")
def index():
    return FileResponse(STATIC / "index.html")
