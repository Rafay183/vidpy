"""Low-level FFmpeg layer: binary discovery, probing, capability detection and
progress-aware execution. Everything else in vidpy builds on this module."""
from __future__ import annotations

import functools
import json
import os
import re
import shutil
import subprocess
import threading
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Iterable, Optional


class FFmpegNotFound(RuntimeError):
    pass


class RenderError(RuntimeError):
    def __init__(self, message: str, command: list[str] | None = None, log: str = ""):
        super().__init__(message)
        self.command = command or []
        self.log = log


# --------------------------------------------------------------------------- binaries

@functools.lru_cache(maxsize=1)
def ffmpeg_bin() -> str:
    """Locate ffmpeg: $VIDPY_FFMPEG, PATH, then the optional imageio-ffmpeg wheel."""
    env = os.environ.get("VIDPY_FFMPEG")
    if env and Path(env).exists():
        return env
    found = shutil.which("ffmpeg")
    if found:
        return found
    try:  # pip install "vidpy-ray[ffmpeg]" ships a static binary
        import imageio_ffmpeg  # type: ignore

        return imageio_ffmpeg.get_ffmpeg_exe()
    except Exception:
        pass
    raise FFmpegNotFound(
        "FFmpeg was not found. Install it (https://ffmpeg.org/download.html, "
        "`winget install ffmpeg`, `brew install ffmpeg`, `sudo apt install ffmpeg`) "
        "or run `pip install 'vidpy-ray[ffmpeg]'`, or set VIDPY_FFMPEG=/path/to/ffmpeg."
    )


@functools.lru_cache(maxsize=1)
def ffprobe_bin() -> Optional[str]:
    env = os.environ.get("VIDPY_FFPROBE")
    if env and Path(env).exists():
        return env
    found = shutil.which("ffprobe")
    if found:
        return found
    sibling = Path(ffmpeg_bin()).with_name("ffprobe" + (".exe" if os.name == "nt" else ""))
    return str(sibling) if sibling.exists() else None


@functools.lru_cache(maxsize=1)
def available_filters() -> frozenset[str]:
    out = subprocess.run([ffmpeg_bin(), "-hide_banner", "-filters"],
                         capture_output=True, text=True).stdout
    names = set()
    for line in out.splitlines():
        m = re.match(r"^\s*[TSC.|]{2,3}\s+(\S+)\s", line)
        if m:
            names.add(m.group(1))
    return frozenset(names)


@functools.lru_cache(maxsize=1)
def available_encoders() -> frozenset[str]:
    out = subprocess.run([ffmpeg_bin(), "-hide_banner", "-encoders"],
                         capture_output=True, text=True).stdout
    names = set()
    for line in out.splitlines():
        m = re.match(r"^\s*[VAS][F.][S.][X.][B.][D.]\s+(\S+)", line)
        if m:
            names.add(m.group(1))
    return frozenset(names)


def has_filter(name: str) -> bool:
    try:
        return name in available_filters()
    except FFmpegNotFound:
        return False


def version() -> str:
    out = subprocess.run([ffmpeg_bin(), "-version"], capture_output=True, text=True).stdout
    return out.splitlines()[0] if out else "unknown"


# --------------------------------------------------------------------------- fonts

_FONT_CANDIDATES = [
    # Linux
    "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
    "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
    "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf",
    "/usr/share/fonts/TTF/DejaVuSans.ttf",
    # macOS
    "/System/Library/Fonts/Supplemental/Arial Bold.ttf",
    "/System/Library/Fonts/Supplemental/Arial.ttf",
    "/Library/Fonts/Arial.ttf",
    # Windows
    "C:/Windows/Fonts/arialbd.ttf",
    "C:/Windows/Fonts/arial.ttf",
    "C:/Windows/Fonts/segoeui.ttf",
]


@functools.lru_cache(maxsize=1)
def default_font() -> Optional[str]:
    for f in _FONT_CANDIDATES:
        if Path(f).exists():
            return f
    fc = shutil.which("fc-match")
    if fc:
        out = subprocess.run([fc, "-f", "%{file}", "sans:bold"], capture_output=True, text=True).stdout
        if out and Path(out).exists():
            return out
    return None


