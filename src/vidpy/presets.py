"""Export presets: containers, codecs, quality levels and canvas sizes."""
from __future__ import annotations

from . import ffmpeg

RESOLUTIONS = {
    "360p": (640, 360), "480p": (854, 480), "720p": (1280, 720), "1080p": (1920, 1080),
    "1440p": (2560, 1440), "4k": (3840, 2160), "8k": (7680, 4320),
}

CANVAS_PRESETS = {
    "youtube_1080p": {"width": 1920, "height": 1080, "fps": 30, "label": "YouTube 16:9 1080p"},
    "youtube_4k": {"width": 3840, "height": 2160, "fps": 30, "label": "YouTube 4K"},
    "shorts_reels_tiktok": {"width": 1080, "height": 1920, "fps": 30, "label": "Shorts / Reels / TikTok 9:16"},
    "instagram_square": {"width": 1080, "height": 1080, "fps": 30, "label": "Instagram 1:1"},
    "instagram_portrait": {"width": 1080, "height": 1350, "fps": 30, "label": "Instagram 4:5"},
    "cinema_dci_4k": {"width": 4096, "height": 2160, "fps": 24, "label": "Cinema DCI 4K 24p"},
    "hd_720p": {"width": 1280, "height": 720, "fps": 30, "label": "HD 720p"},
}

# quality → (x264/x265 crf, preset, vp9/av1 crf, audio bitrate)
QUALITY = {
    "draft": (30, "ultrafast", 40, "96k"),
    "web": (23, "medium", 33, "160k"),
    "high": (18, "slow", 28, "256k"),
    "ultra": (14, "slower", 22, "320k"),
    "lossless": (0, "medium", 0, "320k"),
}

FORMATS = {
    "mp4":       {"label": "MP4 (H.264) — plays everywhere", "ext": "mp4", "video": "h264"},
    "mp4_h265":  {"label": "MP4 (H.265/HEVC) — half the size", "ext": "mp4", "video": "h265"},
    "mp4_av1":   {"label": "MP4 (AV1) — next-gen compression", "ext": "mp4", "video": "av1"},
    "webm":      {"label": "WebM (VP9) — web/open", "ext": "webm", "video": "vp9"},
    "mkv":       {"label": "MKV (H.264) — flexible container", "ext": "mkv", "video": "h264"},
    "mov_prores": {"label": "MOV ProRes 422 HQ — editing master", "ext": "mov", "video": "prores"},
    "gif":       {"label": "Animated GIF (high quality palette)", "ext": "gif", "video": "gif"},
    "mp3":       {"label": "MP3 audio only", "ext": "mp3", "video": None},
    "wav":       {"label": "WAV audio only (lossless)", "ext": "wav", "video": None},
    "aac":       {"label": "M4A / AAC audio only", "ext": "m4a", "video": None},
    "flac":      {"label": "FLAC audio only (lossless)", "ext": "flac", "video": None},
    "png_sequence": {"label": "PNG image sequence", "ext": "png", "video": "png"},
}

HW_ENCODERS = {"h264": ["h264_nvenc", "h264_qsv", "h264_videotoolbox", "h264_amf"],
               "h265": ["hevc_nvenc", "hevc_qsv", "hevc_videotoolbox", "hevc_amf"]}


def list_formats() -> list[dict]:
    return [{"id": k, **v} for k, v in FORMATS.items()]


def pick_encoder(kind: str, hardware: bool = False) -> str:
    enc = ffmpeg.available_encoders()
    if hardware and kind in HW_ENCODERS:
        for h in HW_ENCODERS[kind]:
            if h in enc:
                return h
    return {"h264": "libx264", "h265": "libx265", "vp9": "libvpx-vp9", "av1": "libsvtav1"}.get(kind, kind)


def output_args(fmt: str, quality: str = "high", fps: float = 30, has_audio: bool = True,
                hardware: bool = False, video_bitrate: str | None = None) -> list[str]:
    """Encoder arguments for the chosen format/quality (input mapping is done by the renderer)."""
    if fmt not in FORMATS:
        raise ValueError(f"Unknown format {fmt!r}. Choose from: {', '.join(FORMATS)}")
    crf, preset, vcrf, abr = QUALITY.get(quality, QUALITY["high"])
    spec = FORMATS[fmt]
    v = spec["video"]
    args: list[str] = []
    enc = ffmpeg.available_encoders()
    if v == "h264":
        e = pick_encoder("h264", hardware)
        if e == "libx264":
            args += ["-c:v", "libx264", "-preset", preset, "-crf", str(crf)]
            args += ["-pix_fmt", "yuv444p" if quality == "lossless" else "yuv420p"]
            if quality != "lossless":
                args += ["-profile:v", "high"]
        else:
            args += ["-c:v", e, "-b:v", video_bitrate or {"draft": "4M", "web": "8M", "high": "16M"}.get(quality, "30M"),
                     "-pix_fmt", "yuv420p"]
        args += ["-movflags", "+faststart"] if spec["ext"] == "mp4" else []
    elif v == "h265":
        e = pick_encoder("h265", hardware)
        if e == "libx265":
            args += ["-c:v", "libx265", "-preset", preset, "-crf", str(crf + 4 if crf else 0),
                     "-pix_fmt", "yuv420p", "-tag:v", "hvc1", "-x265-params", "log-level=error"]
            if quality == "lossless":
                args[-1] = "lossless=1:log-level=error"
        else:
            args += ["-c:v", e, "-b:v", video_bitrate or "10M", "-pix_fmt", "yuv420p", "-tag:v", "hvc1"]
        args += ["-movflags", "+faststart"]
    elif v == "av1":
        if "libsvtav1" in enc:
            sp = {"ultrafast": "12", "medium": "8", "slow": "6", "slower": "4"}.get(preset, "8")
            args += ["-c:v", "libsvtav1", "-preset", sp, "-crf", str(max(vcrf, 1) if quality != "lossless" else 1)]
        else:
            args += ["-c:v", "libaom-av1", "-cpu-used", "6", "-crf", str(vcrf or 1), "-b:v", "0"]
        args += ["-pix_fmt", "yuv420p", "-movflags", "+faststart"]
    elif v == "vp9":
        args += ["-c:v", "libvpx-vp9", "-crf", str(vcrf), "-b:v", "0", "-row-mt", "1",
                 "-deadline", "realtime" if quality == "draft" else "good",
                 "-cpu-used", "8" if quality == "draft" else "2", "-pix_fmt", "yuv420p"]
        if quality == "lossless":
            args += ["-lossless", "1"]
    elif v == "prores":
        args += ["-c:v", "prores_ks", "-profile:v", "3", "-pix_fmt", "yuv422p10le", "-vendor", "apl0"]
    elif v == "png":
        args += ["-c:v", "png"]
    elif v == "gif":
        pass  # handled by the renderer (palettegen/paletteuse)

    if v in ("gif", "png"):
        args += ["-an"]
    elif has_audio:
        if fmt == "webm":
            args += ["-c:a", "libopus", "-b:a", abr]
        elif fmt == "mov_prores" or fmt == "wav":
            args += ["-c:a", "pcm_s16le" if fmt == "wav" else "pcm_s24le"]
        elif fmt == "mp3":
            args += ["-c:a", "libmp3lame", "-b:a", abr if abr != "96k" else "128k"]
        elif fmt == "flac":
            args += ["-c:a", "flac"]
        else:
            args += ["-c:a", "aac", "-b:a", abr]
        args += ["-ar", "48000"]
    if v is None:
        args = ["-vn"] + args
    return args
