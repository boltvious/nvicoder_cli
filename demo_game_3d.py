
"""
Demo Game 3D Sederhana dengan Ursina Engine - Headless Screenshot
NVICoder x Ursina Engine Demo
"""
from ursina import *
import sys

# Setup aplikasi Ursina
app = Ursina(title='NVICoder 3D Demo', borderless=False, fullscreen=False, show_fps=True)

# Setup Environment
Sky(texture='sky_sunset')
ambient_light = AmbientLight(color=color.rgba(100, 100, 100, 255))
dir_light = DirectionalLight(color=color.white)
dir_light.look_at(Vec3(1, -1, -1))

# Player & Camera (Manual setup)
player = Entity()
player.position = (0, 2, 10)
camera.parent = player
camera.rotation = (0, 0, 0)

# Ground
ground = Entity(model='plane', texture='grass', collider='box', scale=(100, 1, 100), texture_scale=(50, 50), color=color.green)

# Kubus-kubus Random
for i in range(20):
    Entity(
        model='cube',
        color=color.rgb(random.randint(50, 255), random.randint(50, 255), random.randint(50, 255)),
        position=(random.uniform(-40, 40), 1, random.uniform(-40, 40)),
        scale=(random.uniform(1, 3), random.uniform(1, 5), random.uniform(1, 3)),
        collider='box',
        texture='white_cube'
    )

# UI Text
Text(text='NVICoder x Ursina Engine Demo', position=(0, 0.45), origin=(0, 0), scale=2, color=color.yellow)
Text(text='3D Scene Render Test', position=(0, 0.35), origin=(0, 0), scale=1.5, color=color.white)

counter = 0
def update():
    global counter
    counter += 1
    if counter > 60:
        print("\n📸 Mengambil screenshot...")
        base.screenshot(namePrefix='nvicoder_ursina_demo.png', defaultFilename=False)
        print("✅ Screenshot berhasil disimpan!")
        print("🚀 Selesai! Keluar...")
        sys.exit(0)

print("🎮 Starting NVICoder 3D Demo...")
app.run()
