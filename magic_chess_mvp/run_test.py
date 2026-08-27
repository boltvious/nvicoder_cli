#!/usr/bin/env python3
"""Quick test without full game loop"""
import os
os.environ['DISPLAY'] = ':99'
os.environ['SDL_AUDIODRIVER'] = 'dummy'

print("Testing Ursina import...")
from ursina import Ursina, Entity, Text, Sky, camera, color, time

print("Creating app...")
app = Ursina()

print("Setting up scene...")
camera.position = (0, 15, -12)
camera.rotation_x = 60

Sky(color=color.rgb(30, 30, 50))
Entity(model='cube', color=color.green, position=(0, 0, 0), scale=(2, 2, 2))

print("Creating text...")
Text(text='TEST', position=(0, 0), scale=2, color=color.white)

print("✅ All setup successful!")
print("Running for 3 seconds...")

frame_count = [0]
def update():
    frame_count[0] += 1
    if frame_count[0] > 180:  # ~3 seconds at 60fps
        print(f"✅ Completed {frame_count[0]} frames")
        app.quit()

app.update = update
app.run()

print("✅ Test completed successfully!")
