"""
Client MCP (Model Context Protocol) generik. Baca daftar server dari
`.mcp.json` di root project (format sama seperti dipakai Claude Code),
spawn tiap server sebagai proses stdio, discover tool yang di-expose-nya,
lalu jembatani sebagai tool OpenAI-style function-calling biasa --
prefiks `mcp__<server>__<tool>` biar gak bentrok sama tool bawaan nvicoder
atau tool dari server MCP lain.

SDK `mcp` resminya async (asyncio); nvicoder sendiri sepenuhnya sync. Tiap
server dijalankan di thread + event loop sendiri yang hidup terus selama
proses nvicoder jalan (context manager stdio_client/ClientSession tetap
"terbuka" selama itu), dipanggil dari sisi sync lewat
`asyncio.run_coroutine_threadsafe`.
"""

import asyncio
import atexit
import json
import os
import threading
from pathlib import Path

_MCP_CONFIG_FILENAME = ".mcp.json"


class _ServerSession:
    def __init__(self, name: str, command: str, args: list[str], env: dict[str, str], cwd: str):
        self.name = name
        self._command = command
        self._args = args
        self._env = env
        self._cwd = cwd
        self._loop: asyncio.AbstractEventLoop | None = None
        self._thread: threading.Thread | None = None
        self._main_task: asyncio.Task | None = None
        self._session = None
        self._shutdown: asyncio.Event | None = None
        self.tools: list = []
        self.error: str | None = None
        self._ready = threading.Event()

    def start(self, timeout: float = 30.0) -> None:
        self._thread = threading.Thread(target=self._run, name=f"mcp-{self.name}", daemon=True)
        self._thread.start()
        if not self._ready.wait(timeout=timeout) and not self.error:
            self.error = f"Timeout ({timeout:.0f}s) menunggu server MCP '{self.name}' siap."
        if self.error:
            raise RuntimeError(self.error)

    def _run(self) -> None:
        self._loop = asyncio.new_event_loop()
        asyncio.set_event_loop(self._loop)
        try:
            self._main_task = self._loop.create_task(self._main())
            self._loop.run_until_complete(self._main_task)
        except asyncio.CancelledError:
            pass  # dibatalkan lewat stop() sebelum sempat ready (mis. timeout di start()) -- bukan error
        except Exception as e:  # noqa: BLE001 -- pastikan _ready selalu ke-set walau gagal
            self.error = self.error or str(e)
            self._ready.set()

    async def _main(self) -> None:
        from mcp import ClientSession, StdioServerParameters
        from mcp.client.stdio import stdio_client

        params = StdioServerParameters(
            command=self._command, args=self._args, env=self._env, cwd=self._cwd,
        )
        try:
            async with stdio_client(params) as (read, write):
                async with ClientSession(read, write) as session:
                    await session.initialize()
                    result = await session.list_tools()
                    self._session = session
                    self.tools = result.tools
                    self._shutdown = asyncio.Event()
                    self._ready.set()
                    await self._shutdown.wait()
        except Exception as e:
            self.error = str(e)
            self._ready.set()

    def call_tool(self, tool_name: str, arguments: dict, timeout: float = 60.0):
        if self._session is None or self._loop is None:
            raise RuntimeError(f"Server MCP '{self.name}' belum siap/sudah mati.")
        fut = asyncio.run_coroutine_threadsafe(
            self._session.call_tool(tool_name, arguments), self._loop
        )
        return fut.result(timeout=timeout)

    def stop(self) -> None:
        """Matikan session ini -- termasuk kalau belum sempat 'ready' (mis. start() timeout),
        supaya child process (npx/node, dst) yang sudah kepalang jalan tidak bocor jadi
        proses zombie. Kalau sudah ready: signal _shutdown (exit context manager dengan bersih).
        Kalau belum ready: cancel _main_task langsung -- CancelledError menjalar lewat
        `async with stdio_client(...)` sehingga context manager-nya tetap terminate proses child.
        """
        if self._loop is not None:
            def _request_stop() -> None:
                if self._shutdown is not None:
                    self._shutdown.set()
                elif self._main_task is not None and not self._main_task.done():
                    self._main_task.cancel()
            self._loop.call_soon_threadsafe(_request_stop)
        if self._thread is not None:
            self._thread.join(timeout=10)


