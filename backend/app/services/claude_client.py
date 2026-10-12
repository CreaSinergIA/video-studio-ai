"""Conexión con Claude (Fase 3).

Dos transportes oficiales:

- ``claude_code`` (principal): el CLI de Claude Code que el usuario ya tiene instalado y con
  su sesión iniciada, en modo *headless* documentado (``claude -p``). Se ejecuta **sin
  herramientas** (``--restricted --tools ""``), sin servidores MCP, sin persistir sesiones, en
  un directorio vacío y sin variables de entorno que pudieran cambiar la autenticación (se
  eliminan ``ANTHROPIC_API_KEY``/``ANTHROPIC_AUTH_TOKEN`` para no facturar por API sin
  querer). Consume los límites del plan del usuario; el coste que reporta es una estimación.
- ``api``: Messages API con la clave del usuario guardada en el llavero de macOS. Factura por
  tokens en la Consola de Anthropic.

Claude solo **planifica**: recibe texto e imágenes pequeñas y devuelve JSON validado contra un
esquema. Nunca ejecuta herramientas ni accede a archivos.
"""

from __future__ import annotations

import base64
import contextlib
import json
import logging
import os
import shutil
import subprocess
import tempfile
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from app import edition
from app.domain.preferences import ClaudePreferences
from app.platform import processes
from app.services.media_tools import Cancelled

log = logging.getLogger(__name__)

KEYCHAIN_SERVICE = edition.KEYCHAIN_SERVICE  # propio de esta edición: nunca lee otra copia
KEYCHAIN_ACCOUNT = "anthropic-api-key"
# Única herramienta que Claude Code añade para la salida estructurada (interna, sin efectos).
ALLOWED_INTERNAL_TOOLS = {"StructuredOutput"}
# Variables que podrían cambiar la autenticación o el proveedor del CLI.
_STRIP_ENV_PREFIXES = ("CLAUDECODE", "CLAUDE_CODE_", "CLAUDE_EFFORT", "CLAUDE_PID")
_STRIP_ENV = {
    "ANTHROPIC_API_KEY",
    "ANTHROPIC_AUTH_TOKEN",
    "ANTHROPIC_BASE_URL",
    "ANTHROPIC_MODEL",
    "ANTHROPIC_SMALL_FAST_MODEL",
    "CLAUDE_CODE_USE_BEDROCK",
    "CLAUDE_CODE_USE_VERTEX",
}


class ClaudeError(Exception):
    """Error de conexión o de respuesta. ``code`` es estable; ``message`` se muestra al usuario."""

    def __init__(self, code: str, message: str, *, retryable: bool = False) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.retryable = retryable


@dataclass
class ClaudeResult:
    data: dict[str, Any]
    model_reported: str | None
    usage: dict[str, int | None]
    cost_estimate_usd: float | None
    duration_ms: int | None
    rate_limit: dict[str, Any] | None
    billing: str
    raw_text: str = ""
    extra: dict[str, Any] = field(default_factory=dict)


Block = dict[str, Any]


def text_block(text: str) -> Block:
    return {"type": "text", "text": text}


def image_block(jpeg: bytes) -> Block:
    return {
        "type": "image",
        "source": {
            "type": "base64",
            "media_type": "image/jpeg",
            "data": base64.b64encode(jpeg).decode("ascii"),
        },
    }


# ---------------------------------------------------------------------------
# Claude Code (CLI)
# ---------------------------------------------------------------------------


def cli_transport_allowed() -> bool:
    """El transporte por Claude Code (inicio de sesión de Claude.ai) no se ofrece en la
    Community Edition: Anthropic no permite que aplicaciones de terceros usen la suscripción de
    sus usuarios. Solo se habilita en el entorno de pruebas, con un CLI simulado."""
    return edition.ALLOW_CLAUDE_CODE_TRANSPORT or os.environ.get("VSA_ENV") == "test"


def find_cli(prefs: ClaudePreferences) -> Path | None:
    # Sin transporte por CLI no se busca ni se ejecuta ningún binario: la ruta configurable
    # no puede convertirse en una forma de ejecutar programas arbitrarios.
    if not cli_transport_allowed():
        return None
    if prefs.cli_path:
        p = Path(prefs.cli_path).expanduser()
        return p if p.is_file() and os.access(p, os.X_OK) else None
    found = shutil.which("claude")
    if found:
        return Path(found)
    home = Path.home()
    for candidate in (
        home / ".local/bin/claude",
        home / ".claude/local/claude",
        Path("/opt/homebrew/bin/claude"),
        Path("/usr/local/bin/claude"),
    ):
        if candidate.is_file() and os.access(candidate, os.X_OK):
            return candidate
    return None


