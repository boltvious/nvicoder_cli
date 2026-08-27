"""
Kontrol browser nyata (Playwright) untuk tool `browser_control`.

Browser dibuka lazily saat action pertama yang butuh page dipanggil, lalu
dipertahankan (persist) antar tool_call dalam satu sesi CLI supaya state
(tab, hasil login, dst) tidak hilang tiap panggilan -- mirip cara kerja
"Claude in Chrome". Ditutup eksplisit lewat action="close", atau otomatis
saat proses nvicoder exit.

Default channel="msedge" (lihat config.BROWSER_CHANNEL) karena Microsoft
Edge sudah terpasang bawaan di Windows, jadi tidak perlu download Chromium
~300MB terpisah seperti browser bundled Playwright.
"""

import atexit

from . import config

_playwright = None
_browser = None
_context = None
_page = None

_VALID_ACTIONS = ("open", "click", "type", "get_text", "screenshot", "close")


def is_running() -> bool:
    return _page is not None


def _ensure_page():
    global _playwright, _browser, _context, _page
    if _page is not None:
        return _page

    from playwright.sync_api import sync_playwright

    _playwright = sync_playwright().start()
    launch_kwargs = {"headless": config.BROWSER_HEADLESS}
    if config.BROWSER_CHANNEL != "chromium":
        launch_kwargs["channel"] = config.BROWSER_CHANNEL
    try:
        _browser = _playwright.chromium.launch(**launch_kwargs)
        _context = _browser.new_context()
        _page = _context.new_page()
    except Exception:
        _playwright.stop()
        _playwright = _browser = _context = _page = None
        raise
    return _page


def close() -> str:
    global _playwright, _browser, _context, _page
    if _page is None:
        return "Browser belum/tidak sedang berjalan."
    try:
        _context.close()
        _browser.close()
        _playwright.stop()
    finally:
        _playwright = _browser = _context = _page = None
    return "OK: browser ditutup."


atexit.register(close)  # jaga-jaga: tutup browser walau CLI exit tanpa action='close' eksplisit


def browser_control(action: str, url: str | None = None, selector: str | None = None,
                     value: str | None = None, path: str | None = None,
                     timeout: int | None = None) -> str:
    action = (action or "").strip().lower()
    if action not in _VALID_ACTIONS:
        return f"ERROR: action tidak dikenal: {action!r}. Pakai salah satu: {', '.join(_VALID_ACTIONS)}."

    if action == "close":
        return close()

    timeout_ms = (timeout or 15) * 1000

    try:
        page = _ensure_page()
    except Exception as e:
        return f"ERROR: Gagal membuka browser (channel={config.BROWSER_CHANNEL}): {e}"

    try:
        if action == "open":
            if not url:
                return "ERROR: action 'open' butuh parameter url."
            page.goto(url, timeout=timeout_ms, wait_until="domcontentloaded")
            return f"OK: dibuka {page.url}\nTitle: {page.title()}"

        if action == "click":
            if not selector:
                return "ERROR: action 'click' butuh parameter selector."
            page.click(selector, timeout=timeout_ms)
            return f"OK: klik {selector}"

        if action == "type":
            if not selector or value is None:
                return "ERROR: action 'type' butuh parameter selector dan value."
            page.fill(selector, value, timeout=timeout_ms)
            return f"OK: isi {selector} dengan teks ({len(value)} karakter)"

        if action == "get_text":
            target = page.locator(selector) if selector else page.locator("body")
            content = target.inner_text(timeout=timeout_ms).strip()
            if len(content) > 4000:
                content = content[:4000] + "\n... (dipotong, terlalu panjang)"
            return content or "(kosong)"

        if action == "screenshot":
            out_path = path or f"nvicoder-screenshot-{int(page.evaluate('Date.now()'))}.png"
            page.screenshot(path=out_path, full_page=True, timeout=timeout_ms)
            return f"OK: screenshot disimpan di {out_path}"
    except Exception as e:
        return f"ERROR: action '{action}' gagal: {e}"
