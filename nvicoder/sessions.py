"""
Persistensi sesi percakapan. Setiap sesi REPL dapat UUID sendiri, riwayat
(messages) di-autosave ke `.nvicoder/sessions/<uuid>.json` di dalam project
(folder kerja saat ini) setiap kali satu turn selesai, plus eksplisit saat
`/exit`. Bisa dilanjutkan lagi lewat `nvicoder --resume <uuid>` (boleh UUID
penuh atau prefix pendek asal unik, mirip short-hash git).

Sengaja per-project (bukan global) karena riwayat percakapan biasanya
mereferensikan file/path yang relatif ke project itu -- resume dari
folder yang beda bisa membingungkan.
"""

import json
import os
import time
import uuid as uuid_module


def _sessions_dir(cwd: str | None = None) -> str:
    return os.path.join(cwd or os.getcwd(), ".nvicoder", "sessions")


def new_session_id() -> str:
    return str(uuid_module.uuid4())


def _session_filename(session_id: str) -> str:
    return f"{session_id}.json"


def save_session(session_id: str, agent, cwd: str | None = None) -> str:
    """Simpan/update state sesi ke disk. Return path file-nya."""
    d = _sessions_dir(cwd)
    os.makedirs(d, exist_ok=True)
    path = os.path.join(d, _session_filename(session_id))

    title = ""
    for m in agent.messages:
        if m.get("role") == "user":
            title = (m.get("content") or "").strip().replace("\n", " ")[:60]
            break

    created_at = time.time()
    if os.path.isfile(path):
        try:
            with open(path, "r", encoding="utf-8") as f:
                created_at = json.load(f).get("created_at", created_at)
        except (OSError, json.JSONDecodeError):
            pass

    data = {
        "id": session_id,
        "created_at": created_at,
        "updated_at": time.time(),
        "cwd": cwd or os.getcwd(),
        "effort": agent.effort,
        "model_override": agent.model_override,
        "title": title,
        "session_tokens": agent.session_tokens,
        "messages": agent.messages,
    }
    tmp_path = path + ".tmp"
    with open(tmp_path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)
    os.replace(tmp_path, path)  # atomic-ish: hindari file korup kalau nge-crash pas nulis
    return path


def find_session_files(id_or_prefix: str, cwd: str | None = None) -> list[str]:
    """Cari file sesi cocok id penuh atau prefix. Return list nama file (bukan path lengkap)."""
    d = _sessions_dir(cwd)
    if not os.path.isdir(d):
        return []
    exact = _session_filename(id_or_prefix)
    if os.path.isfile(os.path.join(d, exact)):
        return [exact]
    return sorted(f for f in os.listdir(d) if f.startswith(id_or_prefix) and f.endswith(".json"))


def load_session_file(filename: str, cwd: str | None = None) -> dict | None:
    path = os.path.join(_sessions_dir(cwd), filename)
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except (OSError, json.JSONDecodeError):
        return None


def list_sessions(cwd: str | None = None) -> list[dict]:
    """Semua sesi di project ini, terbaru duluan."""
    d = _sessions_dir(cwd)
    if not os.path.isdir(d):
        return []
    result = []
    for fname in os.listdir(d):
        if not fname.endswith(".json") or fname.endswith(".tmp"):
            continue
        data = load_session_file(fname, cwd)
        if data:
            result.append(data)
    result.sort(key=lambda s: s.get("updated_at", 0), reverse=True)
    return result
