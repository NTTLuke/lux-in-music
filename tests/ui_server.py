"""Isolated browser fixture: tiny files and a fake provider, never real weights."""

import argparse
import time
import copy

from tests.test_models import ModelFixtures


def main():
    parser = argparse.ArgumentParser(); parser.add_argument("--port", type=int, required=True)
    args = parser.parse_args()
    fixture = ModelFixtures(); fixture.setUp()
    external = copy.deepcopy(fixture.catalog[0])
    external.update(id="test-external", name="Test external", delivery="external", precisions={}, vaes={}, required=[], default_precision=None, default_vae=None)
    fixture.manager.catalog[external["id"]] = external
    original_probe = fixture.provider.probe
    def probe(profile, cancel=None):
        time.sleep(0.3)
        return original_probe(profile, cancel)
    fixture.provider.probe = probe
    from studio.app import app
    import uvicorn
    try:
        uvicorn.run(app, host="127.0.0.1", port=args.port, log_level="warning")
    finally:
        fixture.doCleanups()


if __name__ == "__main__": main()
