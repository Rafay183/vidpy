"""Built-in video effects. Each returns an FFmpeg filter chain string.

ctx keys available to builders: w, h (project size), fps, duration (clip duration).
"""
from __future__ import annotations

from .registry import Param as P
from .registry import effect


def col(c: str, alpha: float | None = None) -> str:
    c = (c or "#000000").strip()
    if c.startswith("#"):
        c = "0x" + c[1:]
    return f"{c}@{alpha:.3f}" if alpha is not None else c


def _f(x: float) -> str:
    return f"{x:.4f}".rstrip("0").rstrip(".") if isinstance(x, float) else str(x)


# =========================================================================== Color & Light

@effect("brightness", "Brightness", "Color", [P("amount", "float", 0.1, -1, 1, 0.01)],
        "Lift or lower overall brightness.", ["eq"])
def _(p, c):
    return f"eq=brightness={_f(p['amount'])}"


@effect("contrast", "Contrast", "Color", [P("amount", "float", 1.2, 0, 3, 0.01)], requires=["eq"])
def _(p, c):
    return f"eq=contrast={_f(p['amount'])}"


@effect("saturation", "Saturation", "Color", [P("amount", "float", 1.4, 0, 3, 0.01)], requires=["eq"])
def _(p, c):
    return f"eq=saturation={_f(p['amount'])}"


@effect("gamma", "Gamma", "Color", [P("amount", "float", 1.0, 0.1, 4, 0.01)], requires=["eq"])
def _(p, c):
    return f"eq=gamma={_f(p['amount'])}"


@effect("exposure", "Exposure", "Color", [P("stops", "float", 0.5, -3, 3, 0.05),
                                          P("black", "float", 0.0, -0.1, 0.1, 0.005)],
        "Photographic exposure in stops.", ["exposure"])
def _(p, c):
    return f"format=gbrpf32le,exposure=exposure={_f(p['stops'])}:black={_f(p['black'])},format=yuv420p"


@effect("color_correct", "Color Correct (all-in-one)", "Color", [
    P("brightness", "float", 0, -1, 1, 0.01), P("contrast", "float", 1, 0, 3, 0.01),
    P("saturation", "float", 1, 0, 3, 0.01), P("gamma", "float", 1, 0.1, 4, 0.01),
    P("gamma_r", "float", 1, 0.1, 4, 0.01), P("gamma_g", "float", 1, 0.1, 4, 0.01),
    P("gamma_b", "float", 1, 0.1, 4, 0.01)], "Primary color wheel in one node.", ["eq"])
def _(p, c):
    return ("eq=" + ":".join(f"{k}={_f(p[k])}" for k in
                             ("brightness", "contrast", "saturation", "gamma", "gamma_r", "gamma_g", "gamma_b")))


@effect("hue_shift", "Hue Shift", "Color", [P("degrees", "float", 30, -180, 180, 1)], requires=["hue"])
def _(p, c):
    return f"hue=h={_f(p['degrees'])}"


@effect("temperature", "White Balance / Temperature", "Color",
        [P("kelvin", "int", 5000, 1000, 40000, 100), P("mix", "float", 1.0, 0, 1, 0.01)],
        "Lower = warmer, higher = cooler (6500 is neutral).", ["colortemperature"])
def _(p, c):
    return f"colortemperature=temperature={p['kelvin']}:mix={_f(p['mix'])}"


@effect("tint", "Tint (green/magenta)", "Color", [P("amount", "float", 0.1, -1, 1, 0.01)],
        requires=["colorbalance"])
def _(p, c):
    a = p["amount"]
    return f"colorbalance=gm={_f(-a)}:rm={_f(a / 2)}:bm={_f(a / 2)}"


@effect("vibrance", "Vibrance", "Color", [P("intensity", "float", 0.5, -2, 2, 0.01)],
        "Smart saturation that protects skin tones.", ["vibrance"])
def _(p, c):
    return f"vibrance=intensity={_f(p['intensity'])}"


@effect("color_balance", "Color Balance (3-way)", "Color", [
    P("shadows_r", "float", 0, -1, 1, 0.01), P("shadows_g", "float", 0, -1, 1, 0.01),
    P("shadows_b", "float", 0, -1, 1, 0.01), P("mid_r", "float", 0, -1, 1, 0.01),
    P("mid_g", "float", 0, -1, 1, 0.01), P("mid_b", "float", 0, -1, 1, 0.01),
    P("high_r", "float", 0, -1, 1, 0.01), P("high_g", "float", 0, -1, 1, 0.01),
    P("high_b", "float", 0, -1, 1, 0.01), P("preserve_lightness", "bool", True)],
    "Lift / gamma / gain style 3-way color balance.", ["colorbalance"])
