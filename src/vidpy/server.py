"""vidpy Studio — a local web server (stdlib only) that serves the browser editor
and exposes the engine over a small JSON API."""
from __future__ import annotations

import hashlib
import json
import mimetypes
import os
import re
import tempfile
import threading
import time
import traceback
import uuid
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, unquote, urlparse

from . import __version__, ffmpeg, presets, smart, transitions
from .codegen import to_python
from .project import Project
from .registry import list_effects
from .render import command_string, render, render_frame

WEB = Path(__file__).parent / "web"
CHUNK = 1 << 16


# =========================================================================== workspace

class Workspace:
    def __init__(self, root: str | Path | None = None):
        self.root = Path(root or os.environ.get("VIDPY_WORKSPACE") or Path.home() / "vidpy-studio").expanduser()
        for sub in ("media", "projects", "exports", "cache"):
            (self.root / sub).mkdir(parents=True, exist_ok=True)
        self.index_path = self.root / "media" / "index.json"
        self.lock = threading.RLock()
        self.media: dict[str, dict] = {}
        if self.index_path.exists():
            try:
                self.media = json.loads(self.index_path.read_text())
            except Exception:
                self.media = {}
        self.media = {k: v for k, v in self.media.items() if Path(v["path"]).exists()}

    def _save_index(self):
        with self.lock:
            self.index_path.write_text(json.dumps(self.media, indent=1))

    def add(self, path: str | Path, name: str | None = None) -> dict:
        path = Path(path).resolve()
        info = ffmpeg.probe(path)
        mid = hashlib.sha1(str(path).encode()).hexdigest()[:12]
        rec = {"id": mid, "name": name or path.name, "path": str(path), "added": time.time(), **info.to_dict()}
        rec["path"] = str(path)
        with self.lock:
            self.media[mid] = rec
            self._save_index()
        return rec

    def remove(self, mid: str, delete_file: bool = False):
        with self.lock:
            rec = self.media.pop(mid, None)
            self._save_index()
        if rec and delete_file and Path(rec["path"]).parent == self.root / "media":
            Path(rec["path"]).unlink(missing_ok=True)

    def cache_file(self, mid: str, kind: str, ext: str) -> Path:
        return self.root / "cache" / f"{mid}_{kind}.{ext}"


# =========================================================================== jobs

class Job:
    def __init__(self, kind: str, label: str):
        self.id = uuid.uuid4().hex[:10]
        self.kind, self.label = kind, label
        self.status = "queued"
        self.progress = 0.0
        self.error = ""
        self.output = ""
        self.url = ""
        self.started = time.time()
        self.finished = 0.0
        self.speed = ""
        self.holder: list = []

    def to_dict(self):
        return {k: getattr(self, k) for k in ("id", "kind", "label", "status", "progress", "error", "output",
                                              "url", "started", "finished", "speed")}


class Jobs:
    def __init__(self):
        self.jobs: dict[str, Job] = {}
        self.lock = threading.Lock()

    def start(self, kind: str, label: str, fn) -> Job:
        job = Job(kind, label)
        with self.lock:
            self.jobs[job.id] = job
            # keep the list short
            if len(self.jobs) > 60:
                for k in sorted(self.jobs, key=lambda k: self.jobs[k].started)[:20]:
                    if self.jobs[k].status != "running":
                        self.jobs.pop(k, None)

        def runner():
            job.status = "running"
            try:
                fn(job)
                job.status = "done"
                job.progress = 1.0
            except Exception as e:  # noqa: BLE001
                job.status = "cancelled" if "cancelled" in str(e).lower() else "error"
                job.error = str(e)[-3000:]
                if job.status == "error":
                    traceback.print_exc()
            job.finished = time.time()

        threading.Thread(target=runner, daemon=True).start()
        return job

    def cancel(self, jid: str):
        job = self.jobs.get(jid)
        if job:
            for p in job.holder:
                p.cancel()


# =========================================================================== http

