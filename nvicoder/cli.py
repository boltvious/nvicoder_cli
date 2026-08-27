import argparse
import sys
import time
import subprocess
import tempfile
import os

from . import config, mcp_client, model_utils, onboarding, sessions, tools, trust, ui, userconfig
from .agent import Agent


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="nvicoder", description="Coding agent CLI berbasis NVIDIA NIM API.")
    parser.add_argument(
        "--effort", choices=list(config.EFFORT_PROFILES.keys()), default=config.DEFAULT_EFFORT,
        help="Tingkat effort/model: low (cepat), medium (default), high (paling akurat, lebih lambat).",
    )
    parser.add_argument(
        "--model", default=None,
        help="Override model default secara manual (provider auto dari prefix nama, independen dari --effort).",
    )
    parser.add_argument(
        "--dual-model", action="store_true",
        help="Aktifkan mode dual-model (Constitutional AI Critic): critic model (evaluator) + assistant model (doer).",
    )
    parser.add_argument(
        "--reasoning-model", default=None,
        help="Model untuk critic/evaluation (default: NVICODER_CRITIC_MODEL / nvidia/nemotron-3-ultra-550b-a55b).",
    )
    parser.add_argument(
        "--assistant-model", default=None,
        help="Model untuk eksekusi tool-calling (default: NVICODER_ASSISTANT_MODEL / meta/muse-glimmer-30b).",
    )
    parser.add_argument(
        "--yolo", action="store_true",
        help="Auto-approve semua run_command tanpa konfirmasi (HATI-HATI, hanya untuk sandbox/CI).",
    )
    parser.add_argument(
        "--no-yolo", action="store_true",
        help="Paksa matikan yolo mode, meski diaktifkan lewat file config.toml.",
    )
    parser.add_argument(
        "--prompt-file", default=None, metavar="PATH",
        help="Pakai system prompt kustom dari file .md/.txt ini, ganti nvicoder/prompt.md bawaan.",
    )
    parser.add_argument(
        "-y", "--yes", action="store_true",
        help="Auto-jawab 'ya' untuk prompt trust folder pertama kali (untuk CI/script).",
    )
    parser.add_argument(
        "--logout", action="store_true",
        help="Hapus API key yang tersimpan di ~/.config/nvicoder, lalu keluar.",
    )
    parser.add_argument(
        "--untrust", action="store_true",
        help="Cabut kepercayaan folder saat ini (akan ditanya lagi lain kali), lalu keluar.",
    )
    parser.add_argument(
        "--resume", default=None, metavar="ID",
        help="Lanjutkan sesi tersimpan (UUID lengkap atau prefix unik). Lihat --list-sessions.",
    )
    parser.add_argument(
        "--list-sessions", action="store_true",
        help="Tampilkan semua sesi tersimpan di project ini, lalu keluar.",
    )
    parser.add_argument("prompt", nargs="*", help="Kalau diisi, jalankan satu perintah lalu keluar (non-interaktif). Bisa pakai @file.txt untuk baca isi file.")
    parser.add_argument(
        "--file", "-f", default=None, metavar="PATH",
        help="Baca prompt dari file (alternatif @file.txt)."
    )
    return parser


def repl(agent: Agent, session_id: str) -> None:
    ui.banner(agent.effort, agent.model)
    while True:
        running_jobs = tools.count_running_jobs()
        prompt_label = f"{ui.BOLD}>{ui.RESET} " if running_jobs == 0 else f"{ui.BOLD}[{running_jobs} bg]>{ui.RESET} "
        try:
            user_input = input(prompt_label).strip()
        except (EOFError, KeyboardInterrupt):
            _save_and_announce(agent, session_id)
            print("Sampai jumpa!")
            return

        if not user_input:
            continue

        if user_input.startswith("/"):
            if not handle_slash_command(user_input, agent, session_id):
                return
            continue

        # Support @file.txt di REPL
        if user_input.startswith("@"):
            file_path = user_input[1:].strip()
            try:
                with open(file_path, "r", encoding="utf-8") as f:
                    user_input = f.read().strip()
                print(f"{ui.DIM}[Paste dari @{file_path}, {len(user_input)} char]{ui.RESET}")
            except Exception as e:
                ui.print_error(f"Gagal baca file {file_path}: {e}")
                continue

        try:
            agent.run_turn(user_input)
            sessions.save_session(session_id, agent)  # autosave tiap turn kelar, jaga2 kalau nanti crash/ke-close paksa
        except KeyboardInterrupt:
            print("\n(dibatalkan)")
        except Exception as e:
            ui.print_error(str(e))