def _(p, c):
    m = {"shadows": "s", "mid": "m", "high": "h"}
    parts = [f"{ch}{m[r]}={_f(p[f'{r}_{ch}'])}" for r in m for ch in "rgb"]
    return "colorbalance=" + ":".join(parts) + f":pl={int(p['preserve_lightness'])}"


@effect("curves", "Curves Preset", "Color", [P("preset", "choice", "medium_contrast", choices=[
    "none", "color_negative", "cross_process", "darker", "increase_contrast", "lighter",
    "linear_contrast", "medium_contrast", "negative", "strong_contrast", "vintage"])],
    requires=["curves"])
def _(p, c):
    return f"curves=preset={p['preset']}"


@effect("lift_blacks", "Lift Blacks / Crush Whites", "Color",
        [P("black", "float", 0.08, 0, 0.5, 0.01), P("white", "float", 0.95, 0.5, 1, 0.01)],
        "Matte film look by raising the black point.", ["curves"])
def _(p, c):
    return f"curves=all='0/{_f(p['black'])} 1/{_f(p['white'])}'"


@effect("shadows_highlights", "Shadows / Highlights", "Color",
        [P("shadows", "float", 0.15, -0.5, 0.5, 0.01), P("highlights", "float", -0.1, -0.5, 0.5, 0.01)],
        "Recover detail in dark and bright areas.", ["curves"])
def _(p, c):
    s = min(max(0.25 + p["shadows"], 0.01), 0.99)
    h = min(max(0.75 + p["highlights"], 0.01), 0.99)
    return f"curves=all='0/0 0.25/{_f(s)} 0.75/{_f(h)} 1/1'"


@effect("auto_levels", "Auto Levels", "Color", [P("strength", "float", 1.0, 0, 1, 0.01)],
        "Automatic contrast stretch per frame (smoothed).", ["normalize"])
def _(p, c):
    return f"normalize=smoothing=30:independence=0:strength={_f(p['strength'])}"


@effect("histogram_eq", "Histogram Equalize", "Color", [P("strength", "float", 0.2, 0, 1, 0.01)],
        requires=["histeq"])
def _(p, c):
    return f"histeq=strength={_f(p['strength'])}:intensity=0.21"


@effect("lut", "Apply LUT (.cube/.3dl)", "Color", [P("file", "file", ""), P("intensity", "float", 1, 0, 1, 0.01)],
        "Load any professional 3D LUT file.", ["lut3d"])
def _(p, c):
    from .ffmpeg import esc_path
    if not p["file"]:
        return "null"
    if p["intensity"] >= 0.999:
        return f"lut3d=file={esc_path(p['file'])}"
    return (f"split[lo][lg];[lg]lut3d=file={esc_path(p['file'])}[lt];"
            f"[lo][lt]blend=all_mode=normal:all_opacity={_f(p['intensity'])}")


@effect("black_white", "Black & White", "Color", [P("contrast", "float", 1.15, 0.5, 2, 0.01)], requires=["hue", "eq"])
def _(p, c):
    return f"hue=s=0,eq=contrast={_f(p['contrast'])}"


@effect("sepia", "Sepia", "Color", [P("amount", "float", 1.0, 0, 1, 0.01)], requires=["colorchannelmixer"])
def _(p, c):
    a = p["amount"]
    def m(v, base):
        return _f(base * (1 - a) + v * a)
    return ("colorchannelmixer="
            f"rr={m(.393, 1)}:rg={m(.769, 0)}:rb={m(.189, 0)}:"
            f"gr={m(.349, 0)}:gg={m(.686, 1)}:gb={m(.168, 0)}:"
            f"br={m(.272, 0)}:bg={m(.534, 0)}:bb={m(.131, 1)}")


@effect("colorize", "Colorize / Duotone", "Color",
        [P("hue", "float", 200, 0, 360, 1), P("saturation", "float", 0.6, 0, 1, 0.01),
         P("mix", "float", 0.8, 0, 1, 0.01)], requires=["colorize"])
