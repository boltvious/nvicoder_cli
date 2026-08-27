"""
Definisi tool (function calling) yang bisa dipanggil oleh model, plus
implementasi Python-nya. Setiap tool punya schema OpenAI-style (dipakai
di parameter `tools=` saat memanggil chat.completions.create) dan sebuah
fungsi eksekusi yang dipanggil ketika model mengirim tool_call.
"""

import base64
import fnmatch
import json
import os
import subprocess
import threading
import time
import urllib.parse
import urllib.request

from . import browser, config, mcp_client

TOOLS_SCHEMA = [
    {
        "type": "function",
        "function": {
            "name": "read_file",
            "description": (
                "Baca isi sebuah file teks di disk. Selalu gunakan ini sebelum "
                "mengedit file agar tahu isi & format persisnya."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {"type": "string", "description": "Path file, relatif atau absolut."},
                    "start_line": {"type": "integer", "description": "Baris awal (1-indexed), opsional."},
                    "end_line": {"type": "integer", "description": "Baris akhir (inklusif), opsional."},
                },
                "required": ["path"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "write_file",
            "description": (
                "Buat file baru atau timpa (overwrite) seluruh isi file yang sudah ada. "
                "Untuk perubahan kecil pada file yang sudah ada, lebih baik pakai edit_file."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {"type": "string"},
                    "content": {"type": "string", "description": "Isi lengkap file."},
                },
                "required": ["path", "content"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "edit_file",
            "description": (
                "Ganti satu potongan teks (old_string) dengan teks baru (new_string) di "
                "dalam sebuah file. old_string HARUS unik (muncul persis sekali) di file "
                "tersebut, dan harus cocok persis termasuk indentasi/whitespace."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {"type": "string"},
                    "old_string": {"type": "string"},
                    "new_string": {"type": "string"},
                },
                "required": ["path", "old_string", "new_string"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "list_dir",
            "description": "List isi sebuah direktori (file & subfolder).",
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {"type": "string", "description": "Default '.' kalau tidak diisi."},
                },
                "required": [],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "search_files",
            "description": (
                "Cari string/pola di semua file teks di bawah sebuah folder (mirip grep -rn). "
                "Berguna untuk menemukan definisi fungsi, penggunaan variabel, dsb."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "pattern": {"type": "string", "description": "Teks yang dicari (substring, case-sensitive)."},
                    "path": {"type": "string", "description": "Folder awal pencarian, default '.'."},
                    "glob": {"type": "string", "description": "Filter nama file, misal '*.py'. Default semua file teks."},
                },
                "required": ["pattern"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "run_command",
            "description": (
                "Jalankan perintah shell (bash) di direktori kerja, misalnya untuk menjalankan "
                "test, linter, git, atau build. Perintah yang berpotensi merusak akan meminta "
                "konfirmasi user dulu sebelum benar-benar dieksekusi. UNTUK PROSES YANG MEMANG "
                "DIDESAIN JALAN TERUS (dev server, watch mode, hot-reload) seperti 'npm run dev', "
                "'flutter run', 'next dev', 'uvicorn ... --reload' — WAJIB set background=true, "
                "supaya tool tidak menunggu proses itu selesai (yang tidak akan pernah terjadi) "
                "dan tidak memblokir loop percakapan sampai timeout."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "command": {"type": "string"},
                    "cwd": {"type": "string", "description": "Working directory, default direktori saat ini."},
                    "background": {
                        "type": "boolean",
                        "description": (
                            "Set true untuk command long-running (dev server/watch mode) yang "
                            "tidak berhenti sendiri. Command dijalankan non-blocking, output "
                            "ditulis ke file log yang path-nya dikembalikan, dan tool ini langsung "
                            "return tanpa menunggu command selesai."
                        ),
                    },
                },
                "required": ["command"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "web_search",
            "description": (
                "Cari informasi di internet menggunakan DuckDuckGo HTML (tanpa API key). "
                "Berguna untuk mencari dokumentasi, error message, library terbaru, best practice, dll. "
                "Return snippet hasil pencarian dengan URL sumber."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "Query pencarian (mis. 'python requests timeout error', 'fastapi async database')."},
                    "max_results": {"type": "integer", "description": "Jumlah maksimal hasil (default 5, max 10).", "default": 5},
                },
                "required": ["query"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "searxng_search",
            "description": (
                "Cari informasi via SearXNG instance (JSON API). Butuh SEARXNG_URL di config/env. "
                "Lebih akurat dari scraping karena response JSON terstruktur. "
                "Support filter kategori (general, images, videos, news, dll) dan bahasa."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "Query pencarian (mis. 'python requests timeout error', 'fastapi async database')."},
                    "max_results": {"type": "integer", "description": "Jumlah maksimal hasil (default 5, max 20).", "default": 5},
                    "categories": {"type": "string", "description": "Kategori pencarian: general, images, videos, news, files, social, music, dll. Default: general."},
                    "language": {"type": "string", "description": "Kode bahasa: en, id, de, fr, dll. Default: auto."},
                },
                "required": ["query"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "code_review",
            "description": (
                "Jalankan code review Constitutional AI terhadap file atau diff. "
                "Menggunakan code_review_constitution.md + project_conventions.md. "
                "Return structured report dengan issues by priority (SECURITY > CORRECTNESS > MAINTAINABILITY > PERFORMANCE > STYLE)."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "files": {"type": "array", "items": {"type": "string"}, "description": "List file paths to review (local paths)."},
                    "diff": {"type": "string", "description": "Optional: Git diff content to review instead of full files."},
                    "pr_url": {"type": "string", "description": "Optional: PR URL (GitHub/GitLab) to fetch diff from."},
                    "focus": {"type": "array", "items": {"type": "string"}, "description": "Optional: Focus areas: security, correctness, maintainability, performance, style."},
                },
                "required": [],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "run_linter",
            "description": (
                "Jalankan linter/type checker (ruff, mypy, black --check) pada file atau project. "
                "Return structured output dengan errors/warnings."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {"type": "string", "description": "File or directory to lint. Default: current directory."},
                    "tools": {"type": "array", "items": {"type": "string"}, "description": "Tools to run: ruff, mypy, black, bandit, pip-audit. Default: all available."},
                },
                "required": [],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "run_tests",
            "description": (
                "Jalankan pytest pada file atau project. Return summary: passed, failed, coverage."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {"type": "string", "description": "Test file or directory. Default: auto-detect."},
                    "coverage": {"type": "boolean", "description": "Run with coverage. Default: true."},
                    "args": {"type": "string", "description": "Additional pytest args."},
                },
                "required": [],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_pr_diff",
            "description": (
                "Ambil diff dari PR GitHub/GitLab via API. Butuh GITHUB_TOKEN/GITLAB_TOKEN di env."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "pr_url": {"type": "string", "description": "Full PR URL (https://github.com/owner/repo/pull/123)."},
                },
                "required": ["pr_url"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "browser_control",
            "description": (
                "Kontrol browser nyata (Edge/Chrome via Playwright) untuk membuka halaman web, "
                "klik elemen, isi form, baca teks halaman, atau screenshot. Berguna untuk cek "
                "hasil web app lokal (mis. http://localhost:3000) atau baca halaman yang butuh "
                "JavaScript. Browser TETAP TERBUKA antar tool_call dalam sesi ini (tab/login "
                "tidak hilang) sampai action='close' atau CLI keluar. Akan minta konfirmasi "
                "user sebelum browser pertama kali dibuka."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "action": {
                        "type": "string",
                        "enum": ["open", "click", "type", "get_text", "screenshot", "close"],
                        "description": (
                            "open: navigasi ke url (buka browser dulu kalau belum jalan). "
                            "click: klik elemen sesuai selector. "
                            "type: isi input sesuai selector dengan value. "
                            "get_text: ambil teks visible dari selector (default seluruh body). "
                            "screenshot: simpan screenshot full-page ke path. "
                            "close: tutup browser."
                        ),
                    },
                    "url": {"type": "string", "description": "URL tujuan, wajib untuk action='open'."},
                    "selector": {
                        "type": "string",
                        "description": (
                            "Selector Playwright: CSS biasa (mis. '#submit', '.btn-primary'), atau "
                            "'text=Kirim' untuk cari berdasarkan teks visible. Wajib untuk "
                            "click/type, opsional untuk get_text (default 'body')."
                        ),
                    },
                    "value": {"type": "string", "description": "Teks yang diketik ke input, wajib untuk action='type'."},
                    "path": {"type": "string", "description": "Path file output PNG, dipakai untuk action='screenshot'. Default nama otomatis."},
                    "timeout": {"type": "integer", "description": "Timeout dalam detik untuk action ini. Default 15."},
                },
                "required": ["action"],
            },
        },
    },

    {
        "type": "function",
        "function": {
            "name": "open_editor",
            "description": (
                "Buka editor teks (Notepad/VS Code/Vim) untuk user ngetik input panjang. "
                "Tool ini membuat file temporary, buka editor, tunggu user save (Ctrl+S), "
                "lalu baca isi file & return ke model. Cocok untuk: paste log error, "
                "tulis dokumentasi panjang, input JSON/config besar, dll. "
                "File juga disimpan ke project root sebagai backup (opsional)."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "initial_content": {
                        "type": "string",
                        "description": "Isi awal file (template, placeholder, dll). Default kosong.",
                        "default": ""
                    },
                    "save_as": {
                        "type": "string",
                        "description": "Path file untuk menyimpan hasil final di project root (relatif). Contoh: 'hallo.txt', 'notes/todo.md'. Kalau kosong, hanya return isi tanpa simpan permanen.",
                        "default": ""
                    },
                    "editor": {
                        "type": "string",
                        "description": "Editor yang dipakai: 'notepad' (default Windows), 'code' (VS Code), 'vim', 'nano'. Default dari env EDITOR atau 'notepad'.",
                        "default": ""
                    },
                    "instructions": {
                        "type": "string",
                        "description": "Instruksi yang ditampilkan di header file (sebagai komentar) buat user.",
                        "default": "Edit file ini, lalu SAVE (Ctrl+S). Tutup editor kalau selesai."
                    }
                },
                "required": []
            },
        },
    },
]


def _err(msg: str) -> str:
    return f"ERROR: {msg}"


def get_all_tools_schema() -> list[dict]:
    """TOOLS_SCHEMA bawaan + tool dari semua server MCP yang sudah connect (mcp_client.connect()).
    Auto-discovers .mcp.json configs in workspace and connects to them."""
    # Auto-discover and connect to MCP servers on first call
    if not hasattr(get_all_tools_schema, "_mcp_auto_discovered"):
        mcp_client.auto_connect_all()
        get_all_tools_schema._mcp_auto_discovered = True
    return TOOLS_SCHEMA + mcp_client.get_tools_schema()


def read_file(path: str, start_line: int | None = None, end_line: int | None = None) -> str:
    if not os.path.isfile(path):
        return _err(f"File tidak ditemukan: {path}")
    if os.path.splitext(path)[1].lower() in _SEARCH_BINARY_EXTENSIONS or _looks_binary(path):
        # Insiden nyata: read_file dipanggil ke cache .scn biner Godot,
        # hasilnya ratusan baris sampah byte non-teks kekirim ke model --
        # bikin turn berikutnya gagal/model ngaco. Tolak jelas di awal,
        # daripada model mikir itu "isi file" yang valid.
        size = os.path.getsize(path)
        return _err(
            f"File '{path}' sepertinya biner ({size} byte), bukan teks -- read_file "
            "cuma buat file teks. Kalau butuh info soal resource biner ini, cek lewat "
            "tool yang sesuai (mis. node_get_property/scene_get_tree buat resource Godot "
            "yang sudah ke-import), jangan baca isi mentahnya."
        )
    try:
        with open(path, "r", encoding="utf-8", errors="replace") as f:
            lines = f.readlines()
    except Exception as e:
        return _err(str(e))

    s = (start_line or 1) - 1
    e = end_line if end_line else len(lines)
    s = max(0, s)
    e = min(len(lines), e)
    numbered = [f"{i + 1:>5}\t{lines[i]}" for i in range(s, e)]
    if not numbered:
        return "(file kosong)"
    return "".join(numbered)


def write_file(path: str, content: str) -> str:
    try:
        parent = os.path.dirname(path)
        if parent:
            os.makedirs(parent, exist_ok=True)
        existed = os.path.isfile(path)
        with open(path, "w", encoding="utf-8") as f:
            f.write(content)
        action = "ditimpa" if existed else "dibuat"
        return f"OK: file {path} berhasil {action} ({len(content)} karakter)."
    except Exception as e:
        return _err(str(e))


def edit_file(path: str, old_string: str, new_string: str) -> str:
    if not os.path.isfile(path):
        return _err(f"File tidak ditemukan: {path}")
    try:
        with open(path, "r", encoding="utf-8") as f:
            content = f.read()
    except Exception as e:
        return _err(str(e))

    count = content.count(old_string)
    if count == 0:
        return _err(
            "old_string tidak ditemukan persis di file. Cek ulang whitespace/indentasi, "
            "atau baca ulang file dengan read_file sebelum mencoba lagi."
        )
    if count > 1:
        return _err(
            f"old_string muncul {count} kali (harus unik). Perbesar konteks old_string "
            "agar hanya cocok di satu tempat."
        )

    new_content = content.replace(old_string, new_string, 1)
    with open(path, "w", encoding="utf-8") as f:
        f.write(new_content)
    return f"OK: 1 perubahan diterapkan pada {path}."


def list_dir(path: str = ".") -> str:
    if not os.path.isdir(path):
        return _err(f"Direktori tidak ditemukan: {path}")
    entries = sorted(os.listdir(path))
    if not entries:
        return "(kosong)"
    lines = []
    for name in entries:
        full = os.path.join(path, name)
        tag = "/" if os.path.isdir(full) else ""
        lines.append(f"{name}{tag}")
    return "\n".join(lines)


# Ekstensi yang HAMPIR SELALU biner -- di-skip tanpa perlu buka file dulu.
# Ditemukan lewat insiden nyata: search_files nyedot isi .godot/uid_cache.bin
# (dan bisa juga .blend/.png/dst) sebagai "teks", satu file biner jadi SATU
# baris raksasa isinya sampah (gak ada newline asli di data biner), hasilnya
# ratusan KB garbage terkirim ke model -- boros token & bikin bingung/gagal.
_SEARCH_BINARY_EXTENSIONS = {
    ".bin", ".blend", ".blend1", ".png", ".jpg", ".jpeg", ".gif", ".bmp", ".ico",
    ".webp", ".ttf", ".otf", ".woff", ".woff2", ".zip", ".7z", ".rar", ".tar",
    ".gz", ".exe", ".dll", ".so", ".dylib", ".pdb", ".wasm", ".pyc", ".pyd",
    ".db", ".sqlite", ".sqlite3", ".mp3", ".mp4", ".wav", ".ogg", ".avi",
    ".mov", ".pdf", ".class", ".jar",
}


def _looks_binary(fpath: str) -> bool:
    """Sniff cepat: ada byte NUL di awal file? Itu ciri kuat file biner --
    jaring pengaman buat ekstensi yang gak ke-cover _SEARCH_BINARY_EXTENSIONS."""
    try:
        with open(fpath, "rb") as f:
            return b"\x00" in f.read(4096)
    except Exception:
        return True  # gak kebaca -> aman diskip aja daripada nekat


def search_files(pattern: str, path: str = ".", glob: str | None = None) -> str:
    if not os.path.isdir(path):
        return _err(f"Direktori tidak ditemukan: {path}")
    results = []
    # .nvicoder = folder internal nvicoder sendiri (sesi/log) -- isinya JSON
    # riwayat percakapan yang bisa punya "baris" sepanjang puluhan ribu karakter
    # (string ke-escape dari tool call sebelumnya), ditemukan lewat insiden
    # nyata bikin hasil search 140KB+ dari sesi lama, bukan dari kode project.
    skip_dirs = {".git", "node_modules", "__pycache__", ".venv", "venv", ".nvicoder", ".godot"}
    for root, dirs, files in os.walk(path):
        dirs[:] = [d for d in dirs if d not in skip_dirs]
        for fname in files:
            if glob and not fnmatch.fnmatch(fname, glob):
                continue
            if os.path.splitext(fname)[1].lower() in _SEARCH_BINARY_EXTENSIONS:
                continue
            fpath = os.path.join(root, fname)
            if _looks_binary(fpath):
                continue
            try:
                with open(fpath, "r", encoding="utf-8", errors="ignore") as f:
                    for i, line in enumerate(f, 1):
                        if pattern in line:
                            results.append(f"{fpath}:{i}: {line.strip()}")
                            if len(results) >= 200:
                                results.append("... (dipotong, terlalu banyak hasil)")
                                return "\n".join(results)
            except Exception:
                continue
    return "\n".join(results) if results else "(tidak ada hasil)"


def web_search(query: str, max_results: int = 5) -> str:
    """Cari di internet via DuckDuckGo HTML (tanpa API key)."""
    max_results = min(max(1, max_results), 10)
    url = f"https://html.duckduckgo.com/html/?q={urllib.parse.quote(query)}"
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    }
    try:
        req = urllib.request.Request(url, headers=headers)
        with urllib.request.urlopen(req, timeout=15) as resp:
            html = resp.read().decode("utf-8", errors="replace")
    except Exception as e:
        return _err(f"Gagal request ke DuckDuckGo: {e}")

    # Parse HTML dengan BeautifulSoup
    try:
        from bs4 import BeautifulSoup
        soup = BeautifulSoup(html, "html.parser")
    except Exception as e:
        return _err(f"Gagal parse HTML: {e}")

    results = []
    # DuckDuckGo result class biasanya 'result__snippet' atau 'result__url'
    for result_div in soup.select(".result__snippet, .result__url, .web-result-description"):
        text = result_div.get_text(strip=True)
        if text and len(text) > 20:
            results.append(text)
            if len(results) >= max_results:
                break

    # Fallback: cari semua link dengan class result__url
    if not results:
        for link in soup.select(".result__url, .result__snippet a"):
            text = link.get_text(strip=True)
            href = link.get("href", "")
            if text and len(text) > 20:
                results.append(f"{text} ({href})")
                if len(results) >= max_results:
                    break

    if not results:
        return "(tidak ada hasil pencarian)"

    output = []
    for i, r in enumerate(results, 1):
        output.append(f"{i}. {r}")
    return "\n".join(output)


def searxng_search(query: str, max_results: int = 5, categories: str | None = None,
                   language: str | None = None) -> str:
    """Cari via SearXNG instance (JSON API). Butuh SEARXNG_URL di config/env."""
    if not config.SEARXNG_URL:
        return _err("SEARXNG_URL tidak diset. Set env var SEARXNG_URL=http://your-searxng:8080")
    
    max_results = min(max(1, max_results), 20)
    params = {
        "q": query,
        "format": "json",
        "safesearch": "1",
    }
    if categories:
        params["categories"] = categories  # general, images, videos, news, etc.
    if language:
        params["language"] = language      # en, id, etc.
    
    url = f"{config.SEARXNG_URL.rstrip('/')}/search?{urllib.parse.urlencode(params)}"
    
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "nvicoder/1.0"})
        with urllib.request.urlopen(req, timeout=15) as resp:
            data = json.loads(resp.read().decode("utf-8", errors="replace"))
    except Exception as e:
        return _err(f"Gagal request ke SearXNG: {e}")
    
    results = data.get("results", [])
    if not results:
        return "(tidak ada hasil)"
    
    output = []
    for i, r in enumerate(results[:max_results], 1):
        title = r.get("title", "").strip()
        url = r.get("url", "").strip()
        content = r.get("content", "").strip()
        engine = r.get("engine", "").strip()
        if title and content:
            output.append(f"{i}. {title}\n   {content}\n   Link: {url} (via {engine})")
    
    return "\n\n".join(output) if output else "(tidak ada hasil relevan)"


