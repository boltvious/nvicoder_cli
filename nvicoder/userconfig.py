"""
Layered TOML config untuk nvicoder, supaya kamu tidak perlu ketik --effort/
--model tiap kali. Polanya sama seperti tool CLI Python lain (ruff, black,
pytest): baca dari [tool.nvicoder] di pyproject.toml proyek, atau dari file
config.toml khusus.

Urutan prioritas (paling tinggi menang), dievaluasi di cli.py:

    1. Flag CLI eksplisit (--effort, --model, dst)      <- selalu menang
    2. ./nvicoder.toml                    di folder kerja saat ini (project)
    3. [tool.nvicoder] di ./pyproject.toml di folder kerja saat ini (project)
    4. ~/.config/nvicoder/config.toml                     (global, semua project)
    5. Environment variable (NVICODER_EFFORT, dst)         <- fallback lama
    6. Default bawaan di config.py

Catatan keamanan: loader ini SENGAJA tidak membaca api_key dari TOML.
NVIDIA_API_KEY tetap harus lewat environment variable saja, supaya tidak
ada risiko API key ke-commit tanpa sengaja di file nvicoder.toml yang masuk
ke git repo.
"""

import os
import sys

try:
    import tomllib  # stdlib, Python 3.11+
except ModuleNotFoundError:  # pragma: no cover - hanya untuk Python 3.10
    import tomli as tomllib  # type: ignore

# Key yang boleh datang dari file TOML. Sengaja tidak termasuk api_key.
# "effort" dan "model" independen -- effort cuma ngatur temperature/max_tokens,
# "model" ngatur model default (provider dideteksi otomatis dari nama model).
# Dual-model (CoT): reasoning_model (thinker), assistant_model (doer), dual_model (enable flag)
_ALLOWED_KEYS = {"effort", "model", "yolo", "prompt_file", "safe_commands",
                 "dual_model", "reasoning_model", "assistant_model"}


def _read_toml(path: str) -> dict:
    try:
        with open(path, "rb") as f:
            return tomllib.load(f)
    except (OSError, tomllib.TOMLDecodeError):
        return {}


def global_config_path() -> str:
    if sys.platform == "win32":
        base = os.environ.get("APPDATA", os.path.expanduser("~"))
        return os.path.join(base, "nvicoder", "config.toml")
    xdg = os.environ.get("XDG_CONFIG_HOME", os.path.expanduser("~/.config"))
    return os.path.join(xdg, "nvicoder", "config.toml")


def _filter_allowed(d: dict) -> dict:
    return {k: v for k, v in d.items() if k in _ALLOWED_KEYS}


def load_layered_config(cwd: str | None = None) -> dict:
    """Gabungkan config global + project, project menang kalau bentrok."""
    cwd = cwd or os.getcwd()
    merged: dict = {}

    g_path = global_config_path()
    if os.path.isfile(g_path):
        merged.update(_filter_allowed(_read_toml(g_path)))

    pyproject_path = os.path.join(cwd, "pyproject.toml")
    if os.path.isfile(pyproject_path):
        data = _read_toml(pyproject_path)
        tool_cfg = data.get("tool", {}).get("nvicoder", {})
        merged.update(_filter_allowed(tool_cfg))

    project_path = os.path.join(cwd, "nvicoder.toml")
    if os.path.isfile(project_path):
        merged.update(_filter_allowed(_read_toml(project_path)))

    return merged


def describe_sources(cwd: str | None = None) -> list[str]:
    """Untuk debugging/'/config' command: file mana saja yang kebaca."""
    cwd = cwd or os.getcwd()
    found = []
    g_path = global_config_path()
    if os.path.isfile(g_path):
        found.append(g_path)
    pyproject_path = os.path.join(cwd, "pyproject.toml")
    if os.path.isfile(pyproject_path) and _read_toml(pyproject_path).get("tool", {}).get("nvicoder"):
        found.append(f"{pyproject_path} [tool.nvicoder]")
    project_path = os.path.join(cwd, "nvicoder.toml")
    if os.path.isfile(project_path):
        found.append(project_path)
    return found
