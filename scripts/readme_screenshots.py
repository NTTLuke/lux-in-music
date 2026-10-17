"""Capture the real UI with isolated, synthetic showcase data, never user files.

Run through check_ui.py --readme-screenshots. No inference or downloads occur.
"""

import base64
import hashlib
import io
import json
import math
import wave
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def capture(browser, url, destination):
    from playwright.sync_api import expect

    destination.mkdir(parents=True, exist_ok=True)
    context = browser.new_context(viewport={"width": 1600, "height": 1240}, reduced_motion="reduce")
    page = context.new_page()
    errors = []
    page.on("pageerror", lambda error: errors.append(str(error)))
    page.route("https://**/*", lambda route: route.abort())
    # Draw original geometric landscapes in a blank browser, without image files.
    paintings = page.evaluate("""() => [
      ['#101c37', '#d89668', '#253a50', '#132431'],
      ['#201528', '#bd6f7d', '#514064', '#292438'],
      ['#153d46', '#d7b96b', '#356460', '#183c40']
    ].map(([sky, light, mountain, foreground], i) => {
      const c = document.createElement('canvas'); c.width = 900; c.height = 600;
      const x = c.getContext('2d'), g = x.createLinearGradient(0, 0, 0, 600);
      g.addColorStop(0, sky); g.addColorStop(1, light); x.fillStyle = g; x.fillRect(0, 0, 900, 600);
      x.fillStyle = '#fbe5b0'; x.beginPath(); x.arc(650 - i * 90, 195, 55, 0, Math.PI * 2); x.fill();
      x.fillStyle = mountain; x.beginPath(); x.moveTo(0, 470); x.lineTo(220, 190 + i * 40);
      x.lineTo(460, 440); x.lineTo(670, 280); x.lineTo(900, 465); x.lineTo(900, 600); x.lineTo(0, 600); x.fill();
      x.fillStyle = foreground; x.beginPath(); x.moveTo(0, 480); x.quadraticCurveTo(450, 340, 900, 520);
      x.lineTo(900, 600); x.lineTo(0, 600); x.fill();
      return c.toDataURL('image/png').split(',')[1];
    })""")
    paintings = [base64.b64decode(png) for png in paintings]
    models = json.loads((ROOT / "config/model-catalog.json").read_text())["models"]
    reviews, catalog = [], []
    for model in models:
        review = hashlib.sha256(json.dumps({"model": model["id"], "revision": model["revision"],
                                           "licenses": model["licenses"]}, sort_keys=True).encode()).hexdigest()
        reviews.append(review)
        choices = []
        for precision, main in model["precisions"].items():
            for vae, decoder in (model["vaes"].items() or [(None, None)]):
                size = sum(f["size"] for f in [main, *model["required"], *([decoder] if decoder else [])])
                default = precision == model["default_precision"] and vae == model["default_vae"]
                choices.append({"id": model["id"] + "--" + precision + ("--" + vae if vae else ""),
                    "precision": precision, "vae_precision": vae, "bytes": size,
                    "missing_bytes": 0 if default else size, "installed": default,
                    "ready": default, "license_review_id": review})
        catalog.append({**model, "choices": choices})
    capabilities = {"planning": ["off", "melody", "full"], "abc": True, "instrumental": True,
        "duration_analysis": True, "semantic_edit": True, "max_duration_s": 360,
        "target_duration_s": 330, "min_target_duration_s": 30,
        "options": ["num_inference_steps", "guidance_scale", "semantic_temperature", "semantic_top_p",
                    "semantic_top_k", "semantic_repetition_penalty"]}
    active = {**models[0], "id": "yue2-3b--q8_0--f16", "model_id": "yue2-3b", "precision": "q8_0",
              "vae_precision": "f16", "capabilities": capabilities}
    separators = {m["mode_id"]: next(c["id"] for c in m["choices"] if c["ready"]) for m in catalog if m["task"] != "gen"}
    status = {"active": active, "setup_required": False, "state_error": None, "jobs": [],
              "separators": separators, "accepted_license_reviews": reviews, "profiles": []}
    entry = json.loads((ROOT / "studio/data/vibe-style-catalog.json").read_text())["entries"][0]
    songs = []
    for i, (title, style) in enumerate([
        ("Afterglow", entry["style"]),
        ("Velvet Horizon", "Instrumental, ambient piano, warm strings, gentle percussion"),
        ("Electric Bloom", "Instrumental, progressive metal, layered guitars, expressive drums"),
    ]):
        songs.append({"name": f"showcase-{i}", "title": title, "created": "2026-10-16T18:00:00",
            "params": {"style": style, "lyrics": "", "seed": 4200 + i, "cot": "full"},
            "duration_s": 238 - i * 31, "elapsed_s": 180 + i * 12, "can_edit": True,
            "peaks": [.15 + abs(math.sin(n * .31) * math.cos(n * .071)) * .7 for n in range(240)],
            "model_profile": active, "artifacts": {"vibe_image": f"showcase-{i}.png"},
            "vibe": {"source": "image", "entry_id": entry["id"], "image_count": 3,
                     "images": [{"file": f"showcase-{j}.png", "entry_id": entry["id"]} for j in range(3)]}})
    api = {"settings/catalog": {"models": catalog}, "settings/status": status,
           "library": songs, "jobs": [], "health": {"engine": "ok", "backend": "Metal"},
           "vibe/status": {"installed": True, "runtime_compatible": True, "license_accepted": True, "job": None},
           "vibe/analyze": {"entry_id": entry["id"], "entry_ids": [entry["id"]] * 3,
                             "image_count": 3, "style": entry["style"]}, "vibe/release": {"released": True},
           "beats/showcase-0": {"bpm": 120, "offset_s": 0, "beat_s": .5, "beats_per_bar": 4}}
    stems = [{"id": name, "label": name, "file": f"showcase-{name}.wav",
              "peaks": [.1 + abs(math.sin(n * (.2 + i * .07))) * .65 for n in range(240)],
              "rms_db": -18, "silent": False} for i, name in enumerate(("vocals", "drums", "bass", "other"))]
    api["lux/showcase-0"] = [{"id": "4stems", "mode": "4stems", "mode_label": "4 stems",
                             "elapsed_s": 3.5, "prompt": None, "stems": stems}]
    def respond(route):
        key = route.request.url.split("/api/", 1)[1].split("?", 1)[0]
        if key not in api:
            raise AssertionError(f"Unexpected showcase API: {key}")
        route.fulfill(json=api[key])
    page.route("**/api/**", respond)
    # Silent audio only supplies a timeline for the real Web Audio mixer.
    buffer = io.BytesIO()
    with wave.open(buffer, "wb") as audio:
        audio.setnchannels(1); audio.setsampwidth(2); audio.setframerate(8000)
        audio.writeframes(b"\0\0" * 8000 * 238)
    def artifact(route):
        name = route.request.url.rsplit("/", 1)[1]
        if name.endswith(".png"):
            route.fulfill(body=paintings[int(name[-5])], content_type="image/png")
        elif name.endswith(".wav"):
            route.fulfill(body=buffer.getvalue(), content_type="audio/wav")
        else:
            raise AssertionError(f"Unexpected showcase artifact: {name}")
    page.route("**/outputs/**", artifact)
    try:
        page.goto(url + "/#/")
        expect(page.locator(".song[data-name]")).to_have_count(3)
        expect(page.locator("#go")).to_be_enabled()
        expect(page.locator("#instrumental-toggle")).to_be_visible()
        page.locator("#title").fill("A new musical direction")
        page.locator("#lyrics").fill("")
        page.locator("#instrumental-toggle").click()
        page.locator("#style").fill(entry["style"])
        page.locator("#style").dispatch_event("input")
        page.locator("#cot [data-v='full']").click()
        expect(page.locator("#cot [data-v='full']")).to_have_class("on")
        page.locator("#title").focus()
        page.mouse.move(1500, 1200)
        page.locator(".create").evaluate("panel => panel.scrollTop = 0")
        page.screenshot(path=str(destination / "create.png"), animations="disabled")
        page.locator("#nav-vibe").click()
        page.locator("#vibe-file").set_input_files([{"name": name + ".png", "mimeType": "image/png", "buffer": image}
            for name, image in zip(("Afterglow", "Velvet horizon", "Morning light"), paintings)])
        page.locator("#vibe-analyze").click()
        expect(page.locator("#vibe-style")).to_have_value(entry["style"])
        page.locator("#vibe").evaluate("panel => panel.scrollTop = 0")
        page.screenshot(path=str(destination / "vibe.png"), animations="disabled")
        page.evaluate("Lux.open('showcase-0')")
        expect(page.locator("#lux")).to_be_visible()
        expect(page.locator(".sidebar nav a.active")).to_have_count(1)
        expect(page.locator(".lx-track")).to_have_count(4)
        expect(page.locator(".lx-foot")).not_to_contain_text("loading audio")
        page.screenshot(path=str(destination / "studio.png"), animations="disabled")
        page.locator("#nav-settings").click()
        expect(page.locator("#vibe-model-card")).to_be_visible()
        expect(page.locator("#model-yue2-3b")).to_be_visible()
        expect(page.locator(".sidebar nav a.active")).to_have_count(1)
        page.screenshot(path=str(destination / "settings.png"), animations="disabled")
        assert not errors, errors
    finally:
        context.close()
