"""Flujo completo por la API: almacenamiento, importación, ingesta, reproducción, borrado."""

from __future__ import annotations

import hashlib
import json
import shutil
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.services.imports import quick_hash_file
from tests.conftest import configure, make_client, sha256, upload, wait_idle


def test_security_headers_and_hosts(client: TestClient) -> None:
    # Sin cabecera propia: las mutaciones se rechazan (CSRF).
    res = client.post("/api/projects", json={"name": "x"}, headers={"x-vsa-client": ""})
    assert res.status_code == 403
    # Host ajeno (DNS rebinding): rechazado.
    res = client.get("/api/health", headers={"host": "evil.example.com"})
    assert res.status_code == 400
    assert client.get("/api/health").json()["ok"] is True
    assert client.get("/api/no-existe").status_code == 404


def test_requires_storage_before_projects(client: TestClient) -> None:
    status = client.get("/api/storage/status").json()
    assert status["configured"] is False
    res = client.post("/api/projects", json={"name": "Demo"})
    assert res.status_code == 409 and res.json()["code"] == "not_configured"


def test_validate_and_configure_storage(client: TestClient, disk: Path) -> None:
    report = client.post("/api/storage/validate", json={"path": str(disk)}).json()
    assert report["can_use"] and not report["exists"] and report["parent_exists"]
    bad = client.post("/api/storage/validate", json={"path": "relativa"})
    assert bad.status_code == 422
    result = configure(client, disk)
    assert result["status"]["available"] is True
    assert (disk / ".videostudio.json").is_file()
    browse = client.get("/api/storage/browse", params={"path": str(disk.parent)}).json()
    assert any(e["name"] == "VideoStudio" and e["is_storage"] for e in browse["entries"])


@pytest.mark.parametrize("key", ["horizontal", "vertical", "rotated", "hevc", "silent"])
def test_upload_ingest_and_playback(
    client: TestClient, disk: Path, media: dict[str, Path], key: str
) -> None:
    configure(client, disk)
    source = media[key]
    before = sha256(source)
    res = upload(client, source)
    assert res.status_code == 201, res.text
    body = res.json()
    project_id, asset = body["project"]["id"], body["asset"]
    assert body["job"]["kind"] == "ingest"
    wait_idle()

    detail = client.get(f"/api/projects/{project_id}").json()
    assert detail["status"] == "ready", detail
    src = detail["source"]
    assert src["sha256"] == before
    assert src["playback"] == "original"
    expected = "vertical" if key in ("vertical", "rotated", "hevc") else "horizontal"
    assert src["orientation"] == expected
    assert src["thumbnail_url"] and src["filmstrip"] and src["filmstrip"]["count"] >= 12
    assert (src["waveform_url"] is not None) == src["has_audio"]

    thumb = client.get(src["thumbnail_url"])
    assert thumb.status_code == 200 and thumb.content[:2] == b"\xff\xd8"
    strip = client.get(src["filmstrip"]["url"])
    assert strip.status_code == 200 and strip.headers["content-type"] == "image/jpeg"
    if src["waveform_url"]:
        wave = client.get(src["waveform_url"]).json()
        assert len(wave["peaks"]) >= 100 and wave["max_peak"] > 0

    # Reproducción con Range (necesario para Safari y para buscar en el video).
    ranged = client.get(src["stream_url"], headers={"range": "bytes=0-1023"})
    assert ranged.status_code == 206
    assert ranged.headers["content-range"].startswith("bytes 0-1023/")
    assert len(ranged.content) == 1024

    # El original copiado es idéntico byte a byte y el archivo de origen no cambió.
    stored = disk / src["file_rel"]
    assert sha256(stored) == before
    assert sha256(source) == before
    manifest = json.loads((stored.parents[1] / "project.json").read_text())
    assert manifest["project_id"] == project_id
    assert manifest["assets"][0]["sha256"] == before
    assert not list((disk / "cache" / "uploads").glob("*.partial"))
    assert asset["original_filename"] == source.name


