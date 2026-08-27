"""
Konfigurasi nvicoder: base URL NVIDIA NIM, API key, dan profil "effort".

NVIDIA NIM mengekspos endpoint yang kompatibel dengan OpenAI di
https://integrate.api.nvidia.com/v1 . Kita pakai openai-python SDK biasa,
cuma ganti base_url + api_key.

Katalog model NVIDIA berubah cukup sering (model baru rilis, model lama
di-deprecate). Daftar di bawah ini adalah pilihan yang masuk akal per
Agustus 2026, tapi SELALU cek https://build.nvidia.com/models untuk model
terbaru, dan cek "model card"-nya masing-masing untuk konfirmasi apakah
model itu mendukung tool/function calling (tidak semua model mendukung).
"""

import os
from dataclasses import dataclass

# Load .env file from project root (where this config.py lives)
try:
    from dotenv import load_dotenv
    # Get the directory where this config.py file is located
    _config_dir = os.path.dirname(os.path.abspath(__file__))
    _env_path = os.path.join(_config_dir, "..", ".env")
    _env_path = os.path.normpath(_env_path)
    if os.path.exists(_env_path):
        load_dotenv(dotenv_path=_env_path, override=True)
    else:
        # Fallback: try current working directory
        load_dotenv(override=True)
except ImportError:
    pass

NVIDIA_BASE_URL = os.environ.get("NVIDIA_BASE_URL", "https://integrate.api.nvidia.com/v1")
NVIDIA_API_KEY = os.environ.get("NVIDIA_API_KEY", "")
SEARXNG_URL = os.environ.get("SEARXNG_URL", "")

# Cloudflare Workers AI -- provider alternatif, endpoint OpenAI-compatible-nya
# butuh Account ID (bukan cuma API token) untuk bentuk base_url-nya.
CLOUDFLARE_API_TOKEN = os.environ.get("CLOUDFLARE_API_TOKEN", "")
CLOUDFLARE_ACCOUNT_ID = os.environ.get("CLOUDFLARE_ACCOUNT_ID", "")
CLOUDFLARE_BASE_URL = (
    f"https://api.cloudflare.com/client/v4/accounts/{CLOUDFLARE_ACCOUNT_ID}/ai/v1"
    if CLOUDFLARE_ACCOUNT_ID else ""
)

# Groq -- inference super cepat (LPU) untuk model open-weight, endpoint
# OpenAI-compatible juga.
GROQ_API_KEY = os.environ.get("GROQ_API_KEY", "")
GROQ_BASE_URL = "https://api.groq.com/openai/v1"

# Mistral AI -- endpoint OpenAI-compatible juga. Mendukung BEBERAPA API key
# sekaligus (mis. 3 akun gratis -> total kuota lebih besar): isi
# MISTRAL_API_KEY_1, _2, _3, dst di .env (atau MISTRAL_API_KEY tunggal, tetap
# didukung). nvicoder otomatis rotate ke key berikutnya kalau key yang aktif
# kena rate-limit/kuota habis (429) atau invalid (401). Lihat agent.py.
MISTRAL_API_KEY = os.environ.get("MISTRAL_API_KEY", "")
_mistral_numbered_keys = []
_i = 1
while True:
    _k = os.environ.get(f"MISTRAL_API_KEY_{_i}", "")
    if not _k:
        break
    _mistral_numbered_keys.append(_k)
    _i += 1
MISTRAL_API_KEYS = [k for k in ([MISTRAL_API_KEY] + _mistral_numbered_keys) if k]
MISTRAL_BASE_URL = "https://api.mistral.ai/v1"


@dataclass
class EffortProfile:
    temperature: float
    max_tokens: int
    description: str


# Tiga tingkat "effort" -- MURNI ngatur seberapa "dalam" model boleh mikir
# (temperature/max_tokens), SAMA SEKALI TIDAK nentuin model/provider mana
# yang dipakai. Model dipilih terpisah lewat DEFAULT_MODEL/--model/`/model`,
# dan bisa dikombinasi bebas dengan effort manapun.
EFFORT_PROFILES = {
    "low": EffortProfile(
        temperature=0.2,
        max_tokens=2048,
        description="Paling cepat & murah, cocok untuk task kecil/simple edit.",
    ),
    "medium": EffortProfile(
        temperature=0.2,
        max_tokens=4096,
        description="Seimbang: cukup akurat, masih responsif. Default.",
    ),
    "high": EffortProfile(
        temperature=0.8,
        max_tokens=8192,
        description="Reasoning lebih dalam untuk task kompleks/multi-file. Lebih lambat.",
    ),
    "xhigh": EffortProfile(
        temperature=0.8,
        max_tokens=16384,
        description="Reasoning maksimal untuk task sangat kompleks/arsitektur. Paling lambat & mahal.",
    ),
}

