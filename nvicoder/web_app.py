#!/usr/bin/env python3
"""Simple Flask web app untuk Ojek Online - menampilkan halaman admin & download APK."""

import os
from flask import Flask, render_template, send_file, jsonify

app = Flask(__name__)

# Path ke APK release (sesuai build sebelumnya)
APK_PATH = os.path.join(os.path.dirname(os.path.dirname(__file__)),
                        "ojek_online", "build", "app", "outputs", "apk", "release", "app-release.apk")

@app.route("/")
def index():
    """Halaman utama - menampilkan info dan tautan download."""
    if os.path.exists(APK_PATH):
        apk_size = os.path.getsize(APK_PATH)
        apk_info = f"APK Release ({apk_size // 1024} KB)"
    else:
        apk_info = "APK belum tersedia (belum build)"

    return f"""
    <!DOCTYPE html>
    <html lang="id">
    <head>
        <meta charset="UTF-8">
        <meta name="viewport" content="width=device-width, initial-scale=1.0">
        <title>Ojek Online - Admin Panel</title>
        <style>
            body {{ font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif; 
                   max-width: 800px; margin: 40px auto; line-height: 1.6; color: #333; }}
            .container {{ border: 2px solid #ddd; border-radius: 8px; padding: 2rem; 
                         background: #f9f9f9; }}
            h1 {{ color: #6a0dad; text-align: center; margin-bottom: 1rem; }}
            .status {{ background: #e8f5e9; padding: 1rem; border-radius: 4px; margin: 1rem 0; }}
            .apk-link {{ display: inline-block; background: #6a0dad; color: white; 
                        padding: 12px 24px; border-radius: 4px; text-decoration: none; 
                        font-size: 1.1em; margin: 1rem 0; }}
            .apk-link:hover {{ background: #5a0d9e; }}
            .info {{ background: white; padding: 1rem; border-radius: 4px; margin: 1rem 0; }}
            .endpoint {{ background: #e3f2fd; padding: 1rem; border-radius: 4px; font-family: monospace; 
                        word-break: break-all; margin: 1rem 0; }}
        </style>
    </head>
    <body>
        <div class="container">
            <h1>🚗 Ojek Online</h1>
            
            <div class="status">
                <strong>Status:</strong> Aplikasi siap dipakai<br>
                <strong>APK:</strong> {apk_info}<br>
                <strong>Build:</strong> Release APK sudah terbuat
            </div>
            
            <div class="info">
                <h3>📱 Fitur Tersedia:</h3>
                <ul>
                    <li>Estimasi jarak & waktu via OSRM</li>
                    <li>Pengambilan GPS user</li>
                    <li>Antarmuka Material Design</li>
                </ul>
            </div>
            
            <a href="/download-apk" class="apk-link">
                📥 Download APK Terbaru
            </a>
            
            <div class="info">
                <h3>🔗 API Endpoints:</h3>
                <div class="endpoint">GET /  -> Halaman ini</div>
                <div class="endpoint">GET /download-apk -> Download APK</div>
                <div class="endpoint">GET /health -> Cek kesehatan service</div>
            </div>
            
            <footer style="margin-top: 2rem; text-align: center; color: #666; font-size: 0.9em;">
                Dibuat dengan ❤️ menggunakan Flutter & Flask
            </footer>
        </div>
    </body>
    </html>
    """

@app.route("/download-apk")
def download_apk():
    """Endpoint untuk download file APK."""
    if os.path.exists(APK_PATH):
        return send_file(APK_PATH, as_attachment=True, download_name="ojek_online.apk")
    else:
        return jsonify({"error": "APK file not found. Build terlebih dahulu."}), 404

@app.route("/health")
def health():
    """Endpoint cek kesehatan."""
    return jsonify({
        "status": "ok" if os.path.exists(APK_PATH) else "no_apk",
        "message": "Server running" if os.path.exists(APK_PATH) else "APK belum build"
    })

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    print("Ojek Online Web Admin running at http://0.0.0.0:" + str(port))
    print("APK download: http://0.0.0.0:" + str(port) + "/download-apk")
    app.run(host="0.0.0.0", port=port, debug=False)