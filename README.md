# Lux In Music: local POC

Local generative music software using models compatible with audio.cpp. The current prototype uses
[YuE2-3B GGUF](https://huggingface.co/audio-cpp/Yue2-3B-GGUF) through
[audio.cpp](https://github.com/0xShug0/audio.cpp) (Metal on Apple Silicon).

> Model license: **CC BY-NC 4.0**, so non-commercial use only.

## Contributing and project direction

Start with [CONTRIBUTING.md](CONTRIBUTING.md) and [AGENTS.md](AGENTS.md). Any coding
CLI can use the shared instructions and run `python3 scripts/check.py`. See
[the harness guide](docs/harness.md) for application checks and CLI compatibility.

The [architecture contract](docs/architecture.md) defines the migration toward
model-independent adapters and Settings: a fresh install will start without
weights, show model/component licenses before download, and let the user choose
main-model and VAE precision independently. These features are **planned**;
the current launch/setup behavior is documented below. Track their acceptance
scenarios in [harness/requirements.json](harness/requirements.json).

## Architecture

```
browser ──► studio (FastAPI :8000) ──► audiocpp_server (:8089, Metal) ──► YuE2 Q8 + VAE F16
              │  job queue, library        POST /v1/tasks/run
              └► outputs/<name>.wav | .json (params) | .abc (score, cot=melody/full)
```

* `vendor/audio.cpp/`: the inference engine, built from source with only the `yue2` family
* `models/Yue2-3B-GGUF/`: `yue2-3b-q8_0.gguf`, `yue2-vae-f16.gguf` and `sidecars/`
* `config/audiocpp-server.json`: engine config. Paths are relative to this file
* `studio/params.py`: typed YuE2 parameters, mirroring `vendor/audio.cpp/docs/models/yue2.md`
* `studio/engine.py`: client for the engine. Saves the WAV, metadata and artifacts
* `studio/app.py` + `studio/static/index.html`: web studio
* `studio/cli.py`: generate one song from the terminal

## Run

```bash
scripts/setup.sh   # one time: build engine, download ~4.5 GB weights, uv sync
./studio.sh        # starts engine + studio, opens http://127.0.0.1:8000 (Ctrl+C stops both)
```

Or double-click **`Lux In Music.command`** in Finder.
`scripts/run_engine.sh` / `scripts/run_studio.sh` still start each piece on its own.

### Studio UI

* Create panel: title, lyrics with section-tag buttons, style with genre/mood/instrument/vocal/mix chips,
  length slider, planning mode, random/fixed seed, 1-4 variations, advanced sampling sliders, ABC input
* Library: generative cover art, waveform per song, live queue with progress/ETA, search
* Player bar: waveform scrubbing, prev/next, volume, download. Keys: Space play/pause, arrow keys seek 5 s
* Song panel: lyrics, all generation params, generated ABC score, reuse settings
* Untitled songs get an automatic title from the chorus hook

### Studio Mode: stem separation

Library row or song panel, then **Open in Studio Mode**: it asks what to separate, runs it on the engine,
then opens a multitrack mixer.

| Mode | Model (audio.cpp family) | Stems | License | Measured, 30 s song |
|---|---|---|---|---|
| Vocals & Instrumental | BS-RoFormer ep368 (`bs_roformer`) | vocals, instrumental | Apache-2.0 | 33 s |
| 4 stems | HTDemucs (`htdemucs`) | vocals, drums, bass, other | MIT | 3.5 s |
| 6 stems | HTDemucs 6s (`htdemucs_6stems`) | + guitar, piano | MIT | 3.6 s |
| Anything | SAM Audio base (`sam_audio`) | your text prompt + everything else (mono 48 kHz) | Meta SAM License | 19 s |

Mixer: mute/solo/volume per stem, live meters, click-to-seek lanes, presets (Karaoke, A cappella,
No drums, Rhythm section, Only/Remove prompt), per-stem WAV download and **Export mix** (rendered in
the browser). Stems are stored in `outputs/stems/<song>/<mode>/` with a `stems.json`.

### Studio Mode: regenerate a piece of one stem

In the stem mixer press **Edit** on a track (only that track accepts a selection), drag across its lane,
then **Regenerate** (1-3 takes, lyrics optional). **Play selection** plays only that stem by default
(*Listen: Solo stem*) or the full mix. Only that stem changes inside the selection; every other stem stays
bit-identical. Each take is saved as a new tab of the stem set (`<mode>-take-<time>/`, with `base` and
`edit` in `stems.json`), so you can A/B the tabs and chain edits on a take.

How it works (`studio/separate.py` `replace_stem`, `studio/edit.py` `render_section`):
1. semantic tokens of the song (25/s): exported at generation time, or recovered by re-running the original
   request with `stop_after=semantic` (deterministic: re-render correlates 1.0000 with the original)
2. `semantic_prefix` = tokens before the selection, the model samples the selection with a new seed;
   tokens are spliced back (`new[:B] + old[B:]`) and the song is rendered once
3. the selection plus 3 s of context is separated with the same model as the stem set
4. only the chosen stem is crossfaded (0.2 s) into the selection

Measured: about 14 s per take with HTDemucs 6 stems. YuE2 writes the new part together with its own
backing, so a new vocal line usually fits the original band, but key or timing clashes are possible:
listen to each take.

### Look: after Lux In Tenebris

`studio/static/theme-lux.css` follows [luxintenebris.news](https://luxintenebris.news/): ink background, warm
newsprint text, amber lamplight as the only accent, ember used sparingly, thin rules and kickers. Covers are
generated as watercolour on aged parchment with a sepia-ink music staff (some "in tenebris", with a candle).
Fonts stay Inter.

CLI:

```bash
uv run studio-gen --lyrics-file song.txt --style "English, synthwave, male vocal" --seed 42 --max-duration 90
```

## Parameters (v0.1)

| UI / API field | YuE2 option | Default | Notes |
|---|---|---|---|
| lyrics | `lyrics` | (required) | `[Verse]`, `[Chorus]`, `[Bridge]`… tags |
| style | `style` | (required) | language, genre, instruments, vocal, mix |
| cot | `cot` | `off` here (engine default is `full`) | `off` direct; `melody` / `full` plan an ABC score first |
| seed | `seed` | 1234 | same params + seed gives the same song |
| max_duration_s | `semantic_max_tokens` = s × 25 | ≈ 360 s | upper bound. The model may stop earlier |
| num_inference_steps | `num_inference_steps` | 8 | NAR ODE steps |
| guidance_scale | `guidance_scale` | 1.01 (off) / 1.0 | |
| temperature / top-p / top-k / rep. penalty | `semantic_*` | 1.0 / 0.95 / 100 / 1.2 | |
| abc | `abc` | (none) | condition on your own ABC score (needs cot=melody/full) |

## Measured on M4 Max (Q8 + F16 VAE, Metal)

| Run | Audio | Wall time |
|---|---|---|
| cot=off, cold start (includes model load) | 30 s | 40 s |
| cot=full, warm | 30 s | 15 s |
| cot=off, warm, 60 s cap (model ended the song on its own) | 37.8 s | 16.5 s |

## Roadmap ideas (next steps)

1. Extend / continue a song (`semantic_prefix` + `export_semantic`)
2. Style change mid-song (splice semantic tokens, see `vendor/audio.cpp/examples/yue2_style_change`)
3. Cover / remix from an ABC melody (`cot=melody` + `abc`), and score editing in the UI
4. Batch variations (N seeds per prompt), likes, and persistent projects
5. LoRA styles (`yue2.ar_lora`, `yue2.nar_lora`)
6. Studio features: stems (source separation), waveform timeline, trim/fade, MP3 export
