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
                    expect(page.locator("#download-test-model")).to_be_disabled()
                    expect(page.locator(".model-licenses").first).to_contain_text("MIT")
                    assert page.locator("#precision-test-external").count() == 0
                    assert page.locator("#vae-test-external").count() == 0
                    page.locator("#precision-test-model").select_option("bf16")
                    page.locator("#vae-test-model").select_option("f32")
                    expect(page.locator("#download-test-model")).to_be_disabled()
                    page.locator("#license-test-model").check()
                    page.locator("#download-test-model").click()
                    expect(page.locator("#settings-message")).to_contain_text("Active: Test model · BF16 · VAE F32", timeout=15000)
                    page.screenshot(path=str(args.artifacts / "settings-desktop.png"))
                    page.locator("#nav-create").click()
                    expect(page.locator("#go")).to_be_enabled()
                    expect(page.locator("#cot")).to_be_hidden()  # the fake provider offers no planning
                    expect(page.locator("#abc")).to_be_hidden()
                    page.locator("#go").click()
                    expect(page.locator(".song").first).to_be_visible(timeout=15000)
                    page.locator("#nav-settings").click(); page.set_viewport_size({"width": 390, "height": 844})
                    expect(page.locator(".mobile-nav")).to_be_visible()
                    page.locator(".mobile-nav a[href='#/']").click()
                    expect(page.locator(".workspace")).to_be_visible()
                    page.locator(".mobile-nav a[href='#/settings']").click()
                    expect(page.locator("#settings")).to_be_visible()
                    page.screenshot(path=str(args.artifacts / "settings-mobile.png"))
                    page.locator("#license-test-external").check()
                    page.locator("#download-test-external").click()
                    expect(page.locator("#settings-message")).to_contain_text("Active: Test external", timeout=15000)
                    def unresolved_license(route):
                        data = route.fetch().json()
                        data["models"][0]["licenses"][0]["verified"] = False
                        route.fulfill(json=data)
                    page.route("**/api/settings/catalog", unresolved_license)
                    page.reload()
                    expect(page.locator("#license-test-model")).to_be_disabled()
                    expect(page.locator("#download-test-model")).to_be_disabled()
                    assert not errors, errors
                    browser.close()
                print(json.dumps({"settings_first": True, "license_gate": True, "independent_precision": True,
                                  "fake_download_and_activation": True, "capability_controls": True,
                                  "generation_and_library": True, "mobile_navigation": True, "external_without_weights": True, "unresolved_license_blocked": True, "javascript_errors": errors}))
            finally:
                server.terminate()
                try: server.wait(timeout=10)
                except subprocess.TimeoutExpired: server.kill(); server.wait()


if __name__ == "__main__": main()
