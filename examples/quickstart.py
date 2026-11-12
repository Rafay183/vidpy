"""Run:  python examples/quickstart.py intro.mp4 photo.jpg music.mp3"""
import sys

import vidpy

video, photo, music = sys.argv[1:4]

p = vidpy.Project(name="Quickstart", width=1920, height=1080, fps=30)
p.add_clip(video, start=0, end=6).fx("cinematic").transition_to("circleopen", 1)
p.add_clip(photo, duration=4, fit="fill").fx("ken_burns", end_zoom=1.35, direction="right")
p.add_text("vidpy", start=0.5, duration=3, size=140, animation="zoom_pop", outline=3)
p.add_text("made with Python", start=1.2, duration=3, preset="lower_third", box=True,
           box_color="#7c5cff", box_opacity=0.85, animation="slide_left", size=48)
p.add_audio(music, volume=0.6, loop=True, duck=True, fade_in=1, fade_out=2)
p.afx("normalize", target_lufs=-14)

p.render("quickstart.mp4", quality="high",
         on_progress=lambda f, s: print(f"\r{f:6.1%}  speed {s.get('speed', '')}", end=""))
p.save("quickstart.vidpy.json")
print("\nDone → quickstart.mp4  (open quickstart.vidpy.json in `vidpy studio`)")