def _is_safe_command(command: str, extra_safe: list[str] | None = None) -> bool:
    stripped = command.strip()
    prefixes = config.SAFE_COMMAND_PREFIXES + tuple(extra_safe or [])
    return any(stripped.startswith(p) for p in prefixes)


# ------------------------------------------------- background job registry ---
# Dilacak in-memory per sesi (reset tiap nvicoder start ulang) -- tujuannya
# cuma buat kasih VISIBILITAS ke user: berapa shell yang udah dipanggil di
# background, mana yang masih jalan, mana yang udah selesai. Bukan
# persistence lintas sesi.

_JOBS_LOCK = threading.Lock()
_BACKGROUND_JOBS: list[dict] = []
_NEXT_JOB_ID = [1]


def _reserve_job_id() -> int:
    with _JOBS_LOCK:
        job_id = _NEXT_JOB_ID[0]
        _NEXT_JOB_ID[0] += 1
    return job_id


def _register_background_job(job_id: int, command: str, proc: subprocess.Popen, log_path: str) -> None:
    with _JOBS_LOCK:
        _BACKGROUND_JOBS.append({
            "id": job_id, "command": command, "proc": proc,
            "log_path": log_path, "started_at": time.time(),
        })


def count_running_jobs() -> int:
    with _JOBS_LOCK:
        return sum(1 for job in _BACKGROUND_JOBS if job["proc"].poll() is None)