def test_prores_gets_proxy(client: TestClient, disk: Path, media: dict[str, Path]) -> None:
    configure(client, disk)
    res = upload(client, media["prores"])
    assert res.status_code == 201, res.text
    wait_idle()
    src = client.get(f"/api/projects/{res.json()['project']['id']}").json()["source"]
    assert src["browser_playable"] is False
    assert src["proxy_ready"] is True and src["playback"] == "proxy"
    proxy = client.get(src["stream_url"], headers={"range": "bytes=0-99"})
    assert proxy.status_code == 206


@pytest.mark.parametrize(
    ("key", "code"),
    [("fake", "not_mp4_mov"), ("disguised", "not_mp4_mov"), ("truncated", "unreadable_media")],
)
def test_invalid_uploads_rejected(
    client: TestClient, disk: Path, media: dict[str, Path], key: str, code: str
) -> None:
    configure(client, disk)
    res = upload(client, media[key])
    assert res.status_code == 422, res.text
    assert res.json()["code"] == code
    assert client.get("/api/projects").json() == []
    assert not list((disk / "cache" / "uploads").iterdir())


def test_wrong_extension_rejected_before_upload(client: TestClient, disk: Path) -> None:
    configure(client, disk)
    res = client.post("/api/imports/upload", params={"filename": "clip.avi"}, content=b"x" * 100)
    assert res.status_code == 422 and res.json()["code"] == "unsupported_extension"


def test_duplicates(client: TestClient, disk: Path, media: dict[str, Path]) -> None:
    configure(client, disk)
    source = media["horizontal"]
    assert upload(client, source).status_code == 201
    quick = quick_hash_file(source)
    check = client.post(
        "/api/imports/check",
        json={"filename": source.name, "size_bytes": source.stat().st_size, "quick_hash": quick},
    ).json()
    assert check["ok"] and len(check["duplicates"]) == 1
    dup = upload(client, source)
    assert dup.status_code == 409 and dup.json()["code"] == "duplicate"
    forced = upload(client, source, allow_duplicate="true", project_name="Copia intencional")
    assert forced.status_code == 201
    assert forced.json()["project"]["name"] == "Copia intencional"
    wait_idle()
    assert len(client.get("/api/projects").json()) == 2


def test_quick_hash_matches_browser_algorithm(media: dict[str, Path]) -> None:
    data = media["horizontal"].read_bytes()
    size = len(data)
    chunk = 4 * 1024 * 1024
    expected = hashlib.sha256(f"{size}:".encode() + data[:chunk] + data[max(0, size - chunk) :])
    assert quick_hash_file(media["horizontal"]) == expected.hexdigest()


def test_project_lifecycle(client: TestClient, disk: Path, media: dict[str, Path]) -> None:
    configure(client, disk)
    created = client.post("/api/projects", json={"name": "Mi proyecto"})
    assert created.status_code == 201
    project = created.json()
    assert project["status"] == "empty"
    pid = project["id"]
    project_dir = disk / project["dir_rel"]
    assert (project_dir / "originals").is_dir() and (project_dir / "project.json").is_file()

    # Importar dentro del proyecto existente.
    res = upload(client, media["vertical"], project_id=pid)
    assert res.status_code == 201 and res.json()["project"]["id"] == pid
    wait_idle()
    second = upload(client, media["horizontal"], project_id=pid)
    assert second.status_code == 409 and second.json()["code"] == "source_exists"

    renamed = client.patch(f"/api/projects/{pid}", json={"name": "  Renombrado  "}).json()
    assert renamed["name"] == "Renombrado"
    assert json.loads((project_dir / "project.json").read_text())["name"] == "Renombrado"
    assert client.patch(f"/api/projects/{pid}", json={"name": ""}).status_code == 422

    config = renamed["config"]
    config["subtitles"]["font_size"] = 90
    config["style"]["id"] = "creative_explainer"
    updated = client.patch(
        f"/api/projects/{pid}",
        json={"config": config, "editor_state": {"position": 1.5, "volume": 0.4}},
    ).json()
    assert updated["config"]["subtitles"]["font_size"] == 90
    assert updated["style_id"] == "creative_explainer"
    assert updated["editor_state"]["position"] == 1.5
    bad = client.patch(
        f"/api/projects/{pid}",
        json={"config": {**config, "subtitles": {**config["subtitles"], "text_color": "rojo"}}},
    )
    assert bad.status_code == 422

    applied = client.post(
        f"/api/projects/{pid}/apply-preset", json={"preset_id": "builtin_minimal_motion"}
    ).json()
    assert applied["preset_id"] == "builtin_minimal_motion"
    assert applied["config"]["style"]["id"] == "minimal_motion"

    opened = client.post(f"/api/projects/{pid}/open").json()
    assert opened["last_opened_at"] is not None

    original = disk / opened["source"]["file_rel"]
    outside = disk.parent / "no_tocar.txt"
    outside.write_text("archivo ajeno")
    deleted = client.delete(f"/api/projects/{pid}")
    assert deleted.status_code == 200 and deleted.json()["files_removed"] is True
    assert not project_dir.exists() and not original.exists()
    assert outside.read_text() == "archivo ajeno"
    assert (disk / ".videostudio.json").exists()
    assert client.get(f"/api/projects/{pid}").status_code == 404


