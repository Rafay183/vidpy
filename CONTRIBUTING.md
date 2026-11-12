# Contributing to vidpy

Thank you for helping build an open-source video editor in Python! Every contribution counts: bug reports, new effects and transitions, studio features, docs and translations.

By participating you agree to follow our [Code of Conduct](CODE_OF_CONDUCT.md).

## Ways to contribute

| You have… | Do this |
|---|---|
| 10 minutes | Try `vidpy demo`, report anything confusing as an issue |
| Real footage | Edit something real and report what broke or felt slow |
| An afternoon | Pick an issue labelled **good first issue** |
| FFmpeg knowledge | Add a video effect, audio effect or look (usually 3–10 lines) |
| Python skills | Add a smart tool, export preset or CLI command |
| JavaScript / CSS skills | Improve the timeline, inspector or viewer |
| Writing skills | Improve the README, write tutorials, add examples |

## 1. Set up your development environment

You need Python 3.10+ and **FFmpeg** on your PATH (`winget install ffmpeg` · `brew install ffmpeg` · `sudo apt install ffmpeg`).

```bash
# 1. Fork https://github.com/rafay183/vidpy on GitHub, then:
git clone https://github.com/<your-username>/vidpy.git
cd vidpy
git remote add upstream https://github.com/rafay183/vidpy.git

# 2. Create a virtual environment
python -m venv .venv
# Windows:      .venv\Scripts\activate
# macOS/Linux:  source .venv/bin/activate

# 3. Install vidpy in editable mode with dev tools
pip install -e ".[dev]"

# 4. Check everything works
pytest -q
ruff check src tests
vidpy demo
```

Editable mode means your code changes are live: restart `vidpy demo` after Python changes; for JavaScript/CSS changes just refresh the browser.

## 2. Project structure

```
src/vidpy/
├── cli.py          # `vidpy studio | demo | render | convert | jumpcut | …`
├── server.py       # Local HTTP server (standard library only): API, uploads, jobs, previews
├── project.py      # Timeline data model: Project, Clip, Overlay, Text, AudioClip, slicing
├── render.py       # Compiles a Project into ONE FFmpeg filter_complex graph and renders it
├── registry.py     # Effect / Param schema + @effect / @audio_effect plugin decorators
├── effects.py      # Built-in video effects
├── audio.py        # Built-in audio effects
├── transitions.py  # xfade transition catalog
├── presets.py      # Export formats, quality levels, resolutions, canvas presets
├── smart.py        # Scene/silence detection, jump-cut, highlights, stabilize, compress…
├── codegen.py      # Project → Python script ("edit as code")
├── demo.py         # Sample media + demo project for `vidpy demo`
├── ffmpeg.py       # Binary discovery, probing, progress-aware execution, escaping
└── web/            # The studio (no build step, plain JS)
    ├── index.html
    ├── app.js      # Timeline, viewer, inspector, libraries, export/jobs
    └── style.css
```

**Key design rules**

* A project is plain JSON shared 1:1 by the Python API, the CLI and the studio. The studio never renders anything itself; it sends the project to the server.
* Everything renders through one FFmpeg graph: decode once, encode once.
* The core has **zero Python dependencies**. Keep it that way: only the standard library plus the FFmpeg binary.

## 3. Common contributions

### Add a video effect (usually 3–10 lines)

Open `src/vidpy/effects.py` and add:

```python
@effect("light_leak", "Light Leak", "Looks",
        [P("strength", "float", 0.4, 0, 1, 0.01)],
        "Warm film light leak from the left edge.", requires=["geq", "blend"])
def _(p, c):
    glow = "exp(-X/(W*0.4))"
    return (f"split[lb][lc];[lc]format=gbrp,geq=r='255*{glow}':g='154*{glow}':b='60*{glow}',format=yuv420p[ll];"
            f"[lb][ll]blend=all_mode=screen:all_opacity={p['strength']}")
```

* The builder returns an FFmpeg filter chain. `p` holds the param values, and `c` holds the context: `w`, `h`, `fps` and `duration`.
* Param types: `float`, `int`, `bool`, `color`, `choice`, `text`, `file`. The studio builds the controls automatically.
* Internal labels like `[lb]` are made unique automatically, so the same effect can be used twice.
* List every FFmpeg filter you use in `requires=[...]`, so the studio can grey out the effect on builds that lack it.
* Inside single quotes, commas are fine, but colons must be escaped as `\:`.

### Add an audio effect

The same pattern, using `@audio_effect` in `src/vidpy/audio.py`.

### Add a transition

Add the xfade name to `_CATALOG` in `transitions.py`. Unsupported names are hidden automatically.

### Add an export format

Add an entry to `FORMATS` and its encoder arguments to `output_args()` in `presets.py`, plus a case in `tests/test_vidpy.py::test_formats`.

### Test that every effect renders

```bash
python - <<'PY'
import vidpy
for kind, table in (("video", vidpy.VIDEO_EFFECTS), ("audio", vidpy.AUDIO_EFFECTS)):
    for eid in table:
        p = vidpy.Project(width=320, height=180)
        c = p.add_clip("some_clip.mp4", end=1)
        (c.fx if kind == "video" else c.afx)(eid)
        try:
            p.render(f"/tmp/fx_{eid}.mp4", quality="draft")
        except Exception as e:
            print("FAIL", kind, eid, str(e)[-200:])
PY
```

The **</> Code** button in the studio, and `vidpy.command_string(project)`, show the exact FFmpeg graph. Use them when debugging.

## 4. Coding guidelines

* **Python:** 3.10+ compatible, formatted for `ruff` (`ruff check src tests --fix`). Small, pure functions; raise `RenderError` for user-facing render problems.
* **JavaScript:** plain ES2020, no build tools or frameworks. Timing maths in `app.js` (`clipLen`, `layout`, …) must mirror `project.py`.
* **Dependencies:** none in the core. Optional extras go in `[project.optional-dependencies]`.
* **Security:** the server binds to localhost by default; never add endpoints that read files outside the workspace or imported media.
* **Credit:** keep the author credit "Muhammad Rafay Shaikh, from Pakistan" in the app.

## 5. Tests

```bash
pytest -q                       # all tests (they generate their own media with FFmpeg)
pytest -q -k formats            # a subset
```

## 6. Submit a pull request

```bash
git checkout -b feature/light-leak
# …make changes…
pytest -q && ruff check src tests
git add .
git commit -m "Add Light Leak effect"
git push origin feature/light-leak
```

Then open a PR on GitHub. Keep PRs focused (one feature or fix), fill in the template, attach a screenshot or short clip for visual changes, and add a line to `CHANGELOG.md` under **Unreleased**. CI runs the tests automatically, and a maintainer will review.

To keep your fork up to date:

```bash
git fetch upstream
git checkout main
git merge upstream/main
```

## 7. Releases (maintainers)

See [docs/PUBLISHING.md](docs/PUBLISHING.md).
