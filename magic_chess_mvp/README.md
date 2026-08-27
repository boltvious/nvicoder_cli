# 🎮 Magic Chess MVP - Auto Battle Game

Game auto-battler 3D sederhana terinspirasi oleh Magic Chess, dibuat dengan **Ursina Engine** dan dapat berjalan **tanpa monitor** (headless mode).

## 🎯 Fitur MVP

- ✅ **4 Kelas Unit**: Warrior, Mage, Archer, Tank
- ✅ **Sistem Sinergi**: Bonus untuk 2 atau 4 unit sejenis
- ✅ **Auto-Battle**: Unit bertarung otomatis dengan AI sederhana
- ✅ **Health Bar & Visual Effects**: Feedback visual saat bertarung
- ✅ **Headless Rendering**: Bisa jalan di server tanpa monitor
- ✅ **Screenshot Otomatis**: Capture hasil battle

## 📁 Struktur File

```
magic_chess_mvp/
├── config.py          # Konfigurasi game (stats, synergy, dll)
├── unit.py            # Class Unit dengan stats dan behavior
├── battle_system.py   # Sistem pertarungan dan AI
├── main.py            # Entry point game
├── run_headless.sh    # Script untuk run tanpa monitor
└── README.md          # Dokumentasi ini
```

## 🚀 Cara Menjalankan

### Mode Headless (Tanpa Monitor)

```bash
cd magic_chess_mvp
./run_headless.sh
```

### Mode Normal (Dengan Display)

```bash
cd magic_chess_mvp
python3 main.py
```

## 🎮 Kontrol

| Tombol | Aksi |
|--------|------|
| `SPACE` | Mulai battle manual |
| `R` | Restart battle |
| `ESC` | Keluar game |

## ⚙️ Konfigurasi

Edit `config.py` untuk mengubah:

- Ukuran board (`BOARD_ROWS`, `BOARD_COLS`)
- Stats unit (`UNIT_CLASSES`)
- Bonus sinergi (`SYNERGIES`)
- Kecepatan game (`GAME_SPEED`)

## 🏗️ Arsitektur

### Unit Classes
- **Warrior**: HP sedang, damage sedang, melee
- **Mage**: HP rendah, damage tinggi, range jauh
- **Archer**: HP sedang, damage sedang, attack speed tinggi
- **Tank**: HP tinggi, damage rendah, melee

### Synergy System
Setiap kelas memiliki bonus ketika ada 2 atau 4 unit sejenis:
- Warrior: +15%/+30% armor
- Mage: +20%/+40% magic damage
- Archer: +15%/+35% attack speed
- Tank: +20%/+40% HP

## 🔧 Development

### Requirements
- Python 3.8+
- Ursina Engine
- Pillow (untuk screenshot)
- Xvfb (untuk headless mode)

### Install Dependencies
```bash
pip install ursina pillow
```

### Headless Setup (Linux Server)
```bash
# Install Xvfb
apt-get install xvfb x11-xkb-utils xfonts-base

# Verify installation
Xvfb :99 -screen 0 1280x720x24 &
export DISPLAY=:99
```

## 📸 Screenshot

Screenshot otomatis disimpan sebagai `screenshot_YYYYMMDD_HHMMSS.png` setelah battle selesai.

## 🐛 Troubleshooting

### "Cannot open display"
```bash
# Pastikan Xvfb running
pgrep -x Xvfb

# Start manual jika perlu
Xvfb :99 -screen 0 1280x720x24 &
export DISPLAY=:99
```

### Game crash saat start
```bash
# Cek dependency
python3 -c "from ursina import *; print('OK')"

# Run dengan debug
python3 main.py 2>&1 | tee debug.log
```

## 📝 License

MIT License - Feel free to use and modify!

---

**Dibuat dengan ❤️ untuk demo game development tanpa monitor**
