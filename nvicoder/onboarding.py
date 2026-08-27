"""
Alur onboarding interaktif nvicoder, dipanggil sekali di awal cli.main():

  1. resolve_api_key()     -> env var, lalu key tersimpan, lalu wizard interaktif
  2. ensure_folder_trust()  -> prompt "percaya folder ini?" (sekali per folder)

Pola ini sengaja meniru first-run wizard yang sudah umum di CLI lain
(gh auth login, aws configure, npx create-*, dan Claude Code sendiri):
tanya sesedikit mungkin, cuma sekali, lalu diam selamanya setelah itu.
"""

import sys
from getpass import getpass

from openai import OpenAI

from . import config, model_utils, trust, ui


def resolve_api_key() -> str | None:
    """Urutan: env var -> file tersimpan -> wizard interaktif (kalau TTY)."""
    if config.NVIDIA_API_KEY:
        return config.NVIDIA_API_KEY

    saved = trust.load_saved_api_key()
    if saved:
        return saved

    if not sys.stdin.isatty():
        # Non-interaktif (CI/script/pipe) dan tidak ada key sama sekali:
        # jangan coba getpass (bisa hang), langsung gagal dengan pesan jelas.
        return None

    return _run_api_key_wizard()


def _run_api_key_wizard() -> str | None:
    print(f"{ui.BOLD}Selamat datang di nvicoder!{ui.RESET}")
    print("Belum ada NVIDIA_API_KEY yang terdeteksi (env var ataupun tersimpan).")
    print(f"Ambil API key gratis di {ui.CYAN}https://build.nvidia.com{ui.RESET} "
          "(klik model apa saja -> \"Get API Key\").\n")

    try:
        key = getpass("Paste API key (nvapi-...), input disembunyikan saat diketik: ").strip()
    except (EOFError, KeyboardInterrupt):
        print()
        return None

    if not key:
        ui.print_error("API key kosong, dibatalkan.")
        return None

    print("Memvalidasi key...", end=" ", flush=True)
    models = _try_list_models(key)
    if models is None:
        print(f"{ui.YELLOW}tidak bisa diverifikasi.{ui.RESET}")
        answer = input(
            "Key tidak bisa divalidasi sekarang (mungkin API lambat/limit, "
            "bukan berarti key-nya salah). Tetap pakai key ini? [y/N]: "
        ).strip().lower()
        if answer not in ("y", "yes"):
            return None
    else:
        print(f"{ui.GREEN}OK{ui.RESET} ({len(models)} model terlihat di key ini)")
        _maybe_pick_default_model(models)

    try:
        save = input(
            "\nSimpan key ini di ~/.config/nvicoder supaya tidak perlu input ulang "
            "lain kali? (disimpan plaintext, permission 600) [Y/n]: "
        ).strip().lower()
    except (EOFError, KeyboardInterrupt):
        save = "n"

    if save in ("", "y", "yes"):
        trust.save_api_key(key)
        print(f"Tersimpan di {trust.credentials_path()}.\n")
    else:
        print("Oke, tidak disimpan — akan ditanya lagi di sesi berikutnya.\n")

    return key


def _try_list_models(key: str) -> list[str] | None:
    try:
        client = OpenAI(base_url=config.NVIDIA_BASE_URL, api_key=key)
        resp = client.models.list()
        return [m.id for m in resp.data]
    except Exception:
        return None


def _maybe_pick_default_model(models: list[str]) -> None:
    shortlist = model_utils.shortlist_relevant(models, limit=15)
    if not shortlist:
        return

    print(f"\n{ui.BOLD}Beberapa model yang tersedia di key kamu:{ui.RESET}")
    model_utils.print_model_list(shortlist)
    print(f"  0. Lewati, pakai default bawaan ({config.DEFAULT_MODEL})")

    try:
        choice = input(f"\nPilih model default (dipakai di effort manapun, ganti kapan saja lewat /model) [0]: ").strip()
    except (EOFError, KeyboardInterrupt):
        return

    if not choice or choice == "0":
        return
    try:
        idx = int(choice) - 1
    except ValueError:
        print("Input tidak dikenali, pakai default bawaan.")
        return
    if 0 <= idx < len(shortlist):
        chosen = shortlist[idx]
        config.DEFAULT_MODEL = chosen
        print(f"OK, model default sesi ini: {chosen}.")
        print("(Biar permanen: set NVICODER_MODEL di shell rc, atau 'model' di nvicoder.toml)")


def ensure_folder_trust(path: str | None = None, auto_yes: bool = False) -> bool:
    """True kalau boleh lanjut jalan di folder ini."""
    import os
    target = path or os.getcwd()

    if trust.is_folder_trusted(target):
        return True

    if auto_yes:
        trust.trust_folder(target)
        return True

    if not sys.stdin.isatty():
        ui.print_error(
            f"Folder {os.path.realpath(target)} belum dipercaya dan sesi ini non-interaktif. "
            "Jalankan sekali secara interaktif dulu, atau pakai flag -y/--yes."
        )
        return False

    print(f"\n{ui.YELLOW}⚠ Folder ini belum pernah dipercaya sebelumnya:{ui.RESET}")
    print(f"  {os.path.realpath(target)}\n")
    print("Di dalam folder ini, nvicoder akan bisa:")
    print("  - membaca & menulis file (termasuk menimpa/menghapus isi file)")
    print("  - menjalankan command shell (selalu minta konfirmasi kecuali --yolo)")
    try:
        answer = input(f"\n{ui.BOLD}Percaya folder ini?{ui.RESET} [y/N]: ").strip().lower()
    except (EOFError, KeyboardInterrupt):
        print()
        return False

    if answer in ("y", "yes"):
        trust.trust_folder(target)
        print("OK, folder ini akan diingat — tidak akan ditanya lagi.\n")
        return True

    print("Dibatalkan. nvicoder tidak berjalan di folder yang belum dipercaya.")
    return False