def _(p, c):
    return f"colorize=hue={_f(p['hue'])}:saturation={_f(p['saturation'])}:lightness=0.5:mix={_f(p['mix'])}"


@effect("selective_color", "Selective Color Boost", "Color",
        [P("color", "choice", "reds", choices=["reds", "yellows", "greens", "cyans", "blues", "magentas"]),
         P("saturation", "float", 0.5, -1, 1, 0.01), P("hue", "float", 0, -180, 180, 1)],
        "Change saturation/hue of one color family only.", ["huesaturation"])
def _(p, c):
    code = {"reds": "r", "yellows": "y", "greens": "g", "cyans": "c", "blues": "b", "magentas": "m"}[p["color"]]
    return f"huesaturation=hue={_f(p['hue'])}:saturation={_f(p['saturation'])}:colors={code}"


@effect("invert", "Invert / Negative", "Color", [], requires=["negate"])
def _(p, c):
    return "negate"


@effect("posterize", "Posterize", "Color", [P("levels", "int", 6, 2, 32)], requires=["lutrgb"])
def _(p, c):
    n = p["levels"]
    step = 255 / (n - 1)
    e = f"'floor(val/{_f(256 / n)})*{_f(step)}'"
    return f"lutrgb=r={e}:g={e}:b={e}"


# =========================================================================== Cinematic Looks

@effect("cinematic", "Cinematic Teal & Orange", "Looks",
        [P("intensity", "float", 0.7, 0, 1, 0.01), P("letterbox", "bool", True)],
        "Hollywood blockbuster grade with optional 2.39:1 bars.", ["colorbalance", "eq"])
def _(p, c):
    i = p["intensity"]
    chain = (f"colorbalance=rs={_f(-0.15*i)}:bs={_f(0.2*i)}:rh={_f(0.15*i)}:bh={_f(-0.15*i)}:"
             f"gm={_f(-0.03*i)},eq=contrast={_f(1+0.15*i)}:saturation={_f(1+0.15*i)},"
             f"vignette=angle={_f(0.4*i + 0.05)}")
    if p["letterbox"]:
        chain += ",drawbox=x=0:y=0:w=iw:h='(ih-iw/2.39)/2':color=black:t=fill," \
                 "drawbox=x=0:y='ih-(ih-iw/2.39)/2':w=iw:h='(ih-iw/2.39)/2':color=black:t=fill"
    return chain


@effect("letterbox", "Letterbox Bars", "Looks",
        [P("ratio", "choice", "2.39", choices=["1.85", "2", "2.2", "2.39", "2.76"]),
         P("color", "color", "#000000")], requires=["drawbox"])
def _(p, c):
    r, col_ = p["ratio"], col(p["color"])
    bar = f"max((ih-iw/{r})/2,0)"
    return (f"drawbox=x=0:y=0:w=iw:h='{bar}':color={col_}:t=fill,"
            f"drawbox=x=0:y='ih-{bar}':w=iw:h='{bar}':color={col_}:t=fill")


@effect("vintage", "Vintage Film", "Looks", [P("intensity", "float", 0.8, 0, 1, 0.01)],
        requires=["curves", "noise", "vignette"])
def _(p, c):
    i = p["intensity"]
    return (f"curves=preset=vintage,eq=saturation={_f(1-0.3*i)},"
            f"noise=alls={int(12*i)}:allf=t,vignette=angle={_f(0.3+0.3*i)}")


@effect("noir", "Film Noir", "Looks", [P("contrast", "float", 1.5, 1, 3, 0.01)], requires=["hue", "eq", "vignette"])
def _(p, c):
    return f"hue=s=0,eq=contrast={_f(p['contrast'])}:brightness=-0.05,vignette=angle=0.7"


@effect("cyberpunk", "Cyberpunk Neon", "Looks", [P("intensity", "float", 0.8, 0, 1, 0.01)],
        requires=["colorbalance", "eq"])
def _(p, c):
    i = p["intensity"]
    return (f"colorbalance=rs={_f(0.25*i)}:bs={_f(0.35*i)}:gs={_f(-0.2*i)}:rh={_f(0.2*i)}:bh={_f(0.3*i)}:"
            f"gh={_f(-0.15*i)},eq=contrast={_f(1+0.25*i)}:saturation={_f(1+0.6*i)}")


