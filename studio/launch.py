"""Start the UI first; inference processes are owned by the runtime adapters."""

import argparse
import threading
import time
import urllib.request
import webbrowser
import json


def open_when_ready(url, stop):
    deadline = time.monotonic() + 30
    while not stop.is_set() and time.monotonic() < deadline:
        try:
            with urllib.request.urlopen(url + "/api/settings/status", timeout=1) as response:
                status = json.load(response)
            destination = url + ("/#/settings" if status["setup_required"] else "/")
            print(f"Studio ready: {destination}", flush=True)
            webbrowser.open(destination)
            return
        except (OSError, ValueError):
            stop.wait(0.2)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--port", type=int, default=8000)
    parser.add_argument("--no-open", action="store_true")
    args = parser.parse_args()
    import uvicorn
    url = f"http://127.0.0.1:{args.port}"
    print(f"\n[4/4] Starting Lux In Music at {url} (Ctrl+C to quit)…", flush=True)
    stop = threading.Event()
    if not args.no_open:
        threading.Thread(target=open_when_ready, args=(url, stop), daemon=True).start()
    try:
        uvicorn.run("studio.app:app", host="127.0.0.1", port=args.port, log_level="warning")
    finally:
        stop.set()


if __name__ == "__main__":
    main()