_servers: dict[str, _ServerSession] = {}


def _load_config(cwd: str) -> dict:
    path = os.path.join(cwd, _MCP_CONFIG_FILENAME)
    if not os.path.isfile(path):
        return {}
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, json.JSONDecodeError):
        return {}
    return data.get("mcpServers", {}) if isinstance(data, dict) else {}


def discover_mcp_configs(root_cwd: str | None = None, max_depth: int = 3) -> dict[str, dict]:
    """
    Scan .mcp.json files in root_cwd and subdirectories up to max_depth.
    Returns dict of {server_name: {config, cwd, config_path}}.
    """
    root = Path(root_cwd or os.getcwd()).resolve()
    discovered = {}
    
    def scan_dir(current: Path, depth: int):
        if depth > max_depth:
            return
        config_path = current / _MCP_CONFIG_FILENAME
        if config_path.is_file():
            try:
                with open(config_path, "r", encoding="utf-8") as f:
                    data = json.load(f)
                servers = data.get("mcpServers", {}) if isinstance(data, dict) else {}
                for name, cfg in servers.items():
                    # Prefix with relative path to avoid name collisions
                    rel_path = current.relative_to(root)
                    prefix = str(rel_path).replace(os.sep, "_") if rel_path != Path(".") else ""
                    full_name = f"{prefix}_{name}" if prefix else name
                    discovered[full_name] = {
                        "config": cfg,
                        "cwd": str(current),
                        "config_path": str(config_path),
                        "original_name": name,
                    }
            except (OSError, json.JSONDecodeError):
                pass
        # Scan subdirectories
        try:
            for subdir in current.iterdir():
                if subdir.is_dir() and not subdir.name.startswith("."):
                    scan_dir(subdir, depth + 1)
        except OSError:
            pass
    
    scan_dir(root, 0)
    return discovered


def auto_connect_all(root_cwd: str | None = None, max_depth: int = 3) -> dict[str, _ServerSession]:
    """
    Discover all .mcp.json configs and connect to all servers.
    Returns dict of connected sessions {server_name: _ServerSession}.
    """
    discovered = discover_mcp_configs(root_cwd, max_depth)
    connected = {}
    for name, info in discovered.items():
        try:
            # Use original_name from config, not the prefixed name
            session = connect(info["original_name"], cwd=info["cwd"])
            connected[name] = session
        except Exception:
            # Log but continue with other servers
            pass
    return connected


def available_servers(cwd: str | None = None) -> dict[str, dict]:
    """Server MCP yang terdaftar di .mcp.json cwd (belum tentu sudah nyala)."""
    return _load_config(cwd or os.getcwd())


def running_servers() -> list[str]:
    return [name for name, s in _servers.items() if s.error is None]


def connect(name: str, cwd: str | None = None) -> _ServerSession:
    """Spawn & connect ke satu server MCP dari .mcp.json. Blocking sampai siap atau error."""
    if name in _servers and _servers[name].error is None:
        return _servers[name]
    cwd = cwd or os.getcwd()
    cfg = _load_config(cwd).get(name)
    if cfg is None:
        raise RuntimeError(f"Server MCP '{name}' tidak ada di {_MCP_CONFIG_FILENAME} (cwd={cwd}).")
    env = dict(os.environ)
    env.update(cfg.get("env") or {})
    session = _ServerSession(
        name=name, command=cfg["command"], args=cfg.get("args", []), env=env, cwd=cwd,
    )
    try:
        session.start()
    except Exception:
        session.stop()  # start() gagal (mis. timeout) -- pastikan proses child yang sudah spawn tetap ke-cleanup
        raise
    _servers[name] = session
    return session


def _try_reconnect(session: "_ServerSession") -> "_ServerSession":
    """Coba SEKALI reconnect server yang matinya session.error != None, sebelum nyerah.
    Filosofinya sama kayak /mcp reconnect di Claude Code sendiri: bukan auto-retry
    infinite dengan backoff, cuma satu percobaan fresh -- bedanya di sini dipicu
    otomatis oleh tool call berikutnya, bukan nunggu manusia ngetik /mcp. Sebelum ini,
    server yang mati di tengah sesi permanent ke-stuck ngembaliin "belum aktif" terus
    sampai proses nvicoder direstart total, walau penyebabnya cuma glitch sesaat."""
    try:
        return connect(session.name, cwd=session._cwd)
    except Exception as e:
        failed = _ServerSession(name=session.name, command="", args=[], env={}, cwd=session._cwd)
        failed.error = str(e)
        _servers[session.name] = failed
        return failed


