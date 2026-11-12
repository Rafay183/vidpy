"""Built-in audio effects (sound design, voice tools, mastering)."""
from __future__ import annotations

from . import ffmpeg
from .registry import Param as P
from .registry import audio_effect


def _f(x) -> str:
    return f"{x:.4f}".rstrip("0").rstrip(".") if isinstance(x, float) else str(x)


def pitch_chain(semitones: float, sr: int = 48000) -> str:
    """Pitch shift without changing duration."""
    if abs(semitones) < 1e-3:
        return "anull"
    ratio = 2 ** (semitones / 12)
    if ffmpeg.has_filter("rubberband"):
        return f"rubberband=pitch={_f(ratio)}:formant=preserved"
    tempo = 1 / ratio
    chain = [f"asetrate={int(sr * ratio)}", f"aresample={sr}"]
    chain += atempo_chain(tempo).split(",")
    return ",".join(chain)


def atempo_chain(speed: float) -> str:
    """atempo accepts 0.5..2 per instance (100 on new builds) — chain for any speed."""
    if abs(speed - 1) < 1e-4:
        return "anull"
    parts = []
    s = speed
    while s > 2.0:
        parts.append("atempo=2.0")
        s /= 2.0
    while s < 0.5:
        parts.append("atempo=0.5")
        s /= 0.5
    parts.append(f"atempo={_f(s)}")
    return ",".join(parts)


# --------------------------------------------------------------------------- Levels

@audio_effect("volume", "Volume", "Levels", [P("level", "float", 1.0, 0, 5, 0.01)], requires=["volume"])
def _(p, c):
    return f"volume={_f(p['level'])}"


@audio_effect("gain", "Gain (dB)", "Levels", [P("db", "float", 3, -40, 30, 0.5)], requires=["volume"])
def _(p, c):
    return f"volume={_f(p['db'])}dB"


@audio_effect("normalize", "Loudness Normalize (EBU R128)", "Levels",
              [P("target_lufs", "float", -14, -30, -5, 0.5), P("true_peak", "float", -1.5, -9, 0, 0.1)],
              "Broadcast/streaming loudness. -14 LUFS = YouTube/Spotify, -16 = podcasts.", ["loudnorm"])
def _(p, c):
    return f"loudnorm=I={_f(p['target_lufs'])}:TP={_f(p['true_peak'])}:LRA=11"


@audio_effect("compressor", "Compressor", "Levels", [
    P("threshold_db", "float", -18, -60, 0, 0.5), P("ratio", "float", 4, 1, 20, 0.1),
    P("attack_ms", "float", 10, 0.1, 500, 0.5), P("release_ms", "float", 120, 5, 2000, 5),
    P("makeup_db", "float", 4, 0, 24, 0.5)], requires=["acompressor"])
def _(p, c):
    thr = 10 ** (p["threshold_db"] / 20)
    mk = 10 ** (p["makeup_db"] / 20)
    return (f"acompressor=threshold={_f(thr)}:ratio={_f(p['ratio'])}:attack={_f(p['attack_ms'])}:"
            f"release={_f(p['release_ms'])}:makeup={_f(min(mk, 64.0))}")


@audio_effect("limiter", "Limiter", "Levels", [P("ceiling_db", "float", -1, -12, 0, 0.1)], requires=["alimiter"])
def _(p, c):
    return f"alimiter=limit={_f(10 ** (p['ceiling_db'] / 20))}:level=disabled"


@audio_effect("noise_gate", "Noise Gate", "Levels", [P("threshold_db", "float", -40, -80, -10, 1)], requires=["agate"])
def _(p, c):
    return f"agate=threshold={_f(10 ** (p['threshold_db'] / 20))}:ratio=4:attack=5:release=150"


@audio_effect("fade_in", "Fade In", "Levels", [P("duration", "float", 1.0, 0.05, 20, 0.05),
                                              P("curve", "choice", "tri", choices=["tri", "qsin", "exp", "log", "esin"])],
              requires=["afade"])