def test_import_from_path_job(client: TestClient, disk: Path, media: dict[str, Path]) -> None:
    configure(client, disk)
    source = media["rotated"]
    before = sha256(source)
    res = client.post("/api/imports/from-path", json={"path": str(source)})
    assert res.status_code == 202, res.text
    job = res.json()["job"]
    assert job["kind"] == "import_file"
    wait_idle()
    finished = client.get(f"/api/jobs/{job['id']}").json()
    assert finished["status"] == "succeeded", finished
    project = client.get(f"/api/projects/{finished['result']['project_id']}").json()
    assert project["status"] == "ready"
    assert project["source"]["orientation"] == "vertical"
    assert sha256(source) == before
    again = client.post("/api/imports/from-path", json={"path": str(source)}).json()
    assert again["job"] is None and len(again["duplicates"]) == 1
    missing = client.post("/api/imports/from-path", json={"path": str(disk / "nada.mp4")})
    assert missing.status_code == 404


def test_verify_integrity(client: TestClient, disk: Path, media: dict[str, Path]) -> None:
    configure(client, disk)
    body = upload(client, media["silent"]).json()
    wait_idle()
    asset_id = body["asset"]["id"]
    job = client.post(f"/api/media/{asset_id}/verify").json()
    wait_idle()
    assert client.get(f"/api/jobs/{job['id']}").json()["status"] == "succeeded"
    assert client.get(f"/api/projects/{body['project']['id']}").json()["source"]["verified_at"]
    # Si alguien modifica el original fuera de la app, la verificación lo detecta.
    stored = disk / body["asset"]["file_rel"]
    stored.chmod(0o644)
    with open(stored, "r+b") as fh:
        fh.seek(-10, 2)
        fh.write(b"0123456789")
    job = client.post(f"/api/media/{asset_id}/verify").json()
    wait_idle()
    failed = client.get(f"/api/jobs/{job['id']}").json()
    assert failed["status"] == "failed" and "no coincide" in failed["error"]


