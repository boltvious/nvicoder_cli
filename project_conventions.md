# Project Conventions — nvicoder with Constitutional AI Critic

> **Simpan di root repo sebagai `project_conventions.md`**
> **Load otomatis oleh nvicoder saat `--code-review` aktif**
> **Arsitektur**: Constitutional AI Critic (Assistant → Critic Evaluation)

---

## Language & Framework
- **Language**: Python 3.11+
- **Framework**: nvicoder (CLI agent)
- **Type checker**: mypy (strict)
- **LLM Provider**: NVIDIA API (Nemotron), OpenAI-compatible
- **Models**: nvidia/nemotron-3-ultra-550b-a55b (Critic), meta/muse-glimmer-30b (Assistant)

## Naming Conventions
| Element | Convention | Example |
|---------|------------|---------|
| Modules | `snake_case` | `user_service.py` |
| Classes | `PascalCase` | `UserService` |
| Functions/vars | `snake_case` | `get_user_by_id` |
| Constants | `UPPER_SNAKE_CASE` | `MAX_RETRY_COUNT` |
| Private | `_leading_underscore` | `_internal_cache` |
| Type vars | `PascalCase` + `T` suffix | `UserT` |

## Imports
- **Order**: stdlib → third-party → local
- **Groups** separated by blank line
- **No wildcard imports** (`from x import *`)
- **Relative imports** untuk local packages

```python
# ✅ Good
import os
import sys
from pathlib import Path

import requests
from fastapi import FastAPI

from myapp.models import User
from myapp.services import user_service
```

## Error Handling
- **Custom exceptions** di `exceptions.py` (inherit dari `AppException`)
- **HTTP errors** → `HTTPException` dengan `detail` yang actionable
- **Logging** → `structlog` (preferred) atau `logging` dengan structured format
- **No bare `except:`** — gunakan `except Exception:` minimal
- **Exception chaining** — `raise NewError(...) from original_error`
- **Critic Phase Errors** — Fail gracefully, proceed without critique if critic model unavailable
- **Model Errors** — Log and fallback to single-model mode

```python
# ✅ Good
try:
    result = risky_operation()
except SpecificError as e:
    logger.error("Operation failed", error=str(e), user_id=user.id)
    raise AppError("User-friendly message") from e
except Exception as e:
    logger.exception("Unexpected error")
    raise
```

## Type Hints
- **Wajib** di public API (functions, methods, class attributes)
- **mypy strict mode** (atau setara)
- **Generics** untuk reusable components
- **Protocol** untuk structural subtyping

```python
# ✅ Good
from typing import Protocol, Generic, TypeVar

T = TypeVar("T")

class Repository(Protocol[T]):
    async def get(self, id: str) -> T | None: ...
    async def save(self, entity: T) -> T: ...
```

## Testing
- **Framework**: pytest
- **Coverage target**: ≥ 80% overall, 100% critical paths
- **Naming**: `test_<module>_<function>_<scenario>`
- **Fixtures** di `conftest.py` (shared) atau module-level
- **Async tests** → `@pytest.mark.asyncio` + `asyncio_mode = auto`
- **Critic Tests**: Test critic phase execution, model switching, prompt format
- **Integration Tests**: Test dual-model flow end-to-end

```python
# ✅ Good
async def test_user_service_get_by_id_returns_user_when_exists(
    user_service: UserService,
    sample_user: User,
) -> None:
    result = await user_service.get_by_id(sample_user.id)
    assert result == sample_user
```

## Git & PR Workflow
- **Conventional commits**: `feat:`, `fix:`, `refactor:`, `security:`, `docs:`, `test:`, `chore:`
- **PR title**: `<type>(<scope>): <description>` — contoh: `feat(auth): add JWT refresh endpoint`
- **Review required**: 1 approval minimum (2 untuk security-sensitive)
- **CI gates**: lint → type-check → test → build

