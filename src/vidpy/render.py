"""Timeline compiler: turns a Project into ONE ffmpeg filter_complex graph and renders it."""
from __future__ import annotations

import itertools
import os
import re
import tempfile
from pathlib import Path
from typing import Optional

from . import ffmpeg, transitions
from .audio import atempo_chain
from .effects import col
from .presets import FORMATS, RESOLUTIONS, output_args
from .project import Project
from .registry import AUDIO_EFFECTS, VIDEO_EFFECTS

AFMT = "aresample=48000,aformat=sample_fmts=fltp:sample_rates=48000:channel_layouts=stereo"


def _f(x: float) -> str:
    return f"{float(x):.4f}".rstrip("0").rstrip(".") or "0"


class _Graph:
    def __init__(self):
        self.inputs: list[list[str]] = []
        self.chains: list[str] = []
        self._uid = itertools.count()
        self.tmpfiles: list[str] = []

    def input(self, args: list[str]) -> int:
        self.inputs.append(args)
        return len(self.inputs) - 1

    def uid(self, prefix: str) -> str:
        return f"{prefix}{next(self._uid)}"

    def add(self, chain: str) -> None:
        self.chains.append(chain)

    def fx(self, effects: list, kind: str, ctx: dict) -> str:
        """Build an effect chain; internal [labels] are made unique per instance."""
        table = VIDEO_EFFECTS if kind == "video" else AUDIO_EFFECTS
        parts = []
        for e in effects or []:
            if not e or not e.get("enabled", True):
                continue
            eff = table.get(e.get("id", ""))
            if eff is None:
                raise ValueError(f"Unknown {kind} effect: {e.get('id')!r}")
            chain = eff.build(e.get("params"), ctx)
            if not chain or chain in ("null", "anull"):
                continue
            tag = next(self._uid)
            chain = re.sub(r"\[([A-Za-z][A-Za-z0-9_]*)\]", lambda m, tag=tag: f"[{m.group(1)}_{tag}]", chain)
            parts.append(chain)
        return ",".join(parts)


def _canvas(project: Project, resolution: Optional[str], height: Optional[int]) -> tuple[int, int]:
    W, H = int(project.width), int(project.height)
    target_h = None
    if resolution:
        if resolution in RESOLUTIONS:
            rw, rh = RESOLUTIONS[resolution]
            target_h = rh if W >= H else None
            if W < H:  # vertical canvas: resolution refers to the short side
                nw = rh
                return nw // 2 * 2, int(round(H * nw / W / 2)) * 2
        elif "x" in resolution:
            a, b = resolution.lower().split("x")
            return int(a) // 2 * 2, int(b) // 2 * 2
    if height:
        target_h = height
    if target_h:
        return int(round(W * target_h / H / 2)) * 2, int(target_h) // 2 * 2
    return W // 2 * 2, H // 2 * 2


def _fit(mode: str, W: int, H: int, bg: str) -> str:
    if mode == "fill":
        return f"scale={W}:{H}:force_original_aspect_ratio=increase,crop={W}:{H}"
    if mode == "stretch":
        return f"scale={W}:{H}"
    return (f"scale={W}:{H}:force_original_aspect_ratio=decrease:force_divisible_by=2,"
            f"pad={W}:{H}:(ow-iw)/2:(oh-ih)/2:color={col(bg)}")


def _text_file(g: _Graph, text: str) -> str:
    fd, path = tempfile.mkstemp(prefix="vidpy_txt_", suffix=".txt")
    with os.fdopen(fd, "w", encoding="utf-8") as fh:
        fh.write(text)
    g.tmpfiles.append(path)
    return path