class Handler(BaseHTTPRequestHandler):
    ws: Workspace
    jobs: Jobs
    server_version = f"vidpy/{__version__}"

    def log_message(self, fmt, *args):  # quieter console
        if os.environ.get("VIDPY_DEBUG"):
            super().log_message(fmt, *args)

    # ---------------------------------------------------------------- helpers
    def _json(self, data, status=200):
        body = json.dumps(data).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def _err(self, msg, status=400):
        self._json({"error": str(msg)}, status)

    def _body(self) -> bytes:
        n = int(self.headers.get("Content-Length") or 0)
        return self.rfile.read(n) if n else b""

    def _jbody(self) -> dict:
        b = self._body()
        return json.loads(b or b"{}")

    def _file(self, path: Path, download: bool = False, ctype: str | None = None):
        if not path.exists() or not path.is_file():
            return self._err("not found", 404)
        size = path.stat().st_size
        ctype = ctype or mimetypes.guess_type(str(path))[0] or "application/octet-stream"
        rng = self.headers.get("Range")
        start, end = 0, size - 1
        status = 200
        if rng:
            m = re.match(r"bytes=(\d*)-(\d*)", rng)
            if m:
                if m.group(1):
                    start = int(m.group(1))
                    end = int(m.group(2)) if m.group(2) else size - 1
                elif m.group(2):
                    start = max(size - int(m.group(2)), 0)
                end = min(end, size - 1)
                status = 206
        if start > end:
            self.send_response(416)
            self.send_header("Content-Range", f"bytes */{size}")
            self.end_headers()
            return
        self.send_response(status)
        self.send_header("Content-Type", ctype)
        self.send_header("Accept-Ranges", "bytes")
        self.send_header("Content-Length", str(end - start + 1))
        if status == 206:
            self.send_header("Content-Range", f"bytes {start}-{end}/{size}")
        if download:
            self.send_header("Content-Disposition", f'attachment; filename="{path.name}"')
        self.send_header("Cache-Control", "no-cache")
        self.end_headers()
        try:
            with open(path, "rb") as fh:
                fh.seek(start)
                left = end - start + 1
                while left > 0:
                    chunk = fh.read(min(CHUNK, left))
                    if not chunk:
                        break
                    self.wfile.write(chunk)
                    left -= len(chunk)
        except (BrokenPipeError, ConnectionResetError):
            pass

    def _project(self, d) -> Project:
        return Project.from_dict(d.get("project") if "project" in d else d)

    # ---------------------------------------------------------------- routing
    def do_GET(self):
        self._route("GET")

    def do_POST(self):
        self._route("POST")

    def do_PUT(self):
        self._route("PUT")

    def do_DELETE(self):
        self._route("DELETE")

    def _route(self, method):
        url = urlparse(self.path)
        path = unquote(url.path)
        q = {k: v[0] for k, v in parse_qs(url.query).items()}
        try:
            for (m, pattern), fn in ROUTES:
                if m != method:
                    continue
                match = re.fullmatch(pattern, path)
                if match:
                    return fn(self, q, *match.groups())
            self._err("no such route", 404)
        except ffmpeg.RenderError as e:
            self._err(str(e)[-2500:], 500)
        except FileNotFoundError as e:
            self._err(f"File not found: {e}", 404)
        except (BrokenPipeError, ConnectionResetError):
            pass
        except Exception as e:  # noqa: BLE001
            traceback.print_exc()
            self._err(f"{type(e).__name__}: {e}", 500)


ROUTES: list = []


def route(method, pattern):
    def deco(fn):
        ROUTES.append(((method, pattern), fn))
        return fn
    return deco


# ---------------------------------------------------------------- static
@route("GET", r"/")
def index(h: Handler, q):
    h._file(WEB / "index.html", ctype="text/html; charset=utf-8")


@route("GET", r"/static/([\w.\-]+)")
def static(h: Handler, q, name):
    h._file(WEB / name)


# ---------------------------------------------------------------- info
@route("GET", r"/api/info")
def info(h: Handler, q):
    h._json({"version": __version__, "ffmpeg": ffmpeg.version(), "workspace": str(h.ws.root),
             "font": ffmpeg.default_font(), "rubberband": ffmpeg.has_filter("rubberband"),
             "vidstab": ffmpeg.has_filter("vidstabdetect")})


