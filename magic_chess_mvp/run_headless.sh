#!/bin/bash
# Run Magic Chess MVP headless with virtual display

echo "🎮 Starting Magic Chess MVP (Headless Mode)"
echo "============================================"

# Kill any existing Xvfb
pkill Xvfb 2>/dev/null || true
sleep 1

# Start Xvfb
echo "🖥️  Starting Xvfb on display :99..."
Xvfb :99 -screen 0 1280x720x24 &
XVFB_PID=$!
sleep 2

# Verify Xvfb is running
if ! kill -0 $XVFB_PID 2>/dev/null; then
    echo "❌ Failed to start Xvfb"
    exit 1
fi
echo "✅ Xvfb started (PID: $XVFB_PID)"

# Set display
export DISPLAY=:99
export SDL_AUDIODRIVER=dummy

echo ""
echo "🚀 Running game..."
echo "--------------------------------------------"

# Run the game with timeout (30 seconds max)
cd /workspace/magic_chess_mvp
timeout 30 python3 main.py 2>&1
exit_code=$?

if [ $exit_code -eq 124 ]; then
    echo ""
    echo "⏰ Game timed out after 30 seconds"
elif [ $exit_code -eq 0 ]; then
    echo ""
    echo "✅ Game completed successfully"
else
    echo ""
    echo "❌ Game exited with code: $exit_code"
fi

echo ""
echo "📸 Checking for screenshots..."
ls -lh /workspace/magic_chess_mvp/screenshot_*.png 2>/dev/null || echo "No screenshots found"

echo ""
echo "Cleaning up..."
kill $XVFB_PID 2>/dev/null || true

echo ""
echo "✅ Done!"