def get_tools_schema() -> list[dict]:
    """Tool schema OpenAI-style dari semua server MCP yang SUDAH connect (lihat connect())."""
    schema = []
    for name, session in _servers.items():
        if session.error:
            continue
        for tool in session.tools:
            schema.append({
                "type": "function",
                "function": {
                    "name": f"mcp__{name}__{tool.name}",
                    "description": (tool.description or "")[:1000],
                    "parameters": tool.input_schema or {"type": "object", "properties": {}},
                },
            })
    return schema


def is_mcp_tool(name: str) -> bool:
    return name.startswith("mcp__")


def call(qualified_name: str, arguments: dict) -> dict:
    """qualified_name format: mcp__<server>__<tool>

    Return selalu dict {"text": str, "images": list[{"mime_type", "data"(base64)}]}
    -- BUKAN str lagi. Sebelumnya block ImageContent dari hasil tool (mis.
    screenshot) DIBUANG diam-diam (cuma block.text yang diambil), jadi tool
    kayak runtime_screenshot efektif gak pernah kepakai walau sukses. Caller
    (tools.execute_tool -> agent.py) yang mutusin apa image ini beneran
    dikirim ke model (tergantung model aktif support vision atau nggak)."""
    try:
        _, server_name, tool_name = qualified_name.split("__", 2)
    except ValueError:
        return {"text": f"ERROR: nama tool MCP tidak valid: {qualified_name!r}", "images": []}
    session = _servers.get(server_name)
    if session is None:
        return {"text": f"ERROR: server MCP '{server_name}' belum aktif.", "images": []}

    if session.error:
        session = _try_reconnect(session)
        if session.error:
            return {
                "text": (
                    f"ERROR: server MCP '{server_name}' mati ({session.error}); reconnect "
                    f"otomatis juga gagal. Kemungkinan aplikasi yang dijembatani (mis. "
                    f"Godot/Blender) sudah tertutup, atau butuh restart manual."
                ),
                "images": [],
            }

    try:
        result = session.call_tool(tool_name, arguments)
    except Exception as e:
        # Putus PAS di tengah panggilan ini (bukan udah mati dari sebelumnya) --
        # tandai error di session, coba reconnect sekali, lalu ulang tool call ini SEKALI.
        session.error = str(e)
        session = _try_reconnect(session)
        if session.error:
            return {
                "text": (
                    f"ERROR: panggil tool MCP '{qualified_name}' gagal ({e}); koneksi putus "
                    f"di tengah panggilan ini dan reconnect otomatis juga gagal ({session.error})."
                ),
                "images": [],
            }
        try:
            result = session.call_tool(tool_name, arguments)
        except Exception as e2:
            return {
                "text": (
                    f"ERROR: panggil tool MCP '{qualified_name}' tetap gagal ({e2}) walau "
                    f"sudah reconnect -- server MCP mungkin butuh restart manual."
                ),
                "images": [],
            }

    text_parts = []
    images = []
    for block in getattr(result, "content", None) or []:
        text = getattr(block, "text", None)
        if text:
            text_parts.append(text)
        data = getattr(block, "data", None)
        if data and getattr(block, "type", None) == "image":
            images.append({
                "mime_type": getattr(block, "mime_type", None) or "image/png",
                "data": data,
            })
    if getattr(result, "is_error", False):
        return {
            "text": f"ERROR: {chr(10).join(text_parts) if text_parts else 'tool MCP mengembalikan error tanpa detail.'}",
            "images": [],
        }
    text = "\n".join(text_parts) if text_parts else ("(tidak ada output)" if not images else "")
    return {"text": text, "images": images}


def close_all() -> None:
    for session in _servers.values():
        session.stop()
    _servers.clear()


atexit.register(close_all)  # jaga-jaga: matikan proses server MCP walau CLI exit tanpa cleanup eksplisit