def _save_and_announce(agent: Agent, session_id: str) -> None:
    """Simpan sesi (kalau ada isinya) dan kasih tau cara resume. Dipanggil dari /exit maupun Ctrl+C/Ctrl+D."""
    if len(agent.messages) <= 1:
        return  # cuma system prompt doang, belum ada percakapan beneran -- gak usah disimpan
    sessions.save_session(session_id, agent)
    print(f"\nSesi tersimpan ({session_id}).")
    print(f"Lanjutkan lagi lain kali dengan: nvicoder --resume {session_id}")


def handle_slash_command(cmd: str, agent: Agent, session_id: str) -> bool:
    """Return False kalau harus keluar dari REPL."""
    parts = cmd.split(maxsplit=1)
    name = parts[0].lower()
    arg = parts[1].strip() if len(parts) > 1 else ""

    if name in ("/exit", "/quit"):
        _save_and_announce(agent, session_id)
        print("Sampai jumpa!")
        return False
    if name == "/help":
        print(ui.help_text())
    elif name == "/effort":
        if agent.set_effort(arg):
            print(f"OK, effort diganti ke '{arg}' (model tetap: {agent.model} -- effort tidak mengubah model).")
        else:
            print(f"Effort tidak dikenal. Pilihan: {', '.join(config.EFFORT_PROFILES)}")
    elif name == "/model":
        if arg:
            agent.model_override = arg
            print(f"OK, model di-override manual ke '{arg}'.")
        else:
            print(f"Model saat ini: {agent.model}")
    elif name == "/models":
        show_all = arg.strip().lower() == "all"
        print("Mengambil daftar model dari API key kamu...")
        models = agent.list_models()
        if models is None:
            ui.print_error("Gagal mengambil daftar model (cek koneksi, atau API key sedang bermasalah).")
        elif not models:
            print("Tidak ada model yang terlihat di key ini.")
        else:
            if show_all:
                display = models[:150]
                extra = f", ditampilkan 150 pertama dari {len(models)}" if len(models) > 150 else ""
                print(f"{ui.BOLD}Semua model{extra}:{ui.RESET}")
            else:
                display = model_utils.shortlist_relevant(models, limit=20)
                print(
                    f"{ui.BOLD}Model relevan buat coding-agent ({len(display)} dari {len(models)} total "
                    f"— ketik '/models all' buat lihat semua):{ui.RESET}"
                )
            model_utils.print_model_list(display, current=agent.model)

            try:
                choice = input("\nPilih nomor buat pakai model itu sekarang, atau Enter buat skip: ").strip()
            except (EOFError, KeyboardInterrupt):
                choice = ""
            if choice:
                try:
                    idx = int(choice) - 1
                except ValueError:
                    idx = -1
                if 0 <= idx < len(display):
                    agent.model_override = display[idx]
                    print(f"OK, model aktif sekarang: {agent.model}")
                else:
                    print("Nomor di luar jangkauan, dibatalkan.")
    elif name == "/clear":
        agent.clear()
        print("Riwayat percakapan dihapus.")
    elif name == "/reasoning":
        if agent.last_reasoning:
            print(f"{ui.BOLD}Reasoning lengkap (giliran terakhir):{ui.RESET}\n")
            ui.console.print(f"[dim italic]{agent.last_reasoning}[/dim italic]")
        else:
            print("Belum ada reasoning yang tersimpan (model terakhir mungkin bukan model reasoning).")
    elif name == "/yolo":
        agent.yolo = not agent.yolo
        print(f"yolo mode: {'ON (semua command auto-approve)' if agent.yolo else 'OFF'}")
    elif name == "/paste":
        # Buka editor & polling file untuk auto-detect save (Ctrl+S di Notepad)
        # User: paste teks -> Ctrl+S -> nvicoder auto-baca & jalankan
        editor = os.environ.get("EDITOR", "notepad")
        with tempfile.NamedTemporaryFile(mode="w", suffix=".txt", delete=False, encoding="utf-8") as tf:
            temp_path = tf.name
            tf.write("# Paste teks panjang di sini, lalu SAVE (Ctrl+S)\n# Baris yang mulai # akan diabaikan\n")
        
        print(f"{ui.DIM}Membuka {editor}... Paste teks, lalu SAVE (Ctrl+S). nvicoder akan auto-detect.{ui.RESET}")
        
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
            print(f"{ui.DIM}Menunggu save... (Ctrl+C untuk batal){ui.RESET}")
            
            while True:
                try:
                    time.sleep(0.5)
                    if not os.path.exists(temp_path):
                        print("(File dihapus, dibatalkan)")
                        break
                    
                    stat = os.stat(temp_path)
                    current_mtime = stat.st_mtime
                    current_size = stat.st_size
                    
                    # File berubah (di-save)
                    if current_mtime != last_mtime or current_size != last_size:
                        last_mtime = current_mtime
                        last_size = current_size
                        stable_count = 0
                        continue
                    
                    # File stabil (tidak berubah 2x polling = ~1 detik)
                    stable_count += 1
                    if stable_count >= 2 and current_size > 0:
                        # Baca isi
                        with open(temp_path, "r", encoding="utf-8") as f:
                            content = f.read()
                        lines = [line for line in content.splitlines() if not line.strip().startswith("#")]
                        user_input = "\n".join(lines).strip()
                        if user_input:
                            print(f"{ui.DIM}[Paste dari editor, {len(user_input)} char]{ui.RESET}")
                            agent.run_turn(user_input)
                            sessions.save_session(session_id, agent)
                        else:
                            print("(Dibatalkan - input kosong setelah filter komentar)")
                        break
                        
                except KeyboardInterrupt:
                    print("\n(Dibatalkan)")
                    break
                    
        except Exception as e:
            ui.print_error(f"Gagal: {e}")
        finally:
            try:
                os.unlink(temp_path)
            except:
                pass
    elif name in ("/jobs", "/bg"):
        jobs = tools.list_background_jobs()
        if not jobs:
            print("Belum ada background job di sesi ini.")
        else:
            running = sum(1 for j in jobs if j["status"] == "running")
            print(f"{ui.BOLD}Background jobs ({running} sedang jalan, {len(jobs)} total sejak sesi ini mulai):{ui.RESET}")
            for j in jobs:
                status_color = ui.GREEN if j["status"] == "running" else ui.GREY
                print(f"  #{j['id']}  PID={j['pid']}  {status_color}[{j['status']}]{ui.RESET}  {j['command']}")
                print(f"       log: {j['log_path']}")
    elif name == "/config":
        sources = userconfig.describe_sources()
        if sources:
            print(f"{ui.BOLD}Config aktif dari:{ui.RESET}")
            for s in sources:
                print(f"  - {s}")
        else:
            print("Tidak ada file config.toml/nvicoder.toml yang terbaca, pakai default bawaan.")
        provider = config.provider_for_model(agent.model)
        print(f"{ui.BOLD}Resolved:{ui.RESET} effort={agent.effort} model={agent.model} (provider={provider}) yolo={agent.yolo}")
        print(f"{ui.BOLD}Model default:{ui.RESET} {config.DEFAULT_MODEL} (ganti kapan saja lewat /model, independen dari effort)")
        print(f"{ui.BOLD}Effort tiers (temperature/max_tokens):{ui.RESET}")
        for tier, profile in config.EFFORT_PROFILES.items():
            marker = f" {ui.GREEN}← aktif{ui.RESET}" if tier == agent.effort else ""
            print(f"  {tier}: temperature={profile.temperature} max_tokens={profile.max_tokens}{marker}")
        if agent.model_override:
            print(f"  (model_override sesi ini: {agent.model_override})")
        if agent.extra_safe_commands:
            print(f"{ui.BOLD}Extra safe commands (auto-approve):{ui.RESET}")
            for c in agent.extra_safe_commands:
                print(f"  - {c}")
    elif name == "/sessions":
        sess_list = sessions.list_sessions()
        if not sess_list:
            print("Belum ada sesi tersimpan di project ini.")
        else:
            print(f"{ui.BOLD}Sesi tersimpan di project ini ({len(sess_list)}):{ui.RESET}")
            for s in sess_list:
                marker = f" {ui.GREEN}← sesi ini{ui.RESET}" if s.get("id") == session_id else ""
                updated = time.strftime("%Y-%m-%d %H:%M", time.localtime(s.get("updated_at", 0)))
                title = s.get("title") or "(tanpa judul)"
                print(f"  {s['id']}  [{updated}]  {title}{marker}")
    else:
        print(f"Perintah tidak dikenal: {name}. Ketik /help untuk daftar perintah.")
    return True


