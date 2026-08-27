"""
Inti agentic loop: kirim messages -> model boleh minta tool_call -> kita
eksekusi tool -> hasil dikirim balik -> ulangi sampai model kasih jawaban
final (tanpa tool_call lagi) atau limit iterasi tercapai.

Streaming tetap dipakai (untuk kecepatan/UX) sekaligus tool calling, dengan
merangkai potongan (delta) tool_calls berdasarkan index-nya, sesuai format
streaming OpenAI-compatible yang juga dipakai NVIDIA NIM.
"""

import json
import os
import time
import random
from dataclasses import dataclass, field
from typing import Optional

from openai import (
    OpenAI, APIError, RateLimitError, AuthenticationError, PermissionDeniedError,
    InternalServerError, APIConnectionError, APITimeoutError,
)

from . import config, tools, ui
from .config import ASSISTANT_MODEL, DUAL_MODEL_ENABLED

# Circuit Breaker configuration
_CIRCUIT_BREAKER_FAILURE_THRESHOLD = 5  # jumlah kegagalan sebelum circuit OPEN
_CIRCUIT_BREAKER_RECOVERY_TIMEOUT = 30.0  # detik sebelum circuit HALF-OPEN
_CIRCUIT_BREAKER_SUCCESS_THRESHOLD = 3  # sukses berturut-turut di HALF-OPEN untuk CLOSE

@dataclass
class CircuitBreakerState:
    """State untuk Circuit Breaker per provider."""
    failures: int = 0
    successes: int = 0
    last_failure_time: float = 0.0
    state: str = "CLOSED"  # CLOSED, OPEN, HALF-OPEN
    
@dataclass
class ProviderHealth:
    """Track kesehatan provider untuk smart fallback scoring."""
    total_requests: int = 0
    failed_requests: int = 0
    avg_latency_ms: float = 0.0
    _latency_samples: list = field(default_factory=list)
    
    @property
    def failure_rate(self) -> float:
        if self.total_requests == 0:
            return 0.0
        return self.failed_requests / self.total_requests
    
    @property
    def health_score(self) -> float:
        """Score 0-100, makin tinggi makin sehat (untuk fallback priority)."""
        if self.total_requests == 0:
            return 100.0  # belum ada data, anggap sehat
        failure_penalty = self.failure_rate * 50  # max 50 point penalty
        latency_penalty = min(self.avg_latency_ms / 1000.0 * 20, 20)  # max 20 point penalty
        return max(0, 100 - failure_penalty - latency_penalty)
    
    def record_success(self, latency_ms: float) -> None:
        self.total_requests += 1
        self._latency_samples.append(latency_ms)
        # Keep only last 10 samples for rolling average
        if len(self._latency_samples) > 10:
            self._latency_samples.pop(0)
        self.avg_latency_ms = sum(self._latency_samples) / len(self._latency_samples)
    
    def record_failure(self) -> None:
        self.total_requests += 1
        self.failed_requests += 1

# Global circuit breaker states dan health tracking per provider
_circuit_breakers: dict[str, CircuitBreakerState] = {}
_provider_health: dict[str, ProviderHealth] = {}

def _get_circuit_breaker(provider: str) -> CircuitBreakerState:
    """Dapatkan atau buat CircuitBreakerState baru untuk provider."""
    if provider not in _circuit_breakers:
        _circuit_breakers[provider] = CircuitBreakerState()
    return _circuit_breakers[provider]

def _get_provider_health(provider: str) -> ProviderHealth:
    """Dapatkan atau buat ProviderHealth baru untuk provider."""
    if provider not in _provider_health:
        _provider_health[provider] = ProviderHealth()
    return _provider_health[provider]

def _record_provider_success(provider: str, latency_ms: float) -> None:
    """Catat sukses request ke provider, update circuit breaker dan health."""
    cb = _get_circuit_breaker(provider)
    health = _get_provider_health(provider)
    health.record_success(latency_ms)
    
    if cb.state == "HALF-OPEN":
        cb.successes += 1
        if cb.successes >= _CIRCUIT_BREAKER_SUCCESS_THRESHOLD:
            cb.state = "CLOSED"
            cb.failures = 0
            cb.successes = 0
            ui.print_info(f"✅ Circuit breaker untuk '{provider}' CLOSED (pulih total)")
    elif cb.state == "CLOSED":
        cb.failures = 0  # Reset failure count on success

def _record_provider_failure(provider: str) -> None:
    """Catat kegagalan request ke provider, update circuit breaker dan health."""
    cb = _get_circuit_breaker(provider)
    health = _get_provider_health(provider)
    health.record_failure()
    cb.failures += 1
    cb.last_failure_time = time.time()
    cb.successes = 0
    
    if cb.state == "CLOSED" and cb.failures >= _CIRCUIT_BREAKER_FAILURE_THRESHOLD:
        cb.state = "OPEN"
        ui.print_error(f"⚠️ Circuit breaker untuk '{provider}' OPEN ({cb.failures} kegagalan berturut-turut)")
    elif cb.state == "HALF-OPEN":
        cb.state = "OPEN"
        cb.last_failure_time = time.time()
        ui.print_error(f"⚠️ Circuit breaker untuk '{provider}' kembali OPEN (gagal di HALF-OPEN)")

