"""vidpy — a local-first, programmable video editing studio powered by FFmpeg.

    import vidpy
    p = vidpy.Project()
    p.add_clip("clip.mp4", start=1, end=6).fx("cinematic")
    p.render("out.mp4")

Run the browser studio with:  vidpy studio   (http://localhost:8765)
"""
from __future__ import annotations

from . import audio as _audio  # noqa: F401  (registers audio effects)
from . import effects as _effects  # noqa: F401  (registers video effects)
from . import smart
from .codegen import to_python
from .ffmpeg import FFmpegNotFound, MediaInfo, RenderError, probe
from .presets import CANVAS_PRESETS, FORMATS, QUALITY, RESOLUTIONS, list_formats
from .project import AudioClip, Clip, Overlay, Project, Text
from .registry import AUDIO_EFFECTS, VIDEO_EFFECTS, Effect, Param, audio_effect, effect, get_effect, list_effects
from .render import build_command, command_string, render, render_frame
from .transitions import list_transitions

__version__ = "0.1.1"

__all__ = [
    "Project", "Clip", "Overlay", "Text", "AudioClip", "probe", "MediaInfo", "render", "render_frame",
    "build_command", "command_string", "effect", "audio_effect", "Param", "Effect", "get_effect",
    "list_effects", "list_transitions", "list_formats", "FORMATS", "QUALITY", "RESOLUTIONS",
    "CANVAS_PRESETS", "VIDEO_EFFECTS", "AUDIO_EFFECTS", "FFmpegNotFound", "RenderError", "smart",
    "edit", "studio", "to_python", "__version__",
]


def edit(*sources, **project_kw) -> Project:
    """Quick start: vidpy.edit("a.mp4", "b.mp4").render("out.mp4")"""
    p = Project(**project_kw)
    for s in sources:
        p.add_clip(s)
    return p


def studio(host: str = "127.0.0.1", port: int = 8765, workspace: str | None = None, open_browser: bool = True):
    """Launch the browser-based editing studio on localhost."""
    from .server import serve
    serve(host=host, port=port, workspace=workspace, open_browser=open_browser)