def _(p, c):
    return f"afade=t=in:st=0:d={_f(p['duration'])}:curve={p['curve']}"


@audio_effect("fade_out", "Fade Out", "Levels", [P("duration", "float", 1.0, 0.05, 20, 0.05),
                                                P("curve", "choice", "tri", choices=["tri", "qsin", "exp", "log", "esin"])],
              requires=["afade"])
def _(p, c):
    d = float(c.get("duration") or 0)
    return f"afade=t=out:st={_f(max(d - p['duration'], 0))}:d={_f(p['duration'])}:curve={p['curve']}"


# --------------------------------------------------------------------------- Voice / Cleanup

@audio_effect("denoise", "Noise Reduction", "Voice & Cleanup", [P("reduction_db", "float", 12, 1, 60, 1)],
              "FFT noise reduction — removes hiss, hum and room tone.", ["afftdn"])
def _(p, c):
    return f"afftdn=nr={_f(p['reduction_db'])}:nf=-40:tn=1"


@audio_effect("voice_enhance", "Voice Enhance (podcast chain)", "Voice & Cleanup", [P("strength", "float", 0.7, 0, 1, 0.01)],
              "High-pass, de-noise, presence boost, compression and loudness in one click.",
              ["highpass", "afftdn", "equalizer", "acompressor"])
def _(p, c):
    s = p["strength"]
    return (f"highpass=f=80,lowpass=f=14000,afftdn=nr={_f(6 + 12 * s)}:nf=-42,"
            f"equalizer=f=200:t=q:w=1:g={_f(-2 * s)},equalizer=f=3500:t=q:w=1.2:g={_f(4 * s)},"
            f"acompressor=threshold=0.1:ratio={_f(2 + 3 * s)}:attack=8:release=150:makeup=2")


@audio_effect("speech_normalize", "Speech Leveler", "Voice & Cleanup", [P("expansion", "float", 6, 1, 20, 0.5)],
              "Evens out quiet and loud speakers.", ["speechnorm"])
def _(p, c):
    return f"speechnorm=e={_f(p['expansion'])}:r=0.0001:l=1"


@audio_effect("de_ess", "De-esser", "Voice & Cleanup", [P("amount", "float", 0.5, 0, 1, 0.01)], requires=["deesser"])
def _(p, c):
    return f"deesser=i={_f(p['amount'])}:m=0.5:f=0.5"


@audio_effect("highpass", "High-pass (remove rumble)", "Voice & Cleanup", [P("freq", "float", 100, 20, 2000, 5)], requires=["highpass"])
def _(p, c):
    return f"highpass=f={_f(p['freq'])}"


@audio_effect("lowpass", "Low-pass (remove hiss)", "Voice & Cleanup", [P("freq", "float", 8000, 200, 20000, 50)], requires=["lowpass"])
def _(p, c):
    return f"lowpass=f={_f(p['freq'])}"


@audio_effect("declick", "De-click / De-crackle", "Voice & Cleanup", [], requires=["adeclick"])
def _(p, c):
    return "adeclick"


# --------------------------------------------------------------------------- EQ

@audio_effect("bass_boost", "Bass Boost", "EQ", [P("gain_db", "float", 6, -20, 20, 0.5), P("freq", "float", 100, 30, 300, 5)],
              requires=["bass"])
def _(p, c):
    return f"bass=g={_f(p['gain_db'])}:f={_f(p['freq'])}"


@audio_effect("treble", "Treble / Air", "EQ", [P("gain_db", "float", 4, -20, 20, 0.5), P("freq", "float", 8000, 2000, 16000, 100)],
              requires=["treble"])
def _(p, c):
    return f"treble=g={_f(p['gain_db'])}:f={_f(p['freq'])}"


@audio_effect("eq_3band", "3-Band EQ", "EQ", [P("low_db", "float", 0, -20, 20, 0.5), P("mid_db", "float", 0, -20, 20, 0.5),
                                              P("high_db", "float", 0, -20, 20, 0.5)], requires=["equalizer"])
