"""Turn a long landscape talk into a captioned 9:16 short with jump-cuts and a progress bar."""
import sys

import vidpy
from vidpy import smart

src = sys.argv[1]
p = smart.cut_silences(src, noise_db=-35, min_silence=0.5)   # remove dead air
smart.auto_reframe(p, "9:16")                                 # vertical, center-cropped
p.fx("vibrance", intensity=0.4).fx("progress_bar", color="#ff3b5c")
p.add_text("WATCH TILL THE END", duration=2.5, preset="top", size=70, box=True, animation="zoom_pop")
p.afx("voice_enhance").afx("normalize", target_lufs=-14)
p.render("short.mp4", quality="high")
print("→ short.mp4")
