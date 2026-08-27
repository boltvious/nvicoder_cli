"""
Penyimpanan lokal untuk dua hal:
  1. Folder mana saja yang sudah "dipercaya" user (supaya prompt trust
     cuma muncul sekali per folder, bukan tiap kali nvicoder dipanggil).
  2. NVIDIA_API_KEY yang disimpan opsional supaya tidak perlu di-export
     ulang tiap sesi terminal baru.

Sengaja pakai JSON (bukan TOML) untuk kedua file ini karena keduanya
dikelola otomatis oleh nvicoder sendiri (bukan untuk diedit manual), dan
tomllib di stdlib Python cuma bisa baca TOML, tidak bisa menulis.

File-file ini ada di luar folder project mana pun (~/.config/nvicoder/),
jadi tidak akan pernah ke-commit tidak sengaja ke git.
"""

import json
import os
import stat
import sys


def config_dir() -> str:
    if sys.platform == "win32":
        base = os.environ.get("APPDATA", os.path.expanduser("~"))
        return os.path.join(base, "nvicoder")
    xdg = os.environ.get("XDG_CONFIG_HOME", os.path.expanduser("~/.config"))
    return os.path.join(xdg, "nvicoder")


def _trusted_folders_path() -> str:
    return os.path.join(config_dir(), "trusted_folders.json")


def credentials_path() -> str:
    return os.path.join(config_dir(), "credentials.json")


def _ensure_config_dir() -> None:
    os.makedirs(config_dir(), exist_ok=True)


def _read_json(path: str, default):
    if not os.path.isfile(path):
        return default
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except (OSError, json.JSONDecodeError):
        return default


# ---------------------------------------------------------------- trust ---

def is_folder_trusted(path: str | None = None) -> bool:
    target = os.path.realpath(path or os.getcwd())
    trusted = _read_json(_trusted_folders_path(), [])
    return target in trusted


def trust_folder(path: str | None = None) -> None:
    target = os.path.realpath(path or os.getcwd())
    _ensure_config_dir()
    trusted = _read_json(_trusted_folders_path(), [])
    if target not in trusted:
        trusted.append(target)
    with open(_trusted_folders_path(), "w", encoding="utf-8") as f:
        json.dump(trusted, f, indent=2)


def untrust_folder(path: str | None = None) -> bool:
    target = os.path.realpath(path or os.getcwd())
    p = _trusted_folders_path()
    trusted = _read_json(p, [])
    if target not in trusted:
        return False
    trusted.remove(target)
    with open(p, "w", encoding="utf-8") as f:
        json.dump(trusted, f, indent=2)
    return True


# --------------------------------------------------------- credentials ---

def load_saved_api_key() -> str | None:
    data = _read_json(credentials_path(), {})
    return data.get("nvidia_api_key")


def save_api_key(key: str) -> None:
    _ensure_config_dir()
    p = credentials_path()
    with open(p, "w", encoding="utf-8") as f:
        json.dump({"nvidia_api_key": key}, f, indent=2)
    try:
        os.chmod(p, stat.S_IRUSR | stat.S_IWUSR)  # 600: cuma owner yang bisa baca/tulis
    except OSError:
        pass  # beberapa filesystem (mis. FAT/exFAT di Windows) tidak dukung chmod unix-style


def forget_api_key() -> bool:
    p = credentials_path()
    if os.path.isfile(p):
        os.remove(p)
        return True
    return False