def _can_use_provider(provider: str) -> bool:
    """Cek apakah provider bisa digunakan berdasarkan circuit breaker state."""
    cb = _get_circuit_breaker(provider)
    
    if cb.state == "CLOSED":
        return True
    elif cb.state == "OPEN":
        # Cek apakah sudah waktunya recovery
        if time.time() - cb.last_failure_time >= _CIRCUIT_BREAKER_RECOVERY_TIMEOUT:
            cb.state = "HALF-OPEN"
            cb.successes = 0
            ui.print_info(f"🔄 Circuit breaker untuk '{provider}' HALF-OPEN (mencoba recovery...)")
            return True
        return False
    else:  # HALF-OPEN
        return True

def _exponential_backoff_with_jitter(attempt: int, base_delay: float = 1.0, max_delay: float = 60.0) -> float:
    """Hitung delay dengan exponential backoff + jitter untuk hindari thundering herd.
    
    Formula: min(base_delay * 2^attempt + random_jitter, max_delay)
    Jitter: random value antara 0-25% dari delay untuk variasi
    """
    exponential_delay = min(base_delay * (2 ** attempt), max_delay)
    jitter_range = exponential_delay * 0.25
    jitter = random.uniform(0, jitter_range)
    return exponential_delay + jitter

# Rate-limit Mistral (gratis) biasanya per-menit, payload nvicoder >10rb token/request.
# Jika SEMUA key kena 429, tunggu lalu ulangi dari key pertama -- durasi makin lama.
_MISTRAL_RATE_LIMIT_WAIT_SECONDS = (15.0, 30.0, 60.0)

# Error transient generik (5xx, koneksi, timeout) -- berlaku semua provider.
# Retry singkat di provider sama sebelum fallback.
_TRANSIENT_ERROR_RETRY_WAIT_SECONDS = (3.0, 8.0)

# Provider kadang balikin pesan infrastruktur sebagai teks completion (bukan error HTTP),
# tanpa tool_calls. Deteksi via pattern-match & retry sebelum diterima sbg jawaban asli.
_INFRA_GLITCH_PHRASES = (
    "service temporarily overloaded",
    "engine core encountered an issue",
    "enginecore encountered an issue",
    "internal server error",
)
_INFRA_GLITCH_MAX_LEN = 150
_INFRA_GLITCH_RETRY_WAIT_SECONDS = (2.0, 5.0, 10.0)

# Hasil tool besar (mis. dump scene Godot) ikut dikirim ULANG tiap iterasi -> token meledak.
# Kompaksi: hasil tool LAMA (>threshold) diganti placeholder sebelum dikirim ulang.
# Nilai dari config (set 0 via NVICODER_TOOL_RESULT_COMPACT_THRESHOLD=0 untuk matikan).
def _get_compact_threshold() -> int:
    return config.TOOL_RESULT_COMPACT_THRESHOLD

def _get_keep_recent() -> int:
    return config.TOOL_RESULT_KEEP_RECENT

_TOOL_RESULT_COMPACTED_MARKER = "[dipadatkan-otomatis]"

# prompt.md di package agar bisa edit tanpa sentuh kode & ikut ter-package saat pip install.
_DEFAULT_PROMPT_PATH = os.path.join(os.path.dirname(__file__), "prompt.md")


def load_system_prompt(path: str | None = None) -> str:
    p = path or _DEFAULT_PROMPT_PATH
    try:
        with open(p, "r", encoding="utf-8") as f:
            content = f.read().strip()
            if content:
                return content
    except OSError:
        pass
    # Fallback minimal kalau prompt.md hilang/gagal dibaca, supaya agent
    # tetap bisa jalan (walau kurang optimal) daripada crash total.
    return (
        "Kamu adalah asisten coding agentic di terminal bernama nvicoder. "
        "Baca file sebelum mengedit, pakai edit_file untuk perubahan kecil, "
        "jangan mengarang hasil tool, dan balas dalam bahasa user."
    )


