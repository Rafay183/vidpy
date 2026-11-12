"""Smart / automatic tools: scene detection, silence jump-cuts, highlight reels,
loudness analysis, auto-enhance, waveform & filmstrip images, compress-to-size,
two-pass stabilisation and one-shot conversion."""
from __future__ import annotations

import json
import os
import re
import tempfile
from pathlib import Path
from typing import Optional

from . import ffmpeg
from .project import Project

# --------------------------------------------------------------------------- analysis

def detect_scenes(path: str, threshold: float = 0.35, min_gap: float = 0.6) -> list[float]:
    """Timestamps (s) where the picture changes significantly (cuts)."""
    r = ffmpeg.run_quick(["-i", str(path), "-an", "-vf",
                          f"scale=320:-2,select='gt(scene,{threshold})',showinfo", "-f", "null", "-"],
                         timeout=3600)
    times = [float(m) for m in re.findall(r"pts_time:([\d.]+)", r.stderr)]
    out: list[float] = []
    for t in times:
        if not out or t - out[-1] >= min_gap:
            out.append(round(t, 3))
    return out


def detect_silence(path: str, noise_db: float = -35, min_duration: float = 0.5) -> list[tuple[float, float]]:
    """[(start, end)] of silent stretches."""
    r = ffmpeg.run_quick(["-i", str(path), "-vn", "-af",
                          f"silencedetect=noise={noise_db}dB:d={min_duration}", "-f", "null", "-"], timeout=3600)
    starts = [float(x) for x in re.findall(r"silence_start: (-?[\d.]+)", r.stderr)]
    ends = [float(x) for x in re.findall(r"silence_end: ([\d.]+)", r.stderr)]
    dur = ffmpeg.probe(path).duration
    while len(ends) < len(starts):
        ends.append(dur)
    return [(max(a, 0.0), b) for a, b in zip(starts, ends)]


def detect_black(path: str, min_duration: float = 0.3) -> list[tuple[float, float]]:
    r = ffmpeg.run_quick(["-i", str(path), "-an", "-vf", f"blackdetect=d={min_duration}:pix_th=0.1",
                          "-f", "null", "-"], timeout=3600)
    return [(float(a), float(b)) for a, b in re.findall(r"black_start:([\d.]+) black_end:([\d.]+)", r.stderr)]


def loudness(path: str) -> dict:
    """EBU R128 analysis: integrated LUFS, true peak, loudness range."""
    r = ffmpeg.run_quick(["-i", str(path), "-vn", "-af", "loudnorm=print_format=json", "-f", "null", "-"],
                         timeout=3600)
    m = re.search(r"\{[^{}]*\"input_i\"[^{}]*\}", r.stderr, re.S)
    if not m:
        return {}
    d = json.loads(m.group(0))
    return {"integrated_lufs": float(d["input_i"]), "true_peak_db": float(d["input_tp"]),
            "range_lu": float(d["input_lra"]), "threshold": float(d["input_thresh"])}


def audio_energy(path: str, window: float = 1.0) -> list[float]:
    """RMS level (dBFS) per window — used for highlight detection."""
    n = int(8000 * window)
    r = ffmpeg.run_quick(["-i", str(path), "-vn", "-af",
                          f"aresample=8000,asetnsamples=n={n}:p=0,astats=metadata=1:reset=1,"
                          "ametadata=print:key=lavfi.astats.Overall.RMS_level", "-f", "null", "-"], timeout=3600)
    vals = []
    for m in re.findall(r"RMS_level=(-?[\d.]+|-inf)", r.stderr):
        vals.append(-120.0 if m == "-inf" else float(m))
    return vals


# --------------------------------------------------------------------------- auto-editing

def cut_silences(path: str, noise_db: float = -35, min_silence: float = 0.6, padding: float = 0.15,
                 project: Optional[Project] = None) -> Project:
    """Jump-cut editor: keep only the parts where someone is talking."""
    info = ffmpeg.probe(path)
    sil = detect_silence(path, noise_db, min_silence)
    keep: list[tuple[float, float]] = []
    t = 0.0
    for a, b in sil:
        a2, b2 = a + padding, b - padding
        if a - t > 0.05 and a2 - t > 0.1:
            keep.append((t, a2))
        t = max(b2, t)
    if info.duration - t > 0.1:
        keep.append((t, info.duration))
    p = project or Project(width=info.width or 1920, height=info.height or 1080, fps=round(info.fps or 30, 3))
    for a, b in keep:
        p.add_clip(path, start=round(a, 3), end=round(b, 3))
    return p