@effect("warm_sunset", "Golden Hour", "Looks", [P("intensity", "float", 0.7, 0, 1, 0.01)],
        requires=["colortemperature", "eq"])
def _(p, c):
    i = p["intensity"]
    return f"colortemperature=temperature={int(6500-3000*i)},eq=saturation={_f(1+0.2*i)}:gamma={_f(1+0.05*i)}"


@effect("cold_blue", "Cold Blue", "Looks", [P("intensity", "float", 0.7, 0, 1, 0.01)],
        requires=["colortemperature", "eq"])
def _(p, c):
    i = p["intensity"]
    return f"colortemperature=temperature={int(6500+6000*i)},eq=saturation={_f(1-0.25*i)}:contrast={_f(1+0.1*i)}"


@effect("matrix", "Matrix Green", "Looks", [P("intensity", "float", 0.8, 0, 1, 0.01)], requires=["colorbalance", "eq"])
def _(p, c):
    i = p["intensity"]
    return f"colorbalance=gs={_f(0.3*i)}:gm={_f(0.25*i)}:gh={_f(0.1*i)}:rm={_f(-0.15*i)}:bm={_f(-0.15*i)},eq=contrast={_f(1+0.2*i)}"


@effect("bleach_bypass", "Bleach Bypass", "Looks", [P("intensity", "float", 0.7, 0, 1, 0.01)], requires=["eq", "curves"])
def _(p, c):
    i = p["intensity"]
    return f"eq=saturation={_f(1-0.6*i)}:contrast={_f(1+0.4*i)},curves=preset=increase_contrast"


@effect("faded_film", "Faded Matte", "Looks", [P("fade", "float", 0.12, 0, 0.4, 0.01)], requires=["curves", "eq"])
def _(p, c):
    return f"curves=all='0/{_f(p['fade'])} 0.5/0.5 1/{_f(1-p['fade']/2)}',eq=saturation=0.85"


@effect("vhs", "VHS Tape", "Looks", [P("intensity", "float", 0.8, 0, 1, 0.01)],
        requires=["rgbashift", "noise", "gblur", "eq"])
def _(p, c):
    i = p["intensity"]
    s = max(int(6 * i), 1)
    return (f"rgbashift=rh={s}:bh={-s},gblur=sigma={_f(0.4+0.8*i)},"
            f"noise=alls={int(18*i)}:allf=t,eq=saturation={_f(1+0.3*i)}:contrast={_f(1-0.1*i)}")


@effect("old_film", "Old Film Flicker", "Looks", [P("intensity", "float", 0.8, 0, 1, 0.01)],
        requires=["colorchannelmixer", "noise", "eq", "vignette"])
def _(p, c):
    i = p["intensity"]
    return (f"colorchannelmixer=.393:.769:.189:0:.349:.686:.168:0:.272:.534:.131,"
            f"noise=alls={int(25*i)}:allf=t+u,"
            f"eq=brightness='{_f(0.04*i)}*sin(t*37)':eval=frame,vignette=angle={_f(0.4+0.3*i)}")


@effect("film_grain", "Film Grain", "Looks", [P("amount", "int", 12, 0, 60)], requires=["noise"])
def _(p, c):
    return f"noise=alls={p['amount']}:allf=t"


@effect("vignette", "Vignette", "Looks", [P("angle", "float", 0.5, 0, 1.5, 0.01)], requires=["vignette"])
def _(p, c):
    return f"vignette=angle={_f(p['angle'])}"


@effect("glow", "Bloom / Glow", "Looks", [P("radius", "float", 12, 1, 60, 0.5), P("strength", "float", 0.45, 0, 1, 0.01)],
        "Soft dreamy highlight bloom.", ["gblur", "blend"])
def _(p, c):
    return (f"split[gb][gg];[gg]gblur=sigma={_f(p['radius'])}[gl];"
            f"[gb][gl]blend=all_mode=screen:all_opacity={_f(p['strength'])}")


@effect("dreamy", "Dreamy Soft Focus", "Looks", [P("strength", "float", 0.5, 0, 1, 0.01)], requires=["gblur", "blend"])
def _(p, c):
    return (f"split[db][dg];[dg]gblur=sigma=20,eq=brightness=0.06[dl];"
            f"[db][dl]blend=all_mode=softlight:all_opacity={_f(p['strength'])},eq=saturation=1.1")


# =========================================================================== Blur & Detail

