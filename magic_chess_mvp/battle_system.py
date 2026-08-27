from unit import Unit
import random
from config import BOARD_ROWS, BOARD_COLS, TILE_SIZE, SYNERGIES

class BattleSystem:
    def __init__(self, app):
        self.app = app
        self.player_units = []
        self.enemy_units = []
        self.game_time = 0
        self.battle_started = False
        self.battle_ended = False
        self.winner = None
        
    def spawn_unit(self, unit_class, team, row, col):
        """Spawn a unit on the board"""
        x = col * TILE_SIZE - (BOARD_COLS * TILE_SIZE) / 2 + TILE_SIZE / 2
        z = row * TILE_SIZE - (BOARD_ROWS * TILE_SIZE) / 2 + TILE_SIZE / 2
        
        if team == "player":
            z = -z  # Player on bottom
        else:
            z = -z + BOARD_ROWS * TILE_SIZE / 2  # Enemy on top
        
        position = (x, 0.5, z)
        
        unit = Unit(
            unit_class=unit_class,
            position=position,
            team=team
        )
        
        if team == "player":
            self.player_units.append(unit)
        else:
            self.enemy_units.append(unit)
        
        return unit
    
    def calculate_synergies(self, units):
        """Calculate synergy bonuses for a team"""
        class_counts = {}
        for unit in units:
            if unit.is_alive():
                unit_class = unit.unit_class
                class_counts[unit_class] = class_counts.get(unit_class, 0) + 1
        
        # Apply synergy bonuses
        for unit in units:
            if not unit.is_alive():
                continue
                
            unit_class = unit.unit_class
            count = class_counts.get(unit_class, 0)
            
            bonus = 1.0
            if unit_class in SYNERGIES:
                for threshold, value in sorted(SYNERGIES[unit_class].items()):
                    if count >= threshold:
                        bonus = 1.0 + value
            
            unit.synergy_bonus = bonus
    
    def start_battle(self):
        """Initialize and start the battle"""
        self.battle_started = True
        print("⚔️ BATTLE STARTED!")
        print(f"Player units: {len(self.player_units)}")
        print(f"Enemy units: {len(self.enemy_units)}")
    
    def update(self, dt):
        """Update battle logic"""
        if not self.battle_started or self.battle_ended:
            return
        
        self.game_time += dt
        
        # Remove dead units
        self.player_units = [u for u in self.player_units if u.is_alive()]
        self.enemy_units = [u for u in self.enemy_units if u.is_alive()]
        
        # Check win condition
        if len(self.player_units) == 0:
            self.battle_ended = True
            self.winner = "enemy"
            print("💀 PLAYER DEFEATED!")
            return
        
        if len(self.enemy_units) == 0:
            self.battle_ended = True
            self.winner = "player"
            print("🏆 PLAYER VICTORY!")
            return
        
        # Calculate synergies
        self.calculate_synergies(self.player_units)
        self.calculate_synergies(self.enemy_units)
        
        # AI Combat Logic
        self.process_combat(dt)
    
    def process_combat(self, dt):
        """Process combat actions for all units"""
        all_player_units = self.player_units.copy()
        all_enemy_units = self.enemy_units.copy()
        
        # Each unit finds target and attacks/moves
        for unit in all_player_units:
            if not unit.is_alive():
                continue
                
            enemies = all_enemy_units
            if unit.find_target(enemies, self.game_time):
                if unit.distance_to(unit.target) <= unit.range * 1.5:
                    unit.attack(unit.target, self.game_time)
                else:
                    unit.move_to_target(unit.target, dt)
        
        for unit in all_enemy_units:
            if not unit.is_alive():
                continue
                
            enemies = all_player_units
            if unit.find_target(enemies, self.game_time):
                if unit.distance_to(unit.target) <= unit.range * 1.5:
                    unit.attack(unit.target, self.game_time)
                else:
                    unit.move_to_target(unit.target, dt)
    
    def get_battle_status(self):
        """Get current battle status"""
        return {
            "player_units_alive": len([u for u in self.player_units if u.is_alive()]),
            "enemy_units_alive": len([u for u in self.enemy_units if u.is_alive()]),
            "game_time": self.game_time,
            "battle_ended": self.battle_ended,
            "winner": self.winner
        }