def list_background_jobs() -> list[dict]:
    """Snapshot status semua background job di sesi ini -- dipakai command /jobs."""
    result = []
    with _JOBS_LOCK:
        for job in _BACKGROUND_JOBS:
            exit_code = job["proc"].poll()
            status = "running" if exit_code is None else f"selesai (exit={exit_code})"
            result.append({
                "id": job["id"],
                "command": job["command"],
                "pid": job["proc"].pid,
                "log_path": job["log_path"],
                "status": status,
                "started_at": job["started_at"],
            })
    return result


# Command yang namanya cocok salah satu dari ini didesain buat JALAN TERUS
# (dev server, watch mode) dan TIDAK akan pernah exit sendiri. Kalau ini
# dijalankan blocking (subprocess.run + timeout), agent akan nyangkut
# sampai timeout habis lalu gagal -- padahal command-nya sendiri sebenarnya
# "berhasil" (server-nya emang nyala terus, itu sifatnya).
LONG_RUNNING_HINTS = (
    "flutter run",
    "npm start", "npm run dev", "npm run start", "npm run serve",
    "yarn dev", "yarn start", "yarn serve",
    "pnpm dev", "pnpm start",
    "next dev", "next start",
    "vite dev", "vite serve", "vite preview",
    "manage.py runserver",
    "flask run",
    "uvicorn", "gunicorn",
    "docker run", "docker-compose up", "docker compose up",
    "ng serve",
    "rails server", "rails s ",
    "expo start",
    "webpack serve", "webpack-dev-server",
)


