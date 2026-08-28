#!/bin/bash
# Magic Chess MVP - Headless Runner Script
# Menjalankan game auto-battler di environment tanpa monitor (Linux/WSL)

echo "🚀 Starting Magic Chess MVP (Headless Mode)..."
echo "=============================================="

# Kill any existing Xvfb
pkill Xvfb 2>/dev/null || true
sleep 1

# 1. Setup Virtual Display (Xvfb)
# Menggunakan display :99 dengan resolusi 1920x1080 dan kedalaman warna 24-bit
export DISPLAY=:99
echo "🖥️  Starting Xvfb on display :99..."
Xvfb :99 -screen 0 1920x1080x24 &
XVFB_PID=$!

# Tunggu sebentar agar Xvfb siap
sleep 2

# Verify Xvfb is running
if ! kill -0 $XVFB_PID 2>/dev/null; then
    echo "❌ Failed to start Xvfb"
    exit 1
fi
echo "✅ Xvfb started (PID: $XVFB_PID)"

# Set environment variables
export SDL_AUDIODRIVER=dummy

# Fungsi cleanup saat script selesai atau di-interrupt
cleanup() {
    echo ""
    echo "🧹 Cleaning up..."
    kill $XVFB_PID 2>/dev/null
    exit 0
}
trap cleanup EXIT INT TERM

# 2. Jalankan Game
echo ""
echo "🎮 Launching game engine..."
echo "--------------------------------------------"
# Timeout 15 detik: cukup untuk battle selesai dan screenshot diambil
cd "$(dirname "$0")"
timeout 15 python main.py 2>&1
exit_code=$?

# 3. Cek Hasil
echo ""
if [ $exit_code -eq 0 ] || [ $exit_code -eq 124 ]; then
    # Exit code 0 = sukses, 124 = timeout (normal karena game ditutup otomatis)
    echo "✅ Battle simulation finished."
    
    # Cari file screenshot terbaru
    SCREENSHOT=$(ls -t battle_screenshot_*.jpg 2>/dev/null | head -n1)
    
    if [ -n "$SCREENSHOT" ]; then
        echo "📸 Screenshot berhasil disimpan: $SCREENSHOT"
        echo "📏 Ukuran file: $(ls -lh $SCREENSHOT | awk '{print $5}')"
    else
        echo "⚠️  Screenshot tidak ditemukan. Cek log error di atas."
    fi
else
    echo "❌ Game crashed atau terjadi error fatal (exit code: $exit_code)."
    exit 1
fi

echo ""
echo "🏁 Done."
