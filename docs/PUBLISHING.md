# Publishing vidpy to GitHub and PyPI: step by step

This guide takes you from the zip file to `pip install vidpy-ray` working for everyone, with the repository open for contributors. Follow the parts in order. Commands are for **Windows (Command Prompt / PowerShell)**; they work the same on macOS/Linux.

| Name | Value |
|---|---|
| GitHub repo | `rafay183/vidpy` |
| PyPI package (install name) | `vidpy-ray` |
| Command users type | `vidpy` |
| Python import | `import vidpy` |
| First version | `0.1.0` (tag `v0.1.0`) |

> **Why not `vidpy`?** The name `vidpy` on PyPI already belongs to an unrelated 2017 project, so the install name is `vidpy-ray` (like `pybi-ray`). Before you start, open https://pypi.org/project/vidpy-ray/. A "404 Not Found" page means the name is free. If it is taken, pick another name and replace `vidpy-ray` in `pyproject.toml`, `README.md`, `.github/workflows/publish.yml`, `SECURITY.md` and `src/vidpy/cli.py`.

---

## Part 0: Clean up the earlier attempt (only if you already tried)

1. **GitHub:** if you created `vidpy-studio` (or another repo) earlier, open it → **Settings** → scroll to **Danger Zone** → **Delete this repository**.
2. **PyPI:** open https://pypi.org/manage/projects/
   * If **nothing was uploaded** (the earlier run failed in its tests, so nothing reached PyPI): go to **Your account → Publishing** and **remove** any old *pending publisher* for `vidpy-studio`.
   * If a project **was** uploaded: keep it. Don't delete it, because deleting can lock version numbers forever.
3. **Your computer:** delete the old `vidpy-studio` folder.

> Tip: keep code **outside OneDrive** (e.g. `C:\dev\vidpy`). OneDrive syncing can lock files that Git is writing.

---

## Part 1: Prepare the project on your computer

1. Check FFmpeg is installed: `ffmpeg -version`. If it isn't, run `winget install ffmpeg`, then **close and reopen** the terminal.
2. **Unzip** `vidpy-ray-0.1.0-source.zip` to `C:\dev\`. You get `C:\dev\vidpy`.
3. In File Explorer turn on **View → Show → Hidden items** and check that `C:\dev\vidpy\.github\workflows\` contains **`ci.yml`** and **`publish.yml`**. These hidden files are what make GitHub publish for you.
4. Open a terminal in the folder:

   ```bash
   cd C:\dev\vidpy
   python -m venv .venv
   .venv\Scripts\activate
   pip install -e ".[dev]"
   pytest -q
   vidpy demo
   ```

   You should see `14 passed`, and the studio opens with a ready-made demo edit. The first `vidpy demo` takes about 20 seconds to generate its sample media. Press **Ctrl+C** in the terminal to stop it.
5. **Check the version** in two files. They must match:
   * `pyproject.toml` → `version = "0.1.0"` and `name = "vidpy-ray"`
   * `src/vidpy/__init__.py` → `__version__ = "0.1.0"`

---

## Part 2: Create the GitHub repository and push

1. Go to https://github.com/new
   * Owner: **rafay183** · Repository name: **vidpy**
   * Description: `Open-source video editor in Python: browser studio on localhost, Python API & CLI powered by FFmpeg`
   * **Public**
   * Leave **all** "Add README / .gitignore / license" boxes **unticked**
   * **Create repository**
2. Push the code:

   ```bash
   git config --global user.name "Muhammad Rafay Shaikh"
   git config --global user.email "<the email on your GitHub account>"

   git init
   git add .
   git commit -m "vidpy 0.1.0 - initial release"
   git branch -M main
   git remote add origin https://github.com/rafay183/vidpy.git
   git push -u origin main
   ```

   If Git asks you to sign in, a browser window opens. Sign in to GitHub there.
3. Open **https://github.com/rafay183/vidpy/actions**. A **CI** run starts: lint plus tests on Python 3.10–3.14, plus Windows and macOS. Wait for the green ✓, which takes about 4 minutes.
   * If you see a banner asking to enable workflows, click **I understand my workflows, go ahead and enable them**.
   * The Windows and macOS jobs are non-blocking. The Linux jobs must be green.

---

## Part 3: Connect PyPI to GitHub (trusted publishing, no passwords)

1. Log in at https://pypi.org (turn on 2FA if asked).
2. Choose **one** of these:
   * **New project (vidpy-ray not on PyPI yet):** **Your account → Publishing → Add a new pending publisher → GitHub**
   * **Project already exists:** **Your projects → vidpy-ray → Manage → Publishing → Add a new publisher → GitHub**
3. Fill in **exactly**:

   | Field | Value |
   |---|---|
   | PyPI Project Name (pending only) | `vidpy-ray` |
   | Owner | `rafay183` |
   | Repository name | `vidpy` |
   | Workflow name | `publish.yml` |
   | Environment name | `pypi` |

4. Click **Add**.
5. *(Recommended)* On GitHub: **Settings → Environments → New environment** → name `pypi` → **Configure environment** → tick **Required reviewers** → add yourself → **Save protection rules**. Now every release waits for your approval click, so nobody can publish by accident.

---

## Part 4: Publish version 0.1.0

Publishing happens **only when you push a version tag**. Pushing to `main` runs tests but never publishes.

```bash
git tag v0.1.0
git push origin v0.1.0
```

Then open **https://github.com/rafay183/vidpy/actions** and click the run named **v0.1.0**. It runs four jobs:

```
test  →  build  →  publish  →  github-release
```

* If you set up required reviewers, the run pauses with a yellow banner. Click **Review deployments → tick pypi → Approve and deploy**.
* `build` checks that the tag (`v0.1.0`) matches the version in **both** `pyproject.toml` and `src/vidpy/__init__.py`. If they differ, it stops with a clear error.
* `github-release` creates a **GitHub Release** with the wheel attached and notes generated from your commits.

---

## Part 5: Check it worked

1. Open https://pypi.org/project/vidpy-ray/. You should see **0.1.0** and the README with the demo GIF.
2. In a **new** terminal (not the dev venv):

   ```bash
   pip install vidpy-ray
   vidpy version
   vidpy demo
   ```

   `vidpy version` prints `vidpy 0.1.0` and your FFmpeg version, and the studio opens. 🎉

---

## Part 6: Open the project for contributors (10 minutes, once)

1. **About box** (⚙ next to *About* on the repo page): set the website to `https://pypi.org/project/vidpy-ray/` and add these topics:
   `video-editor` `video-editing` `ffmpeg` `python` `nle` `video-effects` `transitions` `audio` `open-source`