def _looks_long_running(command: str) -> bool:
    lowered = command.lower()
    return any(hint in lowered for hint in LONG_RUNNING_HINTS)


def _run_background(command: str, work_dir: str) -> str:
    log_dir = os.path.join(work_dir, ".nvicoder", "logs")
    try:
        os.makedirs(log_dir, exist_ok=True)
    except OSError as e:
        return _err(f"Gagal membuat folder log: {e}")

    # Reserve job_id DULU (sebelum proses beneran jalan) supaya bisa dipakai
    # sebagai bagian nama file log -- menjamin unik walau ada 2 command
    # identik yang di-background-kan di detik yang sama (timestamp doang
    # gak cukup, resolusinya cuma per detik).
    job_id = _reserve_job_id()
    timestamp = time.strftime("%Y%m%d-%H%M%S")
    safe_name = "".join(c if c.isalnum() else "_" for c in command)[:40].strip("_") or "command"
    log_path = os.path.join(log_dir, f"job{job_id}-{timestamp}-{safe_name}.log")

    try:
        log_file = open(log_path, "w", encoding="utf-8")
        proc = subprocess.Popen(
            command,
            shell=True,
            cwd=work_dir,
            stdout=log_file,
            stderr=subprocess.STDOUT,
            stdin=subprocess.DEVNULL,
        )
    except Exception as e:
        return _err(f"Gagal menjalankan command di background: {e}")

    _register_background_job(job_id, command, proc, log_path)
    running_count = count_running_jobs()

    kill_hint = f"taskkill /PID {proc.pid} /F" if os.name == "nt" else f"kill {proc.pid}"
    return (
        f"OK: command dijalankan sebagai BACKGROUND JOB #{job_id} (PID={proc.pid}).\n"
        f"Total job background yang sedang berjalan sekarang: {running_count}.\n"
        f"Output real-time: {log_path} (baca lewat read_file kapan saja).\n"
        f"Untuk menghentikan: run_command('{kill_hint}'). Untuk lihat semua job: user bisa ketik /jobs."
    )