_TEXT_POS = {
    "center": ("(w-text_w)/2", "(h-text_h)/2"),
    "top": ("(w-text_w)/2", "h*0.08"),
    "bottom": ("(w-text_w)/2", "h*0.88-text_h"),
    "lower_third": ("w*0.06", "h*0.72"),
    "top_left": ("w*0.05", "h*0.06"),
    "top_right": ("w*0.95-text_w", "h*0.06"),
    "bottom_left": ("w*0.05", "h*0.92-text_h"),
    "bottom_right": ("w*0.95-text_w", "h*0.92-text_h"),
}


def _drawtext(g: _Graph, t, W: int, H: int) -> list[str]:
    S = H / 1080.0
    s, e = float(t.start), float(t.start) + float(t.duration)
    fi, fo = max(float(t.fade_in), 0.0), max(float(t.fade_out), 0.0)
    if t.animation == "none":
        fi = fo = 0.0
    x, y = _TEXT_POS.get(t.preset, (f"w*{_f(t.x)}-text_w/2", f"h*{_f(t.y)}-text_h/2"))
    if t.animation == "slide_up":
        y = f"({y})+h*0.06*max(1-(t-{_f(s)})/0.5,0)"
    elif t.animation == "slide_left":
        x = f"({x})+w*0.08*max(1-(t-{_f(s)})/0.5,0)"
    alpha = "1"
    if fi or fo:
        a_in = f"min(max((t-{_f(s)})/{_f(fi)},0),1)" if fi else "1"
        a_out = f"min(max(({_f(e)}-t)/{_f(fo)},0),1)" if fo else "1"
        alpha = f"{a_in}*{a_out}"
    font = t.font if t.font and Path(t.font).exists() else ffmpeg.default_font()
    size = max(int(round(t.size * S)), 6)
    opts = []
    if font:
        opts.append(f"fontfile={ffmpeg.esc_path(font)}")
    base = dict(fontsize=size, fontcolor=col(t.color), x=f"'{x}'", y=f"'{y}'", alpha=f"'{alpha}'",
                enable=f"'between(t,{_f(s)},{_f(e)})'", expansion="none", line_spacing=int(size * 0.2))
    if t.box:
        base.update(box=1, boxcolor=col(t.box_color, t.box_opacity), boxborderw=max(int(size * 0.35), 2))
    if t.outline:
        base.update(borderw=max(int(round(t.outline * S)), 1), bordercolor=col(t.outline_color))
    if t.shadow:
        sh = max(int(round(t.shadow * S)), 1)
        base.update(shadowx=sh, shadowy=sh, shadowcolor="black@0.6")
    if t.animation == "typewriter" and len(t.text) > 0:
        # reveal characters progressively: one drawtext per prefix (cheap for short titles)
        n = len(t.text)
        span = max(min(float(t.duration) * 0.6, n * 0.06), 0.1)
        out = []
        for i in range(1, n + 1):
            ts = s + span * (i - 1) / n
            te = s + span * i / n if i < n else e
            b = dict(base, enable=f"'gte(t,{_f(ts)})*lt(t,{_f(te)})'", alpha="'1'")
            b["textfile"] = ffmpeg.esc_path(_text_file(g, t.text[:i]))
            out.append("drawtext=" + ":".join(opts + [f"{k}={v}" for k, v in b.items() if v is not None]))
        return out
    if t.animation == "zoom_pop":
        # Pop-in with a slight overshoot. Each step is a drawtext with a FIXED font size:
        # a per-frame `fontsize` expression crashes some FFmpeg 8.0 builds (Ubuntu 26.04).
        steps = [0.55, 0.7, 0.85, 1.0, 1.08, 1.04, 1.0]
        span = min(0.35, float(t.duration) / 2)
        tf = ffmpeg.esc_path(_text_file(g, t.text))
        out = []
        for i, k in enumerate(steps):
            ts = s + span * i / len(steps)
            te = s + span * (i + 1) / len(steps) if i < len(steps) - 1 else e
            fs = max(int(round(size * k)), 6)
            b = dict(base, fontsize=fs, enable=f"'gte(t,{_f(ts)})*lt(t,{_f(te)})'", textfile=tf)
            if "borderw" in b:
                b["borderw"] = max(int(round(int(b["borderw"]) * k)), 1)
            out.append("drawtext=" + ":".join(opts + [f"{k2}={v}" for k2, v in b.items() if v is not None]))
        return out
    base["textfile"] = ffmpeg.esc_path(_text_file(g, t.text))
    return ["drawtext=" + ":".join(opts + [f"{k}={v}" for k, v in base.items() if v is not None])]


