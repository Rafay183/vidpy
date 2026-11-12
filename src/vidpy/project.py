"""Timeline data model + fluent Python API.

A Project is plain JSON-serialisable data, shared 1:1 between the Python API,
the CLI and the web studio:

    import vidpy
    p = vidpy.Project(width=1920, height=1080, fps=30)
    p.add_clip("intro.mp4", start=2, end=8).fx("cinematic").transition("circleopen", 1)
    p.add_clip("photo.jpg", duration=4).fx("ken_burns", end_zoom=1.4)
    p.add_text("My Trip", start=0.5, duration=3, size=110, animation="slide_up")
    p.add_audio("music.mp3", volume=0.35, duck=True, fade_out=3, loop=True)
    p.render("trip.mp4", quality="high")
"""
from __future__ import annotations

import copy
import json
import uuid
from dataclasses import asdict, dataclass, field, fields
from pathlib import Path
from typing import Optional

from . import ffmpeg


def _id() -> str:
    return uuid.uuid4().hex[:8]


def _fx(id: str, params: dict | None = None, enabled: bool = True) -> dict:
    return {"id": id, "params": dict(params or {}), "enabled": enabled}


def _from_dict(cls, d: dict):
    names = {f.name for f in fields(cls)}
    return cls(**{k: v for k, v in (d or {}).items() if k in names})


# =========================================================================== items

