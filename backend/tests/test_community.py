"""Pruebas de la Community Edition: instalación nueva e independiente, sin datos ni credenciales
heredadas, solo los tres estilos gratuitos, conexión con Claude por clave de API propia y sin
marcas de agua en la salida."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

ROOT = Path(__file__).resolve().parents[2]


def test_edition_identity_is_separate_from_any_other_install() -> None:
    from app import edition
    from app.config import DEFAULT_PORT
    from app.platform.paths import default_data_dir
    from app.services import claude_client

    assert edition.EDITION == "community"
    assert DEFAULT_PORT == 8775
    assert default_data_dir().name.lower() == "videostudioai-community"
    assert claude_client.KEYCHAIN_SERVICE == "VideoStudioAI-Community"
    assert edition.ALLOW_CLAUDE_CODE_TRANSPORT is False


def test_fresh_install_is_empty(client: TestClient) -> None:
    assert client.get("/api/projects").json() == []
    assert client.get("/api/storage/status").json()["configured"] is False
    presets = client.get("/api/presets").json()
    assert presets and all(p["is_builtin"] for p in presets)  # solo presets integrados
    prefs = client.get("/api/claude/settings").json()
    assert prefs["transport"] == "api" and prefs["cli_path"] is None
    st = client.get("/api/claude/status").json()
    assert st["api_key_saved"] is False or sys.platform != "darwin"  # llavero propio, vacío
    assert client.get("/api/claude/usage").json()["requests"] == 0


def test_subscription_cli_transport_is_not_offered(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("VSA_ENV", "user")  # fuera del entorno de pruebas
    prefs = client.get("/api/claude/settings").json()
    r = client.put("/api/claude/settings", json={**prefs, "transport": "claude_code"})
    assert r.status_code >= 400 and r.json()["code"] == "transport_unavailable"
    assert client.get("/api/claude/status").json()["transports"] == ["api"]


def test_only_the_three_free_styles(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    from app import styles

    assert (
        set(styles.REGISTRY)
        == set(styles.BUILTIN)
        == {
            "motion_tech",
            "minimal_motion",
            "creative_explainer",
        }
    )
    # Un paquete adicional solo se carga si se indica explícitamente (nunca por descubrimiento).
    pkg = tmp_path / "estilos_extra_prueba.py"
    pkg.write_text("from app.styles import StyleDefinition, register\n")
    monkeypatch.syspath_prepend(str(tmp_path))
    assert styles.load_extra_packages("") == []
    assert styles.load_extra_packages("estilos_extra_prueba") == ["estilos_extra_prueba"]
    assert styles.load_extra_packages("paquete_que_no_existe") == []


def test_no_watermark_in_render_or_export_code() -> None:
    """La atribución pertenece solo al panel: ni el renderizador, ni el compositor, ni la
    exportación, ni los subtítulos dibujan textos de marca."""
    targets = [
        *ROOT.joinpath("renderer", "src").rglob("*.ts*"),
        ROOT / "renderer" / "scripts" / "render.mjs",
        ROOT / "backend" / "app" / "services" / "compositor.py",
        ROOT / "backend" / "app" / "services" / "exporter.py",
        ROOT / "backend" / "app" / "services" / "subtitles.py",
        ROOT / "backend" / "app" / "services" / "animation_spec.py",
    ]
    for f in targets:
        text = f.read_text(errors="ignore")
        for word in ("Created by", "Gabo", "Community Edition", "drawtext", "watermark"):
            assert word not in text, (f, word)


def test_repository_passes_the_privacy_check() -> None:
    r = subprocess.run(
        [sys.executable, str(ROOT / "scripts" / "privacy_check.py"), "--all"],
        capture_output=True,
        text=True,
    )
    assert r.returncode == 0, r.stderr


def test_platform_diagnosis_is_reported(client: TestClient) -> None:
    info = client.get("/api/system/info").json()
    p = info["platform"]
    assert p["os"] in ("macos", "windows", "linux")
    ids = {e["id"]: e for e in p["transcription_engines"]}
    assert ids["faster-whisper"]["implemented"] is False  # pendiente (Windows)
    assert info["app"]["edition"] == "Community Edition"
    assert info["app"]["creator"] == "Created by Gabo"


# ---------------------------------------------------------------------------
# Seguridad de la distribución
# ---------------------------------------------------------------------------


def test_security_headers_prevent_framing(client: TestClient) -> None:
    r = client.get("/api/health")
    assert r.headers["x-frame-options"] == "DENY"
    assert "frame-ancestors 'none'" in r.headers["content-security-policy"]
    assert r.headers["x-content-type-options"] == "nosniff"


def test_cli_path_is_never_used_outside_tests(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    from app.domain.preferences import ClaudePreferences
    from app.services import claude_client

    monkeypatch.setenv("VSA_ENV", "user")
    prefs = client.get("/api/claude/settings").json()
    saved = client.put("/api/claude/settings", json={**prefs, "cli_path": "/bin/echo"}).json()
    assert saved["cli_path"] is None
    assert claude_client.find_cli(ClaudePreferences(cli_path="/bin/echo")) is None
    r = client.post("/api/claude/login")
    assert r.status_code >= 400 and r.json()["code"] == "transport_unavailable"


def test_ffprobe_only_opens_local_mp4_mov(tmp_path: Path) -> None:
    from app.config import get_settings
    from app.services.media_probe import MediaValidationError, probe_file

    playlist = tmp_path / "lista.mov"  # una lista HLS con extensión de video
    playlist.write_text(
        "#EXTM3U\n#EXT-X-TARGETDURATION:1\n#EXTINF:1,\nhttp://127.0.0.1:9/x.ts\n#EXT-X-ENDLIST\n"
    )
    with pytest.raises(MediaValidationError):
        probe_file(get_settings().ffprobe, playlist)


def test_import_from_path_checks_the_real_container(
    client: TestClient, media: dict[str, Path]
) -> None:
    r = client.post("/api/imports/from-path", json={"path": str(media["disguised"])})
    assert r.status_code >= 400 and r.json()["code"] == "not_mp4_mov"


def test_adopted_manifest_values_are_measured_again(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, disk: Path, media: dict[str, Path]
) -> None:
    """Un `project.json` manipulado no puede inyectar valores en los filtros de FFmpeg."""
    import json

    from app.config import get_settings
    from app.db import session_scope
    from app.models import MediaAsset
    from app.services.storage import PROJECT_MANIFEST
    from tests.conftest import configure, make_client, upload, wait_idle

    monkeypatch.setenv("VSA_FRONTEND_DIST", str(tmp_path / "no-dist"))
    monkeypatch.setenv("VSA_HOME", str(tmp_path / "home_a"))
    get_settings.cache_clear()
    with make_client() as first:
        configure(first, disk)
        body = upload(first, media["vertical"]).json()
        wait_idle()
    manifest_path = next(disk.glob(f"projects/*/{PROJECT_MANIFEST}"))
    manifest = json.loads(manifest_path.read_text())
    for a in manifest["assets"]:
        a["fps_num"] = "25:x=1"
        a["audio_tracks"] = [{"channel_layout": "stereo[a];[0:a]amovie=/etc/passwd", "channels": 2}]
        a["probe"] = {"inyectado": True}
    manifest_path.write_text(json.dumps(manifest))

    monkeypatch.setenv("VSA_HOME", str(tmp_path / "home_b"))
    get_settings.cache_clear()
    with make_client() as second:
        assert configure(second, disk)["adopted_projects"] == 1
        wait_idle()
        with session_scope() as s:
            asset = s.get(MediaAsset, body["asset"]["id"])
            assert asset is not None
            assert asset.fps_num == 25 and isinstance(asset.fps_num, int)
            layouts = [t.get("channel_layout") for t in asset.audio_tracks]
            assert all(lay in (None, "mono", "stereo") for lay in layouts), layouts
            assert "inyectado" not in (asset.probe or {})
    get_settings.cache_clear()