def test_storage_unavailable_and_reconnect(
    client: TestClient, disk: Path, media: dict[str, Path]
) -> None:
    configure(client, disk)
    body = upload(client, media["horizontal"]).json()
    wait_idle()
    pid = body["project"]["id"]
    db_rows_before = client.get("/api/projects").json()

    # «Desconectar el disco»: la carpeta desaparece.
    hidden = disk.parent / "desconectado"
    disk.rename(hidden)
    status = client.get("/api/storage/status", params={"fresh": True}).json()
    assert status["available"] is False and status["code"] == "path_missing"
    projects = client.get("/api/projects").json()
    assert projects[0]["status"] == "unavailable" and projects[0]["name"] == "Horizontal Clip"
    assert client.get(f"/api/media/{body['asset']['id']}/original").status_code == 503
    assert upload(client, media["vertical"]).status_code == 503
    assert client.post("/api/projects", json={"name": "x"}).status_code == 503
    # Borrar con el disco desconectado solo es posible quitándolo de la biblioteca.
    assert client.delete(f"/api/projects/{pid}").status_code == 503
    assert not disk.exists(), "la app no debe recrear la raíz ausente"

    # «Reconectar»: todo vuelve sin pérdida.
    hidden.rename(disk)
    status = client.get("/api/storage/status", params={"fresh": True}).json()
    assert status["available"] is True
    after = client.get("/api/projects").json()
    assert after[0]["status"] == "ready"
    assert [p["id"] for p in after] == [p["id"] for p in db_rows_before]
    assert client.get(f"/api/media/{body['asset']['id']}/original").status_code == 200

    # Quitar de la biblioteca conservando archivos.
    disk.rename(hidden)
    res = client.delete(f"/api/projects/{pid}", params={"keep_files": True})
    assert res.status_code == 200 and res.json()["files_removed"] is False
    hidden.rename(disk)
    assert (disk / body["asset"]["file_rel"]).exists()


def test_adopt_projects_after_reinstall(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, disk: Path, media: dict[str, Path]
) -> None:
    from app.config import get_settings

    monkeypatch.setenv("VSA_FRONTEND_DIST", str(tmp_path / "no-dist"))
    monkeypatch.setenv("VSA_HOME", str(tmp_path / "home_a"))
    get_settings.cache_clear()
    with make_client() as first:
        configure(first, disk)
        body = upload(first, media["vertical"]).json()
        wait_idle()
        first.patch(f"/api/projects/{body['project']['id']}", json={"name": "Sobreviviente"})

    # Nueva instalación (base de datos vacía) apuntando al mismo disco.
    monkeypatch.setenv("VSA_HOME", str(tmp_path / "home_b"))
    get_settings.cache_clear()
    with make_client() as second:
        result = configure(second, disk)
        assert result["adopted_projects"] == 1
        wait_idle()
        projects = second.get("/api/projects").json()
        assert projects[0]["name"] == "Sobreviviente"
        assert projects[0]["status"] == "ready"
        assert projects[0]["source"]["sha256"] == sha256(media["vertical"])
    get_settings.cache_clear()


def test_change_storage_keeps_old_projects(
    client: TestClient, disk: Path, tmp_path: Path, media: dict[str, Path]
) -> None:
    configure(client, disk)
    upload(client, media["vertical"])
    wait_idle()
    other = tmp_path / "otro_disco"
    other.mkdir()
    configure(client, other / "VS2")
    locations = client.get("/api/storage/locations").json()
    assert len(locations) == 2 and sum(1 for loc in locations if loc["active"]) == 1
    projects = client.get("/api/projects").json()
    assert projects[0]["status"] == "ready"  # sigue disponible en su almacenamiento original
    shutil.rmtree(other)


def test_failed_delete_keeps_project_intact(
    client: TestClient, disk: Path, media: dict[str, Path], monkeypatch: pytest.MonkeyPatch
) -> None:
    configure(client, disk)
    body = upload(client, media["silent"]).json()
    wait_idle()
    pid = body["project"]["id"]
    stored = disk / body["asset"]["file_rel"]

    def broken_rename(*_args: object, **_kwargs: object) -> None:
        raise OSError(5, "Input/output error")

    monkeypatch.setattr("app.services.storage.os.rename", broken_rename)
    res = client.delete(f"/api/projects/{pid}")
    assert res.status_code == 503
    monkeypatch.undo()
    # Nada a medias: el proyecto sigue en la biblioteca y sus archivos, completos.
    assert client.get(f"/api/projects/{pid}").json()["status"] == "ready"
    assert sha256(stored) == body["asset"]["sha256"]
    assert client.delete(f"/api/projects/{pid}").status_code == 200
    assert not stored.exists()
    assert not list((disk / "cache" / "trash").iterdir())