@dataclass
class Clip:
    """An item on the main (magnetic) track. Clips play back-to-back."""
    src: str = ""
    kind: str = "auto"  # auto | video | image | color
    in_point: float = 0.0
    out_point: Optional[float] = None
    duration: Optional[float] = None  # for images / colors
    color: str = "#000000"
    speed: float = 1.0
    reverse: bool = False
    volume: float = 1.0
    mute: bool = False
    fit: str = "fit"  # fit (letterbox) | fill (crop) | stretch
    effects: list = field(default_factory=list)
    audio_effects: list = field(default_factory=list)
    transition: Optional[dict] = None  # transition INTO the next clip: {"type": "fade", "duration": 1}
    name: str = ""
    id: str = field(default_factory=_id)
    # internal (used by slicing/previews)
    t_offset: float = 0.0
    full_duration: Optional[float] = None

    # ----- fluent API
    def trim(self, start: float = 0.0, end: Optional[float] = None) -> "Clip":
        self.in_point, self.out_point = float(start), (None if end is None else float(end))
        return self

    def fx(self, effect_id: str, **params) -> "Clip":
        self.effects.append(_fx(effect_id, params))
        return self

    def afx(self, effect_id: str, **params) -> "Clip":
        self.audio_effects.append(_fx(effect_id, params))
        return self

    def set(self, **kw) -> "Clip":
        for k, v in kw.items():
            if not hasattr(self, k):
                raise AttributeError(f"Clip has no property {k!r}")
            setattr(self, k, v)
        return self

    def to(self, transition: str = "fade", duration: float = 1.0) -> "Clip":
        return self.transition_to(transition, duration)

    def transition_to(self, transition: str = "fade", duration: float = 1.0) -> "Clip":
        self.transition = {"type": transition, "duration": float(duration)}
        return self

    # ----- info
    @property
    def resolved_kind(self) -> str:
        if self.kind != "auto":
            return self.kind
        if not self.src:
            return "color"
        return ffmpeg.probe(self.src).kind

    def source_duration(self) -> float:
        k = self.resolved_kind
        if k in ("image", "color"):
            return float(self.duration or 5.0)
        return ffmpeg.probe(self.src).duration

    def source_span(self) -> tuple[float, float]:
        k = self.resolved_kind
        if k in ("image", "color"):
            d = float(self.duration or 5.0)
            return 0.0, d
        total = self.source_duration()
        a = min(max(self.in_point, 0.0), max(total - 0.04, 0))
        b = total if self.out_point is None else min(max(self.out_point, a + 0.04), total)
        return a, b

    def length(self) -> float:
        """Duration on the timeline (after trim & speed)."""
        a, b = self.source_span()
        if self.resolved_kind in ("image", "color"):
            return b - a
        return (b - a) / max(self.speed, 0.01)

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class Overlay:
    """Picture-in-picture, logo, sticker, B-roll or green-screen layer at an absolute time."""
    src: str = ""
    start: float = 0.0
    duration: Optional[float] = None
    in_point: float = 0.0
    x: float = 0.5  # centre, relative to frame (0..1)
    y: float = 0.5
    scale: float = 0.3  # width relative to frame width
    opacity: float = 1.0
    rotation: float = 0.0
    fade_in: float = 0.0
    fade_out: float = 0.0
    chroma_key: Optional[dict] = None  # {"color": "#00ff00", "similarity": 0.15, "blend": 0.05}
    use_audio: bool = False
    volume: float = 1.0
    effects: list = field(default_factory=list)
    layer: int = 1
    name: str = ""
    id: str = field(default_factory=_id)
    t_offset: float = 0.0
    full_duration: Optional[float] = None

    def fx(self, effect_id: str, **params) -> "Overlay":
        self.effects.append(_fx(effect_id, params))
        return self

    def green_screen(self, color: str = "#00ff00", similarity: float = 0.15, blend: float = 0.08) -> "Overlay":
        self.chroma_key = {"color": color, "similarity": similarity, "blend": blend}
        return self

    def set(self, **kw) -> "Overlay":
        for k, v in kw.items():
            setattr(self, k, v)
        return self

    @property
    def kind(self) -> str:
        return ffmpeg.probe(self.src).kind

    def length(self) -> float:
        if self.duration is not None:
            return float(self.duration)
        if self.kind == "image":
            return 5.0
        return max(ffmpeg.probe(self.src).duration - self.in_point, 0.04)

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class Text:
    text: str = "Title"
    start: float = 0.0
    duration: float = 3.0
    preset: str = "center"  # center | top | bottom | lower_third | top_left | top_right | custom
    x: float = 0.5
    y: float = 0.5
    size: int = 72  # px at 1080p (scales with canvas)
    color: str = "#ffffff"
    font: str = ""
    box: bool = False
    box_color: str = "#000000"
    box_opacity: float = 0.55
    outline: int = 0
    outline_color: str = "#000000"
    shadow: int = 2
    align: str = "center"
    fade_in: float = 0.3
    fade_out: float = 0.3
    animation: str = "fade"  # none | fade | slide_up | slide_left | zoom_pop | typewriter
    name: str = ""
    id: str = field(default_factory=_id)

    def set(self, **kw) -> "Text":
        for k, v in kw.items():
            setattr(self, k, v)
        return self

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class AudioClip:
    """Music, voice-over or sound effect placed at an absolute time."""
    src: str = ""
    start: float = 0.0
    in_point: float = 0.0
    out_point: Optional[float] = None
    volume: float = 1.0
    speed: float = 1.0
    fade_in: float = 0.0
    fade_out: float = 0.0
    loop: bool = False
    duck: bool = False  # auto-lower under dialogue (sidechain)
    effects: list = field(default_factory=list)
    name: str = ""
    id: str = field(default_factory=_id)

    def afx(self, effect_id: str, **params) -> "AudioClip":
        self.effects.append(_fx(effect_id, params))
        return self

    def set(self, **kw) -> "AudioClip":
        for k, v in kw.items():
            setattr(self, k, v)
        return self

    def length(self, project_length: float | None = None) -> float:
        if self.loop and project_length:
            return max(project_length - self.start, 0.04)
        total = ffmpeg.probe(self.src).duration
        b = total if self.out_point is None else min(self.out_point, total)
        return max(b - self.in_point, 0.04) / max(self.speed, 0.01)

    def to_dict(self) -> dict:
        return asdict(self)


# =========================================================================== project

