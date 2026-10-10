"""Check the native probe's real WAV request without loading model weights."""

import base64
import io
import tempfile
import unittest
import wave
from pathlib import Path
from unittest.mock import patch

from studio.models import ModelManager
from studio.providers import AudioCppProvider
from tests.test_models import tiny_audio


class NativeProbeTests(unittest.TestCase):
    def test_separator_probes_use_each_models_required_audio_format(self):
        with tempfile.TemporaryDirectory() as root:
            manager = ModelManager(Path(root) / "state", Path(root) / "models")
            provider = AudioCppProvider(Path(root) / "runtime")
            for model_id, rate in {"htdemucs": 44100, "htdemucs-6stems": 44100,
                                   "bs-roformer": 44100, "sam-audio": 48000}.items():
                with self.subTest(model=model_id):
                    profile = manager.profile(model_id)
                    def run(selected, request, cancel):
                        self.assertEqual(selected["id"], profile["id"])
                        with wave.open(io.BytesIO(base64.b64decode(request["audio_base64"]))) as audio:
                            self.assertEqual(audio.getframerate(), rate)
                            self.assertEqual(audio.getnchannels(), 2)
                            self.assertEqual(audio.getsampwidth(), 2)
                            self.assertEqual(audio.getnframes(), rate)
                        if model_id == "sam-audio":
                            self.assertEqual(request["text"], "voice")
                            self.assertEqual(set(request), {"audio_base64", "text", "seed"})
                        else:
                            self.assertEqual(set(request), {"audio_base64"})
                        return {"named_audio_outputs": [{"id": "test", "audio": tiny_audio()}]}
                    with patch.object(provider, "run", side_effect=run):
                        self.assertEqual(provider.probe(profile)["smoke_test"], "audio")
            self.assertFalse((Path(root) / "models").exists())

    def test_missing_separator_audio_format_fails_before_inference(self):
        provider = AudioCppProvider()
        with patch.object(provider, "run") as run:
            with self.assertRaisesRegex(ValueError, "input audio format"):
                provider.probe({"task": "sep", "family": "unconfigured"})
            run.assert_not_called()
