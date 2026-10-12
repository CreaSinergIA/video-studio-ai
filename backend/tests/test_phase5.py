"""Pruebas de la Fase 5: protección de datos, control de solicitudes a Claude y regeneración
selectiva de escenas (con Claude simulado; el render real se activa con VSA_TEST_REMOTION=1)."""

from __future__ import annotations

import json
import sqlite3
import time
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from tests.conftest import sha256, wait_idle
from tests.test_phase3 import _calls, _generate, _project, _use_fake, fake_cli  # noqa: F401
from tests.test_phase4 import _ffprobe, engine_home  # noqa: F401

# ---------------------------------------------------------------------------
# Entornos y copias de seguridad
# ---------------------------------------------------------------------------


def test_environment_marker_blocks_mixing_user_and_test_data(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from app.services import data_safety as ds

    home = tmp_path / "datos"
    monkeypatch.setenv("VSA_ENV", "test")
    assert ds.ensure_environment(home, "x") == "test"
    assert json.loads((home / ds.MARKER).read_text())["kind"] == "test"
    ds.assert_disposable(home)  # marcado como pruebas: se puede borrar
    # Abrirlo como entorno del usuario se rechaza (y al revés).
    monkeypatch.setenv("VSA_ENV", "user")
    with pytest.raises(ds.EnvironmentError_):
        ds.ensure_environment(home, "x")
    user = tmp_path / "usuario"
    assert ds.ensure_environment(user, "x") == "user"
    with pytest.raises(ds.EnvironmentError_):
        ds.assert_disposable(user)
    monkeypatch.setenv("VSA_ENV", "test")
    with pytest.raises(ds.EnvironmentError_):
        ds.ensure_environment(user, "x")
    # Un entorno de pruebas nunca puede apuntar al directorio de datos real.
    monkeypatch.setattr(ds, "default_home", lambda: (tmp_path / "real").resolve())
    with pytest.raises(ds.EnvironmentError_):
        ds.ensure_environment(tmp_path / "real", "x")
    with pytest.raises(ds.EnvironmentError_):
        ds.assert_disposable(tmp_path / "real")


def test_backups_are_verified_listed_and_restorable(client: TestClient, app_home: Path) -> None:
    health = client.get("/api/health").json()
    assert health["environment"] == "test" and health["db_integrity"] == "ok"
    r = client.post("/api/system/backups")
    assert r.status_code == 201, r.text
    name = r.json()["name"]
    assert name.startswith("manual-")
    items = client.get("/api/system/backups").json()["items"]
    assert any(b["name"] == name and b["kind"] == "manual" for b in items)
    # Un cambio posterior se deshace al restaurar (y el estado previo queda guardado).
    prefs = client.get("/api/settings").json()["general"]
    changed = {**prefs, "autoplay_on_open": not prefs["autoplay_on_open"]}
    assert client.put("/api/settings/general", json=changed).status_code == 200
    assert client.post(f"/api/system/backups/{name}/restore", json={}).status_code == 409
    r = client.post(f"/api/system/backups/{name}/restore", json={"confirm": True})
    assert r.status_code == 200, r.text
    assert r.json()["previous_state"].startswith("antes-de-restaurar-")
    assert client.get("/api/settings").json()["general"] == prefs
    # Nombres arbitrarios o rutas: rechazados.
    for bad in ("..%2Fapp.db", "app.db", "otra-cosa.db"):
        assert (
            client.post(f"/api/system/backups/{bad}/restore", json={"confirm": True}).status_code
            == 404
        )


def test_pending_migration_makes_a_backup_first(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from alembic import command

    from app import db
    from app.config import get_settings
    from app.main import create_app

    home = tmp_path / "home"
    home.mkdir()
    url = f"sqlite:///{home / 'app.db'}"
    db.init_engine(url)
    command.upgrade(db._alembic_config(url), "0004")  # base de una versión anterior
    monkeypatch.setenv("VSA_HOME", str(home))
    monkeypatch.setenv("VSA_ENV", "test")
    monkeypatch.setenv("VSA_FRONTEND_DIST", str(tmp_path / "no-dist"))
    get_settings.cache_clear()
    with TestClient(create_app(), base_url="http://127.0.0.1") as c:
        assert c.get("/api/health").status_code == 200
    names = [p.name for p in (home / "backups").glob("*.db")]
    pre = [n for n in names if n.startswith("pre-migracion-")]
    assert pre and "0005" in pre[0]
    con = sqlite3.connect(home / "backups" / pre[0])
    assert con.execute("select version_num from alembic_version").fetchone()[0] == "0004"
    con.close()
    get_settings.cache_clear()


# ---------------------------------------------------------------------------
# Control de solicitudes a Claude
# ---------------------------------------------------------------------------


def test_budget_requires_confirmation_over_the_authorized_limit(
    client: TestClient, disk: Path, media, fake_cli
) -> None:
    _use_fake(client, fake_cli["cli"], daily_request_limit=1)
    pid, _ = _project(client, disk, media)
    st = client.get("/api/claude/budget").json()
    assert st["used_24h"] == 0 and st["limit_24h"] == 1 and st["billing"] == "subscription"
    # 1 solicitud esperada, pero hasta 4 con reintentos: supera el límite de 1 → confirmación.
    r = client.post(f"/api/projects/{pid}/plan/generate", json={"style": "motion_tech"})
    assert r.status_code == 409 and r.json()["code"] == "budget_confirm", r.text
    details = r.json()["details"]
    assert details["estimate"]["expected"] == 1 and details["limit_24h"] == 1
    assert not _calls(fake_cli["log"])  # no se envió nada
    r = client.post(
        f"/api/projects/{pid}/plan/generate", json={"style": "motion_tech", "confirm_budget": True}
    )
    assert r.status_code == 202, r.text
    wait_idle(120)
    assert len(_calls(fake_cli["log"])) == 1
    st = client.get("/api/claude/budget").json()
    assert st["used_24h"] == 1 and st["remaining_24h"] == 0
    usage = client.get("/api/claude/usage").json()
    assert usage["requests"] == 1 and usage["by_step"] == {"full": 1}


def test_operation_never_exceeds_its_request_cap(
    client: TestClient, disk: Path, media, fake_cli, monkeypatch: pytest.MonkeyPatch
) -> None:
    _use_fake(client, fake_cli["cli"], max_requests_per_operation=1, max_retries=0)
    pid, _ = _project(client, disk, media)
    monkeypatch.setenv("FAKE_CLAUDE_MODE", "invalid")  # respuestas inválidas: pediría repetir
    r = client.post(f"/api/projects/{pid}/plan/generate", json={"style": "motion_tech"})
    assert r.status_code == 202, r.text
    wait_idle(120)
    assert len(_calls(fake_cli["log"])) == 1  # tope de 1: no hubo segundo intento
    job = client.get("/api/jobs?recent_seconds=600").json()[0]
    assert job["status"] == "failed" and "tope" in job["error"]


# ---------------------------------------------------------------------------
# Regeneración selectiva (sin render real)
# ---------------------------------------------------------------------------


def _approved(client: TestClient, pid: str, style: str = "motion_tech") -> list[dict[str, Any]]:
    _generate(client, pid, style=style)
    client.post(f"/api/projects/{pid}/plan/bulk", json={"status": "accepted"})
    plan = client.get(f"/api/projects/{pid}/plan").json()["plan"]
    for c in plan["document"]["validation"].get("conflicts") or []:
        client.patch(
            f"/api/projects/{pid}/plan/interventions/{c['b']}", json={"status": "rejected"}
        )
    r = client.post(f"/api/projects/{pid}/plan/approve", json={})
    assert r.status_code == 200, r.text
    items = client.get(f"/api/projects/{pid}/animations").json()["items"]
    return [i for i in items if i["status"] != "kept"]


def test_scene_revision_creates_a_candidate_without_touching_the_approved_plan(
    client: TestClient, disk: Path, media, fake_cli
) -> None:
    _use_fake(client, fake_cli["cli"])
    pid, _ = _project(client, disk, media)
    animated = _approved(client, pid)
    iid = animated[0]["intervention_id"]
    approved = client.get(f"/api/projects/{pid}/plan").json()["plan"]["approved_version"]
    sc = client.get(f"/api/projects/{pid}/scenes/{iid}").json()
    assert sc["in_use"] == 1 and len(sc["versions"]) == 1
    assert sc["versions"][0]["source"] == "approved" and sc["versions"][0]["in_use"]
    assert sc["budget"]["estimate"]["expected"] == 1
    n0 = len(_calls(fake_cli["log"]))
    r = client.post(
        f"/api/projects/{pid}/scenes/{iid}/revise", json={"instruction": "Utiliza menos texto"}
    )
    assert r.status_code == 202, r.text
    wait_idle(180)
    calls = _calls(fake_cli["log"])
    assert len(calls) == n0 + 1  # una sola solicitud por modificación
    assert calls[-1]["schema"] == ["animation", "changes", "intervention", "summary"]
    sc = client.get(f"/api/projects/{pid}/scenes/{iid}").json()
    cand = next(v for v in sc["versions"] if v["number"] == 2)
    assert cand["status"] == "candidate" and not cand["in_use"] and cand["source"] == "claude"
    assert cand["instruction"] == "Utiliza menos texto" and cand["changes"]
    assert any(d.startswith("elementos") for d in cand["diff"])
    assert cand["preview"] is None  # sin motor: propuesta guardada, vista previa pendiente
    # El plan aprobado no cambió.
    assert client.get(f"/api/projects/{pid}/plan").json()["plan"]["approved_version"] == approved
    # Misma petición sobre la misma versión: se reutiliza (sin solicitud nueva).
    r = client.post(
        f"/api/projects/{pid}/scenes/{iid}/revise", json={"instruction": "utiliza  MENOS texto"}
    )
    assert r.status_code == 202 and r.json()["reused"] is True and r.json()["version"] == 2
    assert len(_calls(fake_cli["log"])) == n0 + 1
    # Descartar y comprobar estados.
    d = client.post(f"/api/projects/{pid}/scenes/{iid}/versions/2/discard").json()
    assert next(v for v in d["versions"] if v["number"] == 2)["status"] == "discarded"
    assert client.post(f"/api/projects/{pid}/scenes/{iid}/versions/1/discard").status_code == 409


def test_scene_scope_cannot_be_escaped(client: TestClient, disk: Path, media, fake_cli) -> None:
    """Claude devuelve otro id: la versión se guarda igualmente para ESTA escena y las demás
    escenas del plan no cambian."""
    _use_fake(client, fake_cli["cli"])
    pid, _ = _project(client, disk, media)
    animated = _approved(client, pid)
    iid = animated[0]["intervention_id"]
    before = client.get(f"/api/projects/{pid}/plan").json()["plan"]["document"]["interventions"]
    r = client.post(
        f"/api/projects/{pid}/scenes/{iid}/revise",
        json={"instruction": "Cambia FUERA de la escena"},
    )
    assert r.status_code == 202
    wait_idle(180)
    sc = client.get(f"/api/projects/{pid}/scenes/{iid}").json()
    assert sc["versions"][0]["number"] == 2 and sc["versions"][0]["status"] == "candidate"
    after = client.get(f"/api/projects/{pid}/plan").json()["plan"]["document"]["interventions"]
    assert before == after


def test_apply_creates_an_immutable_plan_version_and_reuses_directions(
    client: TestClient, disk: Path, media, fake_cli
) -> None:
    _use_fake(client, fake_cli["cli"])
    pid, _ = _project(client, disk, media)
    animated = _approved(client, pid)
    iid = animated[0]["intervention_id"]
    v0 = client.get(f"/api/projects/{pid}/plan").json()["plan"]["approved_version"]
    client.post(
        f"/api/projects/{pid}/scenes/{iid}/revise", json={"instruction": "Reduce el movimiento"}
    )
    wait_idle(180)
    sc = client.get(f"/api/projects/{pid}/scenes/{iid}").json()
    cand = sc["versions"][0]
    assert any("intensidad" in d for d in cand["diff"]), cand["diff"]
    assert (
        client.post(f"/api/projects/{pid}/scenes/{iid}/versions/2/apply", json={}).status_code
        == 409
    )
    r = client.post(f"/api/projects/{pid}/scenes/{iid}/versions/2/apply", json={"confirm": True})
    assert r.status_code == 200, r.text
    v1 = r.json()["plan_version"]
    assert v1 > v0
    wait_idle(120)  # la generación falla sin motor; el plan ya está aprobado
    plan = client.get(f"/api/projects/{pid}/plan").json()["plan"]
    assert plan["approved_version"] == v1
    # La versión aprobada anterior sigue intacta e inmutable.
    old = client.get(f"/api/projects/{pid}/plan/versions/{v0}").json()
    old_iv = next(i for i in old["document"]["interventions"] if i["id"] == iid)
    new_iv = next(i for i in plan["document"]["interventions"] if i["id"] == iid)
    assert old["immutable"] is True
    assert old_iv["intensity"] != "low" or old_iv["motion"] != new_iv["motion"]
    assert new_iv["intensity"] == "low"
    # Las demás escenas son idénticas en ambas versiones.
    others_old = [i for i in old["document"]["interventions"] if i["id"] != iid]
    others_new = [i for i in plan["document"]["interventions"] if i["id"] != iid]
    strip = lambda xs: [{k: v for k, v in i.items() if k != "status_history"} for i in xs]  # noqa: E731
    assert strip(others_old) == strip(others_new)
    sc = client.get(f"/api/projects/{pid}/scenes/{iid}").json()
    assert sc["in_use"] == 2
    assert next(v for v in sc["versions"] if v["number"] == 1)["status"] == "archived"
    # Recuperar la versión original: nueva versión del plan, sin solicitudes a Claude.
    n = len(_calls(fake_cli["log"]))
    r = client.post(f"/api/projects/{pid}/scenes/{iid}/versions/1/apply", json={"confirm": True})
    assert r.status_code == 200, r.text
    wait_idle(120)
    assert client.get(f"/api/projects/{pid}/scenes/{iid}").json()["in_use"] == 1
    assert len(_calls(fake_cli["log"])) == n


def test_impact_reports_dependent_scenes() -> None:
    """Alargar una escena que precede a otra enlazada cambia también la siguiente."""
    from app.services import scenes

    class _Row:
        def __init__(self, iv: dict[str, Any], d: dict[str, Any] | None) -> None:
            self.intervention, self.direction = iv, d

    a = _Row({"type": "overlay_motion", "start": 1.0, "end": 2.0, "intensity": "medium",
              "motion": {"entry": "fade"}}, {"template": "tech.panel", "items": [{"text": "a"}]})  # fmt: skip
    b = _Row({"type": "diagram", "start": 1.0, "end": 2.5, "intensity": "low",
              "motion": {"entry": "draw"}}, {"template": "tech.nodes", "items": [], "text_scale": 1.3})  # fmt: skip
    d = scenes.diff(a, b)  # type: ignore[arg-type]
    joined = " ".join(d)
    for word in (
        "tipo",
        "fin",
        "intensidad",
        "movimiento",
        "plantilla",
        "tamaño del texto",
        "elementos",
    ):
        assert word in joined, d


# ---------------------------------------------------------------------------
# Render real: modificar → previsualizar → aplicar → solo se renderiza lo necesario
# ---------------------------------------------------------------------------


def test_real_selective_regeneration(
    engine_home: Path, client: TestClient, disk: Path, media, fake_cli
) -> None:
    _use_fake(client, fake_cli["cli"])
    pid, _ = _project(client, disk, media, key="vertical")
    src = next(p for p in (disk / "projects").rglob("*.mp4") if p.name == media["vertical"].name)
    before = sha256(src)
    animated = _approved(client, pid)
    r = client.post(f"/api/projects/{pid}/animations/prepare", json={"use_claude": True})
    assert r.status_code == 202, r.text
    wait_idle(600)
    clips = lambda: {p.name for p in (disk / "projects").rglob("animations/clips/*.mov")}  # noqa: E731
    base_clips = clips()
    # Reintentar solo una escena ya generada no crea clips nuevos (misma huella que el plan).
    iid = animated[0]["intervention_id"]
    client.post(
        f"/api/projects/{pid}/animations/prepare", json={"use_claude": False, "only": [iid]}
    )
    wait_idle(300)
    assert clips() == base_clips

    t = time.monotonic()
    r = client.post(
        f"/api/projects/{pid}/scenes/{iid}/revise", json={"instruction": "Haz el título más grande"}
    )
    assert r.status_code == 202
    wait_idle(600)
    sc = client.get(f"/api/projects/{pid}/scenes/{iid}").json()
    cand, cur = sc["versions"][0], next(v for v in sc["versions"] if v["in_use"])
    assert cand["preview"] and cur["preview"], sc
    assert cand["preview"]["window"] == cur["preview"]["window"]  # misma ventana para comparar
    for v in (cand, cur):
        res = client.get(v["preview"]["url"])
        assert res.status_code == 200 and res.headers["content-type"] == "video/mp4"
    assert any("tamaño del texto" in d for d in cand["diff"])
    # Las vistas previas de la candidata no cambian el estado de las animaciones aprobadas.
    st = client.get(f"/api/projects/{pid}/animations").json()
    assert all(i["status"] == "ready" for i in st["items"] if i["status"] != "kept")
    revise_s = time.monotonic() - t

    impacted = {a["intervention_id"] for a in cand["impact"]["affected"]}
    after_preview = clips()
    r = client.post(
        f"/api/projects/{pid}/scenes/{iid}/versions/{cand['number']}/apply", json={"confirm": True}
    )
    assert r.status_code == 200, r.text
    wait_idle(600)
    st = client.get(f"/api/projects/{pid}/animations").json()
    assert st["approved_version"] == r.json()["plan_version"]
    ready = [i for i in st["items"] if i["status"] != "kept"]
    assert all(i["status"] == "ready" for i in ready), st
    rerendered = {i["intervention_id"] for i in ready if not i["reused"]}
    # Solo la escena modificada y sus dependientes informadas (la candidata final a tamaño de
    # exportación es nueva; las vistas previas eran a 540p).
    assert rerendered <= {iid} | impacted, (rerendered, impacted)
    assert iid in rerendered
    assert len(clips() - after_preview) == len(rerendered)
    # Volver a la versión original: todo sale de la caché.
    r = client.post(f"/api/projects/{pid}/scenes/{iid}/versions/1/apply", json={"confirm": True})
    assert r.status_code == 200
    wait_idle(600)
    st = client.get(f"/api/projects/{pid}/animations").json()
    assert all(i["reused"] for i in st["items"] if i["status"] == "ready")
    # Exportación del resultado actualizado.
    r = client.post(f"/api/projects/{pid}/exports", json={"with_animations": True})
    assert r.status_code == 202
    wait_idle(600)
    ex = client.get(f"/api/projects/{pid}/exports").json()[0]
    assert ex["status"] == "succeeded", ex
    info = _ffprobe(disk / ex["file_rel"])
    assert abs(float(info["format"]["duration"]) - 3.0) < 0.15
    assert sha256(src) == before
    print(f"modificación + vistas previas: {revise_s:.1f} s")


# ---------------------------------------------------------------------------
# Registro de estilos
# ---------------------------------------------------------------------------


def test_style_registry_matches_the_renderer() -> None:
    """Cada estilo del backend tiene en el renderizador exactamente las mismas plantillas."""
    import re

    from app import styles

    src = Path(__file__).resolve().parents[2] / "renderer" / "src" / "styles"
    reg = (src / "registry.ts").read_text()
    entries = dict(re.findall(r"^\s+(\w+): \{ templates: (\w+),", reg, re.M))
    assert set(entries) == set(styles.REGISTRY), entries
    maps: dict[str, set[str]] = {}
    for f in src.glob("*.tsx"):
        for name, body in re.findall(
            r"export const (\w+): Record<string, React\.FC<[^>]+>> = \{(.*?)\n\}",
            f.read_text(),
            re.S,
        ):
            maps[name] = set(re.findall(r"'([a-z]+\.[a-z]+)':", body))
    for sid, st in styles.REGISTRY.items():
        assert maps[entries[sid]] == set(st.templates), sid
        assert st.default_template("transition", set(), 0).endswith(".transition")
        assert st.default_template("screen_highlight", set(), 0).endswith(".highlight")


def test_style_registry_rejects_incomplete_styles() -> None:
    from app.styles import StyleDefinition, register

    def bad(**kw: Any) -> StyleDefinition:
        return StyleDefinition(
            id="nuevo", name="Nuevo", palette=lambda c: {}, default_template=lambda *a: "x.a", **kw
        )

    with pytest.raises(ValueError):
        register(bad(templates={"x.panel": "panel"}))  # sin transición ni resaltado
    with pytest.raises(ValueError):
        register(bad(templates={"x.transition": "", "y.highlight": ""}))  # prefijos distintos
    with pytest.raises(ValueError):
        register(
            StyleDefinition(
                id="motion_tech",
                name="dup",
                templates={},
                palette=lambda c: {},
                default_template=lambda *a: "",
            )
        )


# ---------------------------------------------------------------------------
# Regresiones de la revisión de código de la Fase 5
# ---------------------------------------------------------------------------


def test_viewport_only_for_plain_overlays() -> None:
    from app.services.animations import viewport

    base = {"mode": "overlay", "template": "tech.panel", "width": 1080, "height": 1920,
            "region": {"x": 0.06, "y": 0.15, "w": 0.88, "h": 0.12}, "custom": [], "pip": None,
            "background": "none", "chainIn": None}  # fmt: skip
    vp = viewport(base)
    assert vp and vp["y"] < 0.15 * 1920 and vp["y"] + vp["h"] > 0.27 * 1920
    assert vp["w"] % 2 == 0 and vp["h"] % 2 == 0
    # Fondo atenuado/desenfocado, pantalla completa, resaltados, transiciones o primitivas
    # libres: encuadre completo (recortarlos dejaría una caja o cortaría trazos).
    for change in ({"background": "dim"}, {"mode": "fullscreen"}, {"template": "tech.highlight"},
                   {"template": "tech.transition"}, {"custom": [{"type": "rect"}]}):  # fmt: skip
        assert viewport({**base, **change}) is None, change
    # Continuidad: incluye la región de la animación anterior (el contenedor se transforma).
    chained = viewport({**base, "chainIn": {"x": 0.06, "y": 0.5, "w": 0.88, "h": 0.1}})
    assert chained and chained["y"] + chained["h"] >= 0.6 * 1920


def test_budget_cap_and_reservations(client: TestClient, disk: Path, media, fake_cli) -> None:
    from app.db import session_scope
    from app.domain.preferences import ClaudePreferences
    from app.jobs.runner import create_job
    from app.services import claude_budget
    from app.services.planning import PlanError

    prefs = ClaudePreferences(max_requests_per_operation=2, daily_request_limit=10)
    with session_scope() as s:
        # Una operación que necesita más solicitudes que el tope no empieza.
        with pytest.raises(PlanError) as e:
            claude_budget.preflight(s, prefs, claude_budget.estimate(prefs, "animate", 3), False)
        assert e.value.code == "cap_too_low"
        # Lo reservado por operaciones en cola cuenta para el límite de 24 h.
        create_job(s, "plan_generate", payload={"budget": {"max_calls": 9}, "session_id": "x"})
        assert claude_budget.status(s, prefs)["reserved"] == 9
        with pytest.raises(PlanError) as e:
            claude_budget.preflight(s, prefs, claude_budget.estimate(prefs, "revise"), False)
        assert e.value.code == "budget_confirm"
        s.rollback()


def test_restore_marks_stale_jobs_failed(client: TestClient, app_home: Path) -> None:
    from app.db import session_scope
    from app.jobs.runner import create_job

    name = client.post("/api/system/backups").json()["name"]
    # La copia se toma con una tarea «en cola» (simulada directamente en la base copiada).
    import sqlite3

    bak = app_home / "backups" / name
    with session_scope() as s:
        create_job(s, "plan_generate", payload={})
        s.flush()
        jid = s.query(__import__("app.models", fromlist=["Job"]).Job).first().id
        s.rollback()
    con = sqlite3.connect(bak)
    con.execute(
        "insert into jobs (id, kind, status, payload, progress, created_at) values (?, 'plan_generate', 'queued', '{}', 0, '2026-10-09 00:00:00')",
        (jid,),
    )
    con.commit()
    con.close()
    r = client.post(f"/api/system/backups/{name}/restore", json={"confirm": True})
    assert r.status_code == 200, r.text
    assert r.json()["stale_jobs"] == 1
    job = client.get(f"/api/jobs/{jid}").json()
    assert job["status"] == "failed" and "copia de seguridad" in job["error"]


def test_in_use_version_follows_the_real_direction(
    client: TestClient, disk: Path, media, fake_cli
) -> None:
    """Abrir la escena antes de generar su dirección y luego generarla: la versión en uso
    refleja la dirección real (la que se exporta), no la vacía registrada antes."""
    from app.db import session_scope
    from app.models import AnimationDirection, new_id
    from app.services import animations as anim

    _use_fake(client, fake_cli["cli"])
    pid, _ = _project(client, disk, media)
    iid = _approved(client, pid)[0]["intervention_id"]
    v1 = client.get(f"/api/projects/{pid}/scenes/{iid}").json()["versions"][0]
    assert v1["direction"] == "compilador"
    with session_scope() as s:
        ap = anim.load_approved(s, pid)
        s.add(AnimationDirection(id=new_id("ad"), plan_id=ap.plan_id, plan_version=ap.version,
                                 intervention_id=iid, direction={"template": "tech.panel", "items": []},
                                 source="claude"))  # fmt: skip
    sc = client.get(f"/api/projects/{pid}/scenes/{iid}").json()
    cur = next(v for v in sc["versions"] if v["in_use"])
    assert cur["direction"] == "claude" and cur["template"] == "tech.panel"
    assert next(v for v in sc["versions"] if v["number"] == 1)["status"] == "archived"


def test_probe_failure_does_not_delete_a_clip(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import subprocess as sp

    from app.services import animations as anim

    clip = tmp_path / "c.mov"
    clip.write_bytes(b"x" * 100)

    def boom(*a: Any, **k: Any) -> Any:
        raise sp.TimeoutExpired("ffprobe", 60)

    monkeypatch.setattr(anim.subprocess, "run", boom)
    assert anim.valid_clip(clip, {"width": 10, "height": 10, "durationInFrames": 5}) is True
    assert clip.exists()