@route("GET", r"/api/catalog")
def catalog(h: Handler, q):
    h._json({"video_effects": list_effects("video"), "audio_effects": list_effects("audio"),
             "transitions": transitions.list_transitions(), "formats": presets.list_formats(),
             "qualities": list(presets.QUALITY), "resolutions": list(presets.RESOLUTIONS),
             "canvas_presets": presets.CANVAS_PRESETS})


# ---------------------------------------------------------------- media
@route("GET", r"/api/media")
def media_list(h: Handler, q):
    items = sorted(h.ws.media.values(), key=lambda r: r.get("added", 0))
    h._json({"media": items})


@route("POST", r"/api/upload")
def upload(h: Handler, q):
    name = re.sub(r"[^\w.\- ()]+", "_", q.get("name") or "upload.bin")[-120:]
    dest = h.ws.root / "media" / name
    stem, ext, i = dest.stem, dest.suffix, 1
    while dest.exists():
        dest = dest.with_name(f"{stem} ({i}){ext}")
        i += 1
    left = int(h.headers.get("Content-Length") or 0)
    with open(dest, "wb") as fh:
        while left > 0:
            chunk = h.rfile.read(min(CHUNK * 16, left))
            if not chunk:
                break
            fh.write(chunk)
            left -= len(chunk)
    try:
        rec = h.ws.add(dest, name)
    except Exception as e:  # noqa: BLE001
        dest.unlink(missing_ok=True)
        return h._err(f"Not a supported media file: {e}")
    h._json(rec)


@route("POST", r"/api/import")
def import_path(h: Handler, q):
    d = h._jbody()
    added, errors = [], []
    paths = d.get("paths") or [d.get("path")]
    for p in paths:
        if not p:
            continue
        pp = Path(p).expanduser()
        files = [f for f in pp.iterdir() if f.is_file()] if pp.is_dir() else [pp]
        for f in files:
            try:
                added.append(h.ws.add(f))
            except Exception as e:  # noqa: BLE001
                errors.append(f"{f.name}: {e}")
    h._json({"added": added, "errors": errors})


@route("DELETE", r"/api/media/(\w+)")
def media_delete(h: Handler, q, mid):
    h.ws.remove(mid, delete_file=q.get("delete") == "1")
    h._json({"ok": True})


def _rec(h: Handler, mid) -> dict:
    rec = h.ws.media.get(mid)
    if not rec:
        raise FileNotFoundError(mid)
    return rec


@route("GET", r"/media/(\w+)/file")
def media_file(h: Handler, q, mid):
    h._file(Path(_rec(h, mid)["path"]))


@route("GET", r"/media/(\w+)/thumb")
def media_thumb(h: Handler, q, mid):
    rec = _rec(h, mid)
    out = h.ws.cache_file(mid, "thumb", "jpg" if rec["kind"] != "audio" else "png")
    if rec["kind"] == "audio":
        out = h.ws.cache_file(mid, "thumbw", "png")
    if not out.exists():
        smart.thumbnail(rec["path"], str(out), width=320)
    h._file(out)


@route("GET", r"/media/(\w+)/strip")
def media_strip(h: Handler, q, mid):
    rec = _rec(h, mid)
    if rec["kind"] == "audio":
        return media_wave(h, q, mid)
    out = h.ws.cache_file(mid, "strip", "jpg")
    if not out.exists():
        smart.filmstrip(rec["path"], str(out), frames=12, height=54)
    h._file(out)


@route("GET", r"/media/(\w+)/wave")
def media_wave(h: Handler, q, mid):
    rec = _rec(h, mid)
    out = h.ws.cache_file(mid, "wave", "png")
    if not out.exists():
        if not rec.get("has_audio"):
            return h._err("no audio", 404)
        smart.waveform(rec["path"], str(out), width=1600, height=80, color="#5eead4")
    h._file(out)


# ---------------------------------------------------------------- projects
@route("GET", r"/api/projects")
def projects(h: Handler, q):
    items = []
    for f in sorted((h.ws.root / "projects").glob("*.vidpy.json"), key=lambda f: -f.stat().st_mtime):
        items.append({"name": f.name[:-len(".vidpy.json")], "modified": f.stat().st_mtime})
    h._json({"projects": items})