def _(p, c):
    return (f"equalizer=f=120:t=q:w=0.8:g={_f(p['low_db'])},equalizer=f=1200:t=q:w=0.9:g={_f(p['mid_db'])},"
            f"equalizer=f=9000:t=q:w=0.8:g={_f(p['high_db'])}")


@audio_effect("eq_10band", "10-Band Graphic EQ", "EQ",
              [P(f"b{f}", "float", 0, -20, 20, 0.5, label=(f"{f//1000}k" if f >= 1000 else str(f)) + " Hz")
               for f in (31, 62, 125, 250, 500, 1000, 2000, 4000, 8000, 16000)], requires=["equalizer"])
def _(p, c):
    bands = [f"equalizer=f={k[1:]}:t=o:w=1:g={_f(v)}" for k, v in p.items() if abs(v) > 0.01]
    return ",".join(bands) or "anull"


# --------------------------------------------------------------------------- Creative / FX

@audio_effect("pitch_shift", "Pitch Shift", "Creative", [P("semitones", "float", 3, -24, 24, 0.5)],
              "Change pitch without changing speed.", ["asetrate", "atempo"])
def _(p, c):
    return pitch_chain(p["semitones"])


@audio_effect("chipmunk", "Chipmunk Voice", "Creative", [], requires=["asetrate"])
def _(p, c):
    return pitch_chain(7)


@audio_effect("deep_voice", "Deep / Monster Voice", "Creative", [P("semitones", "float", -6, -12, -1, 0.5)], requires=["asetrate"])
def _(p, c):
    return pitch_chain(p["semitones"])


@audio_effect("robot", "Robot Voice", "Creative", [], requires=["afftfilt"])
def _(p, c):
    return "afftfilt=real='hypot(re,im)*sin(0)':imag='hypot(re,im)*cos(0)':win_size=512:overlap=0.75"


@audio_effect("echo", "Echo", "Creative", [P("delay_ms", "float", 350, 20, 3000, 10), P("decay", "float", 0.4, 0, 0.95, 0.01)],
              requires=["aecho"])
def _(p, c):
    return f"aecho=0.8:0.85:{_f(p['delay_ms'])}:{_f(p['decay'])}"


@audio_effect("reverb", "Reverb", "Creative", [P("room", "choice", "hall", choices=["room", "hall", "cathedral", "plate"]),
                                              P("mix", "float", 0.4, 0, 1, 0.01)], requires=["aecho"])
def _(p, c):
    taps = {"room": ("40|67|93|131", "0.35|0.28|0.22|0.15"),
            "hall": ("60|111|167|233|301", "0.42|0.35|0.28|0.21|0.14"),
            "cathedral": ("120|230|370|520|700|900", "0.5|0.44|0.38|0.31|0.25|0.18"),
            "plate": ("23|41|59|83|109", "0.45|0.38|0.31|0.24|0.17")}[p["room"]]
    m = p["mix"]
    decays = "|".join(_f(float(d) * m * 1.6) for d in taps[1].split("|"))
    return f"aecho=0.9:0.9:{taps[0]}:{decays}"


@audio_effect("telephone", "Telephone / Walkie-talkie", "Creative", [], requires=["highpass", "lowpass"])
def _(p, c):
    return "highpass=f=400,lowpass=f=3200,acompressor=threshold=0.1:ratio=6,volume=1.5"


@audio_effect("radio", "AM Radio", "Creative", [], requires=["highpass", "lowpass", "acrusher"])
def _(p, c):
    return "highpass=f=300,lowpass=f=4500,acrusher=bits=10:mode=log:aa=1,volume=1.3"


@audio_effect("underwater", "Underwater / Muffled", "Creative", [P("freq", "float", 500, 150, 2000, 10)], requires=["lowpass"])
def _(p, c):
    return f"lowpass=f={_f(p['freq'])},lowpass=f={_f(p['freq'])},chorus=0.5:0.9:50:0.4:0.25:2"