def run_command(command: str, cwd: str | None = None, auto_approve: bool = False,
                 background: bool = False, extra_safe: list[str] | None = None,
                 on_always_approve=None) -> str:
    work_dir = cwd or os.getcwd()
    is_long_running = _looks_long_running(command)

    if not auto_approve:
        if is_long_running and not background:
            print(f"\n\033[33m[nvicoder] Command ini kelihatan seperti proses long-running "
                  f"(dev server/watch mode) yang TIDAK AKAN SELESAI SENDIRI:\033[0m")
            print(f"  $ {command}")
            answer = input(
                "  Jalankan di background (b, disarankan), paksa foreground dengan timeout (f), "
                "selalu izinkan sesi ini (a), atau batal? [b/f/a/N]: "
            ).strip().lower()
            if answer in ("a", "always", "selalu"):
                background = True
                if on_always_approve:
                    on_always_approve()
                print("  \033[32m[nvicoder] OK, semua command berikutnya di sesi ini auto-approve.\033[0m")
            elif answer in ("b", "bg", "background", "y", "yes"):
                background = True
            elif answer in ("f", "fg", "foreground"):
                background = False
            else:
                return "DITOLAK: user membatalkan command long-running ini."
        elif not _is_safe_command(command, extra_safe):
            print(f"\n\033[33m[nvicoder] Model minta izin menjalankan perintah:\033[0m")
            print(f"  $ {command}")
            answer = input("  Izinkan? [y/N/a=selalu untuk sesi ini]: ").strip().lower()
            if answer in ("a", "always", "selalu"):
                if on_always_approve:
                    on_always_approve()
                print("  \033[32m[nvicoder] OK, semua command berikutnya di sesi ini auto-approve.\033[0m")
            elif answer not in ("y", "yes"):
                return "DITOLAK: user menolak menjalankan perintah ini."
    else:
        # yolo mode: kalau kedeteksi long-running dan model belum minta background
        # secara eksplisit, paksa background otomatis -- daripada nyangkut tanpa
        # ada siapa pun yang bisa menjawab prompt konfirmasi.
        if is_long_running and not background:
            background = True

    if background:
        return _run_background(command, work_dir)

    try:
        proc = subprocess.run(
            command,
            shell=True,
            cwd=work_dir,
            capture_output=True,
            text=True,
            timeout=config.COMMAND_TIMEOUT_SECONDS,
            stdin=subprocess.DEVNULL,  # cegah nyangkut kalau command diam-diam nunggu input interaktif
        )
        out = proc.stdout[-4000:] if proc.stdout else ""
        err = proc.stderr[-2000:] if proc.stderr else ""
        return f"exit_code={proc.returncode}\nstdout:\n{out}\nstderr:\n{err}"
    except subprocess.TimeoutExpired:
        return _err(
            f"Command timeout setelah {config.COMMAND_TIMEOUT_SECONDS}s tanpa selesai. "
            "Kalau ini memang command yang didesain jalan terus (dev server/watch mode), "
            "panggil ulang run_command dengan background=true."
        )
    except Exception as e:
        return _err(str(e))