## Forbidden Patterns (Hard Blocks)
| Pattern | Reason | Alternative |
|---------|--------|-------------|
| `eval()`, `exec()` | Code injection | `ast.literal_eval()`, safe parsing |
| `pickle.loads()` untrusted | RCE | `json`, `msgpack`, `orjson` |
| `shell=True` tanpa validasi | Command injection | `subprocess.run(args_list)` |
| `except:` bare | Menyelamatkan `KeyboardInterrupt`, `SystemExit` | `except Exception:` |
| `print()` di production | Tidak terstruktur, tidak terkelola | `logger.info/debug/error()` |
| Hardcoded secrets/URLs/ports | Security, deployment flexibility | Env var / config file |
| `SELECT *` di production | Performance, breaking changes | Explicit column list |
| `asyncio.run()` di library code | Event loop conflict | Async API, caller manages loop |
| Bypass critic evaluation | Constitutional AI violation | Always run critic when dual-model enabled |
| Direct model output without critique | Safety risk | Critic phase must precede final display |

## Required Patterns (Hard Requirements)
| Pattern | Where |
|---------|-------|
| Type hints di public API | Semua `def`/`async def` public |
| Docstrings (Google/NumPy style) | Public classes, functions, modules |
| Context managers untuk resources | File, DB connections, HTTP clients |
| Structured logging | Semua error paths, business events |
| Input validation (Pydantic) | API boundaries, CLI args, config |

---

## Project-Specific Overrides (nvicoder Constitutional AI)

```markdown
# nvicoder with Constitutional AI Critic Architecture

## Architecture
- Dual-model mode: Constitutional AI Critic
- Assistant Model: `meta/muse-glimmer-30b` (execution, tool-calling)
- Critic Model: `nvidia/nemotron-3-ultra-550b-a55b` (evaluation, constitutional compliance)
- Flow: Assistant → Output → Critic Evaluation → User Display

## Constitutional AI Principles
- Hierarchy: HARMLESS > HONEST > HELPFUL
- Critic evaluates all assistant outputs before final display
- Critique format: ASSESSMENT / ISSUES FOUND / SUGGESTED REVISIONS / FINAL VERDICT
- Verdict options: APPROVE / REQUEST_CHANGES / BLOCK

## Configuration
- Dual-model enabled: `NVICODER_DUAL_MODEL=true`
- Critic model: `NVICODER_CRITIC_MODEL=nvidia/nemotron-3-ultra-550b-a55b`
- Assistant model: `NVICODER_ASSISTANT_MODEL=meta/muse-glimmer-30b`
- Config file: `nvicoder.toml` with `critic_model` and `assistant_model`

## Agent Implementation
- File: `nvicoder/agent.py`
- Method: `_critic_phase()` - Constitutional AI evaluation
- Method: `run_turn()` - Assistant execution → Critic evaluation flow
- Property: `critic_model_name` - Returns critic model name
- Property: `assistant_model_name` - Returns assistant model name

## CLI Options
- `--dual-model`: Enable Constitutional AI Critic architecture
- `--reasoning-model`: Set critic model (alias for backward compatibility)

## Database
- ORM: SQLAlchemy 2.0 (async)
- Migrations: Alembic
- Naming: snake_case tables, PK = `id` (UUID)

## API
- Style: RESTful + OpenAPI 3.1
- Versioning: URL prefix `/api/v1/`
- Pagination: cursor-based (default 50, max 200)

## Auth
- JWT (RS256) + refresh tokens
- Scopes: `read:users`, `write:users`, `admin:*`
- Rate limiting: 100 req/min per IP

## Observability
- Metrics: Prometheus + Grafana
- Tracing: OpenTelemetry → Jaeger
- Logs: JSON → Loki
```

---

## Validation Checklist (CI Gate)

```yaml
# .github/workflows/ci.yml snippet
jobs:
  validate:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - name: Lint (ruff)
        run: ruff check .
      - name: Format check (ruff)
        run: ruff format --check .
      - name: Type check (mypy)
        run: mypy --strict .
      - name: Test (pytest)
        run: pytest --cov=src --cov-fail-under=80
      - name: Security (bandit)
        run: bandit -r src/
      - name: Dependency check (pip-audit)
        run: pip-audit
      - name: Constitutional AI Critic Check
        run: python -m pytest tests/test_critic_integration.py -v
```

### Critic Integration Tests

- `test_critic_phase_runs_with_dual_model_enabled`
- `test_critic_evaluates_assistant_output`
- `test_critic_prompt_includes_constitution`
- `test_critic_model_config_loads_correctly`
- `test_critic_output_format_valid`