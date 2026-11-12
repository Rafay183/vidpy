"""Turn any Project (e.g. one built in the studio) into a readable Python script."""
from __future__ import annotations

from .project import AudioClip, Clip, Overlay, Project, Text


def _kw(obj, defaults, skip=()) -> str:
    parts = []
    for k, v in obj.__dict__.items():
        if k in skip or k in ("id", "effects", "audio_effects", "t_offset", "full_duration"):
            continue
        if getattr(defaults, k, object()) != v:
            parts.append(f"{k}={v!r}")
    return ", ".join(parts)


def _fx_lines(var: str, effects: list, method: str) -> list[str]:
    out = []
    for e in effects or []:
        if not e.get("enabled", True):
            continue
        prm = ", ".join(f"{k}={v!r}" for k, v in (e.get("params") or {}).items())
        out.append(f"{var}.{method}({e['id']!r}{', ' + prm if prm else ''})")
    return out


def to_python(p: Project) -> str:
    L = ["import vidpy", "",
         f"p = vidpy.Project(name={p.name!r}, width={p.width}, height={p.height}, fps={p.fps}, "
         f"background={p.background!r})", ""]
    for i, c in enumerate(p.clips):
        kw = _kw(c, Clip(), skip=("src", "in_point", "out_point"))
        span = []
        if c.in_point:
            span.append(f"start={c.in_point!r}")
        if c.out_point is not None:
            span.append(f"end={c.out_point!r}")
        kw = ", ".join(span + ([kw] if kw else []))
        L.append(f"c{i} = p.add_clip({c.src!r}{', ' + kw if kw else ''})")
        L += _fx_lines(f"c{i}", c.effects, "fx") + _fx_lines(f"c{i}", c.audio_effects, "afx")
    if p.overlays:
        L.append("")
    for i, o in enumerate(p.overlays):
        kw = _kw(o, Overlay(), skip=("src",))
        L.append(f"o{i} = p.add_overlay({o.src!r}{', ' + kw if kw else ''})")
        L += _fx_lines(f"o{i}", o.effects, "fx")
    if p.texts:
        L.append("")
    for t in p.texts:
        kw = _kw(t, Text(), skip=("text",))
        L.append(f"p.add_text({t.text!r}{', ' + kw if kw else ''})")
    if p.audio:
        L.append("")
    for i, a in enumerate(p.audio):
        kw = _kw(a, AudioClip(), skip=("src",))
        L.append(f"a{i} = p.add_audio({a.src!r}{', ' + kw if kw else ''})")
        L += _fx_lines(f"a{i}", a.effects, "afx")
    g = _fx_lines("p", p.effects, "fx") + _fx_lines("p", p.audio_effects, "afx")
    if g:
        L += [""] + g
    if p.subtitles:
        L.append(f"p.burn_subtitles({p.subtitles.get('path')!r}, size={p.subtitles.get('size', 24)})")
    L += ["", "p.render('output.mp4', quality='high')  # formats: mp4, webm, mov, gif, mp3, wav, ..."]
    return "\n".join(L) + "\n"