2. **Settings → General → Features:** tick **Issues** and **Discussions**.
3. **Issues → Labels:** make sure `good first issue`, `help wanted` and `effect` exist.
4. **Create 3–5 starter issues** so newcomers know where to begin, for example:
   * "Add a Light Leak effect" (`effect`, `good first issue`)
   * "Keyframes for overlay position and scale" (`enhancement`, `help wanted`)
   * "Waveform display on main-track clips" (`enhancement`)
   * "Urdu translation of the studio UI" (`good first issue`)
5. **Protect `main`:** **Settings → Branches → Add branch ruleset** → target `main` → tick **Require a pull request before merging** and **Require status checks to pass** → choose the **CI** checks → **Create**.
6. **Pin** the repo on your GitHub profile next to PyBI.

Contributors read `CONTRIBUTING.md` (setup, structure, how to add effects, transitions and formats). The issue and PR forms are already in `.github/`.

---

## Part 7: Every future release

1. Merge the changes you want into `main`.
2. Update the version in **both** files, e.g. `0.1.1`:
   * `pyproject.toml` → `version = "0.1.1"`
   * `src/vidpy/__init__.py` → `__version__ = "0.1.1"`
3. In `CHANGELOG.md`, move the **Unreleased** items into a new `## [0.1.1] - YYYY-MM-DD` section.
4. Commit, push and tag:

   ```bash
   git add .
   git commit -m "Release 0.1.1"
   git push
   git tag v0.1.1
   git push origin v0.1.1
   ```

Version rules (semantic versioning): `0.1.1` = bug fixes · `0.2.0` = new features · `1.0.0` = stable, big promise.

---

## Part 8: Plan B, publishing from your computer (if Actions is stuck or broken)

1. PyPI → **Account settings → API tokens → Add API token**
   * New project: scope **Entire account** · existing project: scope **Project: vidpy-ray**
   * Copy the token (it starts with `pypi-`). It is shown only once.
2. In the project folder:

   ```bash
   pip install build twine
   rmdir /s /q dist        # Windows: remove old builds (macOS/Linux: rm -rf dist)
   python -m build
   twine check dist/*
   twine upload dist/*
   ```
3. Username: `__token__` · Password: paste the token (nothing shows while you paste, which is normal).
4. Afterwards, delete the *Entire account* token and go back to using tags.

---

## Troubleshooting

| Symptom | Cause → Fix |
|---|---|
| `The version '3.9' … was not found for Ubuntu 26.04` | Old workflow. This version's CI uses Python 3.10–3.14, so make sure you pushed the new `.github/workflows/` files. |
| `pip install vidpy-ray` → `from versions: none` | Nothing published yet → push the tag (Part 4) or use Plan B. Wait 1–2 minutes after publishing. |
| `git push origin v0.1.0` → `Everything up-to-date`, no run appears | The tag is already on GitHub but the workflow file isn't. Check `.github/workflows/publish.yml` exists on GitHub, then re-create the tag:<br>`git tag -d v0.1.0`<br>`git push origin :refs/tags/v0.1.0`<br>`git tag v0.1.0`<br>`git push origin v0.1.0` |
| `error: src refspec v0.1.0 does not match any` | Tag not created yet → run `git tag v0.1.0` first. |
| Run stuck on **Queued** for 10+ minutes | GitHub runner problem → check https://www.githubstatus.com, cancel and **Re-run all jobs**, or use Plan B. |
| `publish` job: `invalid-publisher` | The Part 3 values don't match exactly (owner, repo `vidpy`, `publish.yml`, `pypi`). |
| `publish` job: `File already exists` | That version was uploaded before, and PyPI never allows reuse → bump the version and tag again. |
| `build` job: `Tag vX does not match …` | Update the version in `pyproject.toml` **and** `src/vidpy/__init__.py`, commit, then re-create the tag. |
| `test` or `Lint (ruff)` job fails | Click the red job, read the error, fix it locally (`pytest -q`, `ruff check src tests --fix`), push, then re-create the tag. |
| `FFmpeg was not found` (locally) | `winget install ffmpeg`, then reopen the terminal. Or run `pip install "vidpy-ray[ffmpeg]"`. |
| `git push` asks for a password | GitHub doesn't accept passwords → sign in through the browser window, or use a Personal Access Token as the password. |
| `remote origin already exists` | `git remote set-url origin https://github.com/rafay183/vidpy.git` |
