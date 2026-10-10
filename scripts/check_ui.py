"""Browser acceptance test using an isolated app and fake model downloads.

Requires Playwright and an installed Chrome. No model or browser download occurs.
"""

import argparse
import json
import os
import shutil
import socket
import subprocess
import tempfile
import time
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--artifacts", type=Path, default=ROOT / "outputs/checks/ui")
    args = parser.parse_args(); args.artifacts.mkdir(parents=True, exist_ok=True)
    from playwright.sync_api import sync_playwright, expect
    chrome = os.environ.get("LUX_TEST_BROWSER") or shutil.which("google-chrome") or "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"
    if not Path(chrome).is_file(): raise SystemExit("Install Chrome or set LUX_TEST_BROWSER to its executable")
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0)); port = sock.getsockname()[1]
    url = f"http://127.0.0.1:{port}"
    with tempfile.TemporaryDirectory(prefix="lux-browser-") as temp:
        with (Path(temp) / "server.log").open("w+") as log:
            server = subprocess.Popen([str(ROOT / ".venv/bin/python"), "-m", "tests.ui_server", "--port", str(port)], cwd=ROOT,
                                      stdout=log, stderr=subprocess.STDOUT)
            try:
                for _ in range(100):
                    try:
                        urllib.request.urlopen(url + "/api/settings/status", timeout=1).close(); break
                    except OSError:
                        if server.poll() is not None:
                            log.seek(0); raise RuntimeError(log.read())
                        time.sleep(0.1)
                else: raise RuntimeError("Fixture server did not start")
                with sync_playwright() as playwright:
                    browser = playwright.chromium.launch(executable_path=chrome, headless=True)
                    page = browser.new_page(viewport={"width": 1440, "height": 1000})
                    errors = []; page.on("pageerror", lambda error: errors.append(str(error)))
                    page.route("https://**/*", lambda route: route.abort())  # external fonts are optional
                    page.goto(url); page.wait_for_url("**/#/settings")
                    expect(page.locator("#vae-test-model")).to_have_value("f16")
                    expect(page.locator("#setup-test-model")).to_be_disabled()
                    expect(page.locator(".model-licenses").first).to_contain_text("MIT")
                    expect(page.locator(".model-licenses").first).to_contain_text("monetize outputs")
                    expect(page.locator(".model-licenses").first).to_contain_text("company use")
                    assert page.locator("#model-progress").count() == 0
                    assert page.locator("#precision-test-external").count() == 0
                    assert page.locator("#vae-test-external").count() == 0
                    page.locator("#precision-test-model").select_option("bf16")
                    page.locator("#vae-test-model").select_option("f32")
                    expect(page.locator("#setup-test-model")).to_be_disabled()
                    page.locator("#license-test-model").check()
                    page.locator("#setup-test-model").click()
                    expect(page.locator("#model-test-model progress")).to_be_visible()
                    expect(page.locator("#settings-message")).to_contain_text("Active: Test model · BF16 · VAE F32", timeout=15000)
                    expect(page.locator("#setup-test-model")).to_have_text("Active · Verified")
                    expect(page.locator("#setup-test-model")).to_be_disabled()
                    page.reload()
                    expect(page.locator("#precision-test-model")).to_have_value("bf16")
                    expect(page.locator("#vae-test-model")).to_have_value("f32")
                    expect(page.locator("#license-test-model")).to_be_checked()
                    expect(page.locator("#setup-test-model")).to_have_text("Active · Verified")
                    page.locator("#precision-test-model").select_option("q8_0")
                    expect(page.locator("#license-test-model")).to_be_checked()
                    expect(page.locator("#setup-test-model")).to_have_text("Download and activate")
                    page.locator("#precision-test-model").select_option("bf16")
                    expect(page.locator(".model-verification").first).to_contain_text("Verified")
                    expect(page.locator("#setup-test-model")).to_have_text("Active · Verified")
                    expect(page.locator("#progress-test-model")).to_be_hidden()
                    page.locator("#license-test-separator").check()
                    page.locator("#setup-test-separator").click()
                    expect(page.locator("#model-test-separator progress")).to_be_visible()
                    expect(page.locator("#setup-test-separator")).to_have_text("Active · Verified", timeout=15000)
                    expect(page.locator("#setup-test-separator")).to_be_disabled()
                    expect(page.locator("#progress-test-separator")).to_be_hidden()
                    expect(page.locator("#repair-test-separator")).to_be_hidden()
                    page.locator("#precision-test-separator").select_option("bf16")
                    page.locator("#setup-test-separator").click()
                    expect(page.locator("#progress-test-separator")).to_contain_text("Test device does not support this precision", timeout=15000)
                    expect(page.locator("#progress-test-model")).to_be_hidden()
                    page.locator("#precision-test-separator").select_option("q8_0")
                    expect(page.locator("#setup-test-separator")).to_be_disabled()
                    page.locator("#model-test-separator summary").click()
                    page.locator("#repair-test-separator").click()
                    expect(page.locator("#model-test-separator progress")).to_be_visible()
                    expect(page.locator("#setup-test-separator")).to_have_text("Active · Verified", timeout=15000)
                    expect(page.locator("#progress-test-separator")).to_be_hidden()
                    assert page.locator(".model-job").count() == 0
                    page.screenshot(path=str(args.artifacts / "settings-desktop.png"))
                    page.locator("#nav-create").click()
                    expect(page.locator("#go")).to_be_enabled()
                    expect(page.locator("#cot")).to_be_hidden()  # the fake provider offers no planning
                    expect(page.locator("#abc")).to_be_hidden()
                    expect(page.locator("#demo-row [data-demo='lux-tenebris']")).to_have_count(1)
                    expect(page.locator(".template-btn")).to_have_count(5)
                    page.locator("#genre-templates summary").click()
                    page.locator("#title").fill("My working title")
                    page.locator("#lyrics").fill("[Verse]\nKeep my own words\n[Outro]\nWe are home")
                    before_template = page.evaluate("({title: $('title').value, lyrics: $('lyrics').value, length: $('len').value, seed: $('seed').value, cot: state.cot})")
                    generation_posts = []
                    page.on("request", lambda request: generation_posts.append(request.url) if request.method == "POST" and request.url.endswith("/api/generate") else None)
                    for template in ["progressive-metal", "indie-pop", "cinematic-synthwave", "soul-rnb", "jazz-fusion"]:
                        page.locator(f"[data-template='{template}']").click()
                        expect(page.locator(f"[data-template='{template}']")).to_have_attribute("aria-pressed", "true")
                        assert page.evaluate("({title: $('title').value, lyrics: $('lyrics').value, length: $('len').value, seed: $('seed').value, cot: state.cot})") == before_template
                    assert not generation_posts, generation_posts
                    page.locator("[data-template='progressive-metal']").click()
                    assert "progressive metal" in page.locator("#style").input_value()
                    expect(page.locator("#template-status")).to_contain_text("Progressive Metal style applied")
                    page.locator("#style").fill("My custom sound")
                    expect(page.locator("[data-template='progressive-metal']")).to_have_attribute("aria-pressed", "false")
                    page.locator("[data-template='progressive-metal']").click()
                    assert page.locator(".create").bounding_box()["width"] == 520
                    page.locator(".create").evaluate("panel => panel.scrollTop = 0")
                    page.screenshot(path=str(args.artifacts / "templates-desktop.png"))
                    for width in [1280, 1024, 900, 390]:
                        page.set_viewport_size({"width": width, "height": 844})
                        assert page.evaluate("document.documentElement.scrollWidth <= innerWidth"), f"Overflow at {width}px"
                    page.locator("#genre-templates").scroll_into_view_if_needed()
                    expect(page.locator("[data-template='progressive-metal']")).to_be_visible()
                    page.screenshot(path=str(args.artifacts / "templates-mobile.png"))
                    page.set_viewport_size({"width": 1440, "height": 1000})
                    page.locator("#go").click()
                    expect(page.locator(".song")).to_have_count(2, timeout=15000)
                    def stem_set(route):
                        route.fulfill(json=[{"id": "vocals", "mode": "vocals", "mode_label": "Vocals / Instrumental",
                            "prompt": None, "elapsed_s": 0.1, "stems": [{"id": name, "label": name,
                                "file": f"ui-stems/{name}.wav", "peaks": [0.1] * 16, "rms_db": -20, "silent": False}
                                for name in ("vocals", "instrumental")]}])
                    page.route("**/api/lux/*", stem_set)
                    page.route("**/api/beats/*", lambda route: route.fulfill(json={"bpm": 120, "offset_s": 0, "beat_s": 0.5, "beats_per_bar": 4}))
                    page.evaluate("Lux.open('legacy-song')")
                    expect(page.locator(".lx-track")).to_have_count(2)
                    expect(page.locator(".lx-edit-btn")).to_have_count(0)
                    song = page.evaluate("state.library.find((song) => song.name !== 'legacy-song').name")
                    page.evaluate("name => Lux.open(name)", song)
                    expect(page.locator(".lx-track")).to_have_count(2)
                    expect(page.locator(".lx-edit-btn")).to_have_count(2)
                    page.locator(".lx-edit-btn").first.click()
                    expect(page.locator("#lx-editbar")).to_contain_text("Editing vocals")
                    # Offer duration planning through a capability response. The
                    # isolated provider still produces only fixture audio.
                    def duration_capability(route):
                        data = route.fetch().json()
                        data["active"]["capabilities"].update(target_duration_s=330, min_target_duration_s=30,
                            max_duration_s=360, planning=["off", "melody", "full"])
                        route.fulfill(json=data)
                    page.route("**/api/settings/status", duration_capability)
                    page.locator("#nav-create").click()
                    page.evaluate("Settings.refresh(true)")
                    expect(page.locator("#duration-mode")).to_be_visible()
                    page.locator("#duration-mode").select_option("target")
                    page.locator("#len").fill("30")
                    page.locator("#lyrics").fill("[Verse]\n" + "light " * 100)
                    expect(page.locator("#lyrics-advice")).to_contain_text("Dense lyrics")
                    expect(page.locator("#lyrics-advice")).to_contain_text("Add [Outro]")
                    expect(page.locator("#cot [data-v='full']")).to_have_class("on")
                    page.locator("#cot [data-v='off']").click()
                    expect(page.locator("#duration-mode")).to_have_value("cap")
                    expect(page.locator("#duration-hint")).to_contain_text("cut a song")
                    page.locator("#duration-mode").select_option("target")
                    page.locator("#len").fill("240")
                    with page.expect_request("**/api/generate") as generation_request:
                        page.locator("#go").click()
                    body = generation_request.value.post_data_json
                    assert body["target_duration_s"] == 240 and "max_duration_s" not in body, body
                    assert body["model_options"]["cot"] == "full", body
                    page.evaluate("state.library[0].generation = {status:'truncated', message:'Stopped at the hard limit. The song may be unfinished.'}; render()")
                    expect(page.locator(".badge").filter(has_text="Unfinished · limit reached")).to_be_visible()
                    page.screenshot(path=str(args.artifacts / "duration-desktop.png"))
                    page.unroute("**/api/settings/status", duration_capability)
                    page.locator("#nav-settings").click(); page.set_viewport_size({"width": 390, "height": 844})
                    expect(page.locator(".mobile-nav")).to_be_visible()
                    page.locator(".mobile-nav a[href='#/']").click()
                    expect(page.locator(".workspace")).to_be_visible()
                    page.locator(".mobile-nav a[href='#/settings']").click()
                    expect(page.locator("#settings")).to_be_visible()
                    page.screenshot(path=str(args.artifacts / "settings-mobile.png"))
                    page.locator("#license-test-external").check()
                    page.locator("#setup-test-external").click()
                    expect(page.locator("#settings-message")).to_contain_text("Active: Test external", timeout=15000)
                    def unresolved_license(route):
                        data = route.fetch().json()
                        data["models"][0]["licenses"][0]["verified"] = False
                        route.fulfill(json=data)
                    page.route("**/api/settings/catalog", unresolved_license)
                    page.reload()
                    expect(page.locator("#license-test-model")).to_be_disabled()
                    expect(page.locator("#setup-test-model")).to_be_disabled()
                    assert not errors, errors
                    browser.close()
                print(json.dumps({"settings_first": True, "license_gate": True, "independent_precision": True,
                                  "fake_download_and_activation": True, "capability_controls": True,
                                  "generation_and_library": True, "five_style_templates_without_generation": True, "templates_preserve_song_inputs": True, "wider_create_and_responsive_layout": True, "duration_target_and_cap": True, "lyric_advice_and_truncation_badge": True, "mobile_navigation": True, "external_without_weights": True, "verification_survives_reload_and_dropdown": True, "separator_disabled_when_active": True, "card_progress_and_errors_only": True, "creator_terms_visible": True, "mixer_editable_and_legacy_songs": True, "unresolved_license_blocked": True, "javascript_errors": errors}))
            finally:
                server.terminate()
                try: server.wait(timeout=10)
                except subprocess.TimeoutExpired: server.kill(); server.wait()


if __name__ == "__main__": main()