def list_fonts() -> list[str]:
    roots = ["/usr/share/fonts", "/usr/local/share/fonts", str(Path.home() / ".fonts"),
             "/System/Library/Fonts", "/Library/Fonts", "C:/Windows/Fonts"]
    fonts: list[str] = []
    for r in roots:
        p = Path(r)
        if p.exists():
            fonts.extend(str(f) for f in p.rglob("*") if f.suffix.lower() in (".ttf", ".otf"))
    return sorted(set(fonts))[:500]


# --------------------------------------------------------------------------- probing

IMAGE_EXT = {".png", ".jpg", ".jpeg", ".bmp", ".webp", ".tif", ".tiff", ".gif"}
AUDIO_EXT = {".mp3", ".wav", ".aac", ".m4a", ".flac", ".ogg", ".opus", ".wma", ".aiff"}


@dataclass
class MediaInfo:
    path: str
    kind: str = "video"  # video | audio | image
    duration: float = 0.0
    width: int = 0
    height: int = 0
    fps: float = 0.0
    has_video: bool = False
    has_audio: bool = False
    vcodec: str = ""
    acodec: str = ""
    sample_rate: int = 0
    channels: int = 0
    bitrate: int = 0
    size_bytes: int = 0
    rotation: int = 0
    raw: dict = field(default_factory=dict, repr=False)

    def to_dict(self) -> dict:
        d = self.__dict__.copy()
        d.pop("raw", None)
        return d


def _ratio(s: str | None) -> float:
    if not s or s in ("0/0", "N/A"):
        return 0.0
    if "/" in s:
        a, b = s.split("/", 1)
        try:
            return float(a) / float(b) if float(b) else 0.0
        except ValueError:
            return 0.0
    try:
        return float(s)
    except ValueError:
        return 0.0


@functools.lru_cache(maxsize=512)
def _probe_cached(path: str, mtime: float) -> MediaInfo:
    ext = Path(path).suffix.lower()
    info = MediaInfo(path=path, size_bytes=Path(path).stat().st_size)
    probe = ffprobe_bin()
    data: dict = {}
    if probe:
        r = subprocess.run([probe, "-v", "error", "-print_format", "json", "-show_format",
                            "-show_streams", path], capture_output=True, text=True)
        if r.returncode == 0:
            data = json.loads(r.stdout or "{}")
    else:  # parse ffmpeg -i banner as a fallback
        data = _probe_with_ffmpeg(path)
    info.raw = data
    fmt = data.get("format", {})
    info.duration = float(fmt.get("duration") or 0) if fmt.get("duration") not in (None, "N/A") else 0.0
    info.bitrate = int(fmt.get("bit_rate") or 0) if str(fmt.get("bit_rate", "")).isdigit() else 0
    for s in data.get("streams", []):
        if s.get("codec_type") == "video" and not info.has_video:
            if (s.get("disposition") or {}).get("attached_pic"):
                continue
            info.has_video = True
            info.vcodec = s.get("codec_name", "")
            info.width = int(s.get("width") or 0)
            info.height = int(s.get("height") or 0)
            info.fps = _ratio(s.get("avg_frame_rate")) or _ratio(s.get("r_frame_rate"))
            rot = (s.get("tags") or {}).get("rotate")
            for sd in s.get("side_data_list", []) or []:
                if "rotation" in sd:
                    rot = sd["rotation"]
            info.rotation = int(float(rot)) if rot not in (None, "") else 0
            if not info.duration and s.get("duration"):
                info.duration = float(s["duration"])
        elif s.get("codec_type") == "audio" and not info.has_audio:
            info.has_audio = True
            info.acodec = s.get("codec_name", "")
            info.sample_rate = int(s.get("sample_rate") or 0)
            info.channels = int(s.get("channels") or 0)
            if not info.duration and s.get("duration"):
                info.duration = float(s["duration"])
    if abs(info.rotation) in (90, 270):
        info.width, info.height = info.height, info.width
    if ext in IMAGE_EXT and (info.duration < 0.5 or ext != ".gif"):
        info.kind = "image"
        info.duration = 0.0
    elif not info.has_video and info.has_audio:
        info.kind = "audio"
    else:
        info.kind = "video"
    return info


