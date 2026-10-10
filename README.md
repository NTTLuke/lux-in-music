# Lux In Music: local POC

Local generative music software using models compatible with audio.cpp. The current prototype uses
[YuE2-3B GGUF](https://huggingface.co/audio-cpp/Yue2-3B-GGUF) through
[audio.cpp](https://github.com/0xShug0/audio.cpp) (Metal on Apple Silicon).

Model licenses are shown in Settings before any download. YuE2 weights and VAE
are published under **CC BY-NC 4.0**. Optional separation models have their own
terms; they are never installed automatically.
The upstream project also grants additional permission for individual creators
to monetize outputs. Company use of the weights has separate commercial terms;
see [the license review and official links](docs/model-licenses.md).

## Contributing and project direction

Start with [CONTRIBUTING.md](CONTRIBUTING.md) and [AGENTS.md](AGENTS.md). Any coding
CLI can use the shared instructions and run `python3 scripts/check.py`. See
[the harness guide](docs/harness.md) for application checks and CLI compatibility.

The [architecture contract](docs/architecture.md) explains provider/model adapters,
Settings, independent precision choices, and profile records. Track acceptance
scenarios in [harness/requirements.json](harness/requirements.json). Natural song
ending work (#1) now plans and checks EOS near the target before rendering, with
a real audio test and user listening acceptance. Clip mode can still cut off a song.

## Architecture

```
browser ──► studio (FastAPI :8000) ──► provider + model adapter ──► selected runtime
              │  Settings, queue, library                         lazy start
              └► outputs/<name>.wav | .json (profile + params) | model artifacts
```

* `vendor/audio.cpp/`: pinned inference engine, built for the catalog's local families
* `config/model-catalog.json`: pinned downloads, file sizes/checksums and component licenses
* `models/<model>/releases/<revision>/`: verified local artifacts; older downloads are reused
* `.lux/settings.json`: selected profiles, license reviews and verification records
* `.lux/runtime/`: generated runtime configs/logs; generation and separation use dynamic ports
* `studio/providers.py` + `studio/adapters/`: runtime lifecycle and model-specific behavior
* `studio/params.py` + `studio/engine.py`: shared inputs, WAV storage and profile metadata
* `studio/app.py` + `studio/static/index.html`: web studio
* `studio/cli.py`: generate one song from the terminal

## Run

```bash
./studio.sh       # install missing software, start the UI, open Settings if no model is ready
```

The terminal shows four startup stages: prerequisites, Python/dependencies,
native runtime download/build, and UI startup. First-run software setup needs
network access, `curl`, `git`, and a C++ compiler. On macOS, install Apple's
Command Line Tools if requested (`xcode-select --install`). uv is installed
locally when missing; Python 3.12 and CMake are prepared when needed. Linux uses
the CPU build. Later runs reuse installed dependencies and a compatible build.
Source submodules are fetched over HTTPS; public source setup needs no GitHub
SSH key. If setup stops, rerun the same command to continue.

No model weights are downloaded during startup. The UI opens at
http://127.0.0.1:8000. Ctrl+C stops the UI and its owned inference processes.
Or double-click **`Lux In Music.command`** in Finder. Use `NO_OPEN=1 ./studio.sh`
to skip the browser, or `./studio.sh --port 8001` to change the UI port.
`scripts/setup.sh` runs software setup alone. `scripts/run_studio.sh` starts an
already prepared UI; `scripts/run_engine.sh` serves the verified selected profile.

### Settings: choose and install models

1. Choose a generation model. YuE2 main choices are Q8_0, BF16 and Q4_0; choose
   the VAE separately (F16 by default, or F32). BF16 is different from FP16.
2. Review the component licenses and acknowledge the exact release. Unknown
   licenses block setup. Displayed file sizes exclude extra runtime memory.
3. Use the model's setup button to download missing files or verify existing ones.
   Progress appears in that card during transfer, checks and a short runtime test.
4. Open Create after activation. Only supported model controls are shown.

Verified profiles and license reviews persist across restarts. Returning to a
verified precision/VAE combination shows its saved status; switching to it uses
its existing validation. Changed files, releases or runtime binaries require
verification again. Active verified models show a disabled **Active · Verified**
button, including optional separators. **Maintenance → Repair / recheck files**
runs full checks when needed. Completed setup attempts do not accumulate above
the cards.

Downloads can be cancelled and retried; partial files resume when the server
supports ranges. Invalid files or a failed runtime test preserve the previous
selection. Existing downloads in the old model folder are verified and reused.
Optional separation models are installed and selected independently in Settings.
Saved songs remain playable without any active model. Editing needs their original
compatible generation/separation profiles. Changing Settings affects new jobs;
queued jobs retain their recorded selection.

The provider boundary also supports providers without local weights, precision
or a VAE. No MiniMax integration is included yet. For development, `LUX_STATE_DIR`,
`LUX_MODELS_DIR`, `STUDIO_OUTPUT_DIR`, `AUDIOCPP_BINARY` and `LUX_BACKEND` override
the corresponding local paths/runtime. Changing a runtime requires a new probe.

### Studio UI

* Create panel: title, lyrics with section-tag buttons, style with genre/mood/instrument/vocal/mix chips,
  length slider, planning mode, random/fixed seed, 1-4 variations, advanced sampling sliders, ABC input
* Genre templates: Progressive Metal, Indie Pop, Cinematic Synthwave, Soul & R&B,
  and Jazz Fusion. Apply a style while keeping your lyrics, title and settings;
  applying a template starts no generation. The Melodic Techno demo remains above them.
* Library: generative cover art, waveform per song, live queue with progress/ETA, search
* Player bar: waveform scrubbing, prev/next, volume, download. Keys: Space play/pause, arrow keys seek 5 s
* Song panel: lyrics, all generation params, generated ABC score, reuse settings
* Untitled songs get an automatic title from the chorus hook

### Studio Mode: stem separation

Library row or song panel, then **Open in Studio Mode**: it asks what to separate, runs it on the engine,
then opens a multitrack mixer.

| Mode | Model (audio.cpp family) | Stems | License | Measured, 30 s song |
|---|---|---|---|---|
| Vocals & Instrumental | BS-RoFormer ep368 (`bs_roformer`) | vocals, instrumental | Publisher declares Apache-2.0; original checkpoint source undocumented | 33 s |
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
uv run studio-gen --lyrics-file song.txt --style "English, synthwave, male vocal" --seed 42 --target-duration 240
```

## Parameters (v0.1)

The API accepts common song fields plus a `model_options` object validated by
the selected adapter. Legacy flat YuE2 options still work. The table below applies
to the YuE2 adapter; these options are not required by other providers.

| UI / API field | YuE2 option | Default | Notes |
|---|---|---|---|
| lyrics | `lyrics` | (required) | `[Verse]`, `[Chorus]`, `[Bridge]`… tags |
| style | `style` | (required) | language, genre, instruments, vocal, mix |
| cot | `cot` | `off` here (engine default is `full`) | `off` direct; `melody` / `full` plan an ABC score first |
| seed | `seed` | 1234 | same params + seed gives the same song |
| max_duration_s | `semantic_max_tokens` = s × 25 | ≈ 360 s | upper bound. The model may stop earlier |
| target_duration_s | staged adapter planning | none in CLI; 180 s in UI | complete arrangement target, 30–330 s; separate finishing allowance and EOS check |
| num_inference_steps | `num_inference_steps` | 8 | NAR ODE steps |
| guidance_scale | `guidance_scale` | 1.01 (off) / 1.0 | |
| temperature / top-p / top-k / rep. penalty | `semantic_*` | 1.0 / 0.95 / 100 / 1.2 | |
| abc | `abc` | (none) | condition on your own ABC score (needs cot=melody/full) |

Use **Complete arrangement** to plan the full composition before rendering.
**Clip / hard limit** (CLI `--max-duration`) can deliberately cut a song mid-phrase.
The demo now targets four minutes; overlong vocal material is rejected with
shortening/length advice. See [duration and ending behavior](docs/song-endings.md)
for retries, retained artifacts, model limits and listening acceptance.

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