@route("GET", r"/api/projects/(.+)")
def project_get(h: Handler, q, name):
    f = h.ws.root / "projects" / f"{Path(name).name}.vidpy.json"
    if not f.exists():
        return h._err("not found", 404)
    h._json(json.loads(f.read_text()))


@route("PUT", r"/api/projects/(.+)")
def project_put(h: Handler, q, name):
    d = h._jbody()
    Project.from_dict(d)  # validate
    safe = re.sub(r"[^\w\- ]+", "_", Path(name).name) or "Untitled"
    (h.ws.root / "projects" / f"{safe}.vidpy.json").write_text(json.dumps(d, indent=1))
    h._json({"ok": True, "name": safe})


@route("DELETE", r"/api/projects/(.+)")
def project_del(h: Handler, q, name):
    (h.ws.root / "projects" / f"{Path(name).name}.vidpy.json").unlink(missing_ok=True)
    h._json({"ok": True})


# ---------------------------------------------------------------- preview / export
@route("POST", r"/api/frame")
def frame(h: Handler, q):
    d = h._jbody()
    p = h._project(d)
    if p.duration <= 0:
        return h._err("empty project", 400)
    fd, out = tempfile.mkstemp(suffix=".jpg", prefix="vidpy_frame_")
    os.close(fd)
    try:
        render_frame(p, float(d.get("t", 0)), out, height=int(d.get("height", 480)))
        data = Path(out).read_bytes()
    finally:
        Path(out).unlink(missing_ok=True)
    h.send_response(200)
    h.send_header("Content-Type", "image/jpeg")
    h.send_header("Content-Length", str(len(data)))
    h.send_header("Cache-Control", "no-store")
    h.end_headers()
    h.wfile.write(data)


def _start_render(h: Handler, p: Project, kind: str, out: Path, **kw) -> Job:
    def work(job: Job):
        t0 = time.time()

        def prog(f, stats):
            job.progress = f
            job.speed = stats.get("speed", "")
        res = render(p, out, on_progress=prog, process_holder=job.holder, **kw)
        job.output = str(res)
        rel = res.relative_to(h.ws.root)
        job.url = "/files/" + str(rel).replace(os.sep, "/")
        job.speed = job.speed or f"{time.time() - t0:.1f}s"
    return h.jobs.start(kind, out.name, work)


@route("POST", r"/api/preview")
def preview(h: Handler, q):
    d = h._jbody()
    p = h._project(d)
    out = h.ws.root / "cache" / f"preview_{uuid.uuid4().hex[:8]}.mp4"
    for old in sorted((h.ws.root / "cache").glob("preview_*.mp4"), key=lambda f: f.stat().st_mtime)[:-4]:
        old.unlink(missing_ok=True)
    start = d.get("start")
    end = d.get("end")
    job = _start_render(h, p, "preview", out, format="mp4", quality="draft",
                        height=int(d.get("height", 360)), start=start, end=end)
    h._json(job.to_dict())


@route("POST", r"/api/export")
def export(h: Handler, q):
    d = h._jbody()
    p = h._project(d)
    fmt = d.get("format", "mp4")
    ext = presets.FORMATS[fmt]["ext"]
    name = re.sub(r"[^\w\- ]+", "_", d.get("filename") or p.name or "export").strip() or "export"
    out = h.ws.root / "exports" / f"{name}.{ext}"
    i = 1
    while out.exists():
        out = out.with_name(f"{name}-{i}.{ext}")
        i += 1
    if fmt == "png_sequence":
        out = h.ws.root / "exports" / name / f"{name}.png"
    job = _start_render(h, p, "export", out, format=fmt, quality=d.get("quality", "high"),
                        resolution=d.get("resolution") or None, hardware=bool(d.get("hardware")),
                        start=d.get("start"), end=d.get("end"))
    h._json(job.to_dict())


@route("GET", r"/api/jobs")
def jobs(h: Handler, q):
    h._json({"jobs": [j.to_dict() for j in sorted(h.jobs.jobs.values(), key=lambda j: -j.started)]})


@route("GET", r"/api/jobs/(\w+)")
def job_get(h: Handler, q, jid):
    j = h.jobs.jobs.get(jid)
    h._json(j.to_dict()) if j else h._err("not found", 404)


