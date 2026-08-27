import os
os.environ['DISPLAY'] = ':99'
os.environ['PANDA_HIDE_AUDIO'] = '1'

from ursina import *
from panda3d.core import PNMImage

# Create app
app = Ursina(size=(800, 600), show_fps=False)

# Create simple 3D scene
cube = Entity(model='cube', color=color.red, position=(0, 0, 0))
plane = Entity(model='plane', color=color.green, scale=10, rotation_x=-90)
camera.position = (3, 3, 3)
camera.look_at((0, 0, 0))

print("✅ Scene created")

# Force render frames
for i in range(10):
    base.graphicsEngine.renderFrame()

# Simple screenshot - no extra args
print("📸 Taking screenshot...")
result = base.screenshot()
print(f"📄 Result: {result}")

import time
time.sleep(2)

# Check results
print("\n📁 PNG files:")
found = False
for f in sorted(os.listdir('/workspace')):
    if f.endswith('.png'):
        fp = f'/workspace/{f}'
        size = os.path.getsize(fp)
        status = "✅" if size > 1000 else "⚠️"
        print(f"{status} {f}: {size} bytes")
        found = True

if not found:
    print("❌ No PNG files found")

application.quit()
