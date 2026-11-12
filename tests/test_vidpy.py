"""End-to-end tests. They synthesise their own media with FFmpeg, so no fixtures are needed."""
import shutil
import subprocess

import pytest

import vidpy
from vidpy import smart

pytestmark = pytest.mark.skipif(shutil.which("ffmpeg") is None, reason="ffmpeg not installed")


def _ff(*args):
    subprocess.run(["ffmpeg", "-v", "error", "-y", *args], check=True)


@pytest.fixture(scope="session")
def media(tmp_path_factory):
    d = tmp_path_factory.mktemp("media")
    _ff("-f", "lavfi", "-i", "testsrc2=s=640x360:r=25:d=4", "-f", "lavfi", "-i", "sine=f=440:d=4",
        "-shortest", "-c:v", "libx264", "-c:a", "aac", str(d / "a.mp4"))
    _ff("-f", "lavfi", "-i", "aevalsrc=0.5*sin(2*PI*300*t)*gt(mod(t\\,2)\\,1):d=6", "-f", "lavfi",
        "-i", "testsrc=s=320x180:d=6", "-shortest", "-c:v", "libx264", "-c:a", "aac", str(d / "talk.mp4"))
    _ff("-f", "lavfi", "-i", "gradients=s=800x600:d=1", "-frames:v", "1", str(d / "p.jpg"))
    _ff("-f", "lavfi", "-i", "sine=f=220:d=8", "-ac", "2", str(d / "m.mp3"))
    return d


def test_catalog_sizes():
    assert len(vidpy.VIDEO_EFFECTS) >= 75
    assert len(vidpy.AUDIO_EFFECTS) >= 40
    assert sum(t["available"] for t in vidpy.list_transitions()) >= 40


def test_full_timeline(media, tmp_path):
    p = vidpy.Project(width=640, height=360, fps=25)
    p.add_clip(media / "a.mp4", start=0.5, end=3).fx("cinematic").transition_to("circleopen", 0.5)
    p.add_clip(media / "p.jpg", duration=2).fx("ken_burns")
    p.add_clip(media / "a.mp4", end=2).set(speed=2, reverse=True).afx("pitch_shift", semitones=3)
    p.add_overlay(media / "p.jpg", x=0.85, y=0.15, scale=0.2, opacity=0.8, fade_in=0.3)
    p.add_text("Hello", duration=2, animation="slide_up", box=True)
    p.add_text("Typing", start=1, duration=2, animation="typewriter")
    p.add_audio(media / "m.mp3", volume=0.4, duck=True, loop=True, fade_out=1)
    p.afx("normalize")
    expected = 2.5 + 2 + 1 - 0.5
    assert abs(p.duration - expected) < 0.01
    out = p.render(tmp_path / "out.mp4", quality="draft")
    info = vidpy.probe(out)
    assert info.has_video and info.has_audio
    assert abs(info.duration - expected) < 0.15
    assert (info.width, info.height) == (640, 360)


@pytest.mark.parametrize("fmt", ["webm", "gif", "mp3", "wav", "mov_prores", "mp4_h265"])
def test_formats(media, tmp_path, fmt):
    p = vidpy.Project(width=320, height=180)
    p.add_clip(media / "a.mp4", end=1)
    out = p.render(tmp_path / "x", format=fmt, quality="draft")
    assert out.exists() and out.stat().st_size > 0


def test_frame_and_slice(media, tmp_path):
    p = vidpy.Project(width=320, height=180)
    p.add_clip(media / "a.mp4").fx("timecode")
    f = p.preview_frame(2.0, tmp_path / "f.jpg", height=180)
    assert f.exists()
    assert abs(p.slice(1, 3).clips[0].in_point - 1) < 1e-6


def test_json_roundtrip_and_codegen(media, tmp_path):
    p = vidpy.Project()
    p.add_clip(media / "a.mp4", start=1, end=2).fx("vhs")
    p.add_text("x")
    path = p.save(tmp_path / "proj.vidpy.json")
    q = vidpy.Project.load(path)
    assert q.to_dict() == p.to_dict()
    ns = {}
    exec(vidpy.to_python(q).replace("p.render(", "(lambda *a, **k: None)("), ns)  # generated code must be valid
    assert ns["p"].clips[0].effects[0]["id"] == "vhs"


def test_smart(media):
    assert smart.detect_silence(media / "talk.mp4")
    cut = smart.cut_silences(str(media / "talk.mp4"))
    assert 1 <= len(cut.clips) <= 4 and cut.duration < 6
    assert "integrated_lufs" in smart.loudness(media / "a.mp4")


def test_custom_effect_plugin(media, tmp_path):
    @vidpy.effect("test_plugin", "Test Plugin", params=[vidpy.Param("s", "float", 2, 0, 10)])
    def _(p, ctx):
        return f"gblur=sigma={p['s']}"

    p = vidpy.Project(width=320, height=180)
    p.add_clip(media / "a.mp4", end=1).fx("test_plugin", s=4)
    assert "gblur=sigma=4" in vidpy.command_string(p)
    p.render(tmp_path / "plug.mp4", quality="draft")


def test_preview_frame_inside_faded_overlay(media, tmp_path):
    """Regression: slicing into an overlay with fades produced a negative fade start."""
    p = vidpy.Project(width=320, height=180)
    p.add_clip(media / "a.mp4")
    p.add_overlay(media / "p.jpg", start=0.5, duration=2.5, fade_in=0.4, fade_out=0.4, rotation=-6)
    for t in (0.6, 1.5, 2.8):
        assert p.preview_frame(t, tmp_path / f"o{t}.jpg", height=180).exists()


def test_demo_project_builds(tmp_path):
    from vidpy.demo import make_demo

    proj, files = make_demo(tmp_path)
    assert files and proj.clips and proj.duration > 5
    proj.render(tmp_path / "demo.mp4", quality="draft", height=180, end=3)
