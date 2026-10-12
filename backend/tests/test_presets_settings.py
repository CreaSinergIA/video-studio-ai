"""Presets, catálogo de estilos, preferencias y persistencia entre reinicios."""

from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient

from tests.conftest import make_client


def test_catalog(client: TestClient) -> None:
    catalog = client.get("/api/catalog").json()
    ids = [s["id"] for s in catalog["styles"]]
    assert ids == ["motion_tech", "minimal_motion", "creative_explainer"]
    for style in catalog["styles"]:
        assert style["motion_language"] and style["composition"] and style["pacing"]
    assert "Montserrat" in catalog["subtitle_fonts"]
    assert catalog["default_config"]["audio"]["background_music"] is False


def test_builtin_presets_are_distinct_and_readonly(client: TestClient) -> None:
    presets = {p["id"]: p for p in client.get("/api/presets").json()}
    assert set(presets) == {
        "builtin_motion_tech",
        "builtin_minimal_motion",
        "builtin_creative_explainer",
    }
    mt, mm = presets["builtin_motion_tech"]["config"], presets["builtin_minimal_motion"]["config"]
    assert mt["animations"]["pace"] != mm["animations"]["pace"]
    assert mt["subtitles"]["animation"] != mm["subtitles"]["animation"]
    assert presets["builtin_motion_tech"]["is_default"] is True
    res = client.patch("/api/presets/builtin_motion_tech", json={"name": "Otro"})
    assert res.status_code == 409 and res.json()["code"] == "builtin_readonly"
    assert client.delete("/api/presets/builtin_motion_tech").status_code == 409


def test_preset_crud_and_default(client: TestClient) -> None:
    base = client.get("/api/presets/builtin_minimal_motion").json()["config"]
    base["subtitles"]["font_family"] = "Bebas Neue"
    base["export"]["resolution"] = "4k"
    created = client.post(
        "/api/presets",
        json={"name": "Shorts elegantes", "description": "Para Reels", "config": base},
    )
    assert created.status_code == 201
    preset = created.json()
    assert preset["style_id"] == "minimal_motion" and preset["is_builtin"] is False
    dup_name = client.post("/api/presets", json={"name": "Shorts elegantes", "config": base})
    assert dup_name.status_code == 409

    base["style"]["id"] = "motion_tech"
    updated = client.patch(f"/api/presets/{preset['id']}", json={"config": base}).json()
    assert updated["style_id"] == "motion_tech"
    assert updated["config"]["export"]["resolution"] == "4k"

    copy = client.post(f"/api/presets/{preset['id']}/duplicate", json={}).json()
    assert copy["name"] == "Shorts elegantes (copia)"

    default = client.post(f"/api/presets/{preset['id']}/default").json()
    assert default["is_default"] is True
    assert client.get("/api/settings").json()["general"]["default_preset_id"] == preset["id"]

    assert client.delete(f"/api/presets/{preset['id']}").status_code == 204
    assert client.get("/api/settings").json()["general"]["default_preset_id"] is None
    assert client.get(f"/api/presets/{preset['id']}").status_code == 404


def test_invalid_config_rejected(client: TestClient) -> None:
    config = client.get("/api/catalog").json()["default_config"]
    for path, value in [
        (("subtitles", "font_size"), 999),
        (("subtitles", "highlight_color"), "amarillo"),
        (("style", "id"), "estilo_inventado"),
        (("audio", "background_music"), True),
        (("export", "fps"), 13),
    ]:
        broken = {**config, path[0]: {**config[path[0]], path[1]: value}}
        res = client.post("/api/presets", json={"name": f"x{path}", "config": broken})
        assert res.status_code == 422, (path, res.text)


def test_general_settings_validation(client: TestClient) -> None:
    prefs = client.get("/api/settings").json()["general"]
    prefs.update(library_view="list", default_volume=0.35, playback_proxy="always")
    assert client.put("/api/settings/general", json=prefs).status_code == 200
    bad = {**prefs, "default_volume": 3}
    assert client.put("/api/settings/general", json=bad).status_code == 422
    ghost = {**prefs, "default_preset_id": "no_existe"}
    assert client.put("/api/settings/general", json=ghost).status_code == 404


def test_persistence_across_restarts(app_home: Path) -> None:
    with make_client() as c:
        config = c.get("/api/catalog").json()["default_config"]
        c.post("/api/presets", json={"name": "Persistente", "config": config})
        prefs = c.get("/api/settings").json()["general"]
        c.put("/api/settings/general", json={**prefs, "library_view": "list"})
    with make_client() as c:
        names = [p["name"] for p in c.get("/api/presets").json()]
        assert "Persistente" in names
        assert c.get("/api/settings").json()["general"]["library_view"] == "list"
        info = c.get("/api/system/info").json()
        assert info["database"]["integrity"] == "ok"
        assert info["ffmpeg"]["version"]
        caps = {cap["id"]: cap for cap in info["capabilities"]}
        # Fase 5: todas las capacidades del desarrollo inicial existen; las animaciones dependen
        # de que el motor de render esté instalado (en esta prueba aislada no lo está).
        assert caps["scenes"]["available"] and caps["backups"]["available"]
        assert caps["animations"]["available"] is False
