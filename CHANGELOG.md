# Changelog

All notable changes to vidpy are documented here. The format follows [Keep a Changelog](https://keepachangelog.com/) and the project uses [Semantic Versioning](https://semver.org/).

## [Unreleased]

## [0.1.0] - 2026-11-13

First public release.

### Added
- vidpy Studio: browser editor on localhost with a magnetic main track, unlimited overlay / text / audio lanes, trim, split, reorder, snapping, undo/redo, frame-accurate scrubbing and fast preview playback.
- 79 video effects: color correction, 3-way color balance, curves, LUTs, white balance, cinematic looks (teal & orange, VHS, noir, cyberpunk, film grain, bloom…), blur/sharpen/denoise, stylize, Ken Burns, stabilize, lens correction, optical-flow slow motion and a custom FFmpeg node.
- 41 audio effects: EBU R128 loudness, voice enhance, noise reduction, de-esser, compressor, limiter, 10-band EQ, pitch shift, voice changers, reverb, echo, 8D audio.
- 58 transitions (FFmpeg xfade) with audio crossfades.
- Animated titles (fade, slide, zoom-pop, typewriter) and `.srt` subtitle burn-in.
- Picture-in-picture, logos, green-screen chroma key, opacity, rotation, layers.
- Music auto-ducking under dialogue, looping, fades, per-track and master effects.
- Smart tools: silence jump-cut, scene detection, highlight reel, auto-enhance, reframe 9:16 / 1:1, loudness meter, two-pass stabilization, compress to size.
- 12 export formats: MP4 (H.264/H.265/AV1), WebM, MKV, ProRes, GIF, PNG sequence, MP3, WAV, AAC, FLAC; draft to lossless; 360p to 8K; optional GPU encoders.
- Python API (`vidpy.Project`), "edit as code" export to Python and FFmpeg, effect plugin decorators.
- CLI: `studio`, `demo`, `render`, `convert`, `jumpcut`, `highlights`, `scenes`, `loudness`, `stabilize`, `compress`, `effects`, `info`, `version`.

[Unreleased]: https://github.com/rafay183/vidpy/compare/v0.1.0...HEAD
[0.1.0]: https://github.com/rafay183/vidpy/releases/tag/v0.1.0