DEFAULT_EFFORT = os.environ.get("NVICODER_EFFORT", "xhigh")

# Model default dipakai di effort manapun kecuali di-override lewat --model/`/model`.
# Provider (NVIDIA NIM vs Cloudflare Workers AI) dideteksi OTOMATIS dari prefix
# nama model -- lihat provider_for_model() -- bukan dari effort tier.
# Primary: meta/muse-glimmer-30b
# Fallback: mistralai/codestral-22b-instruct-v0.1 (has reasoning, good for coding)
DEFAULT_MODEL = os.environ.get("NVICODER_MODEL", "meta/muse-glimmer-30b")

# Dual-model mode (Constitutional AI Critic architecture):
# - CRITIC_MODEL: "critic" - Constitutional AI self-critique, evaluates output for Harmless/Honest/Helpful
# - ASSISTANT_MODEL: "doer" - fast execution, tool-calling, produces output for critique
# Enable with NVICODER_DUAL_MODEL=true or --dual-model flag
CRITIC_MODEL = os.environ.get("NVICODER_CRITIC_MODEL", "nvidia/nemotron-3-ultra-550b-a55b")
ASSISTANT_MODEL = os.environ.get("NVICODER_ASSISTANT_MODEL", "meta/muse-glimmer-30b")
DUAL_MODEL_ENABLED = os.environ.get("NVICODER_DUAL_MODEL", "").lower() in ("1", "true", "yes", "on")

# Fallback ANTAR-PROVIDER kalau provider yang lagi aktif beneran habis semua
# opsi retry-nya (bukan cuma satu key doang) -- pola "kena 429, kesel, manual
# cari API gratis lain" yang biasanya dilakuin manual, sekarang nvicoder yang
# nyari sendiri. Urutan default cuma masukin provider yang KEY-nya kedeteksi
# ada di .env, model representatif per provider (lihat agent.py::_create_stream
# buat logic switch-nya). Override lewat NVICODER_FALLBACK_MODELS
# (comma-separated, urutan kiri = prioritas). Set NVICODER_FALLBACK_MODELS=""
# (string kosong) buat MATIIN fallback sama sekali -- balik ke perilaku lama
# (gagal ya gagal, gak coba provider lain).
_FALLBACK_ENV = os.environ.get("NVICODER_FALLBACK_MODELS")
if _FALLBACK_ENV is not None:
    FALLBACK_MODELS = [m.strip() for m in _FALLBACK_ENV.split(",") if m.strip()]
else:
    FALLBACK_MODELS = [
        m for m, available in (
            ("ibm/granite-34b-code-instruct", bool(NVIDIA_API_KEY)),  # Primary fallback
            ("nvidia/nemotron-3-super-120b-a12b", bool(NVIDIA_API_KEY)),
            ("mistral/mistral-medium-3-5", bool(MISTRAL_API_KEYS)),
            ("groq/openai/gpt-oss-120b", bool(GROQ_API_KEY)),
            ("@cf/qwen/qwen3.8-27b", bool(CLOUDFLARE_API_TOKEN and CLOUDFLARE_BASE_URL)),
        )
        if available
    ]


def provider_for_model(model: str) -> str:
    """'@cf/...' -> Cloudflare Workers AI, 'groq/...' -> Groq, 'mistral/...' -> Mistral AI, selain itu -> NVIDIA NIM.

    Prefix '@cf/' itu bagian ASLI dari ID model Cloudflare (bukan tag nvicoder).
    Prefix 'groq/' dan 'mistral/' murni tag ROUTING nvicoder -- beberapa model (mis.
    'openai/gpt-oss-120b') ada persis sama namanya di NVIDIA maupun Groq,
    jadi tanpa tag ini providernya ambigu. Lihat strip_provider_prefix().
    """
    if model.startswith("@cf/"):
        return "cloudflare"
    if model.startswith("groq/"):
        return "groq"
    if model.startswith("mistral/"):
        return "mistral"
    return "nvidia"