def split_scenes(path: str, threshold: float = 0.35, project: Optional[Project] = None) -> Project:
    """Put every detected shot on the timeline as its own clip."""
    info = ffmpeg.probe(path)
    cuts = [0.0] + detect_scenes(path, threshold) + [info.duration]
    p = project or Project(width=info.width or 1920, height=info.height or 1080, fps=round(info.fps or 30, 3))
    for a, b in zip(cuts, cuts[1:]):
        if b - a > 0.2:
            p.add_clip(path, start=a, end=b, name=f"Shot {len(p.clips) + 1}")
    return p


def highlight_reel(path: str, clips: int = 5, clip_length: float = 3.0, transition: str = "fade",
                   project: Optional[Project] = None) -> Project:
    """Pick the loudest/most energetic moments and cut them into a reel with transitions."""
    info = ffmpeg.probe(path)
    energy = audio_energy(path, 1.0) if info.has_audio else []
    if not energy:  # fall back to scene changes or evenly spaced picks
        cuts = detect_scenes(path) or [info.duration * (i + 0.5) / clips for i in range(clips)]
        picks = cuts[:clips]
    else:
        L = max(int(round(clip_length)), 1)
        scores = [(sum(energy[i:i + L]) / L, i) for i in range(0, max(len(energy) - L, 1))]
        scores.sort(reverse=True)
        picks: list[float] = []
        for _, i in scores:
            if all(abs(i - q) >= clip_length for q in picks):
                picks.append(float(i))
            if len(picks) >= clips:
                break
    picks.sort()
    p = project or Project(width=info.width or 1920, height=info.height or 1080, fps=round(info.fps or 30, 3))
    for k, s in enumerate(picks):
        e = min(s + clip_length, info.duration)
        if e - s < 0.3:
            continue
        c = p.add_clip(path, start=s, end=e, name=f"Highlight {k + 1}")
        if transition and k < len(picks) - 1:
            c.transition_to(transition, min(0.5, clip_length / 4))
    return p


def slideshow(images: list[str], seconds: float = 3.0, transition: str = "fade", ken_burns: bool = True,
              music: Optional[str] = None, width: int = 1920, height: int = 1080) -> Project:
    p = Project(width=width, height=height)
    dirs = ["center", "left", "right", "up", "down"]
    for i, img in enumerate(images):
        c = p.add_clip(img, duration=seconds, fit="fill")
        if ken_burns:
            c.fx("ken_burns", start_zoom=1.0, end_zoom=1.25, direction=dirs[i % len(dirs)])
        if transition and i < len(images) - 1:
            c.transition_to(transition, min(1.0, seconds / 3))
    if music:
        p.add_audio(music, loop=True, fade_in=1, fade_out=2, volume=0.8)
    return p


def auto_enhance(project: Project, video: bool = True, audio: bool = True) -> Project:
    """One-click polish: gentle auto-levels, vibrance, light denoise + sharpen, broadcast loudness."""
    if video:
        project.effects += [
            {"id": "auto_levels", "params": {"strength": 0.5}, "enabled": True},
            {"id": "vibrance", "params": {"intensity": 0.25}, "enabled": True},
            {"id": "denoise", "params": {"strength": 2}, "enabled": True},
            {"id": "sharpen", "params": {"amount": 0.5, "size": "5"}, "enabled": True},
        ]
    if audio:
        project.audio_effects += [
            {"id": "highpass", "params": {"freq": 70}, "enabled": True},
            {"id": "normalize", "params": {"target_lufs": -14, "true_peak": -1.5}, "enabled": True},
        ]
    return project


def auto_reframe(project: Project, aspect: str = "9:16") -> Project:
    """Re-target a landscape edit to vertical/square by filling (center-crop) every clip."""
    a, b = (int(x) for x in aspect.split(":"))
    base = 1080
    if a < b:
        project.width, project.height = base, int(base * b / a) // 2 * 2
    else:
        project.width, project.height = int(base * a / b) // 2 * 2, base
    for c in project.clips:
        c.fit = "fill"
    return project


# --------------------------------------------------------------------------- media utilities

def thumbnail(path: str, out: str, t: Optional[float] = None, width: int = 480) -> str:
    info = ffmpeg.probe(path)
    if info.kind == "image":
        ffmpeg.run_quick(["-i", str(path), "-vf", f"scale={width}:-2", "-frames:v", "1", "-update", "1", out])
        return out
    if t is None:
        t = min(info.duration * 0.1, 3.0) if info.duration else 0
    if info.kind == "audio":
        return waveform(path, out, width=width, height=int(width * 0.3))
    ffmpeg.run_quick(["-ss", f"{t:.3f}", "-i", str(path), "-vf", f"scale={width}:-2", "-frames:v", "1",
                      "-update", "1", "-q:v", "4", out])
    return out