class Agent:
    def __init__(self, effort: str = config.DEFAULT_EFFORT, model_override: str | None = None,
                 yolo: bool = False, system_prompt: str | None = None, prompt_file: str | None = None,
                 api_key: str | None = None, extra_safe_commands: list[str] | None = None,
                 resume_messages: list[dict] | None = None, session_tokens: dict | None = None,
                 dual_model: bool | None = None, reasoning_model: str | None = None,
                 assistant_model: str | None = None):
        self._nvidia_api_key = api_key or config.NVIDIA_API_KEY
        if not self._nvidia_api_key:
            raise RuntimeError(
                "NVIDIA_API_KEY belum di-set. Ambil API key gratis di https://build.nvidia.com "
                "lalu jalankan: export NVIDIA_API_KEY=nvapi-xxxxxxxx"
            )
        self._clients: dict[str, OpenAI] = {}
        self._mistral_key_index = 0  # index key Mistral yang lagi aktif, rotate kalau kena 429/401
        self.effort = effort
        self.model_override = model_override
        self.yolo = yolo
        self.extra_safe_commands = extra_safe_commands or []
        if resume_messages:
            self.messages = resume_messages
        else:
            resolved_prompt = system_prompt or load_system_prompt(prompt_file)
            self.messages = [{"role": "system", "content": resolved_prompt}]
        self.session_tokens = session_tokens or {"prompt": 0, "completion": 0, "total": 0}
        self.last_critique: str = ""
        
        # Dual-model mode (Constitutional AI Critic architecture)
        # CLI args override env vars
        self.dual_model_enabled = dual_model if dual_model is not None else DUAL_MODEL_ENABLED
        #self.critic_model = reasoning_model if reasoning_model is not None else (CRITIC_MODEL if self.dual_model_enabled else None)
        self.assistant_model = assistant_model if assistant_model is not None else (ASSISTANT_MODEL if self.dual_model_enabled else None)

    @property
    def profile(self) -> config.EffortProfile:
        return config.EFFORT_PROFILES[self.effort]

    @property
    def model(self) -> str:
        return self.model_override or config.DEFAULT_MODEL
    
    @property
    def critic_model_name(self) -> str:
        """Model untuk Constitutional AI self-critique (Ultra) - only used in dual-model mode."""
        return self.critic_model or self.model
    
    @property
    def assistant_model_name(self) -> str:
        """Model untuk eksekusi tool-calling (Muse) - only used in dual-model mode."""
        return self.assistant_model or self.model

    def _client_for(self, provider: str) -> OpenAI:
        """Client OpenAI-compatible per provider, dibuat sekali & dipakai ulang (cache di self._clients)."""
        if provider not in self._clients:
            if provider == "cloudflare":
                if not config.CLOUDFLARE_API_TOKEN or not config.CLOUDFLARE_BASE_URL:
                    raise RuntimeError(
                        "CLOUDFLARE_API_TOKEN/CLOUDFLARE_ACCOUNT_ID belum di-set di .env. "
                        "Model dengan prefix '@cf/' butuh dua-duanya."
                    )
                self._clients[provider] = OpenAI(
                    base_url=config.CLOUDFLARE_BASE_URL, api_key=config.CLOUDFLARE_API_TOKEN
                )
            elif provider == "groq":
                if not config.GROQ_API_KEY:
                    raise RuntimeError(
                        "GROQ_API_KEY belum di-set di .env. Model dengan prefix 'groq/' butuh itu."
                    )
                self._clients[provider] = OpenAI(
                    base_url=config.GROQ_BASE_URL, api_key=config.GROQ_API_KEY
                )
            elif provider == "mistral":
                return self._mistral_client()
            else:
                self._clients[provider] = OpenAI(
                    base_url=config.NVIDIA_BASE_URL, api_key=self._nvidia_api_key
                )
        return self._clients[provider]

    def _mistral_client(self) -> OpenAI:
        """Client Mistral untuk key yang lagi aktif (self._mistral_key_index).
        Cache per-index karena tiap key butuh instance OpenAI client sendiri."""
        if not config.MISTRAL_API_KEYS:
            raise RuntimeError(
                "MISTRAL_API_KEY (atau MISTRAL_API_KEY_1/_2/_3) belum di-set di .env. "
                "Model dengan prefix 'mistral/' butuh itu."
            )
        idx = self._mistral_key_index % len(config.MISTRAL_API_KEYS)
        cache_key = f"mistral:{idx}"
        if cache_key not in self._clients:
            self._clients[cache_key] = OpenAI(
                base_url=config.MISTRAL_BASE_URL, api_key=config.MISTRAL_API_KEYS[idx]
            )
        return self._clients[cache_key]

    def _rotate_mistral_key(self) -> bool:
        """Pindah ke key Mistral berikutnya. True kalau masih ada key lain yang
        belum dicoba di 'putaran' ini, False kalau semua key sudah habis."""
        if self._mistral_key_index + 1 >= len(config.MISTRAL_API_KEYS):
            return False
        self._mistral_key_index += 1
        return True

    def _compact_old_tool_results(self) -> None:
        """Ganti hasil tool LAMA yang gede (>_TOOL_RESULT_COMPACT_THRESHOLD karakter)
        jadi placeholder pendek, biar history yang dikirim ulang tiap iterasi gak
        makin gembung. Cuma nyentuh pesan role='tool'; N hasil PALING BARU
        (_TOOL_RESULT_KEEP_RECENT) tetap dibiarkan utuh supaya model masih bisa
        rujuk detail terbaru kalau perlu. Idempotent (aman dipanggil berkali-kali)
        lewat marker di depan placeholder-nya."""
        # Disable compaction if threshold is 0 (mirip Claude Code - full history)
        compact_threshold = _get_compact_threshold()
        keep_recent = _get_keep_recent()
        if compact_threshold <= 0:
            return
        tool_indices = [i for i, m in enumerate(self.messages) if m.get("role") == "tool"]
        if len(tool_indices) <= keep_recent:
            return
        protected = set(tool_indices[-keep_recent:])
        for i in tool_indices:
            if i in protected:
                continue
            msg = self.messages[i]
            content = msg.get("content") or ""
            if isinstance(content, str):
                if content.startswith(_TOOL_RESULT_COMPACTED_MARKER):
                    continue
                size = len(content)
            else:
                # Content multimodal (list block gambar+teks, lihat _tool_content) --
                # base64 gambar itu paling boros token dari semuanya, jadi tetap
                # dihitung ukurannya (bukan otomatis di-skip) biar ikut kepadatin
                # kalau udah lama.
                size = sum(
                    len(b.get("text", "")) if b.get("type") == "text"
                    else len(b.get("image_url", {}).get("url", ""))
                    for b in content
                )
            if size <= compact_threshold:
                continue
            msg["content"] = (
                f"{_TOOL_RESULT_COMPACTED_MARKER} Hasil tool asli ~{size} karakter "
                f"{'(termasuk gambar)' if not isinstance(content, str) else ''}, "
                "sudah lama & sudah ketutup langkah lebih baru. Panggil ulang tool ini "
                "kalau beneran butuh detail lengkapnya lagi."
            )

    def _compact_long_user_messages(self) -> None:
        """Padatkan user message yang terlalu panjang (paste teks besar ke prompt).
        Mirip tool result compaction: threshold sama, keep N recent user messages utuh.
        Idempotent lewat marker _TOOL_RESULT_COMPACTED_MARKER (pakai marker sama)."""
        compact_threshold = _get_compact_threshold()
        keep_recent = _get_keep_recent()
        if compact_threshold <= 0:
            return
        user_indices = [i for i, m in enumerate(self.messages) if m.get("role") == "user"]
        if len(user_indices) <= keep_recent:
            return
        protected = set(user_indices[-keep_recent:])
        for i in user_indices:
            if i in protected:
                continue
            msg = self.messages[i]
            content = msg.get("content") or ""
            if not isinstance(content, str):
                continue
            if content.startswith(_TOOL_RESULT_COMPACTED_MARKER):
                continue
            size = len(content)
            if size <= compact_threshold:
                continue
            msg["content"] = (
                f"{_TOOL_RESULT_COMPACTED_MARKER} User input asli ~{size} karakter "
                "(teks panjang yang di-paste ke prompt), sudah dipadatkan. "
                "Detail lengkap tidak dikirim ulang ke model untuk hemat token."
            )

    def _tool_content(self, result: dict) -> str | list[dict]:
        """Bangun content pesan role='tool' dari hasil tools.execute_tool().
        Kalau ada gambar (mis. dari runtime_screenshot/get_viewport_screenshot)
        DAN model aktif support vision (config.is_vision_model) --
        kirim content-array multimodal (format {"type":"image_url",...})."""
        text = result.get("text") or ""
        images = result.get("images") or []
        if not images:
            return text
        
        if config.is_vision_model(self.model):
            # Model utama support vision -> kirim gambar native
            blocks: list[dict] = []
            if text:
                blocks.append({"type": "text", "text": text})
            for img in images:
                blocks.append({
                    "type": "image_url",
                    "image_url": {"url": f"data:{img['mime_type']};base64,{img['data']}"},
                })
            return blocks
        
        # Model utama NON-vision, tapi ada gambar -> return text saja
        return text

    def clear(self) -> None:
        system = self.messages[0]
        self.messages = [system]

    def set_effort(self, effort: str) -> bool:
        """Ganti tingkat reasoning (temperature/max_tokens) SAJA -- model yang aktif tidak berubah."""
        if effort not in config.EFFORT_PROFILES:
            return False
        self.effort = effort
        return True

    def list_models(self) -> list[str] | None:
        """Ambil daftar model yang terlihat di API key yang lagi dipakai (provider dari model aktif). None kalau gagal."""
        try:
            resp = self._client_for(config.provider_for_model(self.model)).models.list()
            return sorted(m.id for m in resp.data)
        except Exception:
            return None

    def _enable_session_yolo(self) -> None:
        """Dipanggil tools.run_command saat user jawab 'a' (always) di prompt konfirmasi."""
        self.yolo = True

    @staticmethod
    def _looks_like_infra_glitch(message: str, tool_calls) -> bool:
        """True kalau respons ini kemungkinan besar pesan infrastruktur provider
        yang bocor jadi teks completion (bukan jawaban model beneran) -- lihat
        _INFRA_GLITCH_PHRASES. Cuma dicek kalau TIDAK ada tool_calls (jawaban
        "final") dan teksnya pendek, biar gak salah tangkap jawaban asli yang
        kebetulan nyebut kata serupa di tengah penjelasan panjang."""
        if tool_calls or not message:
            return False
        text = message.strip().lower()
        if len(text) > _INFRA_GLITCH_MAX_LEN:
            return False
        return any(phrase in text for phrase in _INFRA_GLITCH_PHRASES)

    def _critic_phase(self, assistant_output: str, user_input: str) -> str:
        """Phase 1: Critic model (Ultra) self-critique via Constitutional AI."""
        if not self.dual_model_enabled:
            return ""
        
        ui.print_info(f"🔍 Critic phase: {self.critic_model_name} (evaluating...)")
        
        # Simpan model & messages saat ini
        original_model = self.model_override
        original_messages = self.messages.copy()
        
        try:
            # Set model ke critic model
            self.model_override = self.critic_model_name
            
            # Buat prompt khusus Constitutional AI critique
            critic_prompt = (
                "You are a Constitutional AI critic. Evaluate the assistant's output against the Constitution:\n\n"
                "1. HARMLESS - DO NO HARM: No violence, illegality, harm, discrimination, hate speech\n"
                "2. HONEST - Truthfulness: No fabrication, admit limitations, distinguish facts from assumptions\n"
                "3. HELPFUL - Utility: Useful and effective, but never at expense of Safety/Honesty\n\n"
                "Analyze the assistant's output and provide critique in this format:\n"
                "## ASSESSMENT\n[PASS/FAIL for each principle]\n"
                "## ISSUES FOUND\n[List specific issues with line references]\n"
                "## SUGGESTED REVISIONS\n[Specific changes to make output constitutionally compliant]\n"
                "## FINAL VERDICT\n[APPROVE / REQUEST_CHANGES / BLOCK]\n\n"
                "Be strict. If output violates constitution, BLOCK it."
            )
            
            self.messages = [
                {"role": "system", "content": critic_prompt},
                {"role": "user", "content": f"USER REQUEST:\n{user_input}\n\nASSISTANT OUTPUT:\n{assistant_output}"}
            ]
            
            # Call critic model WITHOUT tools
            client = self._client_for(config.provider_for_model(self.critic_model_name))
            stream = client.chat.completions.create(
                model=config.strip_provider_prefix(self.critic_model_name),
                messages=self.messages,
                tools=[],  # NO TOOLS for critic
                tool_choice="none",
                temperature=0.1,  # Low temp for consistent critique
                max_tokens=4096,
                stream=True,
                stream_options={"include_usage": True},
            )
            
            critic_parts = []
            with ui.new_live() as live:
                for chunk in stream:
                    if chunk.choices:
                        delta = chunk.choices[0].delta
                        content = getattr(delta, "content", "")
                        if content:
                            critic_parts.append(content)
                            live.update(ui.render_stream_group(
                                "", "".join(critic_parts), reasoning_done=True,
                            ))
            
            critique = "".join(critic_parts)
            self.last_critique = critique
            
            if critique:
                ui.print_info(f"✅ Critique complete ({len(critique)} chars)")
            
            return critique
            
        except Exception as e:
            ui.print_error(f"Critic phase failed: {e}. Proceeding without critique.")
            return ""
        finally:
            # Restore original state
            self.model_override = original_model
            self.messages = original_messages

    def run_turn(self, user_input: str) -> None:
        """Proses satu input user sampai model selesai memberi jawaban final."""
        
        # Phase 1: Execution with assistant model (Muse) or single model
        self.messages.append({"role": "user", "content": user_input})
        
        # Set model for execution phase
        if self.dual_model_enabled:
            self.model_override = self.assistant_model_name
        
        turn_tokens = {"prompt": 0, "completion": 0, "total": 0}

        for _ in range(config.MAX_AGENT_ITERATIONS):
            glitch_retry = 0
            while True:
                message, tool_calls, usage = self._stream_completion()
                if not self._looks_like_infra_glitch(message, tool_calls):
                    break
                if glitch_retry >= len(_INFRA_GLITCH_RETRY_WAIT_SECONDS):
                    # Sudah dicoba ulang beberapa kali, tetap dapet respons yang
                    # sama mencurigakan -- daripada retry selamanya, terima apa
                    # adanya (masuk ke jalur normal di bawah) dan biarkan user lihat.
                    break
                wait_s = _INFRA_GLITCH_RETRY_WAIT_SECONDS[glitch_retry]
                glitch_retry += 1
                ui.print_error(
                    f"Respons mencurigakan dari provider (kemungkinan pesan infrastruktur "
                    f"bocor jadi teks, bukan jawaban model beneran): {message.strip()!r}. "
                    f"Coba lagi dalam {wait_s:.0f} detik ({glitch_retry}/"
                    f"{len(_INFRA_GLITCH_RETRY_WAIT_SECONDS)})..."
                )
                time.sleep(wait_s)

            if usage:
                turn_tokens["prompt"] += getattr(usage, "prompt_tokens", 0) or 0
                turn_tokens["completion"] += getattr(usage, "completion_tokens", 0) or 0
                turn_tokens["total"] += getattr(usage, "total_tokens", 0) or 0

            assistant_entry = {"role": "assistant", "content": message or ""}
            if tool_calls:
                assistant_entry["tool_calls"] = tool_calls
            self.messages.append(assistant_entry)

            if not tool_calls:
                # Phase 2: Critic evaluation (if dual-model enabled)
                if self.dual_model_enabled:
                    critique = self._critic_phase(message, user_input)
                    if critique:
                        ui.print_info("\n" + "="*80)
                        ui.print_info("🔍 CONSTITUTIONAL AI CRITIQUE")
                        ui.print_info("="*80)
                        print(critique)
                        print("="*80)
                
                self.session_tokens["prompt"] += turn_tokens["prompt"]
                self.session_tokens["completion"] += turn_tokens["completion"]
                self.session_tokens["total"] += turn_tokens["total"]
                if turn_tokens["total"] > 0:
                    ui.print_token_usage(turn_tokens, self.session_tokens)
                print()  # newline penutup setelah jawaban final
                return

            for call in tool_calls:
                name = call["function"]["name"]
                try:
                    arguments = json.loads(call["function"]["arguments"] or "{}")
                except json.JSONDecodeError:
                    # Model (terutama model kecil/vision) kadang nge-glitch pas
                    # streaming tool-call, hasil argumennya JSON korup/dobel.
                    # Eksekusi tetap lanjut dengan {} (aman), TAPI string
                    # mentah yang korup itu JANGAN ikut kesimpen balik ke
                    # history -- kalau dibiarkan, tiap request BERIKUTNYA bakal
                    # ditolak API (400) karena history-nya sendiri gak valid
                    # lagi. `call` di sini objek yang SAMA dengan yang sudah
                    # ke-append ke self.messages (assistant_entry["tool_calls"]),
                    # jadi overwrite di bawah ini otomatis nge-fix history juga.
                    arguments = {}
                call["function"]["arguments"] = json.dumps(arguments)
                ui.print_tool_call(name, arguments)
                result = tools.execute_tool(
                    name, arguments, auto_approve=self.yolo, extra_safe=self.extra_safe_commands,
                    on_always_approve=self._enable_session_yolo,
                )
                ui.print_tool_result(result["text"] or f"({len(result['images'])} gambar)")
                self.messages.append(
                    {"role": "tool", "tool_call_id": call["id"], "content": self._tool_content(result)}
                )
            print()

        ui.print_error(
            f"Berhenti setelah {config.MAX_AGENT_ITERATIONS} iterasi tanpa jawaban final "
            "(kemungkinan model muter-muter). Coba pecah task jadi lebih kecil."
        )

    @staticmethod
    def _retry_after_seconds(e: RateLimitError) -> float | None:
        """Baca header Retry-After dari response 429 kalau providernya kasih tahu
        persis berapa lama harus nunggu -- lebih akurat daripada nebak sendiri."""
        resp = getattr(e, "response", None)
        header = resp.headers.get("retry-after") if resp is not None else None
        if not header:
            return None
        try:
            return max(1.0, float(header))
        except ValueError:
            return None

    def _next_fallback_model(self, tried_providers: set[str]) -> str | None:
        """Model fallback pertama di config.FALLBACK_MODELS yang provider-nya
        belum dicoba sama sekali di panggilan _create_stream ini.
        
        Menggunakan smart fallback dengan health scoring - pilih provider dengan
        health score tertinggi yang belum dicoba."""
        # Filter provider yang belum dicoba dan bisa digunakan (circuit breaker)
        available_providers = []
        for m in config.FALLBACK_MODELS:
            p = config.provider_for_model(m)
            if p not in tried_providers and _can_use_provider(p):
                health = _get_provider_health(p)
                available_providers.append((m, p, health.health_score))
        
        # Sort by health score (descending) untuk pilih yang paling sehat
        if available_providers:
            available_providers.sort(key=lambda x: x[2], reverse=True)
            return available_providers[0][0]
        
        # Fallback ke cara lama kalau tidak ada yang tersedia via health scoring
        for m in config.FALLBACK_MODELS:
            p = config.provider_for_model(m)
            if p not in tried_providers:
                return m
        return None

    def _create_stream(self):
        """Buka stream completion, dengan DUA lapis pemulihan:

        1. Retry DALAM provider yang sama (cuma berlaku ke 'mistral' yang
           punya >1 API key): 429 -> rotate key, kalau semua key di putaran
           ini 429 -> tunggu (_MISTRAL_RATE_LIMIT_WAIT_SECONDS) lalu ulangi
           dari key pertama. 401/403 -> rotate tanpa nunggu (key rusak
           permanen). Provider lain (nvidia/groq/cloudflare) cuma 1 key,
           gak ada yang bisa dirotasi di lapis ini.
        2. Kalau provider yang aktif BENERAN habis semua opsi lapis 1 di atas
           (401/403/429 tanpa key lain buat dirotasi lagi) -> pindah ke
           provider fallback berikutnya (config.FALLBACK_MODELS, provider yang
           beda dari yang barusan gagal), ganti self.model_override, ulangi
           dari awal. Nyerah cuma kalau semua provider fallback juga sudah
           dicoba dan gagal (atau FALLBACK_MODELS kosong).
        
        Circuit Breaker Pattern: Track failure rate per provider, skip provider
        yang sedang 'OPEN' untuk menghindari wasted requests ke provider down.
        
        Exponential Backoff with Jitter: Tambahkan variasi random ke delay retry
        untuk hindari thundering herd problem saat banyak client retry bersamaan."""
        self._compact_old_tool_results()
        self._compact_long_user_messages()
        profile = self.profile
        tried_providers: set[str] = set()
        last_error: Exception | None = None
        backoff_attempt = 0  # Track attempt untuk exponential backoff
        
        while True:
            provider = config.provider_for_model(self.model)
            
            # Cek circuit breaker sebelum mencoba provider
            if not _can_use_provider(provider):
                ui.print_error(f"⚠️ Circuit breaker untuk '{provider}' OPEN, skipping...")
                tried_providers.add(provider)
                next_model = self._next_fallback_model(tried_providers)
                if next_model is None:
                    raise last_error or RuntimeError(f"Provider '{provider}' tidak tersedia")
                ui.print_error(f"Pindah ke fallback: {next_model} ...")
                self.model_override = next_model
                continue
            
            tried_providers.add(provider)
            rate_limit_sweep = 0
            transient_retry = 0
            exhausted = False
            request_start_time = time.time()
            
            while True:
                client = self._client_for(provider)
                if os.environ.get("NVICODER_DEBUG_DUMP_REQUEST"):
                    import json as _json
                    with open(os.environ["NVICODER_DEBUG_DUMP_REQUEST"], "w", encoding="utf-8") as _f:
                        _json.dump({
                            "model": config.strip_provider_prefix(self.model),
                            "messages": self.messages,
                            "tools": tools.get_all_tools_schema(),
                        }, _f, ensure_ascii=False)
                try:
                    result = client.chat.completions.create(
                        model=config.strip_provider_prefix(self.model),
                        messages=self.messages,
                        tools=tools.get_all_tools_schema(),
                        tool_choice="auto",
                        parallel_tool_calls=True,
                        temperature=profile.temperature,
                        max_tokens=profile.max_tokens,
                        stream=True,
                        stream_options={"include_usage": True},
                    )
                    # Record success untuk health tracking
                    latency_ms = (time.time() - request_start_time) * 1000
                    _record_provider_success(provider, latency_ms)
                    return result
                except (AuthenticationError, PermissionDeniedError) as e:
                    last_error = e
                    _record_provider_failure(provider)
                    if provider == "mistral":
                        failed_idx = self._mistral_key_index
                        if self._rotate_mistral_key():
                            ui.print_error(
                                f"Key Mistral #{failed_idx + 1} ditolak (invalid/permission), "
                                f"pindah ke key #{self._mistral_key_index + 1}..."
                            )
                            continue
                    exhausted = True
                except RateLimitError as e:
                    last_error = e
                    _record_provider_failure(provider)
                    if provider == "mistral":
                        failed_idx = self._mistral_key_index
                        if self._rotate_mistral_key():
                            ui.print_error(
                                f"Key Mistral #{failed_idx + 1} kena rate-limit, "
                                f"pindah ke key #{self._mistral_key_index + 1}..."
                            )
                            continue
                        # Semua key sudah dicoba di putaran ini & tetap kena limit --
                        # kemungkinan besar TPM per-menit kepakai bareng oleh payload
                        # gede. Tunggu, reset ke key pertama, coba lagi dari awal.
                        if rate_limit_sweep < len(_MISTRAL_RATE_LIMIT_WAIT_SECONDS):
                            wait_s = self._retry_after_seconds(e) or _MISTRAL_RATE_LIMIT_WAIT_SECONDS[rate_limit_sweep]
                            rate_limit_sweep += 1
                            ui.print_error(
                                f"Semua {len(config.MISTRAL_API_KEYS)} key Mistral kena rate-limit. "
                                f"Nunggu {wait_s:.0f} detik lalu coba lagi ({rate_limit_sweep}/"
                                f"{len(_MISTRAL_RATE_LIMIT_WAIT_SECONDS)})..."
                            )
                            time.sleep(wait_s)
                            self._mistral_key_index = 0
                            continue
                    exhausted = True
                except (InternalServerError, APIConnectionError, APITimeoutError) as e:
                    # 5xx ("service overloaded") / putus koneksi / timeout -- ini
                    # BUKAN masalah key (auth/kuota), jadi rotate key gak ada
                    # gunanya. Kemungkinan besar cuma hiccup sesaat provider,
                    # jadi retry singkat DULU di provider yang sama sebelum
                    # nyerah & fallback ke provider lain (ditemukan lewat crash
                    # nyata: "InternalServerError" belum ketangkep sebelum ini,
                    # bikin task game Godot mati mendadak padahal cuma hiccup).
                    last_error = e
                    _record_provider_failure(provider)
                    
                    # Gunakan exponential backoff with jitter untuk retry
                    if transient_retry < len(_TRANSIENT_ERROR_RETRY_WAIT_SECONDS):
                        base_wait = _TRANSIENT_ERROR_RETRY_WAIT_SECONDS[transient_retry]
                        wait_s = _exponential_backoff_with_jitter(backoff_attempt, base_wait)
                        backoff_attempt += 1
                        transient_retry += 1
                        ui.print_error(
                            f"Provider '{provider}' error sesaat ({type(e).__name__}: {e}). "
                            f"Coba lagi dalam {wait_s:.1f} detik (exponential backoff + jitter) "
                            f"({transient_retry}/{len(_TRANSIENT_ERROR_RETRY_WAIT_SECONDS)})..."
                        )
                        time.sleep(wait_s)
                        continue
                    exhausted = True
                if exhausted:
                    break

            # Provider di atas abis semua opsi retry-nya -- coba fallback ke
            # provider lain (kalau ada & belum dicoba di panggilan ini).
            next_model = self._next_fallback_model(tried_providers)
            if next_model is None:
                raise last_error
            ui.print_error(
                f"Provider '{provider}' abis semua opsi retry-nya. "
                f"Pindah ke fallback: {next_model} ..."
            )
            self.model_override = next_model

    def _stream_completion(self):
        """Buka stream (lewat _create_stream(), yang udah punya retry/fallback
        sendiri) LALU konsumsi chunk-nya. Retry/fallback _create_stream() cuma
        nutupin kegagalan pas REQUEST AWAL -- kalau koneksi putus/error DI
        TENGAH baca stream (mis. abis beberapa chunk), exception itu dulu lolos
        begitu aja sampai ke luar tanpa retry (ditemukan lewat insiden nyata:
        proses mati mendadak abis tool_call, gak ada pesan retry sama sekali).
        Makanya seluruh proses fetch+konsumsi di-bungkus retry loop di sini juga
        -- kalau gagal di tengah, buang stream yang kepotong & minta stream BARU
        dari awal (bukan nyoba nyambung yang lama, itu gak didukung protokolnya)."""
        for attempt in range(len(_TRANSIENT_ERROR_RETRY_WAIT_SECONDS) + 1):
            try:
                return self._consume_stream(self._create_stream())
            except APIError as e:
                # APIError = kelas dasar SEMUA error dari SDK openai (bukan cuma
                # 6 subclass yang tadinya dicek satu-satu) -- ketemu lewat insiden
                # nyata "Service temporarily overloaded" yang ternyata APIError
                # generik (kemungkinan APIResponseValidationError, body respons gak
                # cocok skema pas provider lagi overload), bukan salah satu dari 6
                # subclass yang tadinya di-list eksplisit, jadi lolos gak ke-retry.
                # Di sini gak perlu bedain per-tipe (itu udah ditangani _create_stream()
                # pas retry-nya manggil ulang) -- pokoknya stream yang kepotong dibuang,
                # minta yang baru dari awal.
                if attempt >= len(_TRANSIENT_ERROR_RETRY_WAIT_SECONDS):
                    raise
                wait_s = _TRANSIENT_ERROR_RETRY_WAIT_SECONDS[attempt]
                ui.print_error(
                    f"Koneksi putus/error DI TENGAH baca stream ({type(e).__name__}: {e}). "
                    f"Minta stream baru dalam {wait_s:.0f} detik ({attempt + 1}/"
                    f"{len(_TRANSIENT_ERROR_RETRY_WAIT_SECONDS)})..."
                )
                time.sleep(wait_s)

    def _consume_stream(self, stream):
        content_parts: list[str] = []
        reasoning_parts: list[str] = []
        tool_calls_acc: dict[int, dict] = {}
        usage_info = None
        reasoning_done = False

        with ui.new_live() as live:
            for chunk in stream:
                # Chunk usage-only (di akhir stream) biasanya punya choices
                # kosong -- makanya usage dicek DULU, sebelum baris di bawah
                # skip chunk yang choices-nya kosong.
                chunk_usage = getattr(chunk, "usage", None)
                if chunk_usage:
                    usage_info = chunk_usage

                if not chunk.choices:
                    continue
                delta = chunk.choices[0].delta

                reasoning = getattr(delta, "reasoning_content", None)
                if reasoning:
                    reasoning_parts.append(reasoning)

                if delta.content:
                    if reasoning_parts and not reasoning_done:
                        # Jawaban final mulai muncul -> reasoning resmi selesai,
                        # panel gede-nya "dikill" jadi ringkasan 1 baris mulai
                        # dari update berikutnya.
                        reasoning_done = True
                    content_parts.append(delta.content)

                if reasoning or delta.content:
                    live.update(ui.render_stream_group(
                        "".join(reasoning_parts), "".join(content_parts), reasoning_done=reasoning_done,
                    ))

                if delta.tool_calls:
                    for tc in delta.tool_calls:
                        idx = tc.index
                        if idx not in tool_calls_acc:
                            tool_calls_acc[idx] = {
                                "id": "",
                                "type": "function",
                                "function": {"name": "", "arguments": ""},
                            }
                        if tc.id:
                            tool_calls_acc[idx]["id"] += tc.id
                        if tc.function:
                            if tc.function.name:
                                tool_calls_acc[idx]["function"]["name"] += tc.function.name
                            if tc.function.arguments:
                                tool_calls_acc[idx]["function"]["arguments"] += tc.function.arguments

            # Stream abis tapi reasoning belum sempat ke-collapse (mis. turn ini
            # cuma tool_call tanpa jawaban teks sama sekali) -- paksa collapse
            # sebelum Live block ditutup, supaya yang nempel permanen di
            # scrollback selalu versi ringkas, bukan panel mentah yang gede.
            if reasoning_parts and not reasoning_done:
                live.update(ui.render_stream_group(
                    "".join(reasoning_parts), "".join(content_parts), reasoning_done=True,
                ))

        if reasoning_parts:
            self.last_reasoning = "".join(reasoning_parts)

        tool_calls = [tool_calls_acc[i] for i in sorted(tool_calls_acc)] if tool_calls_acc else None
        return "".join(content_parts), tool_calls, usage_info