@audio_effect("bitcrush", "Bitcrusher / Lo-fi", "Creative", [P("bits", "float", 8, 1, 16, 0.5), P("mix", "float", 0.8, 0, 1, 0.01)],
              requires=["acrusher"])
def _(p, c):
    return f"acrusher=bits={_f(p['bits'])}:mix={_f(p['mix'])}:mode=log:aa=1"


@audio_effect("chorus", "Chorus", "Creative", [P("depth", "float", 0.4, 0.05, 1, 0.01)], requires=["chorus"])
def _(p, c):
    d = p["depth"]
    return f"chorus=0.6:0.9:50|60|40:{_f(d)}|{_f(d*0.8)}|{_f(d*1.1)}:0.25|0.4|0.3:2|2.3|1.3"


@audio_effect("flanger", "Flanger", "Creative", [P("depth", "float", 4, 0, 10, 0.1), P("speed", "float", 0.5, 0.1, 10, 0.1)],
              requires=["flanger"])
def _(p, c):
    return f"flanger=depth={_f(p['depth'])}:speed={_f(p['speed'])}"


@audio_effect("phaser", "Phaser", "Creative", [P("speed", "float", 0.5, 0.1, 2, 0.05)], requires=["aphaser"])
def _(p, c):
    return f"aphaser=speed={_f(p['speed'])}:type=t"


@audio_effect("tremolo", "Tremolo", "Creative", [P("freq", "float", 5, 0.1, 20, 0.1), P("depth", "float", 0.5, 0, 1, 0.01)],
              requires=["tremolo"])
def _(p, c):
    return f"tremolo=f={_f(p['freq'])}:d={_f(p['depth'])}"


@audio_effect("vibrato", "Vibrato", "Creative", [P("freq", "float", 5, 0.1, 20, 0.1), P("depth", "float", 0.4, 0, 1, 0.01)],
              requires=["vibrato"])
def _(p, c):
    return f"vibrato=f={_f(p['freq'])}:d={_f(p['depth'])}"


# --------------------------------------------------------------------------- Stereo / Spatial

@audio_effect("stereo_widen", "Stereo Widener", "Spatial", [P("amount", "float", 2.0, 0, 6, 0.1)], requires=["extrastereo"])
def _(p, c):
    return f"extrastereo=m={_f(p['amount'])}"


@audio_effect("audio_8d", "8D Audio (rotating)", "Spatial", [P("speed_hz", "float", 0.12, 0.02, 2, 0.01)],
              "Sound circles around the listener — best on headphones.", ["apulsator"])
def _(p, c):
    return f"apulsator=hz={_f(p['speed_hz'])}:amount=0.85"


@audio_effect("pan", "Pan (L/R balance)", "Spatial", [P("position", "float", 0, -1, 1, 0.01)], requires=["pan"])
def _(p, c):
    x = p["position"]
    l, r = _f(min(1.0, 1 - x)), _f(min(1.0, 1 + x))
    return f"pan=stereo|c0={l}*c0|c1={r}*c1"


@audio_effect("mono", "Mono (fold down)", "Spatial", [], requires=["pan"])
def _(p, c):
    return "pan=stereo|c0=0.5*c0+0.5*c1|c1=0.5*c0+0.5*c1"


@audio_effect("swap_channels", "Swap L/R", "Spatial", [], requires=["pan"])
def _(p, c):
    return "pan=stereo|c0=c1|c1=c0"


@audio_effect("crystalizer", "Crystalizer (clarity)", "Spatial", [P("intensity", "float", 2, 0, 10, 0.1)], requires=["crystalizer"])
def _(p, c):
    return f"crystalizer=i={_f(p['intensity'])}"


@audio_effect("custom", "Custom FFmpeg Audio Filter", "Expert", [P("filter", "text", "anull")],
              "Any FFmpeg audio filter chain (e.g. 'aecho=0.8:0.9:500:0.3,bass=g=5').")
def _(p, c):
    return (p["filter"] or "anull").strip() or "anull"