@effect("blur", "Gaussian Blur", "Blur & Sharpen", [P("sigma", "float", 5, 0, 100, 0.5)], requires=["gblur"])
def _(p, c):
    return f"gblur=sigma={_f(p['sigma'])}"


@effect("box_blur", "Box Blur", "Blur & Sharpen", [P("radius", "int", 6, 1, 50)], requires=["boxblur"])
def _(p, c):
    return f"boxblur=luma_radius={p['radius']}:luma_power=1"


@effect("motion_blur", "Motion Blur (frame blend)", "Blur & Sharpen", [P("frames", "int", 4, 2, 10)], requires=["tmix"])
def _(p, c):
    return f"tmix=frames={p['frames']}"


@effect("sharpen", "Sharpen", "Blur & Sharpen", [P("amount", "float", 1.0, 0, 5, 0.05), P("size", "choice", "5", choices=["3", "5", "7", "9"])],
        requires=["unsharp"])
def _(p, c):
    s = p["size"]
    return f"unsharp=luma_msize_x={s}:luma_msize_y={s}:luma_amount={_f(p['amount'])}"


@effect("denoise", "Denoise (fast)", "Blur & Sharpen", [P("strength", "float", 4, 0, 20, 0.5)], requires=["hqdn3d"])
def _(p, c):
    s = p["strength"]
    return f"hqdn3d={_f(s)}:{_f(s*0.75)}:{_f(s*1.5)}:{_f(s*1.1)}"


@effect("denoise_hq", "Denoise (high quality, slow)", "Blur & Sharpen", [P("strength", "float", 3, 1, 15, 0.5)], requires=["nlmeans"])
def _(p, c):
    return f"nlmeans=s={_f(p['strength'])}:p=5:r=11"


@effect("pixelate", "Pixelate / Censor", "Blur & Sharpen", [P("block", "int", 16, 2, 128)], requires=["pixelize"])
def _(p, c):
    return f"pixelize=width={p['block']}:height={p['block']}"


@effect("blur_region", "Blur a Region (faces / plates)", "Blur & Sharpen", [
    P("x", "float", 0.35, 0, 1, 0.01), P("y", "float", 0.2, 0, 1, 0.01),
    P("width", "float", 0.3, 0.01, 1, 0.01), P("height", "float", 0.3, 0.01, 1, 0.01),
    P("sigma", "float", 25, 1, 80, 1)], "Box region in relative coordinates.", ["gblur", "overlay", "crop"])