def browser_control(action: str, url: str | None = None, selector: str | None = None,
                     value: str | None = None, path: str | None = None,
                     timeout: int | None = None, auto_approve: bool = False,
                     on_always_approve=None) -> str:
    action_norm = (action or "").strip().lower()
    # Browser belum jalan & action ini bakal memicunya -> minta konfirmasi
    # dulu (sekali per sesi), sama seperti alur konfirmasi run_command.
    if action_norm != "close" and not browser.is_running() and not auto_approve:
        target = f" ke {url}" if url else ""
        print(f"\n\033[33m[nvicoder] Model minta izin membuka browser nyata "
              f"(channel={config.BROWSER_CHANNEL}) untuk action '{action_norm}'{target}:\033[0m")
        answer = input("  Izinkan? [y/N/a=selalu untuk sesi ini]: ").strip().lower()
        if answer in ("a", "always", "selalu"):
            if on_always_approve:
                on_always_approve()
            print("  \033[32m[nvicoder] OK, semua command berikutnya di sesi ini auto-approve.\033[0m")
        elif answer not in ("y", "yes"):
            return "DITOLAK: user menolak membuka browser."
    return browser.browser_control(action, url=url, selector=selector, value=value,
                                    path=path, timeout=timeout)


def open_editor(
    initial_content: str = "",
    save_as: str = "",
    editor: str = "",
    instructions: str = "Edit file ini, lalu SAVE (Ctrl+S). Tutup editor kalau selesai."
) -> dict:
    """Buka editor teks untuk user ngetik input panjang.
    
    Returns:
        {"text": str, "images": []} - isi file setelah user save
    """
    import os
    import subprocess
    import time
    import tempfile
    from pathlib import Path
    
    # Tentukan editor
    if not editor:
        editor = os.environ.get("EDITOR", "notepad")
    
    # Buat temp file
    with tempfile.NamedTemporaryFile(mode="w", suffix=".txt", delete=False, encoding="utf-8") as tf:
        temp_path = tf.name
        header = f"# {instructions}\n# File ini akan dibaca otomatis setelah SAVE (Ctrl+S)\n"
        tf.write(header + initial_content)
    
    try:
        # Launch editor (non-blocking)
        if os.name == "nt" and editor.lower() in ("notepad", "notepad.exe"):
            subprocess.Popen(["notepad.exe", temp_path], shell=False)
        else:
            subprocess.Popen([editor, temp_path])
        
        # Polling file untuk detect save
        last_mtime = 0
        last_size = -1
        stable_count = 0
        
        # Print info ke terminal (bukan ke model)
        print(f"\n[open_editor] Membuka {editor}... Tunggu user SAVE (Ctrl+S).", flush=True)
        
        while True:
            time.sleep(0.5)
            if not os.path.exists(temp_path):
                return {"text": "[open_editor] File dihapus/dibatalkan", "images": []}
            
            stat = os.stat(temp_path)
            current_mtime = stat.st_mtime
            current_size = stat.st_size
            
            if current_mtime != last_mtime or current_size != last_size:
                last_mtime = current_mtime
                last_size = current_size
                stable_count = 0
                continue
            
            # File stabil (tidak berubah ~1 detik)
            stable_count += 1
            if stable_count >= 2 and current_size > len(header):
                with open(temp_path, "r", encoding="utf-8") as f:
                    content = f.read()
                # Hapus header komentar
                lines = [line for line in content.splitlines() if not line.strip().startswith("#")]
                user_content = "\n".join(lines).strip()
                
                # Simpan ke project root kalau save_as diisi
                saved_path = ""
                if save_as:
                    project_root = Path.cwd()
                    target_path = project_root / save_as
                    target_path.parent.mkdir(parents=True, exist_ok=True)
                    target_path.write_text(user_content, encoding="utf-8")
                    saved_path = f"\n[Disimpan ke: {save_as}]"
                
                print(f"[open_editor] User save selesai ({len(user_content)} char){saved_path}", flush=True)
                return {"text": f"[Isi dari editor]{saved_path}\n\n{user_content}", "images": []}
                
    except Exception as e:
        return {"text": f"[open_editor ERROR] {e}", "images": []}
    finally:
        try:
            os.unlink(temp_path)
        except:
            pass


