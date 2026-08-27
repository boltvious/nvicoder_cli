# Game Configuration
SCREEN_WIDTH = 1280
SCREEN_HEIGHT = 720
BOARD_ROWS = 4
BOARD_COLS = 4
TILE_SIZE = 100

# Unit Stats
UNIT_CLASSES = {
    "warrior": {"hp": 150, "damage": 25, "attack_speed": 1.0, "range": 1, "color": (200, 50, 50)},
    "mage": {"hp": 80, "damage": 45, "attack_speed": 0.8, "range": 3, "color": (50, 50, 200)},
    "archer": {"hp": 100, "damage": 30, "attack_speed": 1.2, "range": 2, "color": (50, 200, 50)},
    "tank": {"hp": 250, "damage": 15, "attack_speed": 0.6, "range": 1, "color": (100, 100, 100)},
}

# Synergy Bonuses
SYNERGIES = {
    "warrior": {2: 0.15, 4: 0.30},  # Armor bonus
    "mage": {2: 0.20, 4: 0.40},    # Magic damage bonus
    "archer": {2: 0.15, 4: 0.35},  # Attack speed bonus
    "tank": {2: 0.20, 4: 0.40},    # HP bonus
}

GAME_SPEED = 1.0
AUTO_BATTLE_DELAY = 0.5  # seconds between actions