@dataclass
class Project:
    name: str = "Untitled"
    width: int = 1920
    height: int = 1080
    fps: float = 30.0
    background: str = "#000000"
    clips: list = field(default_factory=list)
    overlays: list = field(default_factory=list)
    texts: list = field(default_factory=list)
    audio: list = field(default_factory=list)
    effects: list = field(default_factory=list)  # global grade
    audio_effects: list = field(default_factory=list)  # master bus
    subtitles: Optional[dict] = None  # {"path": "subs.srt", "size": 24}
    version: int = 1

    # ------------------------------------------------------------- builders
    def add_clip(self, src: str = "", start: float = 0.0, end: Optional[float] = None,
                 duration: Optional[float] = None, **kw) -> Clip:
        c = Clip(src=str(src) if src else "", in_point=float(start), out_point=end, duration=duration, **kw)
        if not src:
            c.kind = "color"
        self.clips.append(c)
        return c

    def add_color(self, color: str = "#000000", duration: float = 3.0) -> Clip:
        c = Clip(kind="color", color=color, duration=duration)
        self.clips.append(c)
        return c

    def add_overlay(self, src: str, start: float = 0.0, duration: Optional[float] = None, **kw) -> Overlay:
        o = Overlay(src=str(src), start=float(start), duration=duration, **kw)
        self.overlays.append(o)
        return o

    def add_text(self, text: str, start: float = 0.0, duration: float = 3.0, **kw) -> Text:
        t = Text(text=text, start=float(start), duration=float(duration), **kw)
        self.texts.append(t)
        return t

    def add_audio(self, src: str, start: float = 0.0, **kw) -> AudioClip:
        a = AudioClip(src=str(src), start=float(start), **kw)
        self.audio.append(a)
        return a

    def fx(self, effect_id: str, **params) -> "Project":
        self.effects.append(_fx(effect_id, params))
        return self

    def afx(self, effect_id: str, **params) -> "Project":
        self.audio_effects.append(_fx(effect_id, params))
        return self

    def burn_subtitles(self, path: str, size: int = 24, color: str = "#ffffff") -> "Project":
        self.subtitles = {"path": str(path), "size": size, "color": color}
        return self

    def canvas(self, preset: str) -> "Project":
        from .presets import CANVAS_PRESETS
        p = CANVAS_PRESETS[preset]
        self.width, self.height, self.fps = p["width"], p["height"], p["fps"]
        return self

    # ------------------------------------------------------------- timing
    def main_layout(self) -> list[tuple[Clip, float, float]]:
        """[(clip, timeline_start, length)] honouring transition overlaps."""
        out = []
        t = 0.0
        for i, c in enumerate(self.clips):
            L = c.length()
            out.append((c, t, L))
            t += L
            if i < len(self.clips) - 1:
                t -= self.transition_duration(i)
        return out

    def transition_duration(self, i: int) -> float:
        c = self.clips[i]
        if not c.transition or i >= len(self.clips) - 1:
            return 0.0
        d = float(c.transition.get("duration", 1.0))
        nxt = self.clips[i + 1]
        return max(0.0, min(d, c.length() - 0.05, nxt.length() - 0.05))

    def main_length(self) -> float:
        lay = self.main_layout()
        return (lay[-1][1] + lay[-1][2]) if lay else 0.0

    @property
    def duration(self) -> float:
        ends = [self.main_length()]
        ends += [o.start + o.length() for o in self.overlays]
        ends += [t.start + t.duration for t in self.texts]
        ends += [a.start + a.length() for a in self.audio if not a.loop]
        return max(ends) if any(e > 0 for e in ends) else 0.0

    # ------------------------------------------------------------- slicing (previews)
    def slice(self, a: float, b: float) -> "Project":
        """Return a new project containing only timeline range [a, b)."""
        a, b = max(0.0, a), max(a + 0.04, b)
        p = Project(name=self.name, width=self.width, height=self.height, fps=self.fps,
                    background=self.background, effects=copy.deepcopy(self.effects),
                    audio_effects=copy.deepcopy(self.audio_effects), subtitles=self.subtitles)
        covered_until = 0.0
        for c, s, L in self.main_layout():
            e = s + L
            lo, hi = max(a, s, covered_until), min(b, e)
            if hi - lo < 0.02:
                continue
            nc = copy.deepcopy(c)
            nc.transition = None
            local0, local1 = lo - s, hi - s
            nc.t_offset = c.t_offset + local0
            nc.full_duration = c.full_duration or L
            if c.resolved_kind in ("image", "color"):
                nc.duration = local1 - local0
            else:
                sa, sb = c.source_span()
                if c.reverse:
                    nc.in_point, nc.out_point = sb - local1 * c.speed, sb - local0 * c.speed
                else:
                    nc.in_point, nc.out_point = sa + local0 * c.speed, sa + local1 * c.speed
            p.clips.append(nc)
            covered_until = hi
        for o in self.overlays:
            os_, oe = o.start, o.start + o.length()
            lo, hi = max(a, os_), min(b, oe)
            if hi - lo < 0.02:
                continue
            no = copy.deepcopy(o)
            no.start = lo - a
            no.in_point = o.in_point + (lo - os_)
            no.t_offset = o.t_offset + (lo - os_)
            no.duration = hi - lo
            no.full_duration = o.full_duration or o.length()
            p.overlays.append(no)
        for t in self.texts:
            if t.start + t.duration > a and t.start < b:
                nt = copy.deepcopy(t)
                nt.start = t.start - a
                p.texts.append(nt)
        for au in self.audio:
            L = au.length(self.duration)
            if au.start + L > a and au.start < b:
                na = copy.deepcopy(au)
                if au.start < a:
                    na.in_point = au.in_point + (a - au.start) * au.speed
                    na.start = 0.0
                else:
                    na.start = au.start - a
                if not au.loop:
                    na.out_point = min(au.out_point or 1e12, na.in_point + (b - a) * au.speed)
                p.audio.append(na)
        p._slice_len = b - a  # type: ignore[attr-defined]
        return p

    # ------------------------------------------------------------- io
    def to_dict(self) -> dict:
        d = asdict(self)
        return d

    def to_json(self, indent: int = 2) -> str:
        return json.dumps(self.to_dict(), indent=indent)

    def save(self, path: str | Path) -> Path:
        path = Path(path)
        path.write_text(self.to_json(), encoding="utf-8")
        return path

    @classmethod
    def from_dict(cls, d: dict) -> "Project":
        d = dict(d or {})
        p = _from_dict(cls, {k: v for k, v in d.items() if k not in ("clips", "overlays", "texts", "audio")})
        p.clips = [_from_dict(Clip, c) for c in d.get("clips", [])]
        p.overlays = [_from_dict(Overlay, o) for o in d.get("overlays", [])]
        p.texts = [_from_dict(Text, t) for t in d.get("texts", [])]
        p.audio = [_from_dict(AudioClip, a) for a in d.get("audio", [])]
        return p

    @classmethod
    def load(cls, path: str | Path) -> "Project":
        return cls.from_dict(json.loads(Path(path).read_text(encoding="utf-8")))

    # ------------------------------------------------------------- render
    def render(self, output: str | Path, format: Optional[str] = None, quality: str = "high",
               resolution: Optional[str] = None, on_progress=None, hardware: bool = False, **kw) -> Path:
        from .render import render
        return render(self, output, format=format, quality=quality, resolution=resolution,
                      on_progress=on_progress, hardware=hardware, **kw)

    def preview_frame(self, t: float, output: str | Path, height: int = 540) -> Path:
        from .render import render_frame
        return render_frame(self, t, output, height=height)

    def command(self, output: str = "out.mp4", **kw) -> list[str]:
        """The exact ffmpeg command vidpy would run (great for learning/debugging)."""
        from .render import build_command
        return build_command(self, output, **kw)[0]