def clean_env() -> dict[str, str]:
    env = {
        k: v
        for k, v in os.environ.items()
        if k not in _STRIP_ENV and not k.startswith(_STRIP_ENV_PREFIXES)
    }
    env["NO_COLOR"] = "1"
    return env


def cli_status(prefs: ClaudePreferences, timeout: float = 20) -> dict[str, Any]:
    """Estado local del CLI sin enviar ninguna solicitud al modelo (no consume cuota)."""
    cli = find_cli(prefs)
    if cli is None:
        return {
            "installed": False,
            "logged_in": False,
            "message": "No se encontró Claude Code en este equipo.",
        }
    out: dict[str, Any] = {"installed": True, "cli_path": str(cli)}
    try:
        version = subprocess.run(
            [str(cli), "--version"],
            capture_output=True,
            text=True,
            timeout=timeout,
            env=clean_env(),
        )
        out["version"] = version.stdout.strip().split(" ")[0] if version.returncode == 0 else None
        auth = subprocess.run(
            [str(cli), "auth", "status"],
            capture_output=True,
            text=True,
            timeout=timeout,
            env=clean_env(),
        )
        info = json.loads(auth.stdout) if auth.stdout.strip().startswith("{") else {}
    except (OSError, subprocess.TimeoutExpired, json.JSONDecodeError) as exc:
        out.update(logged_in=False, message=f"No se pudo consultar Claude Code: {exc}")
        return out
    out.update(
        logged_in=bool(info.get("loggedIn")),
        auth_method=info.get("authMethod"),
        api_provider=info.get("apiProvider"),
        subscription=info.get("subscriptionType"),
    )
    if not out["logged_in"]:
        out["message"] = "Claude Code no tiene una sesión iniciada."
    elif info.get("apiProvider") not in (None, "firstParty"):
        out["message"] = "Claude Code está configurado con un proveedor externo (Bedrock/Vertex)."
    return out


def _error_from_result(msg: dict[str, Any]) -> ClaudeError:
    status = msg.get("api_error_status")
    text = str(msg.get("result") or msg.get("error") or "")
    low = text.lower()
    if status in (401, 403) or "login" in low or "authentication" in low or "oauth" in low:
        return ClaudeError(
            "not_authenticated",
            "Claude Code no tiene una sesión válida. Inicia sesión de nuevo desde Ajustes.",
        )
    if status == 429 or "usage limit" in low or "rate limit" in low or "rate_limit" in low:
        return ClaudeError(
            "rate_limited",
            "Se alcanzó el límite de uso de tu plan. Vuelve a intentarlo cuando se restablezca.",
        )
    if status == 529 or "overloaded" in low:
        return ClaudeError("overloaded", "Claude está saturado en este momento.", retryable=True)
    if status == 404 or ("model" in low and ("not found" in low or "not_found" in low)):
        return ClaudeError("model_not_found", f"Modelo no disponible: {text[:200]}")
    if msg.get("subtype") == "error_max_budget_usd" or "budget" in low:
        return ClaudeError(
            "budget_exceeded", "La solicitud superó el tope de coste estimado configurado."
        )
    if status is not None and int(status) >= 500:
        return ClaudeError("server_error", f"Error del servicio ({status}).", retryable=True)
    return ClaudeError(
        "claude_error", f"Claude devolvió un error: {text[:300] or msg.get('subtype')}"
    )


def _usage(u: dict[str, Any] | None) -> dict[str, int | None]:
    u = u or {}
    return {
        "input_tokens": u.get("input_tokens"),
        "output_tokens": u.get("output_tokens"),
        "cache_creation_tokens": u.get("cache_creation_input_tokens"),
        "cache_read_tokens": u.get("cache_read_input_tokens"),
    }


