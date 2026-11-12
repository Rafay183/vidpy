"""`vidpy demo`: synthesise sample media with FFmpeg and build a ready-made edit."""
from __future__ import annotations

from pathlib import Path

from . import ffmpeg
from .project import Project

_SOURCES = {
    "aurora.mp4": ["-f", "lavfi", "-i", "gradients=s=1920x1080:r=30:speed=0.03:d=6:n=4", "-c:v", "libx264", "-pix_fmt", "yuv420p"],
    "fractal.mp4": ["-f", "lavfi", "-i", "mandelbrot=s=1280x720:r=30", "-t", "5", "-c:v", "libx264", "-pix_fmt", "yuv420p"],
    "life.mp4": ["-f", "lavfi", "-i", "life=s=480x270:mold=10:r=30:ratio=0.1:death_color=#5b21b6:life_color=#22d3ee,"
                 "scale=1920:1080:flags=neighbor", "-t", "5", "-c:v", "libx264", "-pix_fmt", "yuv420p"],
    "bars.mp4": ["-f", "lavfi", "-i", "testsrc2=s=1920x1080:r=30:d=5", "-f", "lavfi", "-i", "sine=f=440:d=5",
                 "-shortest", "-c:v", "libx264", "-pix_fmt", "yuv420p", "-c:a", "aac"],
    "photo.png": ["-f", "lavfi", "-i", "gradients=s=1600x1200:c0=0x7c5cff:c1=0x22d3ee:c2=0xff4d6d:n=3:d=1", "-frames:v", "1"],
    "music.mp3": ["-f", "lavfi", "-i",
                  "aevalsrc='(0.18*sin(2*PI*220*t)+0.12*sin(2*PI*277.2*t)+0.1*sin(2*PI*329.6*t))"
                  "*(0.6+0.4*sin(2*PI*2*t))':d=30:s=44100", "-ac", "2", "-b:a", "192k"],
}


def make_demo(workspace: str | Path) -> tuple[Project, list[Path]]:
    folder = Path(workspace) / "media" / "demo"
    folder.mkdir(parents=True, exist_ok=True)
    files = []
    for name, args in _SOURCES.items():
        out = folder / name
        if not out.exists():
            r = ffmpeg.run_quick(args + [str(out)], timeout=300)
            if r.returncode != 0 or not out.exists():
                continue  # a source filter may be missing in very small FFmpeg builds
        files.append(out)
    f = {p.name: str(p) for p in files}

    p = Project(name="Demo", width=1920, height=1080, fps=30)
    if "aurora.mp4" in f:
        p.add_clip(f["aurora.mp4"], end=5).fx("cinematic", intensity=0.6).transition_to("circleopen", 1)
    if "photo.png" in f:
        p.add_clip(f["photo.png"], duration=4, fit="fill").fx("ken_burns", end_zoom=1.35, direction="right").transition_to("slideleft", 0.8)
    if "fractal.mp4" in f:
        p.add_clip(f["fractal.mp4"], end=4).fx("glow", radius=14, strength=0.5).transition_to("pixelize", 0.8)
    if "life.mp4" in f:
        p.add_clip(f["life.mp4"], end=4).fx("vhs", intensity=0.6).transition_to("fadeblack", 0.8)
    if "bars.mp4" in f:
        p.add_clip(f["bars.mp4"], end=3, mute=True).fx("old_film").fx("fade_out", duration=1)
    p.add_text("vidpy Studio", start=0.6, duration=3.2, size=150, animation="zoom_pop", outline=3, shadow=4)
    p.add_text("Video editing in Python", start=1.4, duration=3.4, preset="lower_third", size=52, box=True,
               box_color="#7c5cff", box_opacity=0.85, animation="slide_left")
    p.add_text("79 effects · 58 transitions · 41 audio FX", start=6, duration=3.5, preset="bottom", size=48,
               animation="slide_up", box=True)
    if "photo.png" in f:
        p.add_overlay(f["photo.png"], start=10, duration=3.5, x=0.84, y=0.2, scale=0.22, rotation=-6,
                      fade_in=0.4, fade_out=0.4)
    if "music.mp3" in f:
        p.add_audio(f["music.mp3"], volume=0.7, loop=True, fade_in=1, fade_out=2)
    p.afx("normalize", target_lufs=-16)
    return p, files
