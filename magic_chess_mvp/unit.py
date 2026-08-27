from ursina import Entity, Vec3, Vec4, Color, lerp, color
import random

class Unit(Entity):
    def __init__(self, unit_class, position, team, **kwargs):
        super().__init__(**kwargs)
        
        # Basic properties
        self.unit_class = unit_class
        self.team = team  # "player" or "enemy"
        self.position = position
        
        # Stats from config
        from config import UNIT_CLASSES
        stats = UNIT_CLASSES[unit_class]
        
        self.max_hp = stats["hp"]
        self.current_hp = self.max_hp
        self.damage = stats["damage"]
        self.attack_speed = stats["attack_speed"]
        self.range = stats["range"]
        self.base_color = stats["color"]  # RGB tuple
        
        # Combat state
        self.target = None
        self.last_attack_time = 0
        self.is_attacking = False
        self.synergy_bonus = 1.0
        
        # Visual representation - use RGBA with alpha=255
        self.model = 'cube'
        self.scale = (0.8, 0.8, 0.8)
        r, g, b = self.base_color
        self.color = Vec4(r/255.0, g/255.0, b/255.0, 1.0)
        
        # Health bar
        self.hp_bar = Entity(
            parent=self,
            model='quad',
            scale=(0.9, 0.15),
            position=(0, 0.6, 0),
            color=color.lime,
            billboard=True
        )
        self.hp_bar_bg = Entity(
            parent=self,
            model='quad',
            scale=(0.9, 0.15),
            position=(0, 0.6, -0.01),
            color=color.dark_gray,
            billboard=True
        )
        
        # Team indicator
        self.team_color = color.azure if team == "player" else color.red
        self.glow = Entity(
            parent=self,
            model='sphere',
            scale=(1.2, 0.2, 1.2),
            position=(0, -0.4, 0),
            color=self.team_color,
            alpha=0.3
        )
    
    def take_damage(self, amount):
        """Apply damage to unit"""
        actual_damage = amount * self.synergy_bonus
        self.current_hp -= actual_damage
        
        # Update health bar
        hp_percent = max(0, self.current_hp / self.max_hp)
        self.hp_bar.scale_x = 0.9 * hp_percent
        
        return self.current_hp <= 0
    
    def attack(self, target, game_time):
        """Attack target unit"""
        if game_time - self.last_attack_time >= 1.0 / self.attack_speed:
            if self.distance_to(target) <= self.range * 1.5:
                # Deal damage
                is_killed = target.take_damage(self.damage)
                self.last_attack_time = game_time
                return is_killed
        return False
    
    def find_target(self, enemies, game_time):
        """Find nearest enemy in range"""
        valid_targets = [e for e in enemies if e.current_hp > 0 and self.distance_to(e) <= self.range * 1.5]
        
        if valid_targets:
            self.target = min(valid_targets, key=lambda x: self.distance_to(x))
            return True
        return False
    
    def move_to_target(self, target, dt):
        """Move towards target if out of range"""
        if self.distance_to(target) > self.range * 1.2:
            direction = (target.position - self.position).normalized()
            self.position += direction * 2 * dt
    
    def update(self):
        """Update health bar position"""
        self.hp_bar.position = (0, 0.6, 0)
        self.hp_bar_bg.position = (0, 0.6, -0.01)
    
    def is_alive(self):
        return self.current_hp > 0
