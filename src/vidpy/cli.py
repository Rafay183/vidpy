"""Command line interface:  vidpy <command> ..."""
from __future__ import annotations

import argparse
import json
import sys
import time

from . import __version__


def _bar(f: float, stats: dict, t0=[0.0]) -> None:  # noqa: B006
    if not t0[0]:
        t0[0] = time.time()
    n = int(f * 32)
    sys.stderr.write(f"\r  [{'█' * n}{'·' * (32 - n)}] {f * 100:5.1f}%  speed {stats.get('speed', '?'):>7}")
    sys.stderr.flush()
    if f >= 1:
        sys.stderr.write(f"\n  done in {time.time() - t0[0]:.1f}s\n")


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="vidpy", description="vidpy — local video editing studio & engine")
    ap.add_argument("--version", action="version", version=f"vidpy {__version__}")
    sub = ap.add_subparsers(dest="cmd")

    s = sub.add_parser("studio", help="launch the browser editor on localhost")
    s.add_argument("--host", default="127.0.0.1")
    s.add_argument("--port", type=int, default=8765)
    s.add_argument("--workspace", default=None, help="folder for media/projects/exports (default ~/vidpy-studio)")
    s.add_argument("--no-browser", action="store_true")

    d = sub.add_parser("demo", help="open the studio with generated sample media and a ready-made edit")
    d.add_argument("--host", default="127.0.0.1")
    d.add_argument("--port", type=int, default=8765)
    d.add_argument("--workspace", default=None)
    d.add_argument("--no-browser", action="store_true")

    sub.add_parser("version", help="show vidpy and FFmpeg versions")

    r = sub.add_parser("render", help="render a .vidpy.json project")
    r.add_argument("project")
    r.add_argument("output")
    r.add_argument("-f", "--format")
    r.add_argument("-q", "--quality", default="high", choices=["draft", "web", "high", "ultra", "lossless"])
    r.add_argument("-r", "--resolution")
    r.add_argument("--hw", action="store_true", help="use GPU encoder if available")

    c = sub.add_parser("convert", help="convert a media file (any → any)")
    c.add_argument("input")
    c.add_argument("output")
    c.add_argument("-f", "--format")
    c.add_argument("-q", "--quality", default="high")
    c.add_argument("-r", "--resolution")

    i = sub.add_parser("info", help="show media information")
    i.add_argument("input")

    e = sub.add_parser("effects", help="list effects / transitions / formats")
    e.add_argument("kind", nargs="?", default="video", choices=["video", "audio", "transitions", "formats"])

    for name, hlp in [("jumpcut", "remove silences (auto jump-cut)"), ("scenes", "detect scene cuts"),
                      ("highlights", "auto highlight reel"), ("loudness", "measure EBU R128 loudness"),
                      ("stabilize", "stabilize shaky footage"), ("compress", "compress to a target size (MB)")]:
        x = sub.add_parser(name, help=hlp)
        x.add_argument("input")
        if name in ("jumpcut", "highlights", "stabilize", "compress"):
            x.add_argument("output")
        if name == "compress":
            x.add_argument("--mb", type=float, default=25)
        if name == "jumpcut":
            x.add_argument("--noise", type=float, default=-35)
            x.add_argument("--min-silence", type=float, default=0.6)
        if name == "highlights":
            x.add_argument("--clips", type=int, default=5)
            x.add_argument("--length", type=float, default=3)
        if name == "scenes":
            x.add_argument("--threshold", type=float, default=0.3)

    a = ap.parse_args(argv)
    if not a.cmd:
        a = ap.parse_args(["studio"] + (argv or sys.argv[1:]))

    from . import ffmpeg, presets, smart, transitions
    from .project import Project
    from .registry import list_effects

    try:
        if a.cmd == "studio":
            from .server import serve
            serve(a.host, a.port, a.workspace, not a.no_browser)
        elif a.cmd == "demo":
            from .server import serve
            serve(a.host, a.port, a.workspace, not a.no_browser, demo=True)
        elif a.cmd == "version":
            print(f"vidpy {__version__}  (pip package: vidpy-ray)")
            print(ffmpeg.version())
        elif a.cmd == "render":
            p = Project.load(a.project)
            out = p.render(a.output, format=a.format, quality=a.quality, resolution=a.resolution,
                           hardware=a.hw, on_progress=_bar)
            print(f"  → {out}")
        elif a.cmd == "convert":
            print(f"  → {smart.convert(a.input, a.output, a.format, a.quality, a.resolution, on_progress=_bar)}")
        elif a.cmd == "info":
            print(json.dumps(ffmpeg.probe(a.input).to_dict(), indent=2))
        elif a.cmd == "effects":
            if a.kind == "transitions":
                rows = [(t["category"], t["id"], t["name"]) for t in transitions.list_transitions() if t["available"]]
            elif a.kind == "formats":
                rows = [("format", f["id"], f["label"]) for f in presets.list_formats()]
            else:
                rows = [(x["category"], x["id"], x["name"] + ("" if x["available"] else "  (unavailable)"))
                        for x in list_effects(a.kind)]
            for cat, id_, name in rows:
                print(f"  {cat:<16} {id_:<22} {name}")
            print(f"\n  {len(rows)} total")
        elif a.cmd == "jumpcut":
            p = smart.cut_silences(a.input, a.noise, a.min_silence)
            print(f"  kept {len(p.clips)} segments, {p.duration:.1f}s of {ffmpeg.probe(a.input).duration:.1f}s")
            print(f"  → {p.render(a.output, on_progress=_bar)}")
        elif a.cmd == "scenes":
            for t in smart.detect_scenes(a.input, a.threshold):
                print(f"  {t:9.3f}s")
        elif a.cmd == "highlights":
            p = smart.highlight_reel(a.input, a.clips, a.length)
            print(f"  → {p.render(a.output, on_progress=_bar)}")
        elif a.cmd == "loudness":
            print(json.dumps(smart.loudness(a.input), indent=2))
        elif a.cmd == "stabilize":
            print(f"  → {smart.stabilize(a.input, a.output, on_progress=_bar)}")
        elif a.cmd == "compress":
            print(f"  → {smart.compress_to_size(a.input, a.output, a.mb, on_progress=_bar)}")
    except ffmpeg.FFmpegNotFound as e:
        print(f"\n  ✖ {e}\n", file=sys.stderr)
        return 2
    except ffmpeg.RenderError as e:
        print(f"\n  ✖ Render failed:\n{e}\n", file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        return 130
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