def connect_mcp_servers(auto_yes: bool = False) -> None:
    """Kalau ada .mcp.json di cwd, tawarkan konek ke server MCP-nya (sekali per proses).
    Server MCP jalan proses eksternal (bisa download/eksekusi kode pihak ketiga) -> minta konfirmasi."""
    servers = mcp_client.available_servers()
    if not servers:
        return

    names = list(servers.keys())
    print(f"\n{ui.BOLD}Ditemukan {len(names)} server MCP di .mcp.json:{ui.RESET} {', '.join(names)}")
    if not auto_yes:
        answer = input("  Konek sekarang? [y/N]: ").strip().lower()
        if answer not in ("y", "yes"):
            print("  Dilewati -- tool dari server MCP ini tidak akan tersedia di sesi ini.")
            return

    for name in names:
        cfg = servers[name]
        cmd_repr = " ".join([cfg.get("command", "")] + cfg.get("args", []))
        print(f"  Menghubungkan '{name}' ({cmd_repr})...", end=" ", flush=True)
        try:
            session = mcp_client.connect(name)
            print(f"{ui.GREEN}OK{ui.RESET} ({len(session.tools)} tool tersedia)")
        except Exception as e:
            print(f"{ui.YELLOW}GAGAL{ui.RESET}: {e}")


