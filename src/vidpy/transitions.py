"""Transitions between adjacent clips on the main track (FFmpeg xfade)."""
from __future__ import annotations

import functools
import re
import subprocess

from . import ffmpeg

_CATALOG = {
    "Basic": ["fade", "fadeblack", "fadewhite", "fadegrays", "dissolve", "fadefast", "fadeslow", "distance"],
    "Wipe": ["wipeleft", "wiperight", "wipeup", "wipedown", "wipetl", "wipetr", "wipebl", "wipebr",
             "diagtl", "diagtr", "diagbl", "diagbr"],
    "Slide": ["slideleft", "slideright", "slideup", "slidedown", "smoothleft", "smoothright", "smoothup",
              "smoothdown", "coverleft", "coverright", "coverup", "coverdown", "revealleft", "revealright",
              "revealup", "revealdown"],
    "Shape": ["circleopen", "circleclose", "circlecrop", "rectcrop", "vertopen", "vertclose", "horzopen",
              "horzclose", "radial"],
    "Slice": ["hlslice", "hrslice", "vuslice", "vdslice", "hlwind", "hrwind", "vuwind", "vdwind"],
    "Stylized": ["pixelize", "hblur", "zoomin", "squeezeh", "squeezev"],
}


@functools.lru_cache(maxsize=1)
def supported() -> frozenset[str]:
    try:
        out = subprocess.run([ffmpeg.ffmpeg_bin(), "-hide_banner", "-h", "filter=xfade"],
                             capture_output=True, text=True).stdout
    except ffmpeg.FFmpegNotFound:
        return frozenset()
    names = set(re.findall(r"^\s{5,}(\w+)\s+-?\d+\s", out, re.M))
    return frozenset(names) or frozenset(n for v in _CATALOG.values() for n in v[:4])


def list_transitions() -> list[dict]:
    sup = supported()
    out = []
    for cat, names in _CATALOG.items():
        for n in names:
            out.append({"id": n, "name": _pretty(n), "category": cat, "available": n in sup})
    return out


def _pretty(n: str) -> str:
    for a, b in [("fade", "Fade "), ("wipe", "Wipe "), ("slide", "Slide "), ("smooth", "Smooth "),
                 ("cover", "Cover "), ("reveal", "Reveal "), ("circle", "Circle "), ("vert", "Vertical "),
                 ("horz", "Horizontal "), ("diag", "Diagonal "), ("squeeze", "Squeeze "), ("zoom", "Zoom ")]:
        if n.startswith(a) and n != a:
            return (b + n[len(a):]).title().replace("Tl", "↖").replace("Tr", "↗").replace("Bl", "↙").replace("Br", "↘")
    return n.title()


def resolve(name: str) -> str:
    sup = supported()
    if name in sup:
        return name
    return "fade"
