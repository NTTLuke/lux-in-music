# Duration and song endings (#1)

## What caused the reported cutoffs

The old length slider became `semantic_max_tokens = seconds * 25`. This is a
hard stop in audio.cpp, not a duration instruction for the composer. The score
planner received lyrics and style without a time budget.

Three saved Lux In Tenebris plans show the mismatch:

| Original output | Planned bars | Tempo | Nominal score length | Actual audio |
| --- | ---: | ---: | ---: | ---: |
| `20261010-084758` | 166 | 125 BPM | 318.72 s | 180 s |
| `20261010-184549` | 171 | 122 BPM | 336.39 s | 180 s |
| `20261010-190644` | 148 | 124 BPM | 286.45 s | 120 s |

All three audio runs hit their semantic cap. The later two retain explicit
`truncated=true` artifact metadata; the first was recorded in the runtime log.
Having `[Outro]` in the lyrics did not make a 5-minute composition fit in 3 minutes.

## Current behavior

Clicking **Create** starts one job. Its progress shows the model analyzing the
lyrics, style and tempo, preparing the arrangement, composing and checking the
ending, then rendering audio. The Create panel explains that planning uses extra
model processing time. There is no separate analysis button or duration control
in the UI, CLI or generation API.

The Create form still exposes the selected model's supported Planning modes.
Automatic length analysis does not hide those controls or overwrite the user's
selection.

- YuE2 plans a score before audio, estimates its length from meter, bars and
  tempo, and uses that estimate as Lux's internal target. An unambiguous BPM in
  the style is applied before fitting. The score is adapted to the inferred
  length, not to a duration entered by the user.
- The adapter requests only the score, checks its bar durations, meter and tempo,
  and fits generated arrangements by shortening instrumental passages. It keeps
  all vocal bars, adjacent breathing rests, tempo, first two bars and final four
  bars. If the style gives one unambiguous BPM target, generated scores are
  retimed to that requested tempo before fitting; supplied scores stay unchanged.
  It removes complete instrumental phrases without severing boundary ties.
- Scores use the native two-voice format and groups of up to four measures.
  Unsupported notation, changed meter/key fields and malformed bars are rejected
  rather than assigned guessed durations. Supplied scores are inspected and
  retained exactly; the user must edit an overlong supplied score.
- If a generated plan cannot fit safely, try up to three planner seeds
  (`requested seed`, `seed+1`, `seed+2`, modulo 2^63). When the shortest complete
  plan exceeds the model limit, Lux stops before audio rendering and suggests
  shortening a verse, removing a repeated section or requesting a more compact
  arrangement. Lyrics are never deleted to force a fit.
- The hard audio limit defaults to target plus the larger of 15 seconds or
  12.5%, capped at 360 seconds. Targets are 30–330 seconds. These are application
  limits and finishing allowance, not a universal minimum for music or a promise
  of sample-exact duration. These values are selected internally and recorded
  with the generated song.
- Compose semantic tokens before acoustic rendering. Require observed EOS and
  duration within the larger of 15 seconds or 12.5% of the target. Planning only
  shortens instrumental sections. If the model finishes a little earlier than
  the estimate, it is labelled **Shorter than target** and explained in the song
  message. An ending far before the plan is rejected because sections may have
  been dropped. Try at most two semantic seeds (`seed`, `seed+1`). If both fail,
  save a failure report with every plan/token attempt and no playable song.
- Render the accepted full token stream using `semantic_prefix` and equal token
  bounds. That render reports a full window by construction; its metadata is
  stored separately from the composing stage's EOS evidence.
- Existing hard-cap results retain their **Unfinished · limit reached** label.
  New EOS results say **Model ended** and ask the listener to check the musical
  ending. EOS alone is not listening verification.
- Job progress names planning, composing/ending checks and rendering. Songs keep
  the original and fitted scores, all attempts, effective seeds, profile and
  truncation flags. Failed attempts use `.failure-report`, outside the library.
  Existing verified profiles get current capability declarations without another
  model download or compatibility probe; saved job/song snapshots stay intact.

## Practical lyric advice

Use clear section tags and include a final section with the intended last phrase.
If Lux reports that the complete vocal plan exceeds the model limit, remove an
extra repeated chorus or shorten a verse. More words generally need more vocal
time, but language, tempo, delivery, breathing and melody matter. The actual
score check decides how much time this arrangement needs.

For the first saved demo score, preserving vocal passages, breathing and final
bars needs about 217 seconds at 125 BPM. Its 180-second cap was unsuitable.
The demo no longer requests a fixed length; Lux infers an internal target for
each song. Other seeds can need different durations; refusal/retry is deliberate
when fitting would remove vocal material.

## Verification and acceptance

Offline tests cover implicit analysis and fitting in one generation call, the
single-job API, rejection of manual duration fields, and shared arrangement reuse
for variations. They also cover timing (including compressed rests and different units),
phrase-safe shortening, vocal/final-bar preservation, invalid/truncated plans,
bounded retries, early/capped semantics, forced rendering versus actual EOS,
storage, capability refresh and token recovery with the checked score/retry seed.
The browser check verifies there is no duration field or pre-check button, and
that one Generate request includes no duration controls, using a fake provider.

Real tests use existing Q8_0 main / F16 VAE weights, Metal, audio.cpp revision
`6c3ab9ad4e599a44d287697863b4f8846ef658be`, YuE2 GGUF release
`cca74d8980c00f30ab8d52248a367c01ad633ec2`. No weights were downloaded or
active Settings changed. The saved 318.72-second score was fitted to 240 seconds
by removing 41 instrumental bars. Semantic trials emitted EOS after 5,938 and
5,948 frames (237.52 and 237.92 seconds), seeds 454234436 and 454234437.

An earlier one-bar-per-group rewrite hit a 270-second cap. Keeping native groups
of up to four bars succeeded in the later trials. This is observed behavior on
these runs, not proof that every score, style or seed will follow its nominal
duration. Adding a textual 180-second instruction to the style also produced
overlong/malformed plans in two exploratory trials; that alone is not the fix.

The full app-path WAV test and listening acceptance are recorded in
`docs/progress.md`. After receiving the test WAV link, the user accepted it on
2026-10-10 with "è perfetta !! bravo". This human feedback completes listening
acceptance for the example; the agent did not listen or conduct a lyric audit.
PR #7 is merged and #1 is closed. New songs still require
their own listening check: a valid WAV and EOS alone do not prove a musically
satisfactory ending across other lyrics, styles or seeds.

## Official sources reviewed (2026-10-10)

- [YuE2 generation guide](https://github.com/multimodal-art-projection/YuE/blob/main/docs/generation.md): staged planning, exact score reuse, truncation checks.
- [YuE2 ABC reference](https://github.com/multimodal-art-projection/YuE/blob/main/skills/yue2-music/references/abc-editing.md): native voices/groups, note/rest timing, invariants and separate audio checks.
- [Pinned audio.cpp YuE2 guide](https://github.com/0xShug0/audio.cpp/blob/6c3ab9ad4e599a44d287697863b4f8846ef658be/docs/models/yue2.md): 25 fps, truncation, `stop_after`, prefix continuation and exact-stream rendering.
- [Official sampling code](https://github.com/multimodal-art-projection/YuE/blob/main/src/yue2/sampling.py) and [request protocol](https://github.com/multimodal-art-projection/YuE/blob/main/src/yue2/protocol.py): explicit music end token and sampling bounds. Inspection found no established EOS-masking bug in the pinned native path.