def main(argv=None) -> int:
    parser = build_parser()

    # Layer config.toml (global + project) sebagai default baru untuk parser,
    # sebelum parsing argumen CLI — jadi flag eksplisit tetap selalu menang.
    file_cfg = userconfig.load_layered_config()
    if file_cfg:
        overrides = {}
        if file_cfg.get("effort") in config.EFFORT_PROFILES:
            overrides["effort"] = file_cfg["effort"]
        if "model" in file_cfg:
            overrides["model"] = file_cfg["model"]
        if "yolo" in file_cfg:
            overrides["yolo"] = bool(file_cfg["yolo"])
        if "prompt_file" in file_cfg:
            overrides["prompt_file"] = file_cfg["prompt_file"]
        # Dual-model (CoT) config from TOML
        if "dual_model" in file_cfg:
            overrides["dual_model"] = bool(file_cfg["dual_model"])
        if "reasoning_model" in file_cfg:
            overrides["reasoning_model"] = file_cfg["reasoning_model"]
        if "assistant_model" in file_cfg:
            overrides["assistant_model"] = file_cfg["assistant_model"]
        if overrides:
            parser.set_defaults(**overrides)

    extra_safe_commands = file_cfg.get("safe_commands") if isinstance(file_cfg.get("safe_commands"), list) else None

    args = parser.parse_args(argv)
    if args.no_yolo:
        args.yolo = False

    # --logout / --untrust / --list-sessions: aksi sekali-jalan, tidak perlu bikin Agent.
    if args.logout:
        removed = trust.forget_api_key()
        print("API key tersimpan sudah dihapus." if removed else "Tidak ada API key tersimpan.")
        return 0
    if args.untrust:
        removed = trust.untrust_folder()
        print("Folder ini dicabut dari daftar trusted." if removed else "Folder ini memang belum trusted.")
        return 0
    if args.list_sessions:
        sess_list = sessions.list_sessions()
        if not sess_list:
            print("Belum ada sesi tersimpan di project ini.")
        else:
            print(f"{ui.BOLD}Sesi tersimpan ({len(sess_list)}):{ui.RESET}")
            for s in sess_list:
                updated = time.strftime("%Y-%m-%d %H:%M", time.localtime(s.get("updated_at", 0)))
                title = s.get("title") or "(tanpa judul)"
                print(f"  {s['id']}  [{updated}]  effort={s.get('effort')}  {title}")
            print(f"\nLanjutkan salah satunya: nvicoder --resume <id> (boleh id pendek asal unik)")
        return 0

    # --resume: cari & baca sesi tersimpan SEBELUM bikin Agent, supaya effort/model
    # hasil resume bisa jadi default baru (tapi tetap kalah kalau user override
    # eksplisit lewat --effort/--model di command yang sama).
    resume_data = None
    if args.resume:
        matches = sessions.find_session_files(args.resume)
        if len(matches) == 0:
            ui.print_error(f"Tidak ada sesi yang cocok dengan '{args.resume}'. Coba --list-sessions.")
            return 1
        if len(matches) > 1:
            ui.print_error(f"'{args.resume}' cocok dengan {len(matches)} sesi, kasih id yang lebih spesifik:")
            for m in matches:
                print(f"  - {m[:-5]}")  # buang '.json'
            return 1
        resume_data = sessions.load_session_file(matches[0])
        if not resume_data:
            ui.print_error("Gagal membaca file sesi tersimpan (mungkin corrupt).")
            return 1

        resume_overrides = {}
        if resume_data.get("effort") in config.EFFORT_PROFILES:
            resume_overrides["effort"] = resume_data["effort"]
        if resume_data.get("model_override"):
            resume_overrides["model"] = resume_data["model_override"]
        if resume_overrides:
            parser.set_defaults(**resume_overrides)
            args = parser.parse_args(argv)  # re-parse: default baru kepakai, tapi flag eksplisit tetap menang
            if args.no_yolo:
                args.yolo = False

    # 1) Pastikan ada API key: env var -> tersimpan -> wizard interaktif.
    api_key = onboarding.resolve_api_key()
    if not api_key:
        ui.print_error(
            "Tidak ada NVIDIA_API_KEY yang valid. Set env var NVIDIA_API_KEY, "
            "atau jalankan nvicoder secara interaktif sekali untuk setup."
        )
        return 1

    # 2) Pastikan folder saat ini sudah dipercaya user (sekali per folder).
    if not onboarding.ensure_folder_trust(auto_yes=args.yes):
        return 1

    # 3) Kalau ada .mcp.json, tawarkan konek ke server MCP-nya.
    connect_mcp_servers(auto_yes=args.yes or args.yolo)

    try:
        agent = Agent(
            effort=args.effort, model_override=args.model, yolo=args.yolo,
            prompt_file=args.prompt_file, api_key=api_key,
            extra_safe_commands=extra_safe_commands,
            resume_messages=resume_data["messages"] if resume_data else None,
            session_tokens=resume_data.get("session_tokens") if resume_data else None,
            dual_model=args.dual_model,
            reasoning_model=args.reasoning_model,
            assistant_model=args.assistant_model,
        )
    except RuntimeError as e:
        ui.print_error(str(e))
        return 1

    session_id = resume_data["id"] if resume_data else sessions.new_session_id()
    if resume_data:
        n_msgs = len(resume_data["messages"]) - 1  # kurangi system prompt
        print(f"{ui.DIM}Melanjutkan sesi {session_id} ({n_msgs} pesan sebelumnya).{ui.RESET}")

    def _resolve_prompt(prompt_parts: list[str], file_arg: str | None) -> tuple[str, str | None]:
        """Gabungkan prompt parts, support @file.txt syntax dan --file argument.
        Return: (content, preview) - preview untuk tampilan visual [isi...]"""
        if file_arg:
            # --file takes priority
            try:
                with open(file_arg, "r", encoding="utf-8") as f:
                    content = f.read().strip()
                preview = f"[File: {file_arg}, {len(content)} char]"
                return content, preview
            except Exception as e:
                ui.print_error(f"Gagal baca file {file_arg}: {e}")
                raise
        # Cek @file.txt di prompt parts
        full_prompt = " ".join(prompt_parts)
        if full_prompt.startswith("@"):
            file_path = full_prompt[1:].strip()
            try:
                with open(file_path, "r", encoding="utf-8") as f:
                    content = f.read().strip()
                preview = f"[Paste dari @{file_path}, {len(content)} char]"
                return content, preview
            except Exception as e:
                ui.print_error(f"Gagal baca file {file_path}: {e}")
                raise
        return full_prompt, None

    if args.prompt or args.file:
        # Mode non-interaktif: satu perintah dari argumen CLI, lalu keluar.
        prompt, preview = _resolve_prompt(args.prompt, args.file)
        if preview:
            print(f"{ui.DIM}{preview}{ui.RESET}")
        try:
            agent.run_turn(prompt)
        except Exception as e:
            ui.print_error(str(e))
            sessions.save_session(session_id, agent)
            return 1
        sessions.save_session(session_id, agent)
        return 0

    repl(agent, session_id)
    return 0


if __name__ == "__main__":
    sys.exit(main())
