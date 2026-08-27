"""Helper tampilan terminal. Chrome CLI (banner/error/tool call) pakai ANSI
polos biar ringan; output STREAMING dari model (reasoning + jawaban)
pakai `rich` supaya markdown ke-render rapi dan reasoning kepisah jelas
dalam panel, mirip tampilan Claude Code/Codex CLI."""

from rich.console import Console, Group
from rich.live import Live
from rich.markdown import Markdown
from rich.panel import Panel
from rich.text import Text

RESET = "\033[0m"
DIM = "\033[2m"
BOLD = "\033[1m"
CYAN = "\033[36m"
GREEN = "\033[32m"
YELLOW = "\033[33m"
MAGENTA = "\033[35m"
GREY = "\033[90m"

# Windows-safe console: force UTF-8 encoding, replace unencodable chars
import sys
import io

if sys.platform == "win32":
    # Wrap stdout/stderr to handle encoding errors gracefully
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8', errors='replace')
    # Use legacy_windows=False for VT sequences
    console = Console(force_terminal=True, legacy_windows=False)
else:
    console = Console()


def banner(effort: str, model: str) -> None:
    print(f"{BOLD}{CYAN}nvicoder{RESET} — coding agent (NVIDIA NIM backend)")
    print(f"{DIM}effort={effort}  model={model}{RESET}")
    print(f"{DIM}Ketik pertanyaan/perintah. '/help' untuk daftar perintah, Ctrl+C/'/exit' untuk keluar.{RESET}\n")


def help_text() -> str:
    return (
        f"{BOLD}Perintah:{RESET}\n"
        "  /help              tampilkan bantuan ini\n"
        "  /effort <level>    ganti effort: low | medium | high\n"
        "  /model <nama>      ganti model manual (provider auto dari prefix nama, independen dari effort)\n"
        "  /models [all]      lihat daftar model dari API key kamu, bisa pilih langsung\n"
        "  /clear             hapus riwayat percakapan (mulai sesi baru)\n"
        "  /reasoning         lihat teks reasoning LENGKAP dari giliran terakhir\n"
        "  /jobs              lihat semua background job (shell) di sesi ini + statusnya\n"
        "  /sessions          lihat semua sesi tersimpan di project ini\n"
        "  /yolo              toggle mode auto-approve untuk semua run_command\n"
        "  /config            tampilkan file config.toml aktif & setting resolved\n"
        "  /exit              keluar\n"
    )


def print_tool_call(name: str, arguments: dict) -> None:
    args_preview = str(arguments)
    if len(args_preview) > 160:
        args_preview = args_preview[:160] + "..."
    console.print(f"\n[magenta][tool][/magenta] [bold]{name}[/bold]([dim]{args_preview}[/dim])")


def print_tool_result(result: str) -> None:
    # Tampilkan full output supaya bisa di-copy-paste seperti Claude Code
    console.print(f"[dim]{result}[/dim]")


def print_error(msg: str) -> None:
    console.print(f"[yellow][error] {msg}[/yellow]")


def print_info(msg: str) -> None:
    console.print(f"[cyan][info] {msg}[/cyan]")


def print_token_usage(turn: dict, session: dict) -> None:
    console.print(
        f"[dim][tokens] turn: prompt={turn['prompt']} completion={turn['completion']} "
        f"total={turn['total']}  |  sesi: {session['total']}[/dim]"
    )


# --------------------------------------------------- streaming (rich) ---

REASONING_TAIL_LINES = 5
REASONING_TAIL_CHARS = 600  # jaga-jaga kalau reasoning satu baris raksasa tanpa newline


def _reasoning_tail(text: str, max_lines: int = REASONING_TAIL_LINES,
                     max_chars: int = REASONING_TAIL_CHARS) -> str:
    """Ambil ekor teks reasoning aja -- biar panelnya kebentuk 'jendela geser'
    kira-kira setinggi max_lines, bukan tumbuh terus makin panjang."""
    lines = text.splitlines()
    if len(lines) > max_lines:
        text = "\n".join(lines[-max_lines:])
    if len(text) > max_chars:
        text = text[-max_chars:]
    return text


def _reasoning_one_line_summary(text: str) -> str:
    """Buat ringkasan 1 baris dari reasoning text untuk tampilan compact.
    Menampilkan jumlah baris dan karakter, plus potongan kecil isi reasoning."""
    if not text:
        return ""
    lines = text.splitlines()
    line_count = len(lines)
    char_count = len(text)
    
    # Ambil potongan kecil dari akhir reasoning untuk preview
    last_line = lines[-1] if lines else ""
    if len(last_line) > 40:
        last_line = "..." + last_line[-37:]
    
    if line_count == 1:
        return f"[dim]⚡ Reasoning: {last_line}[/dim]"
    else:
        return f"[dim]⚡ Reasoning ({line_count} baris, {char_count} kar) — klik /reasoning untuk lihat lengkap[/dim]"


def render_stream_group(reasoning_text: str, content_text: str, reasoning_done: bool = False):
    """Gabungan [ringkasan 1 baris reasoning (kalau ada)] + [markdown jawaban]
    buat ditampilkan lewat Live selama streaming.

    Selama reasoning MASIH JALAN: tampil sebagai ringkasan 1 baris compact
    yang update real-time dengan potongan isi reasoning.

    Begitu reasoning SELESAI (reasoning_done=True, dipicu begitu jawaban
    final mulai muncul): ringkasan tetap 1 baris dengan info lengkap
    (jumlah baris & karakter), plus petunjuk ketik /reasoning buat lihat
    teks lengkapnya. Teks lengkapnya tetap tersimpan di Agent.last_reasoning
    dan bisa dipanggil ulang lewat perintah /reasoning."""
    parts = []
    if reasoning_text:
        # Selalu pakai format 1 baris, baik sedang berjalan atau sudah selesai
        summary = _reasoning_one_line_summary(reasoning_text)
        if reasoning_done:
            # Tambahkan indikator [OK] kalau sudah selesai
            lines = reasoning_text.splitlines()
            line_count = len(lines)
            char_count = len(reasoning_text)
            summary = f"[dim][OK] Reasoning selesai ({line_count} baris, {char_count} kar) — ketik /reasoning buat lihat lengkap[/dim]"
        parts.append(Text.from_markup(summary))
    if content_text:
        parts.append(Markdown(content_text))
    return Group(*parts) if parts else Text("")


def new_live() -> Live:
    """Live region baru untuk satu putaran streaming (satu panggilan API).
    vertical_overflow='visible' penting -- tanpa ini, jawaban panjang yang
    melebihi tinggi terminal saat ini bisa ke-crop oleh rich, bukan discroll
    natural."""
    return Live(console=console, refresh_per_second=12, transient=False, vertical_overflow="visible")
