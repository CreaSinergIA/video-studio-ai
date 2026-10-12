"""Community Edition — Fase 2: instalación local multiplataforma.

Cubre la sesión de la API local, la primera configuración, el almacén de credenciales (macOS y
Windows/Linux con un llavero en memoria), Claude por la API con un servidor SIMULADO (sin red ni
cargos), faster-whisper, los límites de recursos, el vigilante de FFmpeg, los procesos huérfanos,
el bloqueo de instancia, el lanzador y las herramientas portátiles.

Lo que depende de Windows se prueba con adaptadores simulados; la validación en un equipo
Windows real está pendiente y se documenta en docs/WINDOWS-VALIDATION.md.
"""

from __future__ import annotations

import io
import json
import os
import shutil
import socket
import subprocess
import sys
import threading
import time
import zipfile
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from tests.conftest import FFMPEG, TEST_TOKEN, configure, make_client, upload, wait_idle
from tests.test_phase3 import fake_cli  # noqa: F401  (fixture del CLI simulado)
from tests.test_phase4 import engine_home  # noqa: F401  (fixture del render real)

BACKEND = Path(__file__).resolve().parents[1]
ROOT = BACKEND.parent


# ---------------------------------------------------------------------------
# Sesión de la API local
# ---------------------------------------------------------------------------


def test_api_requires_session_token(app_home: Path) -> None:
    with make_client(authenticated=False) as anon:
        r = anon.get("/api/projects")
        assert r.status_code == 401 and r.json()["code"] == "session_required"
        # Con la cabecera CSRF pero sin token, tampoco se puede modificar nada.
        assert anon.post("/api/system/backups").status_code == 401
        h = anon.get("/api/health").json()  # pública: solo identificación
        assert h["ok"] and h["edition"] == "community" and len(h["instance"]) == 16
        assert anon.get("/api/projects", headers={"x-vsa-token": "otro"}).status_code == 401
        assert anon.get("/api/projects", headers={"x-vsa-token": TEST_TOKEN}).status_code == 200
        # Documentación interactiva desactivada (cargaría recursos de un CDN).
        assert anon.get("/api/docs", headers={"x-vsa-token": TEST_TOKEN}).status_code == 404


def test_open_exchanges_token_for_httponly_cookie(app_home: Path) -> None:
    with make_client(authenticated=False) as anon:
        bad = anon.get("/open", params={"t": "malo"}, follow_redirects=False)
        assert bad.status_code == 303 and bad.headers["location"] == "/?session=invalid"
        r = anon.get("/open", params={"t": TEST_TOKEN}, follow_redirects=False)
        assert r.status_code == 303 and r.headers["location"] == "/"
        cookie = r.headers["set-cookie"].lower()
        assert "httponly" in cookie and "samesite=strict" in cookie and "path=/" in cookie
        assert anon.get("/api/projects").status_code == 200  # la cookie basta