def _probe_with_ffmpeg(path: str) -> dict:
    r = subprocess.run([ffmpeg_bin(), "-hide_banner", "-i", path], capture_output=True, text=True)
    txt = r.stderr
    data: dict = {"format": {}, "streams": []}
    m = re.search(r"Duration: (\d+):(\d+):([\d.]+)", txt)
    if m:
        h, mi, s = m.groups()
        data["format"]["duration"] = str(int(h) * 3600 + int(mi) * 60 + float(s))
    m = re.search(r"Video: (\w+).*?, (\d{2,5})x(\d{2,5}).*?([\d.]+) (?:fps|tbr)", txt)
    if m:
        data["streams"].append({"codec_type": "video", "codec_name": m.group(1), "width": m.group(2),
                                "height": m.group(3), "avg_frame_rate": m.group(4)})
    m = re.search(r"Audio: (\w+).*?(\d+) Hz", txt)
    if m:
        data["streams"].append({"codec_type": "audio", "codec_name": m.group(1), "sample_rate": m.group(2),
                                "channels": 2})
    return data


def probe(path: str | os.PathLike) -> MediaInfo:
    p = str(Path(path).resolve())
    if not Path(p).exists():
        raise FileNotFoundError(p)
    return _probe_cached(p, Path(p).stat().st_mtime)


# --------------------------------------------------------------------------- running

ProgressCB = Callable[[float, dict], None]


class Process:
    """A running ffmpeg process with live progress (0..1) and cancellation."""

    def __init__(self, args: list[str], total_duration: float = 0.0,
                 on_progress: ProgressCB | None = None):
        self.args = args
        self.total = max(total_duration, 0.001)
        self.on_progress = on_progress
        self.progress = 0.0
        self.stats: dict = {}
        self.log_lines: list[str] = []
        self._proc: subprocess.Popen | None = None
        self.cancelled = False

    def run(self) -> None:
        cmd = [ffmpeg_bin(), "-hide_banner", "-nostdin", "-y", "-progress", "pipe:1",
               "-stats_period", "0.25"] + self.args
        self._proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                      text=True, bufsize=1, errors="replace")
        err_thread = threading.Thread(target=self._drain_err, daemon=True)
        err_thread.start()
        assert self._proc.stdout
        for line in self._proc.stdout:
            k, _, v = line.strip().partition("=")
            self.stats[k] = v
            if k == "out_time_us" and v.lstrip("-").isdigit():
                self.progress = min(max(int(v) / 1e6 / self.total, 0.0), 0.999)
                if self.on_progress:
                    self.on_progress(self.progress, dict(self.stats))
        code = self._proc.wait()
        err_thread.join(timeout=2)
        if self.cancelled:
            raise RenderError("Render cancelled", cmd, self.log)
        if code != 0:
            tail = "\n".join(self.log_lines[-25:])
            raise RenderError(f"FFmpeg failed (exit {code}):\n{tail}", cmd, self.log)
        self.progress = 1.0
        if self.on_progress:
            self.on_progress(1.0, dict(self.stats))

    def _drain_err(self) -> None:
        assert self._proc and self._proc.stderr
        for line in self._proc.stderr:
            self.log_lines.append(line.rstrip())
            if len(self.log_lines) > 4000:
                del self.log_lines[:1000]

    def cancel(self) -> None:
        self.cancelled = True
        if self._proc and self._proc.poll() is None:
            self._proc.terminate()

    @property
    def log(self) -> str:
        return "\n".join(self.log_lines)


def run(args: Iterable[str], total_duration: float = 0.0, on_progress: ProgressCB | None = None) -> Process:
    p = Process(list(args), total_duration, on_progress)
    p.run()
    return p


def run_quick(args: list[str], timeout: float = 120) -> subprocess.CompletedProcess:
    """Run ffmpeg for analysis tasks; returns the completed process (stderr has the log)."""
    return subprocess.run([ffmpeg_bin(), "-hide_banner", "-nostdin", "-y"] + args,
                          capture_output=True, text=True, timeout=timeout, errors="replace")


# --------------------------------------------------------------------------- escaping

def esc_text(s: str) -> str:
    """Escape text for drawtext's text='...' option inside a filtergraph."""
    return (s.replace("\\", "\\\\\\\\").replace("'", "\u2019").replace(":", "\\:")
            .replace("%", "\\%").replace(",", "\\,").replace(";", "\\;")
            .replace("[", "\\[").replace("]", "\\]"))


def esc_path(p: str) -> str:
    """Escape a file path used as a filter option value (fontfile, lut3d file, ...)."""
    p = str(p).replace("\\", "/")
    return "'" + p.replace("'", "'\\''").replace(":", "\\:") + "'"
