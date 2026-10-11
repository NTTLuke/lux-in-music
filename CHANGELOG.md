# Changelog

All notable changes to Lux In Music are documented in this file, one
section per GitHub release, newest first.

Entries are written by `./release.sh` from the merged pull requests and the
commits on `main`. Each release also appears on the
[releases page](https://github.com/NTTLuke/lux-in-music/releases).

## [0.3.0] - 2026-10-11

### Added

- Review song duration before creating audio ([#20](https://github.com/NTTLuke/lux-in-music/pull/20))
- Set up models in parallel, add instrumental songs and song delete ([#17](https://github.com/NTTLuke/lux-in-music/pull/17))

### Documentation

- docs: Prepare the v0.3.0 installation guide

## [0.2.0] - 2026-10-11

### Added

- Add --host to choose the address the studio listens on ([#14](https://github.com/NTTLuke/lux-in-music/pull/14))
- Add FLAC and MP3 downloads for songs ([#12](https://github.com/NTTLuke/lux-in-music/pull/12))
- Add a way to stop a queued or running generation ([#11](https://github.com/NTTLuke/lux-in-music/pull/11))

### Fixed

- Keep the lock file in step with the released version ([#16](https://github.com/NTTLuke/lux-in-music/pull/16))
- Create the artifact ignore rule before the release guard ([#15](https://github.com/NTTLuke/lux-in-music/pull/15))
- Accept complete songs that are shorter than the target ([#13](https://github.com/NTTLuke/lux-in-music/pull/13))

## [0.1.0] - 2026-10-11

First published release of Lux In Music.

### Added

- Add a manual release build for versioned GitHub releases ([#10](https://github.com/NTTLuke/lux-in-music/pull/10))
- Widen Create and add five genre templates ([#8](https://github.com/NTTLuke/lux-in-music/pull/8))
- Add model Settings and first-run software setup without weights ([#6](https://github.com/NTTLuke/lux-in-music/pull/6))
- Use Lux In Music naming and add a portable contributor harness ([#5](https://github.com/NTTLuke/lux-in-music/pull/5))
- Add beat snapping, variation modes, and beat-grid API for stem edits

### Changed

- Studio UX: per-track Edit arming, solo/mix audition, and demo template
- Lux In Music: local music studio on YuE2 + audio.cpp

### Fixed

- Plan songs against the requested duration and check EOS before rendering ([#7](https://github.com/NTTLuke/lux-in-music/pull/7))

### Documentation

- Add a beginner installation guide and playable Complete Demo preview ([#9](https://github.com/NTTLuke/lux-in-music/pull/9))