def strip_provider_prefix(model: str) -> str:
    """Buang tag routing nvicoder ('groq/...', 'mistral/...') sebelum dikirim ke API asli
    providernya. '@cf/...' TIDAK di-strip -- itu memang bagian dari ID model
    Cloudflare yang sebenarnya, harus dikirim apa adanya."""
    if model.startswith("groq/"):
        return model[len("groq/"):]
    if model.startswith("mistral/"):
        return model[len("mistral/"):]
    return model


# Model vision (bisa "liat" gambar sekaligus tool-calling) dideteksi dari
# nama-nya -- katalog berubah sering, jadi keyword heuristic lebih tahan lama
# daripada daftar id yang di-hardcode. Dikonfirmasi jalan (teks+tool call
# sekaligus liat gambar): nvidia/nemotron-nano-12b-v2-vl, meta/llama-3.2-*-vision-instruct. Override via
# NVICODER_VISION_MODELS (comma-separated substring match) kalau heuristik
# ini salah nebak buat model tertentu.
_VISION_MODEL_KEYWORDS = ("vision", "-vl", "vlm", "vl-", "nemotron-nano-12b-v2-vl", "llama-3.2", "vision-instruct", "muse", "glimmer")
_VISION_MODEL_ENV = os.environ.get("NVICODER_VISION_MODELS")
_VISION_MODEL_OVERRIDES = (
    [s.strip().lower() for s in _VISION_MODEL_ENV.split(",") if s.strip()]
    if _VISION_MODEL_ENV else []
)

# Default vision model (fallback jika model utama bukan vision)
# Override via NVICODER_VISION_MODEL env var
VISION_MODEL_DEFAULT = os.environ.get("NVICODER_VISION_MODEL", "meta/muse-glimmer-30b")


def is_vision_model(model: str) -> bool:
    """True kalau model (nama lengkap, prefix routing nvicoder udah gak
    relevan di sini) kemungkinan besar bisa terima input gambar. Dipakai
    agent.py buat mutusin apa gambar dari tool MCP (mis. screenshot) beneran
    dikirim ke model, atau di-fallback jadi catatan teks doang."""
    m = model.lower()
    if _VISION_MODEL_OVERRIDES:
        return any(o in m for o in _VISION_MODEL_OVERRIDES)
    if any(k in m for k in _VISION_MODEL_KEYWORDS):
        return True
    # Auto-fallback: if model name matches vision default, treat as vision
    try:
        if m == VISION_MODEL_DEFAULT.lower():
            return True
    except Exception:
        pass
    return False



# Perintah yang dianggap "aman" (read-only) sehingga tidak perlu konfirmasi
# manual saat agent memanggil tool run_command. Semua command lain akan
# selalu minta konfirmasi dulu, kecuali mode --yolo diaktifkan.
SAFE_COMMAND_PREFIXES = (
    "ls", "cat", "head", "tail", "pwd", "echo", "grep", "find",
    "git status", "git diff", "git log", "git show", "git branch",
    "python -m pytest", "pytest", "npm test", "npm run test",
    "wc", "which", "whoami", "date",
)

MAX_AGENT_ITERATIONS = int(os.environ.get("NVICODER_MAX_AGENT_ITERATIONS", "40"))  # batas aman: hentikan loop kalau kelamaan/muter-muter
COMMAND_TIMEOUT_SECONDS = 120

# Tool result history compaction (untuk hemat token).
# Set 0 untuk MATIKAN compaction (simpan full history, mirip Claude Code).
# Default 1200 char threshold, keep 3 recent results uncompacted.
TOOL_RESULT_COMPACT_THRESHOLD = int(os.environ.get("NVICODER_TOOL_COMPACT_THRESHOLD", "1200"))
TOOL_RESULT_KEEP_RECENT = int(os.environ.get("NVICODER_TOOL_KEEP_RECENT", "3"))

# Channel Playwright untuk tool browser_control. Default "msedge" karena Edge
# sudah terpasang bawaan di Windows -- tidak perlu download Chromium terpisah.
# Override ke "chrome" kalau Google Chrome terpasang, atau "chromium" untuk
# browser bundled Playwright (perlu `playwright install chromium` sekali).
BROWSER_CHANNEL = os.environ.get("NVICODER_BROWSER_CHANNEL", "msedge")
BROWSER_HEADLESS = os.environ.get("NVICODER_BROWSER_HEADLESS", "0") == "1"
