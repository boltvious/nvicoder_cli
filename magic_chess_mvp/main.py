#!/usr/bin/env python3
"""Magic Chess MVP - Auto Battle Game (Headless Ready)"""
import os
os.environ['SDL_AUDIODRIVER'] = 'dummy'

from ursina import Ursina, Entity, Text, Sky, AmbientLight, DirectionalLight, camera, color, time, invoke, application
from config import BOARD_ROWS, BOARD_COLS, TILE_SIZE
from battle_system import BattleSystem
import sys

class MagicChessGame:
    def __init__(self):
        self.app = Ursina()
        self.battle_system = None
        self.status_text = None
        self.frame_count = 0
        
    def setup(self):
        self.app.title = "Magic Chess MVP"
        camera.position = (0, 15, -12)
        camera.rotation_x = 60
        camera.fov = 40
        
        Sky(color=color.rgb(30, 30, 50))
        AmbientLight(color=color.rgba(100, 100, 100, 0.5))
        DirectionalLight(color=color.white, direction=(1, -1, -1))
        
        for row in range(BOARD_ROWS):
            for col in range(BOARD_COLS):
                tc = color.rgb(80, 80, 80) if (row + col) % 2 == 0 else color.rgb(60, 60, 60)
                x = col * TILE_SIZE - (BOARD_COLS * TILE_SIZE) / 2 + TILE_SIZE / 2
                z = row * TILE_SIZE - (BOARD_ROWS * TILE_SIZE) / 2
                Entity(model='cube', color=tc, position=(x, -0.5, z), scale=(TILE_SIZE-2, 1, TILE_SIZE-2))
        
        bw, bh = BOARD_COLS * TILE_SIZE + 4, BOARD_ROWS * TILE_SIZE + 4
        Entity(model='cube', color=color.gold, position=(0, -1, -bh/2), scale=(bw, 2, 2))
        Entity(model='cube', color=color.gold, position=(0, -1, bh/2), scale=(bw, 2, 2))
        Entity(model='cube', color=color.gold, position=(-bw/2, -1, 0), scale=(2, 2, bh))
        Entity(model='cube', color=color.gold, position=(bw/2, -1, 0), scale=(2, 2, bh))
        
        self.battle_system = BattleSystem(self)
        for uc, r, c in [("tank",0,0), ("warrior",0,1), ("mage",0,2), ("archer",0,3)]:
            self.battle_system.spawn_unit(uc, "player", r, c)
        for uc, r, c in [("warrior",3,0), ("tank",3,1), ("archer",3,2), ("mage",3,3)]:
            self.battle_system.spawn_unit(uc, "enemy", r, c)
        
        print(f"⚔️ Teams: Player={len(self.battle_system.player_units)}, Enemy={len(self.battle_system.enemy_units)}")
        
        Text(text='MAGIC CHESS MVP', position=(-0.85, 0.45), scale=2, color=color.gold)
        Text(text='Auto-Battle Demo', position=(-0.85, 0.40), scale=1, color=color.white)
        self.status_text = Text(text='Starting...', position=(-0.80, -0.40), scale=0.7, color=color.lime)
        
        print("🎮 Starting battle in 1 second...")
        invoke(self.start_battle, delay=1.0)
    
    def start_battle(self):
        if self.battle_system and not self.battle_system.battle_started:
            self.battle_system.start_battle()
            print("⚔️ BATTLE STARTED!")
    
    def update(self):
        self.frame_count += 1
        dt = time.dt
        if self.battle_system and self.battle_system.battle_started:
            self.battle_system.update(dt)
            if not self.battle_system.battle_ended:
                s = self.battle_system.get_battle_status()
                self.status_text.text = f"Time: {s['game_time']:.1f}s\nPlayer: {s['player_units_alive']}\nEnemy: {s['enemy_units_alive']}"
            else:
                w = self.battle_system.winner
                self.status_text.text = f"{'🏆 VICTORY!' if w=='player' else '💀 DEFEATED!'}"
                self.status_text.color = color.gold if w=='player' else color.red
                print(f"🏁 Battle ended after {s['game_time']:.1f}s - Winner: {w}")
                # Auto quit after 2 seconds
                if self.frame_count > 240:
                    print("✅ Demo complete!")
                    sys.exit(0)
    
    def run(self):
        self.setup()
        self.app.run()

if __name__ == "__main__":
    print("🎮 Magic Chess MVP - Headless Auto-Battler")
    game = MagicChessGame()
    game.run()