def filmstrip(path: str, out: str, frames: int = 10, height: int = 60) -> str:
    info = ffmpeg.probe(path)
    if info.kind != "video" or not info.duration:
        return thumbnail(path, out, width=height * 2)
    step = info.duration / frames
    fps = 1 / max(step, 0.04)
    ffmpeg.run_quick(["-i", str(path), "-an", "-vf",
                      f"fps={fps:.5f},scale=-2:{height},tile={frames}x1", "-frames:v", "1", "-update", "1",
                      "-q:v", "5", out], timeout=600)
    return out


def waveform(path: str, out: str, width: int = 1200, height: int = 120, color: str = "#4fd1c5") -> str:
    c = color.lstrip("#")
    ffmpeg.run_quick(["-i", str(path), "-filter_complex",
                      f"[0:a]aformat=channel_layouts=mono,showwavespic=s={width}x{height}:colors=0x{c}",
                      "-frames:v", "1", "-update", "1", out], timeout=600)
    return out


def convert(src: str, out: str, format: Optional[str] = None, quality: str = "high",
            resolution: Optional[str] = None, on_progress=None) -> Path:
    """Convert any media file using the same export presets as the editor."""
    p = Project()
    info = ffmpeg.probe(src)
    if info.kind == "audio":
        p.add_audio(src)
    else:
        if info.width and info.height:
            p.width, p.height = info.width // 2 * 2, info.height // 2 * 2
        p.fps = round(info.fps or 30, 3)
        p.add_clip(src)
    return p.render(out, format=format, quality=quality, resolution=resolution, on_progress=on_progress)


def compress_to_size(src: str, out: str, target_mb: float, audio_kbps: int = 128, on_progress=None) -> Path:
    """Two-pass H.264 encode that lands close to a target file size (e.g. 25 MB for Discord/email)."""
    info = ffmpeg.probe(src)
    dur = max(info.duration, 0.1)
    total_kbps = target_mb * 8192 / dur
    vk = max(int(total_kbps - audio_kbps), 100)
    logbase = os.path.join(tempfile.gettempdir(), f"vidpy2pass_{os.getpid()}")
    common = ["-i", str(src), "-c:v", "libx264", "-b:v", f"{vk}k", "-preset", "medium", "-pix_fmt", "yuv420p",
              "-passlogfile", logbase]
    ffmpeg.run(common + ["-pass", "1", "-an", "-f", "null", os.devnull], dur,
               (lambda f, s: on_progress(f * 0.5, s)) if on_progress else None)
    ffmpeg.run(common + ["-pass", "2", "-c:a", "aac", "-b:a", f"{audio_kbps}k", "-movflags", "+faststart", str(out)],
               dur, (lambda f, s: on_progress(0.5 + f * 0.5, s)) if on_progress else None)
    for f in Path(tempfile.gettempdir()).glob(f"vidpy2pass_{os.getpid()}*"):
        f.unlink(missing_ok=True)
    return Path(out)


def stabilize(src: str, out: str, smoothing: int = 15, on_progress=None) -> Path:
    """Professional two-pass stabilisation (vid.stab) with deshake fallback."""
    dur = ffmpeg.probe(src).duration
    if ffmpeg.has_filter("vidstabdetect"):
        trf = os.path.join(tempfile.gettempdir(), f"vidpy_{os.getpid()}.trf")
        ffmpeg.run(["-i", str(src), "-vf", f"vidstabdetect=shakiness=6:accuracy=12:result={trf}", "-f", "null", "-"],
                   dur, (lambda f, s: on_progress(f * 0.4, s)) if on_progress else None)
        ffmpeg.run(["-i", str(src), "-vf", f"vidstabtransform=input={trf}:smoothing={smoothing}:zoom=3,unsharp=5:5:0.6",
                    "-c:v", "libx264", "-crf", "18", "-preset", "medium", "-c:a", "copy", str(out)],
                   dur, (lambda f, s: on_progress(0.4 + f * 0.6, s)) if on_progress else None)
        Path(trf).unlink(missing_ok=True)
    else:
        ffmpeg.run(["-i", str(src), "-vf", "deshake", "-c:v", "libx264", "-crf", "18", "-c:a", "copy", str(out)],
                   dur, on_progress)
    return Path(out)


def extract_audio(src: str, out: str, format: Optional[str] = None) -> Path:
    p = Project()
    p.add_audio(src)
    return p.render(out, format=format)