def _call_vision_model(image_path: str, question: str, max_retries: int = 3) -> str:
    """Panggil model vision meta/muse-glimmer-30b untuk analisis gambar.
    
    Args:
        image_path: Path ke file gambar lokal
        question: Pertanyaan/instruksi untuk analisis
        max_retries: Maksimal percobaan retry
    
    Returns:
        String hasil analisis dari model
    """
    import base64
    from pathlib import Path
    
    # Encode gambar ke base64
    with open(image_path, "rb") as f:
        image_data = base64.b64encode(f.read()).decode("utf-8")
    
    # Detect mime type dari extension
    ext = Path(image_path).suffix.lower()
    mime_map = {
        '.jpg': 'image/jpeg', '.jpeg': 'image/jpeg',
        '.png': 'image/png', '.gif': 'image/gif',
        '.webp': 'image/webp', '.bmp': 'image/bmp'
    }
    mime_type = mime_map.get(ext, 'image/jpeg')
    
    # Setup client dan model
    vision_model = "meta/muse-glimmer-30b"
    
    # Coba dengan provider fallback
    providers_to_try = ["nvidia", "mistral", "groq"]
    last_error = None
    
    for attempt in range(max_retries):
        for provider in providers_to_try:
            try:
                # Cek circuit breaker
                if not _can_use_provider(provider):
                    continue
                
                start_time = time.time()
                
                # Buat client sesuai provider
                if provider == "nvidia":
                    from openai import OpenAI
                    client = OpenAI(
                        base_url="https://integrate.api.nvidia.com/v1",
                        api_key=config.NVIDIA_API_KEY
                    )
                elif provider == "mistral":
                    # Ambil key pertama dari list MISTRAL_API_KEYS
                    mistral_key = config.MISTRAL_API_KEYS[0] if config.MISTRAL_API_KEYS else ""
                    client = OpenAI(
                        base_url="https://api.mistral.ai/v1",
                        api_key=mistral_key
                    )
                elif provider == "groq":
                    client = OpenAI(
                        base_url="https://api.groq.com/openai/v1",
                        api_key=config.GROQ_API_KEY
                    )
                else:
                    continue
                
                # Call model vision
                response = client.chat.completions.create(
                    model=vision_model,
                    messages=[
                        {
                            "role": "user",
                            "content": [
                                {"type": "text", "text": question},
                                {"type": "image_url", "image_url": {"url": f"data:{mime_type};base64,{image_data}"}}
                            ]
                        }
                    ],
                    max_tokens=1024
                )
                
                latency_ms = (time.time() - start_time) * 1000
                _record_provider_success(provider, latency_ms)
                
                if response.choices and response.choices[0].message.content:
                    return response.choices[0].message.content.strip()
                else:
                    return "(Tidak ada respons dari model vision)"
                    
            except Exception as e:
                last_error = e
                _record_provider_failure(provider)
                
                # Exponential backoff sebelum retry berikutnya
                if attempt < max_retries - 1:
                    delay = _exponential_backoff_with_jitter(attempt)
                    time.sleep(delay)
                continue
    
    error_msg = f"Gagal memanggil model vision setelah {max_retries} percobaan"
    if last_error:
        error_msg += f": {str(last_error)}"
    return error_msg
