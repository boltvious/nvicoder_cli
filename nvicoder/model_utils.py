"""
Helper buat menampilkan daftar model dari sebuah NVIDIA API key. Dipakai
bareng oleh wizard onboarding (nvicoder/onboarding.py, saat setup pertama
kali) dan command /models di REPL (nvicoder/cli.py, on-demand kapan saja),
supaya logic filter & format tampilannya tidak duplikat di dua tempat.
"""

from . import ui

# Heuristik sederhana: model yang namanya mengandung salah satu keyword ini
# kemungkinan besar chat/instruct model yang relevan buat coding-agent.
# Ini BUKAN filter sempurna — kalau model yang kamu cari tidak muncul di
# sini, pakai '/models all' buat lihat daftar lengkap tanpa filter.
RELEVANT_KEYWORDS = (
    "instruct", "chat", "coder", "nemotron", "qwen", "deepseek",
    "llama", "glm", "mistral", "minimax", "kimi", "gemma", "granite",
)


def shortlist_relevant(models: list[str], limit: int = 20) -> list[str]:
    relevant = [m for m in models if any(k in m.lower() for k in RELEVANT_KEYWORDS)]
    pool = relevant if relevant else models
    return sorted(pool)[:limit]


def print_model_list(models: list[str], current: str | None = None) -> None:
    for i, m in enumerate(models, 1):
        marker = f" {ui.GREEN}← aktif sekarang{ui.RESET}" if m == current else ""
        print(f"  {i}. {m}{marker}")