def _(p, c):
    w, h = c.get("w", 1920), c.get("h", 1080)
    cw, ch = max(int(w * p["width"]) // 2 * 2, 2), max(int(h * p["height"]) // 2 * 2, 2)
    cx, cy = int(w * p["x"]), int(h * p["y"])
    return (f"split[rb][rr];[rr]crop={cw}:{ch}:{cx}:{cy},gblur=sigma={_f(p['sigma'])}[rbl];"
            f"[rb][rbl]overlay={cx}:{cy}")


# =========================================================================== Stylize

@effect("edge_detect", "Edge Detect / Sketch", "Stylize", [P("mode", "choice", "wires", choices=["wires", "colormix", "canny"])],
        requires=["edgedetect"])
def _(p, c):
    return f"edgedetect=mode={p['mode']}:low=0.1:high=0.3"


@effect("cartoon", "Cartoon", "Stylize", [P("levels", "int", 8, 3, 24)], requires=["edgedetect", "lutrgb"])
def _(p, c):
    n = p["levels"]
    e = f"'floor(val/{_f(256/n)})*{_f(255/(n-1))}'"
    return f"hqdn3d=8:8:4:4,lutrgb=r={e}:g={e}:b={e},edgedetect=mode=colormix:high=0.15,eq=saturation=1.6"


@effect("emboss", "Emboss", "Stylize", [], requires=["convolution"])
def _(p, c):
    return "convolution='-2 -1 0 -1 1 1 0 1 2:-2 -1 0 -1 1 1 0 1 2:-2 -1 0 -1 1 1 0 1 2:-2 -1 0 -1 1 1 0 1 2'"


@effect("glitch", "Digital Glitch", "Stylize", [P("intensity", "float", 0.7, 0, 1, 0.01)], requires=["rgbashift", "noise"])
def _(p, c):
    i = p["intensity"]
    s = max(int(14 * i), 1)
    return f"rgbashift=rh={s}:gv={-s//2}:bh={-s},noise=c0s={int(30*i)}:c0f=t+u"


@effect("chromatic_aberration", "Chromatic Aberration", "Stylize", [P("shift", "int", 4, 0, 40)], requires=["rgbashift"])
def _(p, c):
    s = p["shift"]
    return f"rgbashift=rh={s}:bh={-s}"


@effect("mirror", "Mirror", "Stylize", [P("mode", "choice", "left", choices=["left", "right", "top", "bottom"])],
        requires=["crop", "hflip", "hstack"])
def _(p, c):
    m = p["mode"]
    if m in ("left", "right"):
        crop = "crop=iw/2:ih:0:0" if m == "left" else "crop=iw/2:ih:iw/2:0"
        order = "[ma][mb]" if m == "left" else "[mb][ma]"
        return f"{crop},split[ma][mf];[mf]hflip[mb];{order}hstack"
    crop = "crop=iw:ih/2:0:0" if m == "top" else "crop=iw:ih/2:0:ih/2"
    order = "[ma][mb]" if m == "top" else "[mb][ma]"
    return f"{crop},split[ma][mf];[mf]vflip[mb];{order}vstack"


@effect("thermal", "Thermal Vision", "Stylize", [], requires=["pseudocolor"])
def _(p, c):
    return "format=yuv420p,pseudocolor=preset=heat"


@effect("night_vision", "Night Vision", "Stylize", [P("intensity", "float", 0.8, 0, 1, 0.01)],
        requires=["hue", "colorbalance", "noise", "vignette"])
def _(p, c):
    i = p["intensity"]
    return (f"hue=s=0,eq=brightness={_f(0.1*i)}:contrast={_f(1+0.3*i)},"
            f"colorchannelmixer=rr=0.2:gg=1:bb=0.2,noise=alls={int(20*i)}:allf=t,vignette=angle=0.8")


@effect("monochrome_tint", "Monochrome Tint", "Stylize", [P("color", "color", "#3a7bd5"), P("mix", "float", 0.6, 0, 1, 0.01)],
        requires=["hue", "colorchannelmixer"])
def _(p, c):
    hx = (p["color"] or "#3a7bd5").lstrip("#")
    try:
        r, g, b = (int(hx[i:i+2], 16) / 255 for i in (0, 2, 4))
    except ValueError:
        r, g, b = 0.23, 0.48, 0.84
    m = p["mix"]
    k = lambda v: _f((1 - m) + m * v * 1.6)
    return f"hue=s=0,colorchannelmixer=rr={k(r)}:gg={k(g)}:bb={k(b)}"


# =========================================================================== Transform

@effect("crop", "Crop", "Transform", [
    P("left", "float", 0, 0, 0.49, 0.005), P("right", "float", 0, 0, 0.49, 0.005),
    P("top", "float", 0, 0, 0.49, 0.005), P("bottom", "float", 0, 0, 0.49, 0.005)],
    "Crop edges (fractions of size). The clip is refit to the frame afterwards.", ["crop"])
def _(p, c):
    l, r, t, b = p["left"], p["right"], p["top"], p["bottom"]
    return (f"crop=w='trunc(iw*{_f(1-l-r)}/2)*2':h='trunc(ih*{_f(1-t-b)}/2)*2':"
            f"x='iw*{_f(l)}':y='ih*{_f(t)}'")


@effect("zoom", "Zoom / Punch-in", "Transform", [P("factor", "float", 1.3, 1, 5, 0.01),
                                                  P("center_x", "float", 0.5, 0, 1, 0.01),
                                                  P("center_y", "float", 0.5, 0, 1, 0.01)], requires=["crop"])
def _(p, c):
    z, cx, cy = p["factor"], p["center_x"], p["center_y"]
    return (f"crop=w='trunc(iw/{_f(z)}/2)*2':h='trunc(ih/{_f(z)}/2)*2':"
            f"x='min(max(iw*{_f(cx)}-ow/2,0),iw-ow)':y='min(max(ih*{_f(cy)}-oh/2,0),ih-oh)'")


@effect("ken_burns", "Ken Burns (animated zoom)", "Transform", [
    P("start_zoom", "float", 1.0, 1, 4, 0.01), P("end_zoom", "float", 1.3, 1, 4, 0.01),
    P("direction", "choice", "center", choices=["center", "left", "right", "up", "down"])],
    "Smooth pan & zoom over the clip duration (great for photos).", ["scale", "zoompan"])
def _(p, c):
    d = max(float(c.get("duration") or 5), 0.1)
    w, h, fps = int(c.get("w", 1920)), int(c.get("h", 1080)), float(c.get("fps") or 30)
    z0, z1 = p["start_zoom"], p["end_zoom"]
    prog = f"min(it/{_f(d)},1)"
    z = f"{_f(z0)}+({_f(z1 - z0)})*{prog}"
    pos = {"center": ("iw/2-iw/zoom/2", "ih/2-ih/zoom/2"),
           "left": (f"(iw-iw/zoom)*(1-{prog})", "ih/2-ih/zoom/2"),
           "right": (f"(iw-iw/zoom)*{prog}", "ih/2-ih/zoom/2"),
           "up": ("iw/2-iw/zoom/2", f"(ih-ih/zoom)*(1-{prog})"),
           "down": ("iw/2-iw/zoom/2", f"(ih-ih/zoom)*{prog}")}[p["direction"]]
    # upscale first so sub-pixel motion stays smooth, then zoompan one output frame per input frame
    return (f"scale={w * 2}:{h * 2}:flags=bicubic,"
            f"zoompan=z='{z}':x='{pos[0]}':y='{pos[1]}':d=1:s={w}x{h}:fps={_f(fps)}")


@effect("rotate", "Rotate", "Transform", [P("degrees", "float", 5, -180, 180, 0.5), P("fill", "color", "#000000")],
        requires=["rotate"])
def _(p, c):
    return f"rotate=a={_f(p['degrees'])}*PI/180:fillcolor={col(p['fill'])}"


@effect("rotate90", "Rotate 90° / 180°", "Transform", [P("turns", "choice", "90", choices=["90", "180", "270"])],
        requires=["transpose"])
def _(p, c):
    return {"90": "transpose=1", "180": "hflip,vflip", "270": "transpose=2"}[p["turns"]]


@effect("flip_h", "Flip Horizontal", "Transform", [], requires=["hflip"])
def _(p, c):
    return "hflip"


@effect("flip_v", "Flip Vertical", "Transform", [], requires=["vflip"])
def _(p, c):
    return "vflip"


@effect("camera_shake", "Camera Shake / Handheld", "Transform", [P("amount", "float", 12, 1, 80, 1), P("speed", "float", 6, 0.5, 30, 0.5)],
        requires=["crop", "scale"])
def _(p, c):
    a, s = p["amount"], p["speed"]
    return (f"scale=iw*1.1:ih*1.1,crop=w='iw/1.1':h='ih/1.1':"
            f"x='(iw-ow)/2+{_f(a)}*sin(t*{_f(s)})*cos(t*{_f(s*0.7)})':"
            f"y='(ih-oh)/2+{_f(a)}*sin(t*{_f(s*1.3)})':exact=0")


@effect("stabilize", "Stabilize (Deshake)", "Transform", [P("range", "int", 16, 4, 64)], requires=["deshake"])
def _(p, c):
    return f"deshake=rx={p['range'] // 4 * 4}:ry={p['range'] // 4 * 4}"


@effect("lens_correction", "Lens Correction / Fisheye", "Transform",
        [P("k1", "float", -0.2, -1, 1, 0.01), P("k2", "float", 0.0, -1, 1, 0.01)],
        "Negative removes barrel distortion (GoPro); positive adds fisheye.", ["lenscorrection"])
def _(p, c):
    return f"lenscorrection=k1={_f(p['k1'])}:k2={_f(p['k2'])}"


@effect("border", "Border / Frame", "Transform", [P("size", "int", 30, 0, 400), P("color", "color", "#ffffff")],
        requires=["pad"])
def _(p, c):
    s = p["size"]
    return f"pad=iw+{2*s}:ih+{2*s}:{s}:{s}:color={col(p['color'])}"


@effect("rounded_frame", "Picture Frame Shadow", "Transform", [P("margin", "float", 0.08, 0, 0.3, 0.01), P("color", "color", "#111111")],
        requires=["pad", "scale"])
def _(p, c):
    m = p["margin"]
    return f"scale=trunc(iw*{_f(1-2*m)}/2)*2:trunc(ih*{_f(1-2*m)}/2)*2,pad=iw/{_f(1-2*m)}:ih/{_f(1-2*m)}:(ow-iw)/2:(oh-ih)/2:color={col(p['color'])}"


# =========================================================================== Time

@effect("fade_in", "Fade In", "Time", [P("duration", "float", 1.0, 0.05, 10, 0.05), P("color", "choice", "black", choices=["black", "white"])],
        requires=["fade"])
def _(p, c):
    return f"fade=t=in:st=0:d={_f(p['duration'])}:color={p['color']}"


@effect("fade_out", "Fade Out", "Time", [P("duration", "float", 1.0, 0.05, 10, 0.05), P("color", "choice", "black", choices=["black", "white"])],
        requires=["fade"])
def _(p, c):
    d = float(c.get("duration") or 0)
    st = max(d - p["duration"], 0)
    return f"fade=t=out:st={_f(st)}:d={_f(p['duration'])}:color={p['color']}"


@effect("smooth_slowmo", "Smooth Slow-Mo (optical flow)", "Time", [P("fps", "int", 60, 24, 240)],
        "Synthesises in-between frames with motion interpolation. Combine with clip speed < 1.", ["minterpolate"])
def _(p, c):
    return f"minterpolate=fps={p['fps']}:mi_mode=mci:mc_mode=aobmc:vsbmc=1"


@effect("frame_blend", "Frame Blend / Ghosting", "Time", [P("frames", "int", 3, 2, 12)], requires=["tmix"])
def _(p, c):
    return f"tmix=frames={p['frames']}"


@effect("strobe", "Strobe / Flash", "Time", [P("rate", "float", 4, 0.5, 20, 0.5), P("strength", "float", 0.3, 0, 1, 0.01)],
        requires=["eq"])
def _(p, c):
    return f"eq=brightness='{_f(p['strength'])}*gt(sin(2*PI*t*{_f(p['rate'])}),0.9)':eval=frame"


@effect("posterize_time", "Choppy / Stop-Motion", "Time", [P("fps", "int", 8, 1, 30)], requires=["fps"])
def _(p, c):
    return f"fps={p['fps']}"


# =========================================================================== Overlay helpers

@effect("progress_bar", "Progress Bar", "Overlay", [P("height", "int", 8, 1, 60), P("color", "color", "#ff3b5c"),
                                                     P("position", "choice", "bottom", choices=["bottom", "top"])],
        "Animated bar that fills over the clip's duration (great for Shorts/Reels).", ["drawbox"])
def _(p, c):
    d = max(float(c.get("duration") or 1), 0.1)
    y = "ih-{h}".format(h=p["height"]) if p["position"] == "bottom" else "0"
    return f"drawbox=x=0:y={y}:w='iw*t/{_f(d)}':h={p['height']}:color={col(p['color'])}:t=fill:replace=1"


@effect("timecode", "Burn-in Timecode", "Overlay", [P("size", "int", 36, 10, 200), P("color", "color", "#ffffff")],
        requires=["drawtext"])
def _(p, c):
    from .ffmpeg import default_font, esc_path
    font = default_font()
    ff = f"fontfile={esc_path(font)}:" if font else ""
    return (f"drawtext={ff}text='%{{pts\\:hms}}':fontsize={p['size']}:"
            f"fontcolor={col(p['color'])}:box=1:boxcolor=black@0.5:boxborderw=8:x=(w-tw)/2:y=h-th-40")


@effect("color_overlay", "Color Overlay / Wash", "Overlay", [P("color", "color", "#ff6a00"), P("opacity", "float", 0.2, 0, 1, 0.01)],
        requires=["drawbox"])
def _(p, c):
    return f"drawbox=x=0:y=0:w=iw:h=ih:color={col(p['color'], p['opacity'])}:t=fill"


@effect("grid_overlay", "Rule-of-Thirds Grid", "Overlay", [P("color", "color", "#ffffff"), P("opacity", "float", 0.4, 0, 1, 0.01)],
        requires=["drawgrid"])
def _(p, c):
    return f"drawgrid=w=iw/3:h=ih/3:t=2:c={col(p['color'], p['opacity'])}"


# =========================================================================== Expert

@effect("custom", "Custom FFmpeg Filter", "Expert", [P("filter", "text", "null")],
        "Type any FFmpeg filter chain — unlimited possibilities (e.g. 'hue=s=2,gblur=sigma=3').")
def _(p, c):
    return (p["filter"] or "null").strip() or "null"