@route("POST", r"/api/jobs/(\w+)/cancel")
def job_cancel(h: Handler, q, jid):
    h.jobs.cancel(jid)
    h._json({"ok": True})


@route("GET", r"/files/(.+)")
def files(h: Handler, q, rel):
    p = (h.ws.root / rel).resolve()
    if h.ws.root.resolve() not in p.parents:
        return h._err("forbidden", 403)
    h._file(p, download=q.get("dl") == "1")


@route("POST", r"/api/code")
def code(h: Handler, q):
    d = h._jbody()
    p = h._project(d)
    h._json({"python": to_python(p), "ffmpeg": command_string(p, "output.mp4")})


# ---------------------------------------------------------------- smart tools
@route("POST", r"/api/smart/(\w+)")
def smart_tool(h: Handler, q, tool):
    d = h._jbody()
    rec = _rec(h, d.get("media_id", ""))
    path = rec["path"]
    prm = d.get("params") or {}
    if tool == "scenes":
        return h._json({"times": smart.detect_scenes(path, float(prm.get("threshold", 0.3)))})
    if tool == "loudness":
        return h._json(smart.loudness(path))
    if tool == "silence":
        return h._json({"silences": smart.detect_silence(path, float(prm.get("noise_db", -35)),
                                                         float(prm.get("min_duration", 0.5)))})
    if tool in ("cut_silences", "split_scenes", "highlights"):
        if tool == "cut_silences":
            p = smart.cut_silences(path, float(prm.get("noise_db", -35)), float(prm.get("min_silence", 0.6)),
                                   float(prm.get("padding", 0.15)))
        elif tool == "split_scenes":
            p = smart.split_scenes(path, float(prm.get("threshold", 0.3)))
        else:
            p = smart.highlight_reel(path, int(prm.get("clips", 5)), float(prm.get("clip_length", 3)),
                                     prm.get("transition", "fade"))
        return h._json({"clips": [c.to_dict() for c in p.clips]})
    if tool in ("stabilize", "compress"):
        stem = Path(path).stem
        out = h.ws.root / "media" / (f"{stem}_stabilized.mp4" if tool == "stabilize" else f"{stem}_small.mp4")

        def work(job: Job):
            cb = lambda f, s: setattr(job, "progress", f)  # noqa: E731
            if tool == "stabilize":
                smart.stabilize(path, str(out), int(prm.get("smoothing", 15)), on_progress=cb)
            else:
                smart.compress_to_size(path, str(out), float(prm.get("target_mb", 25)), on_progress=cb)
            h.ws.add(out)
            job.output = str(out)
        job = h.jobs.start(tool, out.name, work)
        return h._json(job.to_dict())
    h._err(f"unknown tool {tool}")


# =========================================================================== entry point

def serve(host: str = "127.0.0.1", port: int = 8765, workspace: str | None = None, open_browser: bool = True,
          demo: bool = False, project: str | None = None):
    ffmpeg.ffmpeg_bin()  # fail early with a helpful message
    ws = Workspace(workspace)
    if demo:
        from .demo import make_demo
        print("  generating demo media…")
        proj, files = make_demo(ws.root)
        for f in files:
            ws.add(f)
        (ws.root / "projects" / "Demo.vidpy.json").write_text(proj.to_json())
        project = "Demo"
    Handler.ws = ws
    Handler.jobs = Jobs()
    httpd = None
    for p in range(port, port + 20):
        try:
            httpd = ThreadingHTTPServer((host, p), Handler)
            port = p
            break
        except OSError:
            continue
    if httpd is None:
        raise SystemExit(f"Could not bind a port near {port}")
    httpd.daemon_threads = True
    url = f"http://{'localhost' if host in ('127.0.0.1', '0.0.0.0') else host}:{port}"
    print(f"\n  ✨ vidpy Studio {__version__}  →  {url}\n  workspace: {ws.root}\n  {ffmpeg.version()}\n"
          f"  Press Ctrl+C to stop.\n")
    if project:
        from urllib.parse import quote
        url += "/?project=" + quote(project)
    if open_browser:
        threading.Timer(0.8, lambda: webbrowser.open(url)).start()
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\n  bye 👋")
    finally:
        httpd.server_close()