def build_command(project: Project, output: str | Path, format: Optional[str] = None,
                  quality: str = "high", resolution: Optional[str] = None, height: Optional[int] = None,
                  hardware: bool = False, start: Optional[float] = None, end: Optional[float] = None,
                  frame_at: Optional[float] = None, gif_fps: int = 15):
    """Compile the project. Returns (ffmpeg_args, duration, tmpfiles)."""
    if start is not None or end is not None:
        a = start or 0.0
        b = end if end is not None else project.duration
        project = project.slice(a, b)
    output = str(output)
    fmt = format or _guess_format(output)
    W, H = _canvas(project, resolution, height)
    if fmt == "gif" and not resolution and not height and W > 720:
        W, H = 720, int(round(project.height * 720 / project.width / 2)) * 2
    fps = float(project.fps)
    bg = project.background
    g = _Graph()

    T = getattr(project, "_slice_len", None) or project.duration
    if T <= 0:
        raise ValueError("The project is empty — add clips, overlays, texts or audio first.")

    # ------------------------------------------------------------ main track
    segs: list[tuple[str, str, float]] = []
    for c in project.clips:
        kind = c.resolved_kind
        L = c.length()
        ctx = {"w": W, "h": H, "fps": fps, "duration": c.full_duration or L}
        if kind == "video":
            a, b = c.source_span()
            i = g.input(["-ss", _f(a), "-t", _f(b - a), "-i", c.src])
            info = ffmpeg.probe(c.src)
        elif kind == "image":
            i = g.input(["-loop", "1", "-framerate", _f(fps), "-t", _f(L), "-i", c.src])
            info = None
        else:
            i = g.input(["-f", "lavfi", "-t", _f(L), "-i", f"color=c={col(c.color)}:s={W}x{H}:r={_f(fps)}"])
            info = None
        vl = g.uid("v")
        v = [f"[{i}:v]setpts=PTS-STARTPTS"]
        if c.reverse and kind == "video":
            v.append("reverse")
        if abs(c.speed - 1) > 1e-4 and kind == "video":
            v.append(f"setpts=PTS/{_f(c.speed)}")
        v.append(f"fps={_f(fps)}")
        v.append(_fit(c.fit, W, H, bg))
        chain = g.fx(c.effects, "video", ctx)
        if chain:
            if c.t_offset:
                v.append(f"setpts=PTS+{_f(c.t_offset)}/TB")
            v.append(chain)
            if c.t_offset:
                v.append("setpts=PTS-STARTPTS")
            v.append(_fit("fit", W, H, bg))
        v += ["setsar=1", f"fps={_f(fps)}", "format=yuv420p", f"trim=duration={_f(L)}", "setpts=PTS-STARTPTS"]
        g.add(",".join(v) + f"[{vl}]")

        al = g.uid("a")
        if kind == "video" and info and info.has_audio and not c.mute and c.volume > 0:
            ach = [f"[{i}:a]asetpts=PTS-STARTPTS", AFMT]
            if c.reverse:
                ach.append("areverse")
            if abs(c.speed - 1) > 1e-4:
                ach.append(atempo_chain(c.speed))
            if abs(c.volume - 1) > 1e-4:
                ach.append(f"volume={_f(c.volume)}")
            achain = g.fx(c.audio_effects, "audio", ctx)
            if achain:
                if c.t_offset:
                    ach.append(f"asetpts=PTS+{_f(c.t_offset)}/TB")
                ach.append(achain)
                if c.t_offset:
                    ach.append("asetpts=PTS-STARTPTS")
        else:
            ach = [f"anullsrc=r=48000:cl=stereo,atrim=duration={_f(L)}"]
        ach += [AFMT, "apad", f"atrim=duration={_f(L)}", "asetpts=PTS-STARTPTS"]
        g.add(",".join(ach) + f"[{al}]")
        segs.append((vl, al, L))

    # join with transitions
    if segs:
        cv, ca, acc = segs[0]
        for idx in range(1, len(segs)):
            nv, na, L = segs[idx]
            d = project.transition_duration(idx - 1)
            ov, oa = g.uid("jv"), g.uid("ja")
            if d > 0.01:
                tr = transitions.resolve(project.clips[idx - 1].transition.get("type", "fade"))
                g.add(f"[{cv}][{nv}]xfade=transition={tr}:duration={_f(d)}:offset={_f(acc - d)}[{ov}]")
                g.add(f"[{ca}][{na}]acrossfade=d={_f(d)}:c1=tri:c2=tri[{oa}]")
                acc += L - d
            else:
                g.add(f"[{cv}][{nv}]concat=n=2:v=1:a=0[{ov}]")
                g.add(f"[{ca}][{na}]concat=n=2:v=0:a=1[{oa}]")
                acc += L
            cv, ca = ov, oa
        main_len = acc
        if T - main_len > 0.02:
            pv, pa = g.uid("pv"), g.uid("pa")
            g.add(f"[{cv}]tpad=stop_mode=add:stop_duration={_f(T - main_len)}:color={col(bg)}[{pv}]")
            g.add(f"[{ca}]apad=pad_dur={_f(T - main_len)}[{pa}]")
            cv, ca = pv, pa
    else:
        cv, ca = g.uid("bv"), g.uid("ba")
        g.add(f"color=c={col(bg)}:s={W}x{H}:r={_f(fps)}:d={_f(T)},format=yuv420p,setsar=1[{cv}]")
        g.add(f"anullsrc=r=48000:cl=stereo,atrim=duration={_f(T)},{AFMT}[{ca}]")

    # trim to exact project length
    tv, ta = g.uid("tv"), g.uid("ta")
    g.add(f"[{cv}]trim=duration={_f(T)},setpts=PTS-STARTPTS[{tv}]")
    g.add(f"[{ca}]atrim=duration={_f(T)},asetpts=PTS-STARTPTS[{ta}]")
    cv, ca = tv, ta

    # ------------------------------------------------------------ global grade
    gchain = g.fx(project.effects, "video", {"w": W, "h": H, "fps": fps, "duration": T})
    if gchain:
        gv = g.uid("gv")
        g.add(f"[{cv}]{gchain},{_fit('fit', W, H, bg)},setsar=1,format=yuv420p[{gv}]")
        cv = gv

    # ------------------------------------------------------------ overlays
    extra_audio: list[tuple[str, bool]] = []  # (label, duck)
    for o in sorted(project.overlays, key=lambda o: o.layer):
        info = ffmpeg.probe(o.src)
        L = o.length()
        if info.kind == "image":
            i = g.input(["-loop", "1", "-framerate", _f(fps), "-t", _f(L), "-i", o.src])
        else:
            i = g.input(["-ss", _f(o.in_point), "-t", _f(L), "-i", o.src])
        ow = max(int(W * o.scale) // 2 * 2, 2)
        ch = [f"[{i}:v]setpts=PTS-STARTPTS", f"fps={_f(fps)}", f"scale={ow}:-2"]
        if o.chroma_key:
            ck = o.chroma_key
            ch.append(f"format=yuva420p,chromakey=color={col(ck.get('color', '#00ff00'))}:"
                      f"similarity={_f(ck.get('similarity', 0.15))}:blend={_f(ck.get('blend', 0.08))}")
        full = o.full_duration or L
        chain = g.fx(o.effects, "video", {"w": ow, "h": H, "fps": fps, "duration": full})
        if chain:
            if o.t_offset:
                ch.append(f"setpts=PTS+{_f(o.t_offset)}/TB")
            ch.append(chain)
            if o.t_offset:
                ch.append("setpts=PTS-STARTPTS")
        ch.append("format=rgba")
        if o.opacity < 0.999:
            ch.append(f"colorchannelmixer=aa={_f(max(o.opacity, 0))}")
        if abs(o.rotation) > 0.01:
            r = f"{_f(o.rotation)}*PI/180"
            ch.append(f"rotate={r}:ow=rotw({r}):oh=roth({r}):c=none")
        if o.fade_in > 0 or o.fade_out > 0:
            # fades use the overlay's ORIGINAL clock, so sliced previews stay correct
            if o.t_offset:
                ch.append(f"setpts=PTS+{_f(o.t_offset)}/TB")
            if o.fade_in > 0:
                ch.append(f"fade=t=in:st=0:d={_f(o.fade_in)}:alpha=1")
            if o.fade_out > 0:
                ch.append(f"fade=t=out:st={_f(max(full - o.fade_out, 0))}:d={_f(o.fade_out)}:alpha=1")
            if o.t_offset:
                ch.append("setpts=PTS-STARTPTS")
        ch.append(f"setpts=PTS+{_f(o.start)}/TB")
        ol, nb = g.uid("ov"), g.uid("ob")
        g.add(",".join(ch) + f"[{ol}]")
        g.add(f"[{cv}][{ol}]overlay=x='W*{_f(o.x)}-w/2':y='H*{_f(o.y)}-h/2':eof_action=pass:"
              f"enable='between(t,{_f(o.start)},{_f(o.start + L)})'[{nb}]")
        cv = nb
        if o.use_audio and info.has_audio:
            al = g.uid("oa")
            ms = int(o.start * 1000)
            g.add(f"[{i}:a]asetpts=PTS-STARTPTS,{AFMT},volume={_f(o.volume)},adelay={ms}|{ms}[{al}]")
            extra_audio.append((al, False))

    # ------------------------------------------------------------ texts & subtitles
    dt: list[str] = []
    for t in project.texts:
        if t.text.strip():
            dt += _drawtext(g, t, W, H)
    if project.subtitles and project.subtitles.get("path") and Path(project.subtitles["path"]).exists():
        sz = int(project.subtitles.get("size", 24))
        colr = (project.subtitles.get("color") or "#ffffff").lstrip("#")
        bgr = colr[4:6] + colr[2:4] + colr[0:2] if len(colr) == 6 else "FFFFFF"
        dt.append(f"subtitles=filename={ffmpeg.esc_path(project.subtitles['path'])}:"
                  f"force_style='Fontsize={sz},PrimaryColour=&H00{bgr},Outline=2,Shadow=1,MarginV=40'")
    if dt:
        if any(d.startswith("drawtext") for d in dt) and not ffmpeg.has_filter("drawtext"):
            raise ffmpeg.RenderError(
                "Your FFmpeg build has no text support (the 'drawtext' filter is missing), so titles can't be "
                "rendered. Install a full FFmpeg build: macOS → `brew uninstall ffmpeg && brew tap homebrew-ffmpeg/ffmpeg "
                "&& brew install homebrew-ffmpeg/ffmpeg/ffmpeg`; any OS → `pip install 'vidpy-ray[ffmpeg]'` "
                "and set VIDPY_FFMPEG to its path. Or remove the text items from the project.")
        if any(d.startswith("subtitles") for d in dt) and not ffmpeg.has_filter("subtitles"):
            raise ffmpeg.RenderError("Your FFmpeg build has no subtitle support (libass). Install a full FFmpeg build "
                                     "or remove the subtitles from the project.")
        xv = g.uid("xv")
        g.add(f"[{cv}]" + ",".join(dt) + f"[{xv}]")
        cv = xv

    # ------------------------------------------------------------ audio tracks
    for au in project.audio:
        info = ffmpeg.probe(au.src)
        if not info.has_audio:
            continue
        L = au.length(T)
        if au.loop:
            i = g.input(["-stream_loop", "-1", "-ss", _f(au.in_point), "-i", au.src])
        else:
            src_len = L * max(au.speed, 0.01)
            i = g.input(["-ss", _f(au.in_point), "-t", _f(src_len), "-i", au.src])
        ch = [f"[{i}:a]asetpts=PTS-STARTPTS", AFMT]
        if abs(au.speed - 1) > 1e-4:
            ch.append(atempo_chain(au.speed))
        ch.append(f"atrim=duration={_f(L)}")
        if abs(au.volume - 1) > 1e-4:
            ch.append(f"volume={_f(au.volume)}")
        chain = g.fx(au.effects, "audio", {"duration": L})
        if chain:
            ch.append(chain)
        if au.fade_in > 0:
            ch.append(f"afade=t=in:st=0:d={_f(au.fade_in)}")
        if au.fade_out > 0:
            ch.append(f"afade=t=out:st={_f(max(L - au.fade_out, 0))}:d={_f(au.fade_out)}")
        ms = int(round(au.start * 1000))
        if ms > 0:
            ch.append(f"adelay={ms}|{ms}")
        al = g.uid("ma")
        g.add(",".join(ch) + f"[{al}]")
        extra_audio.append((al, au.duck))

    if extra_audio:
        ducked = [l for l, d in extra_audio if d]
        normal = [l for l, d in extra_audio if not d]
        mix_inputs = []
        if ducked:
            m1, sc = g.uid("am"), g.uid("sc")
            g.add(f"[{ca}]asplit=2[{m1}][{sc}]")
            mix_inputs.append(m1)
            bus = ducked[0]
            if len(ducked) > 1:
                bus = g.uid("db")
                g.add("".join(f"[{l}]" for l in ducked) + f"amix=inputs={len(ducked)}:duration=longest:normalize=0[{bus}]")
            dk = g.uid("dk")
            g.add(f"[{bus}][{sc}]sidechaincompress=threshold=0.02:ratio=10:attack=15:release=450:makeup=1[{dk}]")
            mix_inputs.append(dk)
        else:
            mix_inputs.append(ca)
        mix_inputs += normal
        mx = g.uid("mx")
        g.add("".join(f"[{l}]" for l in mix_inputs) +
              f"amix=inputs={len(mix_inputs)}:duration=first:dropout_transition=0:normalize=0,"
              f"alimiter=limit=0.97:level=disabled[{mx}]")
        ca = mx

    mchain = g.fx(project.audio_effects, "audio", {"duration": T})
    if mchain:
        mm = g.uid("mm")
        g.add(f"[{ca}]{mchain},{AFMT}[{mm}]")
        ca = mm

    # ------------------------------------------------------------ output
    spec = FORMATS[fmt]
    if fmt == "gif":
        gp, g1, g2 = g.uid("gp"), g.uid("gs"), g.uid("gq")
        gf = min(gif_fps, int(fps))
        g.add(f"[{cv}]fps={gf},split[{g1}][{g2}];[{g1}]palettegen=stats_mode=diff[{gp}];"
              f"[{g2}][{gp}]paletteuse=dither=sierra2_4a[gifout]")
        cv = "gifout"

    args: list[str] = []
    for inp in g.inputs:
        args += inp
    graph = ";\n".join(g.chains)
    fd, gpath = tempfile.mkstemp(prefix="vidpy_graph_", suffix=".txt")
    with os.fdopen(fd, "w", encoding="utf-8") as fh:
        fh.write(graph)
    g.tmpfiles.append(gpath)
    args += ffmpeg.filter_graph_file_args(gpath)

    if frame_at is not None or spec["video"] in ("gif", "png"):
        g.add(f"[{ca}]anullsink")
    if spec["video"] is None:
        g.add(f"[{cv}]nullsink")
    graph = ";\n".join(g.chains)
    with open(gpath, "w", encoding="utf-8") as fh:
        fh.write(graph)

    if frame_at is not None:
        args +=["-map", f"[{cv}]", "-ss", _f(frame_at), "-frames:v", "1", "-update", "1", "-q:v", "3", output]
        return args, 0.1, g.tmpfiles

    if spec["video"] is not None:
        args += ["-map", f"[{cv}]"]
    if spec["video"] not in ("gif", "png"):
        args += ["-map", f"[{ca}]"]
    args += output_args(fmt, quality, fps, True, hardware)
    if spec["video"] not in (None, "gif", "png"):
        args += ["-r", _f(fps)]
    args += ["-t", _f(T)]
    if fmt == "png_sequence":
        base = Path(output)
        output = str(base.with_name(base.stem + "_%05d.png"))
    args += ["-metadata", f"title={project.name}", "-metadata", "encoder=vidpy", output]
    return args, T, g.tmpfiles


def _guess_format(output: str) -> str:
    ext = Path(output).suffix.lower().lstrip(".")
    return {"mp4": "mp4", "m4v": "mp4", "mov": "mov_prores", "mkv": "mkv", "webm": "webm", "gif": "gif",
            "mp3": "mp3", "wav": "wav", "m4a": "aac", "aac": "aac", "flac": "flac",
            "png": "png_sequence"}.get(ext, "mp4")


def render(project: Project, output: str | Path, format: Optional[str] = None, quality: str = "high",
           resolution: Optional[str] = None, on_progress=None, hardware: bool = False,
           height: Optional[int] = None, start: Optional[float] = None, end: Optional[float] = None,
           process_holder: Optional[list] = None, keep_graph: bool = False) -> Path:
    """Render a project to a file. on_progress(fraction, stats) is called during encoding."""
    output = Path(output)
    output.parent.mkdir(parents=True, exist_ok=True)
    fmt = format or _guess_format(str(output))
    if FORMATS[fmt]["ext"] != output.suffix.lower().lstrip(".") and fmt != "png_sequence":
        output = output.with_suffix("." + FORMATS[fmt]["ext"])
    args, T, tmp = build_command(project, output, format=fmt, quality=quality, resolution=resolution,
                                 height=height, hardware=hardware, start=start, end=end)
    proc = ffmpeg.Process(args, T, on_progress)
    if process_holder is not None:
        process_holder.append(proc)
    try:
        proc.run()
    finally:
        if keep_graph:
            print("filter graph:", tmp[-1])
        else:
            for f in tmp:
                try:
                    os.unlink(f)
                except OSError:
                    pass
    return output


def render_frame(project: Project, t: float, output: str | Path, height: int = 540) -> Path:
    """Render a single still of the timeline at time t (fast: only the needed slice is decoded)."""
    t = max(0.0, min(float(t), max(project.duration - 1.0 / project.fps, 0)))
    sl = project.slice(t, t + 2.0 / project.fps)
    output = Path(output)
    args, _, tmp = build_command(sl, output, format="mp4", height=height, frame_at=0)
    try:
        ffmpeg.run(args)
    finally:
        for f in tmp:
            try:
                os.unlink(f)
            except OSError:
                pass
    return output


def command_string(project: Project, output: str = "out.mp4", **kw) -> str:
    args, _, tmp = build_command(project, output, **kw)
    graph = Path(tmp[-1]).read_text()
    parts = []
    for a in args:
        if a == tmp[-1]:
            parts.append("graph.txt")
        else:
            parts.append(f'"{a}"' if (" " in a or ";" in a) else a)
    return f"ffmpeg -y {' '.join(parts)}\n\n# graph.txt\n{graph}"