def run_claude_code(
    prefs: ClaudePreferences,
    system: str,
    blocks: list[Block],
    schema: dict[str, Any],
    *,
    cancel: threading.Event | None = None,
    on_event: Callable[[str], None] | None = None,
    model: str | None = None,
) -> ClaudeResult:
    cli = find_cli(prefs)
    if cli is None:
        raise ClaudeError("not_installed", "No se encontró Claude Code en este equipo.")
    cmd = [
        str(cli),
        "-p",
        "--model",
        model or prefs.model,
        "--effort",
        prefs.effort,
        "--restricted",
        # Sin personalizaciones del usuario (CLAUDE.md, plugins, hooks, MCP, agentes, skills);
        # la autenticación funciona igual.
        "--safe-mode",
        "--tools",
        "",
        "--strict-mcp-config",
        "--disable-slash-commands",
        "--no-session-persistence",
        "--system-prompt",
        system,
        "--input-format",
        "stream-json",
        "--output-format",
        "stream-json",
        "--verbose",
        "--json-schema",
        json.dumps(schema, ensure_ascii=False),
        "--max-budget-usd",
        f"{prefs.max_budget_usd_per_call:.2f}",
    ]
    message = {"type": "user", "message": {"role": "user", "content": blocks}}
    workdir = Path(tempfile.mkdtemp(prefix="vsa-claude-"))
    started = time.monotonic()
    try:
        proc = subprocess.Popen(
            cmd,
            cwd=workdir,
            env=clean_env(),
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            **processes.group_kwargs(),  # para poder terminar el árbol completo al cancelar
        )
    except OSError as exc:
        shutil.rmtree(workdir, ignore_errors=True)
        raise ClaudeError("not_installed", f"No se pudo ejecutar Claude Code: {exc}") from exc

    killed: dict[str, str] = {}

    def _kill(reason: str) -> None:
        killed.setdefault("reason", reason)
        processes.terminate_tree(proc, grace=3)

    def _watch() -> None:
        while proc.poll() is None:
            if cancel is not None and cancel.is_set():
                _kill("cancelled")
                return
            if time.monotonic() - started > prefs.timeout_seconds:
                _kill("timeout")
                return
            time.sleep(0.2)

    stderr_tail: list[str] = []

    def _drain() -> None:
        assert proc.stderr is not None
        for line in proc.stderr:
            stderr_tail.append(line.rstrip())
            del stderr_tail[:-20]

    threading.Thread(target=_watch, daemon=True).start()
    threading.Thread(target=_drain, daemon=True).start()
    try:
        assert proc.stdin is not None
        proc.stdin.write(json.dumps(message, ensure_ascii=False) + "\n")
        proc.stdin.close()
    except (BrokenPipeError, OSError):
        pass

    init: dict[str, Any] = {}
    result: dict[str, Any] | None = None
    rate_limit: dict[str, Any] | None = None
    assert proc.stdout is not None
    try:
        for line in proc.stdout:
            try:
                msg = json.loads(line)
            except json.JSONDecodeError:
                continue
            kind = msg.get("type")
            if kind == "system" and msg.get("subtype") == "init":
                init = msg
                tools = set(msg.get("tools") or [])
                if tools - ALLOWED_INTERNAL_TOOLS or msg.get("mcp_servers"):
                    # Defensa en profundidad: nunca planificar con herramientas activas.
                    _kill("unsafe")
                    break
                if msg.get("apiKeySource") not in (None, "none"):
                    # La ruta de suscripción nunca debe facturar con una clave de API.
                    _kill("api_key")
                    break
                if on_event:
                    on_event("connected")
            elif kind == "assistant":
                if on_event:
                    on_event("responding")
            elif kind == "rate_limit_event":
                rate_limit = msg.get("rate_limit_info")
            elif kind == "result":
                result = msg
        proc.wait()
    finally:
        if proc.poll() is None:
            _kill("cleanup")
        shutil.rmtree(workdir, ignore_errors=True)

    if result is not None and not init and not killed:
        killed["reason"] = "unsafe"  # sin evento de arranque no se puede verificar el aislamiento
    reason = killed.get("reason")
    if reason == "api_key":
        raise ClaudeError(
            "unexpected_auth",
            "Claude Code se autenticó con una clave de API en lugar de tu sesión; se canceló "
            "para no generar cargos. Revisa la configuración de Claude Code.",
        )
    if reason == "cancelled":
        raise Cancelled()
    if reason == "timeout":
        raise ClaudeError(
            "timeout", f"Claude no respondió en {prefs.timeout_seconds} s.", retryable=True
        )
    if reason == "unsafe":
        raise ClaudeError(
            "unsafe_config",
            "Claude Code arrancó con herramientas o servidores MCP activos; se canceló por "
            "seguridad.",
        )
    if result is None:
        tail = " ".join(stderr_tail[-3:])[:300]
        raise ClaudeError("claude_error", f"Claude Code terminó sin respuesta. {tail}".strip())
    if result.get("is_error") or result.get("subtype") != "success":
        raise _error_from_result(result)
    data = result.get("structured_output")
    if not isinstance(data, dict):
        raise ClaudeError("invalid_output", "Claude no devolvió datos estructurados válidos.")
    model_usage = result.get("modelUsage") or {}
    reported = next(iter(model_usage), None) or init.get("model")
    return ClaudeResult(
        data=data,
        model_reported=reported,
        usage=_usage(result.get("usage")),
        cost_estimate_usd=result.get("total_cost_usd"),
        duration_ms=result.get("duration_ms"),
        rate_limit=rate_limit,
        billing="subscription" if init.get("apiKeySource") in (None, "none") else "api",
        raw_text=str(result.get("result") or "")[:2000],
        extra={
            "api_key_source": init.get("apiKeySource"),
            "cli_version": init.get("claude_code_version"),
        },
    )