def test_token_file_is_private_and_stable(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from app import session

    monkeypatch.delenv("VSA_SESSION_TOKEN", raising=False)
    token = session.ensure_token(tmp_path)
    assert len(token) >= 40 and session.ensure_token(tmp_path) == token
    if os.name != "nt":
        assert (session.token_path(tmp_path).stat().st_mode & 0o777) == 0o600
    assert session.read_token(tmp_path) == token


# ---------------------------------------------------------------------------
# Primera configuración
# ---------------------------------------------------------------------------


def test_setup_status_and_completion(client: TestClient, disk: Path) -> None:
    st = client.get("/api/setup/status").json()
    ids = {c["id"] for c in st["checks"]}
    assert {"platform", "resources", "ffmpeg", "node", "remotion", "transcription", "claude"} <= ids
    assert st["completed_at"] is None and st["storage_configured"] is False
    ffmpeg = next(c for c in st["checks"] if c["id"] == "ffmpeg")
    assert ffmpeg["status"] == "ok"  # FFmpeg del equipo de pruebas
    configure(client, disk)
    assert client.get("/api/setup/status").json()["storage_configured"] is True
    done = client.post("/api/setup/complete", json={"completed": True}).json()
    assert done["completed_at"]
    assert client.get("/api/setup/status").json()["completed_at"] == done["completed_at"]
    client.post("/api/setup/complete", json={"completed": False})  # «Repetir la configuración»
    assert client.get("/api/setup/status").json()["completed_at"] is None


# ---------------------------------------------------------------------------
# Credenciales
# ---------------------------------------------------------------------------


def test_test_environment_never_touches_the_real_keychain(app_home: Path) -> None:
    from app.platform import credentials

    store = credentials.store()
    assert isinstance(store, credentials.TestFileStore)
    store.set("sk-ant-test-abc_DEF-123")
    assert store.has() and store.get() == "sk-ant-test-abc_DEF-123"
    assert (app_home / "test-credentials.json").is_file()
    store.delete()
    assert not store.has()
    with pytest.raises(credentials.CredentialError):
        store.set("clave con espacios")


@pytest.fixture
def memory_keyring(monkeypatch: pytest.MonkeyPatch):
    import keyring
    from keyring.backend import KeyringBackend

    class Memory(KeyringBackend):
        priority = 1  # type: ignore[assignment]

        def __init__(self) -> None:
            super().__init__()
            self.data: dict[tuple[str, str], str] = {}

        def get_password(self, service: str, username: str) -> str | None:
            return self.data.get((service, username))

        def set_password(self, service: str, username: str, password: str) -> None:
            self.data[(service, username)] = password

        def delete_password(self, service: str, username: str) -> None:
            self.data.pop((service, username), None)

    previous = keyring.get_keyring()
    backend = Memory()
    keyring.set_keyring(backend)
    yield backend
    keyring.set_keyring(previous)


def test_windows_credential_manager_adapter(
    monkeypatch: pytest.MonkeyPatch, memory_keyring: Any
) -> None:
    """En Windows la clave va al Administrador de credenciales (keyring → WinVault). Aquí se
    simula el sistema y el llavero: valida el adaptador, no la integración real con Windows."""
    from app.platform import credentials

    monkeypatch.setenv("VSA_ENV", "user")
    monkeypatch.setattr(credentials, "os_id", lambda: "windows")
    store = credentials.store()
    assert isinstance(store, credentials.KeyringStore)
    assert "Administrador de credenciales" in store.label
    assert not store.has()
    store.set("sk-ant-test-ABCdef_123-xyz")
    assert memory_keyring.data == {
        ("VideoStudioAI-Community", "anthropic-api-key"): "sk-ant-test-ABCdef_123-xyz"
    }
    assert store.get() == "sk-ant-test-ABCdef_123-xyz"
    store.delete()
    assert store.get() is None


def test_missing_os_keyring_gives_a_clear_error(monkeypatch: pytest.MonkeyPatch) -> None:
    import keyring
    from keyring.backends import fail

    from app.platform import credentials

    previous = keyring.get_keyring()
    keyring.set_keyring(fail.Keyring())
    try:
        monkeypatch.setenv("VSA_ENV", "user")
        monkeypatch.setattr(credentials, "os_id", lambda: "linux")
        with pytest.raises(credentials.CredentialError) as exc:
            credentials.store().set("sk-ant-test-x1234567890")
        assert exc.value.code == "keychain_unavailable"
    finally:
        keyring.set_keyring(previous)


@pytest.mark.skipif(
    sys.platform != "darwin" or os.environ.get("VSA_TEST_REAL_KEYCHAIN") != "1",
    reason="Llavero real de macOS: VSA_TEST_REAL_KEYCHAIN=1 (usa el servicio «-test» y lo borra)",
)
def test_real_macos_keychain_roundtrip(monkeypatch: pytest.MonkeyPatch) -> None:
    from app.platform import credentials

    monkeypatch.setenv("VSA_ENV", "test")
    store = credentials.store()
    assert isinstance(store, credentials.MacKeychain)
    try:
        store.set("sk-ant-test-keychain-roundtrip-123")
        assert store.has() and store.get() == "sk-ant-test-keychain-roundtrip-123"
    finally:
        store.delete()
    assert not store.has()


# ---------------------------------------------------------------------------
# Claude por la API (servidor SIMULADO: sin red ni cargos)
# ---------------------------------------------------------------------------


@pytest.fixture
def fake_api(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    from tests.fake_anthropic import serve

    server, url = serve()
    log = tmp_path / "anthropic.jsonl"
    monkeypatch.setenv("VSA_TEST_ANTHROPIC_BASE_URL", url)
    monkeypatch.setenv("FAKE_ANTHROPIC_LOG", str(log))
    yield {"url": url, "log": log}
    server.shutdown()


def _log(path: Path) -> list[dict[str, Any]]:
    return [json.loads(x) for x in path.read_text().splitlines()] if path.exists() else []


def test_api_key_flow_verify_is_free_and_errors_are_clear(client: TestClient, fake_api) -> None:
    st = client.get("/api/claude/status").json()
    assert st["transport"] == "api" and st["api_key_saved"] is False and st["ready"] is False
    assert st["pricing"]["usd_per_mtok"] == {
        "input": 4.0,
        "output": 20.0,
        "cache_write": 5.0,
        "cache_read": 0.2,
    }
    assert client.post("/api/claude/verify-key").json()["code"] == "not_authenticated"
    # Formato inválido: rechazado antes de llegar al llavero.
    assert (
        client.put("/api/claude/api-key", json={"key": "no-es-una-clave-valida-000"}).status_code
        == 422
    )
    assert (
        client.put("/api/claude/api-key", json={"key": "sk-ant-test-valida-0123456789"}).status_code
        == 204
    )
    st = client.get("/api/claude/status").json()
    assert st["api_key_saved"] is True and st["ready"] is True and st["verified"] is False
    r = client.post("/api/claude/verify-key").json()
    assert r["ok"] is True and r["model"] == "claude-opus-5-5"
    calls = _log(fake_api["log"])
    assert [c["method"] for c in calls] == [
        "GET"
    ]  # solo la API de modelos: ninguna solicitud al modelo
    assert client.get("/api/claude/usage").json()["requests"] == 0  # no cuenta como solicitud
    client.put("/api/claude/api-key", json={"key": "sk-ant-test-revoked-0123456789"})
    r = client.post("/api/claude/verify-key").json()
    assert r["ok"] is False and r["code"] == "not_authenticated" and "API Keys" in r["error"]
    client.put("/api/claude/api-key", json={"key": "sk-ant-test-nocredit-0123456789"})
    r = client.post("/api/claude/test").json()
    assert r["ok"] is False and r["code"] == "no_credit" and "Billing" in r["error"]
    # Eliminar la clave: estado limpio.
    assert client.delete("/api/claude/api-key").status_code == 204
    st = client.get("/api/claude/status").json()
    assert st["api_key_saved"] is False and st["last_check"] is None


def test_api_transport_end_to_end_with_cost_estimate(
    client: TestClient, disk: Path, media, fake_api
) -> None:
    from tests.test_phase3 import _generate, _project

    client.put("/api/claude/api-key", json={"key": "sk-ant-test-valida-0123456789"})
    test = client.post("/api/claude/test").json()
    assert test["ok"] is True and test["billing"] == "api"
    # 1200 tokens de entrada × 4 USD/M + 800 de salida × 20 USD/M
    assert abs(test["cost_estimate_usd"] - (1200 * 4 + 800 * 20) / 1e6) < 1e-9
    pid, _ = _project(client, disk, media)
    st = _generate(client, pid, style="motion_tech")
    plan = st["plan"]
    assert plan is not None and plan["document"]["style"] == "motion_tech"
    assert len(plan["document"]["interventions"]) >= 2
    posts = [c for c in _log(fake_api["log"]) if c["method"] == "POST"]
    assert posts[-1]["model"] == "claude-opus-5-5" and posts[-1]["effort"] == "medium"
    assert posts[-1]["images"] >= 1  # fotogramas reducidos, nunca el video
    usage = client.get(f"/api/projects/{pid}/usage").json()
    assert usage["billing"] == ["api"] and usage["calls"] == 1
    assert usage["cost_estimate_usd"] and usage["cost_estimate_usd"] > 0


def test_api_rate_limit_is_reported_and_counted(client: TestClient, fake_api, monkeypatch) -> None:
    client.put("/api/claude/api-key", json={"key": "sk-ant-test-valida-0123456789"})
    monkeypatch.setenv("FAKE_ANTHROPIC_MODE", "rate_limit")
    r = client.post("/api/claude/test").json()
    assert r["ok"] is False and r["code"] == "rate_limited" and "límite" in r["error"].lower()
    assert client.get("/api/claude/usage").json()["requests"] == 1  # llegó a Claude: cuenta


# ---------------------------------------------------------------------------
# Transcripción: motores por plataforma
# ---------------------------------------------------------------------------


def test_engine_selection_by_platform(monkeypatch: pytest.MonkeyPatch) -> None:
    from app.platform import transcription
    from app.services import asr_models

    engines = {e.id: e for e in transcription.engines()}
    assert engines["faster-whisper"].implemented and engines["mlx-whisper"].implemented
    if transcription.detect().apple_silicon:
        assert transcription.active().id == "mlx-whisper"  # type: ignore[union-attr]
        assert asr_models.default_model_id() == "large-v3-turbo"
        assert "fw-small" not in asr_models.available_ids()
    monkeypatch.setenv("VSA_ASR_ENGINES", "faster-whisper")
    assert transcription.active().id == "faster-whisper"  # type: ignore[union-attr]
    assert asr_models.default_model_id() == "fw-large-v3-turbo"
    assert set(asr_models.available_ids()) == {"fw-large-v3-turbo", "fw-small"}
    with pytest.raises(asr_models.ModelError) as exc:
        asr_models.require_usable("large-v3-turbo")
    assert exc.value.code == "engine_unavailable"
    # Sin GPU NVIDIA: CPU INT8 (nunca se exige NVIDIA).
    monkeypatch.setattr(transcription, "cuda_devices", lambda: 0)
    assert transcription.preferred_device() == ("cpu", "int8")
    monkeypatch.setattr(transcription, "cuda_devices", lambda: 1)
    assert transcription.preferred_device() == ("cuda", "float16")
    monkeypatch.setenv("VSA_ASR_DEVICE", "cpu")
    assert transcription.preferred_device() == ("cpu", "int8")


def test_default_model_follows_the_platform(client: TestClient, monkeypatch) -> None:
    from app.services import asr_models

    prefs = client.get("/api/settings/analysis").json()
    assert prefs["transcription_model"] == asr_models.default_model_id()
    models = client.get("/api/asr/models").json()
    assert {m["id"] for m in models["models"]} == set(asr_models.available_ids())
    assert all(m["engine"] for m in models["models"]) and models["engines"]
    # Una base traída de otro sistema con un modelo de un motor ausente: se usa el recomendado.
    monkeypatch.setenv("VSA_ASR_ENGINES", "faster-whisper")
    assert client.get("/api/settings/analysis").json()["transcription_model"] == "fw-large-v3-turbo"
    bad = {**prefs, "transcription_model": "large-v3-turbo"}
    assert client.put("/api/settings/analysis", json=bad).status_code == 409


def _fw_models_dir() -> Path | None:
    raw = os.environ.get("VSA_TEST_FW_MODELS")
    return (
        Path(raw) if raw and (Path(raw) / "asr" / "fw-small" / "vsa-model.json").is_file() else None
    )


@pytest.mark.skipif(
    _fw_models_dir() is None, reason="Define VSA_TEST_FW_MODELS con fw-small descargado"
)
@pytest.mark.skipif(
    shutil.which("say") is None, reason="Voz sintética de macOS (say) no disponible"
)
def test_faster_whisper_transcribes_and_realigns_through_the_api(
    client: TestClient, disk: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """El motor de Windows (faster-whisper, CPU INT8), ejecutado de verdad en este equipo."""
    monkeypatch.setenv("VSA_ASR_ENGINES", "faster-whisper")
    monkeypatch.setenv("VSA_MODELS_DIR", str(_fw_models_dir()))
    from app.config import get_settings

    get_settings.cache_clear()
    wav = tmp_path / "voz.wav"
    subprocess.run(
        ["say", "-v", "Eddy (Español (España))", "-o", str(wav), "--file-format=WAVE",
         "--data-format=LEI16@16000", "Hola a todos, bienvenidos al programa. Hoy hablamos de edición."],
        check=True,
    )  # fmt: skip
    video = tmp_path / "voz fw.mp4"
    subprocess.run(
        [FFMPEG, "-hide_banner", "-loglevel", "error", "-y", "-f", "lavfi", "-i",
         "testsrc2=s=360x640:r=25:d=6", "-i", str(wav), "-c:v", "libx264", "-pix_fmt", "yuv420p",
         "-c:a", "aac", "-shortest", str(video)],
        check=True,
    )  # fmt: skip
    configure(client, disk)
    prefs = client.get("/api/settings/analysis").json()
    assert (
        client.put(
            "/api/settings/analysis", json={**prefs, "transcription_model": "fw-small"}
        ).status_code
        == 200
    )
    res = upload(client, video)
    assert res.status_code == 201, res.text
    wait_idle()
    pid = res.json()["project"]["id"]
    r = client.post(f"/api/projects/{pid}/analyze", json={"transcribe": True, "visual": False})
    assert r.status_code == 202, r.text
    wait_idle(300)
    t = client.get(f"/api/projects/{pid}/analysis").json()["transcript"]
    assert t["engine"] == "faster-whisper" and t["model"] == "fw-small" and t["language"] == "es"
    text = " ".join(s["text"] for s in t["segments"]).lower()
    assert "bienvenidos" in text and "programa" in text
    assert t["stats"]["device"]["value"] == "cpu"
    words = [w for s in t["segments"] for w in s["words"]]
    assert all(0 <= w["start"] <= w["end"] <= 6.5 for w in words)


# ---------------------------------------------------------------------------
# Límites de recursos
# ---------------------------------------------------------------------------


def _probe(width: int, height: int, duration: float, fps: str = "30/1") -> dict[str, Any]:
    return {
        "format": {"format_name": "mov,mp4,m4a,3gp,3g2,mj2", "duration": str(duration), "tags": {}},
        "streams": [
            {"codec_type": "video", "codec_name": "h264", "width": width, "height": height,
             "avg_frame_rate": fps, "pix_fmt": "yuv420p"},
        ],
    }  # fmt: skip


def test_resource_limits_on_import() -> None:
    from app.services.media_probe import MediaValidationError, parse_probe

    assert parse_probe(_probe(7680, 4320, 60), "8k.mp4").width == 7680  # 8K admitido
    assert parse_probe(_probe(4320, 7680, 60), "8k vertical.mp4").height == 7680
    for data, code in (
        (_probe(15360, 8640, 60), "too_large"),
        (_probe(1920, 1080, 4 * 3600), "too_long"),
        (_probe(1920, 1080, 60, "480/1"), "too_many_fps"),
    ):
        with pytest.raises(MediaValidationError) as exc:
            parse_probe(data, "x.mp4")
        assert exc.value.code == code


def test_editable_texts_are_bounded() -> None:
    from annotated_types import MaxLen

    from app.domain.edit_plan import PlanIntervention

    limits = {
        name: next(m.max_length for m in field.metadata if isinstance(m, MaxLen))
        for name, field in PlanIntervention.model_fields.items()
        if any(isinstance(m, MaxLen) for m in field.metadata)
    }
    assert limits["goal"] == 400 and limits["visual_description"] == 1200
    assert limits["rationale"] == 800 and limits["user_note"] == 1000


# ---------------------------------------------------------------------------
# FFmpeg: vigilante (bloqueo, tiempo máximo, cancelación)
# ---------------------------------------------------------------------------


def _live_children() -> list[int]:
    import psutil

    return [
        p.pid
        for p in psutil.Process().children(recursive=True)
        if p.is_running() and p.status() != psutil.STATUS_ZOMBIE
    ]


def test_ffmpeg_timeout_kills_the_process(tmp_path: Path) -> None:
    from app.services.media_tools import FFmpegError, run_ffmpeg

    started = time.monotonic()
    with pytest.raises(FFmpegError, match="tiempo máximo"):
        run_ffmpeg(
            FFMPEG,
            ["-re", "-f", "lavfi", "-i", "testsrc2=s=64x64:r=10:d=120", "-f", "null", "-"],
            duration=120,
            max_seconds=2,
        )
    assert time.monotonic() - started < 10
    assert not _live_children()


@pytest.mark.skipif(os.name == "nt", reason="Usa una FIFO de POSIX para simular un bloqueo")
def test_ffmpeg_stall_is_detected(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from app import limits
    from app.services.media_tools import FFmpegError, run_ffmpeg

    monkeypatch.setattr(limits, "FFMPEG_STALL_SECONDS", 2)
    fifo = tmp_path / "bloqueo.fifo"
    os.mkfifo(fifo)  # nadie escribe: FFmpeg se queda esperando sin avanzar
    started = time.monotonic()
    with pytest.raises(FFmpegError, match="dejó de avanzar"):
        run_ffmpeg(
            FFMPEG, ["-f", "s16le", "-ar", "16000", "-ac", "1", "-i", str(fifo), "-f", "null", "-"]
        )
    assert time.monotonic() - started < 15
    assert not _live_children()


def test_ffmpeg_cancel_is_immediate(tmp_path: Path) -> None:
    from app.services.media_tools import Cancelled, run_ffmpeg

    cancel = threading.Event()
    threading.Timer(1.0, cancel.set).start()
    started = time.monotonic()
    with pytest.raises(Cancelled):
        run_ffmpeg(
            FFMPEG,
            ["-re", "-f", "lavfi", "-i", "testsrc2=s=64x64:r=10:d=120", "-f", "null", "-"],
            duration=120,
            cancel=cancel,
        )
    assert time.monotonic() - started < 8
    assert not _live_children()


# ---------------------------------------------------------------------------
# Procesos: huérfanos y bloqueo de instancia
# ---------------------------------------------------------------------------


@pytest.mark.skipif(
    os.name == "nt", reason="En Windows lo cubre el Job Object (validación pendiente)"
)
def test_orphans_from_a_crashed_run_are_reaped(tmp_path: Path) -> None:
    import psutil

    from app.platform import processes

    run_dir = tmp_path / "run"
    processes.reap_orphans(run_dir)  # registro nuevo
    child = subprocess.Popen(["sleep", "60"], **processes.group_kwargs())
    processes.track(child)
    registry = json.loads((run_dir / "children.json").read_text())
    assert registry[0]["pid"] == child.pid
    # Un PID reutilizado por otro proceso (otra hora de creación) nunca se toca.
    other = subprocess.Popen(["sleep", "60"])
    (run_dir / "children.json").write_text(
        json.dumps([*registry, {"pid": other.pid, "created": 1.0}])
    )
    # «Reinicio» tras un cierre abrupto: el servidor recoge lo que quedó vivo.
    assert processes.reap_orphans(run_dir) == 1
    child.wait(timeout=5)
    assert child.returncode is not None
    assert psutil.pid_exists(other.pid) and other.poll() is None
    other.kill()
    other.wait()
    assert json.loads((run_dir / "children.json").read_text()) == []


def test_only_one_server_per_data_dir(tmp_path: Path) -> None:
    code = (
        "import sys, time; from pathlib import Path; from app import lifecycle; "
        "ok = lifecycle.acquire_lock(Path(sys.argv[1])); print(ok, flush=True); time.sleep(3)"
    )
    first = subprocess.Popen(
        [sys.executable, "-c", code, str(tmp_path)], cwd=BACKEND, stdout=subprocess.PIPE, text=True
    )
    assert first.stdout is not None and first.stdout.readline().strip() == "True"
    second = subprocess.run(
        [sys.executable, "-c", code.replace("time.sleep(3)", "pass"), str(tmp_path)],
        cwd=BACKEND, capture_output=True, text=True, timeout=30,
    )  # fmt: skip
    assert second.stdout.strip() == "False"
    first.wait(timeout=10)


# ---------------------------------------------------------------------------
# Lanzador: instancia única, puerto ocupado, cierre sin huérfanos, persistencia
# ---------------------------------------------------------------------------


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return int(s.getsockname()[1])


def _launcher(home: Path, *args: str, port: int | None = None) -> subprocess.CompletedProcess[str]:
    env = {
        **os.environ,
        "VSA_HOME": str(home),
        "VSA_NO_BROWSER": "1",
        "VSA_ENV": "test",
        "VSA_FRONTEND_DIST": str(home.parent / "sin-panel"),
        "PYTHONUTF8": "1",
    }
    env.pop("VSA_SESSION_TOKEN", None)
    if port:
        env["VSA_PORT"] = str(port)
    return subprocess.run(
        [sys.executable, "-m", "app.launcher", *args],
        cwd=BACKEND, env=env, capture_output=True, text=True, timeout=180,
    )  # fmt: skip


def test_launcher_lifecycle(tmp_path: Path) -> None:
    home, other = tmp_path / "home", tmp_path / "home2"
    try:
        _launcher_flow(tmp_path, home, other)
    finally:
        # Pase lo que pase, ningún servidor de la prueba queda en marcha.
        for h in (home, other):
            _launcher(h, "stop")


def _launcher_flow(tmp_path: Path, home: Path, other: Path) -> None:
    import psutil

    port = _free_port()
    r = _launcher(home, "start", port=port)
    assert r.returncode == 0, r.stdout + r.stderr
    inst = json.loads((home / "run" / "instance.json").read_text())
    assert inst["port"] == port and psutil.pid_exists(inst["pid"])
    token = (home / "run" / "session.token").read_text().strip()
    # Instancia única: un segundo «start» reutiliza la que está en marcha.
    again = _launcher(home, "start", port=port)
    assert again.returncode == 0 and "Ya está en marcha" in again.stdout
    assert json.loads((home / "run" / "instance.json").read_text())["pid"] == inst["pid"]
    # Puerto ocupado por otro programa (otra instalación): se elige el siguiente libre.
    r2 = _launcher(other, "start", port=port)
    assert r2.returncode == 0, r2.stdout + r2.stderr
    inst2 = json.loads((other / "run" / "instance.json").read_text())
    assert inst2["port"] != port and "ocupado" in r2.stdout
    # Persistencia: un dato creado antes del reinicio sigue después.
    import urllib.request

    def call(method: str, path: str, body: dict | None = None) -> Any:
        req = urllib.request.Request(
            f"http://127.0.0.1:{port}{path}",
            method=method,
            data=json.dumps(body).encode() if body is not None else None,
            headers={"x-vsa-token": token, "x-vsa-client": "1", "content-type": "application/json"},
        )
        with urllib.request.urlopen(req, timeout=10) as resp:
            return json.loads(resp.read() or b"null")

    disk = tmp_path / "disk" / "VideoStudio"
    disk.parent.mkdir()
    call("POST", "/api/storage/configure", {"path": str(disk)})
    created = call("POST", "/api/projects", {"name": "Persistente", "preset_id": None})
    r = _launcher(home, "restart", "--no-browser", port=port)
    assert r.returncode == 0, r.stdout + r.stderr
    assert any(p["id"] == created["id"] for p in call("GET", "/api/projects"))
    pid = json.loads((home / "run" / "instance.json").read_text())["pid"]
    # Cierre ordenado: sin proceso del servidor ni hijos.
    children = [c.pid for c in psutil.Process(pid).children(recursive=True)]
    for h in (home, other):
        stop = _launcher(h, "stop")
        assert stop.returncode == 0 and "Detenido" in stop.stdout
    time.sleep(0.5)
    assert not psutil.pid_exists(pid) or psutil.Process(pid).status() == psutil.STATUS_ZOMBIE
    assert not any(psutil.pid_exists(c) for c in children)
    assert not (home / "run" / "instance.json").exists()
    assert "Detenido" in _launcher(home, "status").stdout


# ---------------------------------------------------------------------------
# Herramientas portátiles y navegador de render
# ---------------------------------------------------------------------------


def test_safe_extract_rejects_path_traversal(tmp_path: Path) -> None:
    from app.platform import tools

    archive = tmp_path / "malo.zip"
    with zipfile.ZipFile(archive, "w") as zf:
        zf.writestr("../fuera.txt", "x")
    with pytest.raises(tools.ToolError):
        tools.safe_extract(archive, tmp_path / "out")
    assert not (tmp_path / "fuera.txt").exists()


def test_portable_tool_install_verifies_sha256(tmp_path: Path, monkeypatch) -> None:
    import hashlib

    from app.platform import tools

    payload = io.BytesIO()
    with zipfile.ZipFile(payload, "w") as zf:
        info = zipfile.ZipInfo("demo/bin/demo")
        info.external_attr = 0o755 << 16
        zf.writestr(info, "#!/bin/sh\necho demo\n")
    data = payload.getvalue()
    served = tmp_path / "srv"
    served.mkdir()
    (served / "demo.zip").write_bytes(data)

    class Quiet(SimpleHTTPRequestHandler):
        def __init__(self, *a: Any, **kw: Any) -> None:
            super().__init__(*a, directory=str(served), **kw)

        def log_message(self, *args: Any) -> None:
            return

    httpd = ThreadingHTTPServer(("127.0.0.1", 0), Quiet)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    url = f"http://127.0.0.1:{httpd.server_address[1]}/demo.zip"
    try:
        good = tools.ToolSpec(
            "demo", "1.0", (tools.Download(url, len(data), hashlib.sha256(data).hexdigest()),),
            {"demo": "demo/bin/demo"}, "MIT",
        )  # fmt: skip
        bad = tools.ToolSpec(
            "demo", "1.0", (tools.Download(url, len(data), "0" * 64),), {"demo": "demo/bin/demo"},
            "MIT",
        )  # fmt: skip
        monkeypatch.setitem(tools.CATALOG, "demo", {tools._platform_key(): bad})
        with pytest.raises(tools.ToolError) as exc:
            tools.install(tmp_path / "home", "demo")
        assert exc.value.code == "checksum"
        assert tools.installed_executable(tmp_path / "home", "demo") is None
        monkeypatch.setitem(tools.CATALOG, "demo", {tools._platform_key(): good})
        exe = tools.install(tmp_path / "home", "demo")
        assert exe.is_file() and tools.installed_executable(tmp_path / "home", "demo") == exe
        if os.name != "nt":
            assert os.access(exe, os.X_OK)
        assert tools.install(tmp_path / "home", "demo") == exe  # idempotente
    finally:
        httpd.shutdown()


def test_portable_ffmpeg_is_preferred(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from app import config
    from app.platform import tools

    fake = tmp_path / "ffmpeg-bin"
    fake.write_text("")
    monkeypatch.delenv("VSA_FFMPEG", raising=False)
    monkeypatch.setattr(
        tools,
        "installed_executable",
        lambda home, name, exe=None: fake if name == "ffmpeg" else None,
    )
    assert config._resolve_binary("ffmpeg", "VSA_FFMPEG", tmp_path) == str(fake)
    monkeypatch.setenv("VSA_FFMPEG", "/explicito/ffmpeg")
    assert config._resolve_binary("ffmpeg", "VSA_FFMPEG", tmp_path) == "/explicito/ffmpeg"


def test_pinned_downloads_cover_mac_and_windows() -> None:
    from app.platform import tools
    from app.services import render_engine

    for key in ("mac-arm64", "mac-x64", "win64"):
        b = render_engine.BROWSERS[key]
        assert b["url"].startswith(
            "https://storage.googleapis.com/chrome-for-testing-public/157.0.8080.0/"
        )
        assert (
            len(b["sha256"]) == 64
            and b["size"] > 50_000_000
            and b["executable"].startswith(b["folder"])
        )
    assert render_engine.BROWSERS["win64"]["executable"].endswith(".exe")
    for name in ("node", "ffmpeg"):
        for key in ("macos-arm64", "macos-x86_64", "windows-x86_64"):
            spec = tools.CATALOG[name][key]
            assert all(
                d.url.startswith("https://") and len(d.sha256) == 64 and d.size
                for d in spec.downloads
            )
    # El instalador de Windows y el de macOS fijan la misma versión de uv.
    ps1 = (ROOT / "videostudio.ps1").read_text(encoding="utf-8-sig")
    sh = (ROOT / "videostudio").read_text(encoding="utf-8")
    assert 'UvVersion = "0.12.18"' in ps1 and 'UV_VERSION="0.12.18"' in sh


def test_render_env_on_windows_keeps_what_chrome_needs(monkeypatch: pytest.MonkeyPatch) -> None:
    from app.services import render_engine

    monkeypatch.setattr(
        render_engine.os,
        "environ",
        {"SYSTEMROOT": r"C:\Windows", "TEMP": r"C:\T", "LOCALAPPDATA": r"C:\L",
         "ANTHROPIC_API_KEY": "sk-ant-secreta", "PATH": r"C:\otro"},
    )  # fmt: skip
    env = render_engine._env(Path("C:/VSA/tools/node/node.exe"), windows=True)
    assert env["SYSTEMROOT"] == r"C:\Windows" and env["TEMP"] == r"C:\T"
    assert "ANTHROPIC_API_KEY" not in env  # nunca secretos en el render
    assert "System32" in env["PATH"]


# ---------------------------------------------------------------------------
# Instalador: reanudable ante instalaciones incompletas
# ---------------------------------------------------------------------------


def test_installer_resumes_after_a_failure(app_home: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from app import installer

    calls: list[str] = []

    def ok_step(name: str):
        def run() -> str:
            calls.append(name)
            return name

        return run

    def failing() -> str:
        calls.append("ffmpeg")
        raise installer.InstallError("sin conexión")

    state = installer.load_state()
    installer.run_step(state, "requirements", "1", ok_step("requirements"))
    with pytest.raises(installer.InstallError):
        installer.run_step(state, "ffmpeg", "2", failing)
    saved = json.loads((app_home / "install-state.json").read_text())
    assert saved["steps"]["requirements"]["status"] == "done"
    assert saved["steps"]["ffmpeg"] == {"status": "failed", "error": "sin conexión"}
    assert "completed_at" not in saved
    installer.run_step(installer.load_state(), "ffmpeg", "2", ok_step("ffmpeg"))
    assert (
        json.loads((app_home / "install-state.json").read_text())["steps"]["ffmpeg"]["status"]
        == "done"
    )


def test_launcher_scripts_are_consistent() -> None:
    sh = (ROOT / "videostudio").read_text(encoding="utf-8")
    ps1 = (ROOT / "videostudio.ps1").read_bytes()
    assert ps1.startswith(b"\xef\xbb\xbf")  # BOM: PowerShell 5.1 lee bien los acentos
    for cmd in (
        "Video Studio AI.cmd",
        "Instalar Video Studio AI.cmd",
        "Cerrar Video Studio AI.cmd",
    ):
        raw = (ROOT / cmd).read_bytes()
        assert raw.isascii() and b"\r\n" in raw and b"-ExecutionPolicy Bypass" in raw
    for name in ("install", "start", "stop", "restart", "status", "open", "logs", "doctor"):
        assert name in sh
    assert "sudo" not in sh and "Set-ExecutionPolicy" not in ps1.decode("utf-8-sig")


# ---------------------------------------------------------------------------
# Render real: ningún navegador huérfano tras cancelar (VSA_TEST_REMOTION=1)
# ---------------------------------------------------------------------------


def _render_browsers(home: Path) -> list[int]:
    import psutil

    out = []
    for p in psutil.process_iter(["name", "cmdline"]):
        try:
            cmd = " ".join(p.info["cmdline"] or [])
        except (psutil.Error, TypeError):
            continue
        if "chrome-headless-shell" in (p.info["name"] or "") + cmd and str(home) in cmd:
            out.append(p.pid)
    return out


def test_cancelled_render_leaves_no_browser(
    engine_home: Path, client: TestClient, disk: Path, media, fake_cli
) -> None:
    """Remotion lanza el navegador en su propio grupo de procesos: al cancelar un render, la
    señal al grupo de Node no lo alcanza. El vigilante del árbol debe cerrarlo igualmente."""
    from tests.test_phase3 import _generate, _project, _use_fake

    _use_fake(client, fake_cli["cli"])
    pid, _ = _project(client, disk, media, key="vertical")
    _generate(client, pid, style="motion_tech")
    client.post(f"/api/projects/{pid}/plan/bulk", json={"status": "accepted"})
    assert client.post(f"/api/projects/{pid}/plan/approve", json={}).status_code == 200
    job = client.post(f"/api/projects/{pid}/animations/prepare", json={"use_claude": False}).json()[
        "job"
    ]
    deadline = time.monotonic() + 120
    while time.monotonic() < deadline and not _render_browsers(engine_home):
        time.sleep(0.1)
    assert _render_browsers(engine_home), "el render no llegó a abrir el navegador"
    assert client.post(f"/api/jobs/{job['id']}/cancel").status_code in (200, 202)
    wait_idle(120)
    assert client.get(f"/api/jobs/{job['id']}").json()["status"] == "cancelled"
    time.sleep(1)
    assert _render_browsers(engine_home) == []
    # Y un render completo tampoco deja el navegador abierto.
    client.post(f"/api/projects/{pid}/animations/prepare", json={"use_claude": False})
    wait_idle(600)
    time.sleep(1)
    assert _render_browsers(engine_home) == []


def test_tree_watcher_reaps_children_outside_the_process_group(tmp_path: Path) -> None:
    """Reproduce de forma determinista lo que hace Remotion: un hijo en su PROPIO grupo de
    procesos sobrevive a la terminación del grupo del padre; el vigilante del árbol lo cierra."""
    import psutil

    from app.platform import processes

    script = (
        "import subprocess, sys, time\n"
        "kw = {'start_new_session': True} if sys.platform != 'win32' else "
        "{'creationflags': subprocess.CREATE_NEW_PROCESS_GROUP}\n"
        "subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(120)'], **kw)\n"
        "time.sleep(120)\n"
    )

    def run(watch: bool) -> int:
        parent = subprocess.Popen([sys.executable, "-c", script], **processes.group_kwargs())
        tree = processes.TreeWatcher(parent)
        deadline = time.monotonic() + 10
        while time.monotonic() < deadline and not psutil.Process(parent.pid).children():
            time.sleep(0.05)
        child = psutil.Process(parent.pid).children()[0]
        if watch:
            tree.snapshot()
        processes.terminate_tree(parent, grace=2)
        parent.wait(timeout=10)
        if watch:
            tree.reap()
        time.sleep(0.3)
        alive = child.is_running() and child.status() != psutil.STATUS_ZOMBIE
        if alive:
            child.kill()
        return int(alive)

    assert run(watch=False) == 1  # sin vigilante: el hijo queda huérfano (el fallo real)
    assert run(watch=True) == 0  # con vigilante: no queda nada
