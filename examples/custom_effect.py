"""Register your own effect; it appears in the studio's Effects panel automatically."""
import vidpy


@vidpy.effect("neon_edges", "Neon Edges", category="My FX",
              params=[vidpy.Param("glow", "float", 6, 0, 30), vidpy.Param("saturation", "float", 2, 0, 3)],
              description="Glowing outlines")
def neon_edges(p, ctx):
    return f"edgedetect=mode=colormix:high=0.2,gblur=sigma={p['glow'] / 4},eq=saturation={p['saturation']}"


@vidpy.audio_effect("megaphone", "Megaphone", category="My FX")
def megaphone(p, ctx):
    return "highpass=f=600,lowpass=f=3000,acrusher=bits=8:mix=0.4,volume=2"


if __name__ == "__main__":
    vidpy.studio()