DISPATCH = {
    "read_file": read_file,
    "write_file": write_file,
    "edit_file": edit_file,
    "list_dir": list_dir,
    "search_files": search_files,
    "run_command": run_command,
    "web_search": web_search,
    "searxng_search": searxng_search,
    "browser_control": browser_control,
    "open_editor": open_editor,
}


def execute_tool(name: str, arguments: dict, auto_approve: bool = False,
                  extra_safe: list[str] | None = None, on_always_approve=None) -> dict:
    """Return selalu {"text": str, "images": list[{"mime_type","data"}]} --
    tool native selalu images=[], tool MCP (mis. screenshot) bisa isi images
    (lihat mcp_client.call). agent.py yang mutusin apa image-nya beneran
    dikirim ke model, tergantung model aktif support vision atau nggak."""
    if mcp_client.is_mcp_tool(name):
        try:
            return mcp_client.call(name, arguments)
        except Exception as e:
            return {"text": _err(f"Gagal menjalankan {name}: {e}"), "images": []}

    fn = DISPATCH.get(name)
    if fn is None:
        return {"text": _err(f"Tool tidak dikenal: {name}"), "images": []}
    try:
        if name == "run_command":
            arguments = dict(arguments)
            arguments["auto_approve"] = auto_approve
            arguments["extra_safe"] = extra_safe
            arguments["on_always_approve"] = on_always_approve
        elif name == "browser_control":
            arguments = dict(arguments)
            arguments["auto_approve"] = auto_approve
            arguments["on_always_approve"] = on_always_approve
        result = fn(**arguments)

        return {"text": result, "images": []}
    except TypeError as e:
        return {"text": _err(f"Argumen tidak valid untuk {name}: {e}"), "images": []}
    except Exception as e:
        return {"text": _err(f"Gagal menjalankan {name}: {e}"), "images": []}