# ---------------------------------------------------------------------------
# Messages API (alternativa con clave)
# ---------------------------------------------------------------------------


def keychain_get() -> str | None:
    try:
        out = subprocess.run(
            [
                "security",
                "find-generic-password",
                "-s",
                KEYCHAIN_SERVICE,
                "-a",
                KEYCHAIN_ACCOUNT,
                "-w",
            ],
            capture_output=True,
            text=True,
            timeout=10,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    key = out.stdout.strip()
    return key if out.returncode == 0 and key else None


def keychain_has_key() -> bool:
    """Comprueba si hay clave guardada sin leer el secreto."""
    try:
        out = subprocess.run(
            ["security", "find-generic-password", "-s", KEYCHAIN_SERVICE, "-a", KEYCHAIN_ACCOUNT],
            capture_output=True,
            timeout=10,
        )
    except (OSError, subprocess.TimeoutExpired):
        return False
    return out.returncode == 0


def keychain_set(key: str) -> None:
    # La clave viaja por stdin (modo interactivo de `security`), nunca como argumento visible
    # en la lista de procesos. Su formato ya está validado: sin espacios ni comillas.
    if not key.replace("-", "").replace("_", "").isalnum():
        raise ClaudeError("invalid_key", "Formato de clave no válido.")
    command = f"add-generic-password -U -s {KEYCHAIN_SERVICE} -a {KEYCHAIN_ACCOUNT} -w {key}\n"
    try:
        out = subprocess.run(
            ["security", "-i"], input=command, capture_output=True, text=True, timeout=10
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        # Sin la herramienta `security` (p. ej. Windows): error claro en lugar de un 500.
        raise ClaudeError(
            "keychain_unavailable", "El llavero del sistema no está disponible en este equipo."
        ) from exc
    if out.returncode != 0:
        raise ClaudeError("keychain", "No se pudo guardar la clave en el llavero de macOS.")


def keychain_delete() -> None:
    try:
        subprocess.run(
            ["security", "delete-generic-password", "-s", KEYCHAIN_SERVICE, "-a", KEYCHAIN_ACCOUNT],
            capture_output=True,
            timeout=10,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise ClaudeError(
            "keychain_unavailable", "El llavero del sistema no está disponible en este equipo."
        ) from exc


def api_schema(schema: dict[str, Any]) -> dict[str, Any]:
    """Esquema compatible con las salidas estructuradas de la API (sin restricciones
    numéricas ni de longitud, que la API no admite; el backend las valida después)."""
    drop = {
        "maxLength",
        "minLength",
        "maxItems",
        "minItems",
        "minimum",
        "maximum",
        "exclusiveMinimum",
        "exclusiveMaximum",
        "default",
        "title",
    }

    def walk(node: Any) -> Any:
        if isinstance(node, dict):
            return {k: walk(v) for k, v in node.items() if k not in drop}
        if isinstance(node, list):
            return [walk(v) for v in node]
        return node

    return walk(schema)


def _api_error(exc: Exception) -> ClaudeError:
    import anthropic

    if isinstance(exc, anthropic.AuthenticationError):
        return ClaudeError("not_authenticated", "La clave de API no es válida.")
    if isinstance(exc, anthropic.PermissionDeniedError):
        return ClaudeError("forbidden", f"Permiso denegado: {exc.message}")
    if isinstance(exc, anthropic.NotFoundError):
        return ClaudeError("model_not_found", f"Modelo no disponible: {exc.message}")
    if isinstance(exc, anthropic.RateLimitError):
        return ClaudeError("rate_limited", "Límite de la API alcanzado.", retryable=True)
    if isinstance(exc, anthropic.APIStatusError):
        return ClaudeError(
            "server_error",
            f"Error de la API ({exc.status_code}).",
            retryable=exc.status_code >= 500,
        )
    if isinstance(exc, anthropic.APIConnectionError):
        return ClaudeError("network", "Sin conexión con la API de Anthropic.", retryable=True)
    return ClaudeError("claude_error", f"Error de la API: {type(exc).__name__}")


def run_api(
    prefs: ClaudePreferences,
    system: str,
    blocks: list[Block],
    schema: dict[str, Any],
    *,
    cancel: threading.Event | None = None,
    on_event: Callable[[str], None] | None = None,
    model: str | None = None,
) -> ClaudeResult:
    import anthropic

    key = keychain_get()
    if not key:
        raise ClaudeError("not_authenticated", "No hay una clave de API guardada.")
    client = anthropic.Anthropic(api_key=key, timeout=prefs.timeout_seconds, max_retries=0)
    started = time.monotonic()
    text = ""
    stop = threading.Event()
    aborted: dict[str, str] = {}
    try:
        with client.messages.stream(
            model=model or prefs.model,
            max_tokens=32000,
            system=system,
            messages=[{"role": "user", "content": blocks}],  # type: ignore[typeddict-item]
            extra_body={
                "output_config": {
                    "effort": prefs.effort,
                    "format": {"type": "json_schema", "schema": api_schema(schema)},
                }
            },
        ) as stream:

            def _watch() -> None:
                # Cancelación y tiempo total efectivos aunque aún no haya llegado ningún token.
                while not stop.wait(0.2):
                    if cancel is not None and cancel.is_set():
                        aborted["reason"] = "cancelled"
                    elif time.monotonic() - started > prefs.timeout_seconds:
                        aborted["reason"] = "timeout"
                    else:
                        continue
                    with contextlib.suppress(Exception):
                        stream.close()
                    return

            threading.Thread(target=_watch, daemon=True).start()
            if on_event:
                on_event("connected")
            for chunk in stream.text_stream:
                text += chunk
                if on_event:
                    on_event("responding")
            final = stream.get_final_message()
    except Exception as exc:
        if aborted.get("reason") == "cancelled":
            raise Cancelled() from exc
        if aborted.get("reason") == "timeout":
            raise ClaudeError(
                "timeout", f"Claude no respondió en {prefs.timeout_seconds} s.", retryable=True
            ) from exc
        raise _api_error(exc) from exc
    finally:
        stop.set()
    if aborted.get("reason") == "cancelled":
        raise Cancelled()
    try:
        data = json.loads(text)
    except json.JSONDecodeError as exc:
        raise ClaudeError("invalid_output", "La respuesta no es JSON válido.") from exc
    usage = final.usage
    return ClaudeResult(
        data=data,
        model_reported=final.model,
        usage={
            "input_tokens": usage.input_tokens,
            "output_tokens": usage.output_tokens,
            "cache_creation_tokens": usage.cache_creation_input_tokens,
            "cache_read_tokens": usage.cache_read_input_tokens,
        },
        cost_estimate_usd=None,  # la API no informa del coste; consultar la Consola
        duration_ms=int((time.monotonic() - started) * 1000),
        rate_limit=None,
        billing="api",
        raw_text=text[:2000],
    )


def run(
    prefs: ClaudePreferences,
    system: str,
    blocks: list[Block],
    schema: dict[str, Any],
    *,
    cancel: threading.Event | None = None,
    on_event: Callable[[str], None] | None = None,
    model: str | None = None,
) -> ClaudeResult:
    if prefs.transport != "api" and not cli_transport_allowed():
        raise ClaudeError(
            "transport_unavailable",
            "Esta edición se conecta a Claude con tu propia clave de API de Anthropic "
            "(Ajustes → Claude).",
        )
    fn = run_api if prefs.transport == "api" else run_claude_code
    return fn(prefs, system, blocks, schema, cancel=cancel, on_event=on_event, model=model)
