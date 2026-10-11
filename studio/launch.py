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
    parser.add_argument("--host", default="127.0.0.1", help="address to listen on; 0.0.0.0 means every network")
    args = parser.parse_args()
    import uvicorn
    shown = "127.0.0.1" if args.host == "0.0.0.0" else f"[{args.host}]" if ":" in args.host else args.host
    url = f"http://{shown}:{args.port}"
    print(f"\n[4/4] Starting Lux In Music at {url} (Ctrl+C to quit)…", flush=True)
    if args.host not in ("127.0.0.1", "localhost", "::1"):
        print(f"WARNING: listening on {args.host}. The studio has no login: anyone who can reach this "
              "address can generate, remove jobs, download songs and start model downloads.", flush=True)
    stop = threading.Event()
    if not args.no_open:
        threading.Thread(target=open_when_ready, args=(url, stop), daemon=True).start()
    try:
        uvicorn.run("studio.app:app", host=args.host, port=args.port, log_level="warning")
    finally:
        stop.set()


if __name__ == "__main__":
    main()
