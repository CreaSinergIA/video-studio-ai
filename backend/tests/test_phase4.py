"""Pruebas de la Fase 4: motor de animaciones, composición y exportación con animaciones.

Dos niveles:

- **Sin motor** (siempre): compilador de especificaciones, sincronía con palabras, zonas
  seguras, validación de la dirección de Claude, efectos de sonido, composición real con FFmpeg
  (clip con alfa sintético), aislamiento del proceso de render y API sin motor.
- **Render real** (``VSA_TEST_REMOTION=1``): Remotion + navegador de render ya instalados en
  el equipo (se enlazan al directorio temporal de la prueba). Genera animaciones de verdad,
  vistas previas, exportación con animaciones, cancelación y reutilización de la caché.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import time
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from tests.conftest import FFMPEG, sha256, wait_idle
from tests.test_phase3 import _calls, _generate, _project, _use_fake, fake_cli  # noqa: F401

REAL_ENGINE = os.environ.get("VSA_TEST_REMOTION") == "1"
# Navegador de render ya instalado por esta edición (o el indicado en VSA_TEST_ENGINES_DIR).
ENGINES = Path(
    os.environ.get("VSA_TEST_ENGINES_DIR")
    or Path.home() / "Library/Application Support/VideoStudioAI-Community/engines"
)


def _ffprobe(path: Path) -> dict[str, Any]:
    out = subprocess.run(
        [shutil.which("ffprobe") or "/opt/homebrew/bin/ffprobe", "-v", "error", "-show_streams",
         "-show_format", "-of", "json", str(path)],
        check=True, capture_output=True, text=True,
    ).stdout  # fmt: skip
    return json.loads(out)


def _frame_rgb(path: Path, t: float, x: int, y: int) -> tuple[int, int, int]:
    raw = subprocess.run(
        [FFMPEG, "-v", "error", "-ss", f"{t}", "-i", str(path), "-frames:v", "1",
         "-vf", f"crop=2:2:{x}:{y}", "-f", "rawvideo", "-pix_fmt", "rgb24", "-"],
        check=True, capture_output=True,
    ).stdout  # fmt: skip
    return raw[0], raw[1], raw[2]


def _clock(words: list[tuple[str, float]]):
    from app.services.animation_spec import WordClock

    ws = [
        {"id": f"w{k + 1:06d}", "text": t, "start": s, "end": s + 0.25}
        for k, (t, s) in enumerate(words)
    ]
    return WordClock([{"id": "s1", "start": 0, "end": 10, "text": "", "words": ws}])


def _config():
    from app.domain.edit_config import EditConfig

    return EditConfig()


def _iv(**extra: Any) -> dict[str, Any]:
    iv = {
        "id": "iv_test0001",
        "type": "diagram",
        "status": "accepted",
        "start": 1.0,
        "end": 4.0,
        "goal": "Explicar el flujo",
        "visual_description": "Nodos que se conectan",
        "composition": {"layout": "overlay_top", "background": "original_video",
                        "region": {"x": 0.05, "y": 0.05, "w": 0.9, "h": 0.25}},
        "elements": [
            {"kind": "diagram_node", "text": "Datos", "description": "", "role": "primary"},
            {"kind": "diagram_node", "text": "Proceso", "description": "", "role": "secondary"},
            {"kind": "diagram_node", "text": "Resultado", "description": "", "role": "secondary"},
        ],
        "motion": {"entry": "fade", "exit": "fade", "easing": "smooth", "camera": "none",
                   "emphasis": "", "entry_seconds": 0.4, "exit_seconds": 0.3},
        "transitions": {"into": "cut", "out": "cut"},
        "sfx": [{"kind": "pop", "at": 1.2, "description": ""}],
        "intensity": "medium",
        "avoid_face": True,
        "subtitles": "keep",
        "protected_regions": [],
    }  # fmt: skip
    iv.update(extra)
    return iv


CLOCK_WORDS = [("Primero", 1.1), ("llegan", 1.4), ("los", 1.6), ("datos", 1.8), ("luego", 2.3),
               ("el", 2.5), ("proceso", 2.7), ("y", 3.1), ("sale", 3.2), ("el", 3.4),
               ("resultado", 3.5)]  # fmt: skip


def _compile(style: str = "motion_tech", **kw: Any):
    from app.services import animation_spec

    return animation_spec.compile_intervention(
        kw.pop("iv", None) or _iv(),
        plan_version=3,
        style=style,
        config=_config(),
        clock=kw.pop("clock", None) or _clock(CLOCK_WORDS),
        width=1080,
        height=1920,
        fps=30.0,
        subtitle_band=kw.pop("band", (0.62, 0.74)),
        direction=kw.pop("direction", None),
    )


# ---------------------------------------------------------------------------
# Compilador de especificaciones
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("style", ["motion_tech", "minimal_motion", "creative_explainer"])
def test_compile_each_style_has_its_own_grammar(style: str) -> None:
    from app.services import animation_spec

    out, _ = _compile(style)
    spec = out["spec"]
    assert spec["version"] == animation_spec.SPEC_VERSION and spec["planVersion"] == 3
    assert spec["style"] == style and spec["template"] in animation_spec.TEMPLATES[style]
    assert spec["width"] == 1080 and spec["height"] == 1920 and spec["fps"] == 30.0
    assert spec["durationInFrames"] == 90  # 3 s exactos del plan aprobado
    assert spec["mode"] == "overlay" and len(spec["items"]) == 3
    # Paletas distintas por estilo (la gramática visual no es la misma con otro color).
    palettes = {s: _compile(s)[0]["spec"]["palette"]["accent"] for s in animation_spec.TEMPLATES}
    assert len(set(palettes.values())) == 3


def test_items_appear_on_the_spoken_word() -> None:
    out, notes = _compile()
    cues = {it["text"]: it["cue"] for it in out["spec"]["items"]}
    # «datos» se dice a 1.8 s → 0.8 s después del inicio (1.0 s) → fotograma 24 a 30 fps.
    assert cues == {"Datos": 24, "Proceso": 51, "Resultado": 75}
    assert not [n for n in notes if "sin palabra medida" in n]


def test_fullscreen_and_transition_modes() -> None:
    full, _ = _compile(iv=_iv(type="fullscreen_animation",
                              composition={"layout": "fullscreen", "background": "style_background"}))  # fmt: skip
    assert full["spec"]["mode"] == "fullscreen" and full["spec"]["background"] == "style"
    tr, _ = _compile(iv=_iv(type="transition", elements=[]))
    assert tr["spec"]["mode"] == "transition" and tr["spec"]["template"].endswith(".transition")


def test_safe_region_avoids_faces_and_subtitles() -> None:
    from app.services.animation_spec import safe_region

    face = {"x": 0.3, "y": 0.2, "w": 0.4, "h": 0.25}
    region, notes = safe_region(
        {"x": 0.1, "y": 0.25, "w": 0.8, "h": 0.3}, "overlay_top", [face], (0.62, 0.74), False
    )
    top, bottom = region["y"], region["y"] + region["h"]
    assert bottom <= face["y"] + 1e-6 or top >= face["y"] + face["h"] - 1e-6
    assert bottom <= 0.62 + 1e-6 or top >= 0.74 - 1e-6
    assert notes  # la corrección queda registrada


def test_overlay_never_covers_face_in_compiled_spec() -> None:
    face = {"x": 0.25, "y": 0.12, "w": 0.5, "h": 0.3}
    out, _ = _compile(iv=_iv(protected_regions=[face]))
    r = out["spec"]["region"]
    assert r["y"] + r["h"] <= face["y"] + 1e-6 or r["y"] >= face["y"] + face["h"] - 1e-6


# ---------------------------------------------------------------------------
# Dirección de Claude: lenguaje declarativo validado
# ---------------------------------------------------------------------------


def _direction(**extra: Any) -> dict[str, Any]:
    d = {
        "template": "tech.nodes",
        "title": "Del dato al resultado",
        "items": [
            {"kind": "diagram_node", "text": "Datos", "icon": "Database", "role": "primary",
             "cue_word": "w000004"},
            {"kind": "diagram_node", "text": "Proceso", "icon": "NoExiste", "cue_word": "proceso"},
            {"kind": "diagram_node", "text": "Resultado", "cue_word": "w000011", "state": "done",
             "state_word": "w000011"},
        ],
        "links": [{"from": 0, "to": 1}, {"from": 1, "to": 2}, {"from": 0, "to": 7}],
        "custom": [],
    }  # fmt: skip
    d.update(extra)
    return d


def test_direction_is_validated_and_synced() -> None:
    out, _ = _compile(direction=_direction())
    spec = out["spec"]
    items = spec["items"]
    assert spec["template"] == "tech.nodes" and spec["title"] == "Del dato al resultado"
    assert [i["text"] for i in items] == ["Datos", "Proceso", "Resultado"]
    assert items[0]["icon"] == "Database" and items[1]["icon"] is None  # icono fuera de la lista
    # «proceso» (palabra en lugar de id) se busca dentro del tramo: 2.7 s → fotograma 51.
    assert items[1]["cue"] == 51
    assert items[2]["state"] == "done" and items[2]["stateCue"] == 75
    assert [(ln["from"], ln["to"]) for ln in spec["links"]] == [("d0", "d1"), ("d1", "d2")]


def test_direction_cannot_escape_the_approved_span_or_template_set() -> None:
    d = _direction(template="exp.character")  # plantilla de otro estilo
    d["items"][0]["cue_word"] = "w000001"  # existe, pero dentro del tramo
    d["items"][1]["cue_word"] = "w999999"  # no existe
    out, notes = _compile(direction=d, clock=_clock([*CLOCK_WORDS, ("después", 9.0)]))
    spec = out["spec"]
    assert spec["template"] != "exp.character"
    assert any("no válida" in n for n in notes) and any("w999999" in n for n in notes)
    d2 = _direction()
    d2["items"][0]["cue_word"] = "w000012"  # «después», a 9 s: fuera del tramo aprobado
    out2, notes2 = _compile(direction=d2, clock=_clock([*CLOCK_WORDS, ("después", 9.0)]))
    assert any("fuera del tramo" in n for n in notes2)
    assert 0 <= out2["spec"]["items"][0]["cue"] < out2["spec"]["durationInFrames"]
    # El tiempo y la duración siguen siendo los del plan aprobado.
    assert out2["spec"]["durationInFrames"] == 90


def test_duplicates_and_empty_items_are_tidied() -> None:
    d = _direction(template="min.statement")
    d["items"] = [
        {"kind": "headline", "text": "Las herramientas ya existen.", "role": "primary",
         "cue_word": "w000001"},
        {"kind": "keyword", "text": "ya existen", "cue_word": "w000004"},
        {"kind": "keyword", "text": "?", "cue_word": "w000005"},
    ]  # fmt: skip
    out, notes = _compile("minimal_motion", direction=d)
    items = out["spec"]["items"]
    assert [i["text"] for i in items] == ["Las herramientas ya existen."]
    assert items[0]["state"] == "highlight" and items[0]["stateCue"] == 24
    assert any("repetía parte" in n for n in notes) and any("sin contenido" in n for n in notes)


def test_custom_primitives_policy() -> None:
    prim = {"type": "rect", "x": 0.6, "y": 0.1, "w": 0.3, "h": 0.1, "fill": True}
    # Con elementos de plantilla: las primitivas libres se descartan (podrían tapar textos).
    out, notes = _compile(direction=_direction(custom=[prim]))
    assert out["spec"]["custom"] == [] and any("descartadas" in n for n in notes)
    # Composición propia (sin elementos): se admite, validada.
    custom = [
        prim,
        {"type": "path", "x": 0, "y": 0, "d": "M 0.1 0.1 L 0.5 0.2 Q 0.6 0.3 0.7 0.1 Z"},
        {"type": "path", "x": 0, "y": 0, "d": "M 0 0 A 1 1 0 0 1 1 1"},  # orden no permitida
        {"type": "line", "x": 0.1, "y": 0.1, "x2": 1.4, "y2": 0.2},  # fuera del encuadre
        {"type": "arrow", "x": 0.1, "y": 0.6, "x2": 0.4, "y2": 0.7},  # sobre los subtítulos
        {"type": "text", "x": 0.1, "y": 0.2, "h": 0.04, "text": "Hola"},
    ]
    out, notes = _compile(direction=_direction(items=[], links=[], custom=custom))
    spec = out["spec"]
    assert spec["template"] == "custom" and spec["items"] == []
    assert [p["type"] for p in spec["custom"]] == ["rect", "path", "text"]
    assert any("no permitidas" in n for n in notes)
    assert any("fuera del encuadre" in n for n in notes)
    assert any("subtítulos" in n for n in notes)


def test_direction_schema_is_closed() -> None:
    from pydantic import ValidationError

    from app.services.animation_direction import DirAnimation, DirResponse

    ok = {"id": "iv_1", "template": "tech.nodes", "items": [], "rationale": "r"}
    DirAnimation.model_validate(ok)
    for bad in (
        {**ok, "code": "fetch('http://x')"},  # campos extra: prohibido
        {**ok, "template": "custom.js"},
        {**ok, "items": [{"kind": "headline", "text": "x" * 49}]},
        {**ok, "custom": [{"type": "rect", "x": 2, "y": 0}]},
    ):
        with pytest.raises(ValidationError):
            DirAnimation.model_validate(bad)
    schema = DirResponse.model_json_schema()
    assert "animations" in schema["properties"]


# ---------------------------------------------------------------------------
# Efectos de sonido y composición real con FFmpeg
# ---------------------------------------------------------------------------


def test_sfx_are_programmatic_and_deterministic(app_home: Path) -> None:
    import numpy as np

    from app.services import sfx

    assert {"whoosh", "pop", "click", "ding", "glitch", "impact"} <= set(sfx.KINDS)
    for kind in sfx.KINDS:
        a, b = sfx.synth(kind), sfx.synth(kind)
        assert np.array_equal(a, b)
        peak = float(np.max(np.abs(a)))
        # Fase 4.1: normalizado por energía (−16 dBFS en 100 ms) con techo de pico de −1 dBFS.
        assert peak <= 10 ** (-1 / 20) + 1e-6
        assert -22.0 <= sfx.short_rms_db(a) <= -15.9
        # Las variantes suenan distinto (no son la misma muestra repetida).
        assert not np.array_equal(sfx.synth(kind, 1)[: len(a)], a[: len(sfx.synth(kind, 1))])
    p = sfx.path_for("pop")
    info = _ffprobe(p)["streams"][0]
    assert info["sample_rate"] == "48000" and info["channels"] == 2
    assert [c["kind"] for c in sfx.catalog()] == list(sfx.KINDS)


@pytest.fixture
def alpha_clip(tmp_path: Path) -> Path:
    """Clip ProRes 4444 con alfa (como los de Remotion): cuadro rojo opaco a la izquierda."""
    out = tmp_path / "clip.mov"
    subprocess.run(
        [FFMPEG, "-v", "error", "-y", "-f", "lavfi", "-i", "color=c=black@0.0:s=640x360:d=1:r=30",
         "-vf", "format=yuva444p10le,drawbox=x=0:y=0:w=200:h=200:color=red@1.0:t=fill",
         "-c:v", "prores_ks", "-profile:v", "4444", "-pix_fmt", "yuva444p10le", str(out)],
        check=True,
    )  # fmt: skip
    return out


def test_compositor_overlays_clip_keeps_audio_and_duration(
    app_home: Path, media: dict[str, Path], alpha_clip: Path, tmp_path: Path
) -> None:
    from app.services import compositor

    src = media["horizontal"]  # 640×360, 30 fps, 3 s, tono de 440 Hz
    before = sha256(src)
    plan = compositor.preview_plan(640, 360, short_side=360)
    comp = compositor.Composition(
        clips=[compositor.ClipLayer(alpha_clip, 1.0, 2.0, "overlay")],
        sfx=[compositor.SfxCue("pop", 1.0)],
    )
    out = tmp_path / "out.mp4"
    compositor.compose(src, out, plan, comp, None, 3.0, preview=True)
    info = _ffprobe(out)
    v = next(s for s in info["streams"] if s["codec_type"] == "video")
    assert (v["width"], v["height"]) == (640, 360)
    assert abs(float(info["format"]["duration"]) - 3.0) < 0.1
    assert any(s["codec_type"] == "audio" for s in info["streams"])
    r, g, b = _frame_rgb(out, 1.5, 50, 50)
    assert r > 180 and g < 80 and b < 80  # el clip se ve en su tramo
    r0, g0, _ = _frame_rgb(src, 0.5, 50, 50)
    r1, g1, _ = _frame_rgb(out, 0.5, 50, 50)
    assert abs(r0 - r1) < 40 and abs(g0 - g1) < 40  # fuera del tramo, el original
    assert _frame_rgb(out, 1.5, 500, 300) != (255, 0, 0)  # zona transparente: original
    assert sha256(src) == before  # el original no se toca


def test_compositor_without_sfx_preserves_voice_level(
    app_home: Path, media: dict[str, Path], alpha_clip: Path, tmp_path: Path
) -> None:
    from app.services import compositor

    src = media["horizontal"]
    plan = compositor.preview_plan(640, 360, short_side=360)
    comp = compositor.Composition(clips=[compositor.ClipLayer(alpha_clip, 0.5, 1.5, "overlay")])
    out = tmp_path / "out.mp4"
    compositor.compose(src, out, plan, comp, None, 3.0, preview=True)

    def mean_db(p: Path) -> float:
        err = subprocess.run(
            [FFMPEG, "-nostdin", "-i", str(p), "-af", "volumedetect", "-f", "null", "-"],
            capture_output=True, text=True,
        ).stderr  # fmt: skip
        return float(err.split("mean_volume:")[1].split("dB")[0])

    assert abs(mean_db(out) - mean_db(src)) < 1.0


def test_render_process_env_has_no_secrets(monkeypatch: pytest.MonkeyPatch) -> None:
    from app.services import render_engine

    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-secreto")
    monkeypatch.setenv("CLAUDE_CODE_OAUTH_TOKEN", "secreto")
    monkeypatch.setenv("AWS_SECRET_ACCESS_KEY", "secreto")
    env = render_engine._env(Path("/usr/local/bin/node"))
    assert not {k for k in env if "KEY" in k or "TOKEN" in k or "SECRET" in k}
    assert env["REMOTION_DISABLE_TELEMETRY"] == "1"
    assert env["PATH"].startswith("/usr/local/bin:")


def test_spec_hash_depends_on_renderer_source(monkeypatch: pytest.MonkeyPatch) -> None:
    from app.services import animations, render_engine

    spec = _compile()[0]["spec"]
    monkeypatch.setattr(render_engine, "source_hash", lambda: "a" * 16)
    h1 = animations.spec_hash(spec)
    # Volver a aprobar un plan idéntico (otra versión) no obliga a renderizar de nuevo.
    assert animations.spec_hash({**spec, "planVersion": 99}) == h1
    assert animations.spec_hash({**spec, "durationInFrames": 91}) != h1
    monkeypatch.setattr(render_engine, "source_hash", lambda: "b" * 16)
    assert animations.spec_hash(spec) != h1


# ---------------------------------------------------------------------------
# API sin motor instalado
# ---------------------------------------------------------------------------


def test_api_without_engine_reports_clearly(
    client: TestClient, disk: Path, media, fake_cli
) -> None:
    _use_fake(client, fake_cli["cli"])
    pid, _ = _project(client, disk, media)
    st = client.get("/api/animations/engine").json()
    assert st["ready"] is False and st["browser"]["installed"] is False
    assert st["browser"]["source"].startswith("https://storage.googleapis.com/chrome-for-testing")
    # Sin plan aprobado: no hay nada que animar.
    a = client.get(f"/api/projects/{pid}/animations").json()
    assert a["approved_version"] is None and a["items"] == []
    r = client.post(f"/api/projects/{pid}/animations/prepare", json={"use_claude": False})
    assert r.status_code == 409 and r.json()["code"] == "not_approved"
    _generate(client, pid, style="motion_tech")
    assert (
        client.post(f"/api/projects/{pid}/plan/bulk", json={"status": "accepted"}).status_code
        == 200
    )
    assert client.post(f"/api/projects/{pid}/plan/approve", json={}).status_code == 200
    a = client.get(f"/api/projects/{pid}/animations").json()
    assert a["approved_version"] is not None and a["items"]
    kept = [i for i in a["items"] if i["type"] == "keep_original"]
    assert all(i["status"] == "kept" for i in kept)
    assert all(i["status"] == "pending" for i in a["items"] if i["type"] != "keep_original")
    r = client.post(f"/api/projects/{pid}/animations/prepare", json={"use_claude": False})
    assert r.status_code == 409 and r.json()["code"] == "engine_missing"
    # Exportar con animaciones sin motor: falla con un mensaje claro, no exporta a medias.
    r = client.post(f"/api/projects/{pid}/exports", json={"with_animations": True})
    assert r.status_code == 202, r.text
    wait_idle(120)
    ex = client.get(f"/api/projects/{pid}/exports").json()[0]
    assert ex["status"] == "failed" and "motor" in (ex["error"] or "").lower()
    assert not list((disk / "projects").rglob("*.partial*"))
    # El catálogo de efectos funciona sin motor.
    assert client.get("/api/animations/sfx/pop").status_code == 200
    assert client.get("/api/animations/sfx/../../etc/passwd").status_code == 404


# ---------------------------------------------------------------------------
# Render real (Remotion + navegador instalados en el equipo)
# ---------------------------------------------------------------------------


@pytest.fixture
def engine_home(app_home: Path) -> Path:
    if not REAL_ENGINE:
        pytest.skip("Render real desactivado (VSA_TEST_REMOTION=1 para activarlo).")
    if not ENGINES.is_dir():
        pytest.skip("El navegador de render no está instalado en este equipo.")
    app_home.mkdir(parents=True, exist_ok=True)
    (app_home / "engines").symlink_to(ENGINES)
    return app_home


def test_real_render_preview_export_cancel_and_cache(
    engine_home: Path, client: TestClient, disk: Path, media, fake_cli
) -> None:
    _use_fake(client, fake_cli["cli"])
    pid, _ = _project(client, disk, media, key="vertical")
    src = next(p for p in (disk / "projects").rglob("*.mp4") if p.name == media["vertical"].name)
    before = sha256(src)
    _generate(client, pid, style="creative_explainer")
    client.post(f"/api/projects/{pid}/plan/bulk", json={"status": "accepted"})
    assert client.post(f"/api/projects/{pid}/plan/approve", json={}).status_code == 200
    assert client.get("/api/animations/engine").json()["ready"] is True

    # Cancelación: se detiene el render y no quedan clips a medias.
    r = client.post(f"/api/projects/{pid}/animations/prepare", json={"use_claude": False})
    job = r.json()["job"]
    for _ in range(100):
        j = client.get(f"/api/jobs/{job['id']}").json()
        if j["status"] == "running" and (j.get("stage") or "").startswith("Renderizando"):
            break
        time.sleep(0.1)
    assert client.post(f"/api/jobs/{job['id']}/cancel").status_code in (200, 202)
    wait_idle(120)
    assert client.get(f"/api/jobs/{job['id']}").json()["status"] == "cancelled"
    assert not list((disk / "projects").rglob("*.partial.mov"))

    # Generación con la dirección (simulada) de Claude.
    r = client.post(f"/api/projects/{pid}/animations/prepare", json={"use_claude": True})
    assert r.status_code == 202, r.text
    wait_idle(600)
    st = client.get(f"/api/projects/{pid}/animations").json()
    animated = [i for i in st["items"] if i["status"] != "kept"]
    assert animated and all(i["status"] == "ready" for i in animated), st
    assert all(i["direction"] == "claude" for i in animated)
    assert any("descartadas" in n for i in animated for n in i["notes"])
    assert any(c["schema"] == ["animations"] for c in _calls(fake_cli["log"]))
    clips = list((disk / "projects").rglob("animations/clips/*.mov"))
    assert len(clips) >= len(animated)
    s0 = _ffprobe(clips[0])["streams"][0]
    assert s0["codec_name"] == "prores" and "a" in s0["pix_fmt"]  # con canal alfa
    # Resolución del original (360×640) o, desde la Fase 5, solo la zona útil de la
    # superposición (mismas coordenadas, sin reescalar).
    from app.db import session_scope
    from app.models import AnimationRender

    with session_scope() as s:
        row = next(
            r
            for r in s.query(AnimationRender).filter(AnimationRender.purpose == "final")
            if r.file_rel and r.file_rel.endswith(clips[0].name)
        )
        vp = row.spec.get("viewport")
        assert (row.spec["width"], row.spec["height"]) == (360, 640)
        want = (vp["w"], vp["h"]) if vp else (360, 640)
    assert (s0["width"], s0["height"]) == want

    # Caché: una segunda generación no vuelve a renderizar.
    client.post(f"/api/projects/{pid}/animations/prepare", json={"use_claude": True})
    wait_idle(120)
    again = client.get(f"/api/projects/{pid}/animations").json()
    assert all(i["reused"] for i in again["items"] if i["status"] == "ready")

    # Vista previa real del tramo.
    iid = animated[0]["intervention_id"]
    assert client.post(f"/api/projects/{pid}/animations/{iid}/preview").status_code == 202
    wait_idle(300)
    item = next(
        i
        for i in client.get(f"/api/projects/{pid}/animations").json()["items"]
        if i["intervention_id"] == iid
    )
    assert item["preview"]
    res = client.get(item["preview"]["url"])
    assert res.status_code == 200 and res.headers["content-type"] == "video/mp4"

    # Exportación con animaciones: misma duración, tamaño y fps; audio presente.
    r = client.post(f"/api/projects/{pid}/exports", json={"with_animations": True})
    assert r.status_code == 202, r.text
    wait_idle(600)
    ex = client.get(f"/api/projects/{pid}/exports").json()[0]
    assert ex["status"] == "succeeded", ex
    assert ex["settings"]["with_animations"] is True and ex["settings"]["animations"]["animations"]
    out = disk / ex["file_rel"]
    info = _ffprobe(out)
    v = next(s for s in info["streams"] if s["codec_type"] == "video")
    assert (v["width"], v["height"]) == (360, 640) and v["avg_frame_rate"] == "25/1"
    assert abs(float(info["format"]["duration"]) - 3.0) < 0.15
    assert any(s["codec_type"] == "audio" for s in info["streams"])
    assert sha256(src) == before

    # Restaurar y volver a aprobar el mismo plan: la dirección de Claude de las intervenciones
    # sin cambios se reutiliza (sin solicitudes nuevas) y se marca así.
    calls_before = len(_calls(fake_cli["log"]))
    approved = client.get(f"/api/projects/{pid}/plan").json()["plan"]["approved_version"]
    assert client.post(f"/api/projects/{pid}/plan/versions/{approved}/restore").status_code == 200
    assert client.post(f"/api/projects/{pid}/plan/approve", json={}).status_code == 200
    again = client.get(f"/api/projects/{pid}/plan").json()["plan"]["approved_version"]
    assert again > approved
    client.post(f"/api/projects/{pid}/animations/prepare", json={"use_claude": True})
    wait_idle(300)
    st2 = client.get(f"/api/projects/{pid}/animations").json()
    assert st2["approved_version"] == again
    assert all(i["direction"] == "claude" for i in st2["items"] if i["status"] != "kept")
    assert len(_calls(fake_cli["log"])) == calls_before


def test_fullscreen_content_avoids_subtitle_band_and_pip() -> None:
    face = {"x": 0.3, "y": 0.15, "w": 0.4, "h": 0.2}
    iv = _iv(type="fullscreen_animation", protected_regions=[face],
             composition={"layout": "picture_in_picture", "background": "style_background"})  # fmt: skip
    out, notes = _compile("creative_explainer", iv=iv, band=(0.62, 0.74))
    spec = out["spec"]
    pip, r = spec["pip"], spec["region"]
    assert pip["shape"] == "circle" and r["y"] >= pip["y"] + pip["h"]
    assert r["y"] + r["h"] <= 0.62 or r["y"] >= 0.74
    assert any("subtítulos" in n for n in notes)
    # Si el plan oculta los subtítulos en ese tramo, el contenido puede usar esa franja.
    out2, _ = _compile("creative_explainer", iv={**iv, "subtitles": "hide"}, band=(0.62, 0.74))
    assert out2["spec"]["region"]["h"] > r["h"]


def test_container_enters_just_before_first_spoken_item() -> None:
    from app.services.animation_spec import entry_start

    late = _clock([("relleno", 1.1), *[(w, t + 1.5) for w, t in CLOCK_WORDS]])
    out, _ = _compile("creative_explainer", clock=late)
    spec = out["spec"]
    first = min(i["cue"] for i in spec["items"])
    start = entry_start(spec)
    assert 0 < start < first and first - start <= spec["entryFrames"] + 9
    tech, _ = _compile("motion_tech", clock=late)
    assert entry_start(tech["spec"]) == 0  # Tech muestra su título desde el principio


def test_compositor_circular_pip_over_fullscreen(
    app_home: Path, media: dict[str, Path], tmp_path: Path
) -> None:
    from app.services import compositor

    full = tmp_path / "full.mov"
    subprocess.run(
        [FFMPEG, "-v", "error", "-y", "-f", "lavfi", "-i", "color=c=blue:s=640x360:d=1:r=30",
         "-vf", "format=yuva444p10le", "-c:v", "prores_ks", "-profile:v", "4444",
         "-pix_fmt", "yuva444p10le", str(full)],
        check=True,
    )  # fmt: skip
    src = media["horizontal"]
    plan = compositor.preview_plan(640, 360, short_side=360)
    box = {"x": 0.3, "y": 0.1, "w": 0.4, "h": 0.7, "shape": "circle"}
    comp = compositor.Composition(clips=[compositor.ClipLayer(
        full, 1.0, 2.0, "fullscreen", pip_src={"x": 0.3, "y": 0.1, "w": 0.4, "h": 0.7},
        pip_box=box)])  # fmt: skip
    out = tmp_path / "pip.mp4"
    t = time.monotonic()
    compositor.compose(src, out, plan, comp, None, 3.0, preview=True)
    assert time.monotonic() - t < 30
    r, _, b = _frame_rgb(out, 1.6, 10, 10)
    assert b > 150 and r < 80  # fondo de la animación
    # Dentro del círculo, el video original (en ese punto testsrc2 es amarillo).
    got, ref = _frame_rgb(out, 1.6, 250, 140), _frame_rgb(src, 1.6, 250, 140)
    assert all(abs(a - b) <= 12 for a, b in zip(got, ref, strict=True))
    corner = _frame_rgb(out, 1.6, int(640 * 0.3) + 4, int(360 * 0.1) + 4)
    assert corner[2] > 150 and corner[0] < 80  # esquina del recuadro, fuera del círculo


def _plan(w: int, h: int, *, prores: bool = False, fps: str = "original"):
    from app.services.exporter import ExportPlan

    if prores:
        return ExportPlan(w, h, fps, "mov", "prores", "software",
                          ["-c:v", "prores_ks", "-profile:v", "3"], "yuv422p10le",
                          ["-map", "0:a?", "-c:a", "pcm_s24le"], [], 0)  # fmt: skip
    return ExportPlan(w, h, fps, "mp4", "h264", "software", ["-c:v", "libx264", "-crf", "16"],
                      "yuv420p", ["-map", "0:a?", "-c:a", "aac"], [], 0)  # fmt: skip


def test_camera_move_zooms_toward_the_face_center(
    app_home: Path, alpha_clip: Path, tmp_path: Path
) -> None:
    from app.services import compositor

    ramp = tmp_path / "ramp.mp4"
    subprocess.run(
        [FFMPEG, "-v", "error", "-y", "-f", "lavfi",
         "-i", "color=black:s=640x360:d=2:r=30,format=gray,geq=lum='X/W*255'",
         "-c:v", "libx264", "-pix_fmt", "yuv444p", "-crf", "1", str(ramp)],
        check=True,
    )  # fmt: skip
    comp = compositor.Composition(
        camera=[compositor.CameraMove(0.5, 1.5, "slow_push_in", 0.9, 0.5)], fps_rate="30/1"
    )
    out = tmp_path / "cam.mp4"
    compositor.compose(ramp, out, _plan(640, 360), comp, None, 2.0, audio_tracks=0)
    info = _ffprobe(out)["streams"][0]
    assert (info["width"], info["height"], info["r_frame_rate"]) == (640, 360, "30/1")
    left_before = _frame_rgb(out, 0.2, 0, 180)[0]
    left_zoomed = _frame_rgb(out, 1.45, 0, 180)[0]
    # Zoom ≈1,07 hacia x=0,9: el borde izquierdo muestra la rampa desplazada (≈ 37 px → ~15).
    assert left_before < 4 and 9 <= left_zoomed <= 22


def test_sfx_on_a_source_without_audio(
    app_home: Path, media: dict[str, Path], alpha_clip: Path, tmp_path: Path
) -> None:
    from app.services import compositor

    src = media["silent"]  # 320×240, 24 fps, 2 s, sin pista de audio
    comp = compositor.Composition(
        clips=[compositor.ClipLayer(alpha_clip, 0.5, 1.5, "overlay")],
        sfx=[compositor.SfxCue("pop", 0.6)],
        duration=2.0,
    )
    out = tmp_path / "silent.mp4"
    compositor.compose(src, out, _plan(320, 240), comp, None, 2.0, audio_tracks=0)
    streams = _ffprobe(out)["streams"]
    audio = [s for s in streams if s["codec_type"] == "audio"]
    assert audio and abs(float(audio[0]["duration"]) - 2.0) < 0.1


def test_ten_bit_sources_stay_ten_bit(
    app_home: Path, media: dict[str, Path], alpha_clip: Path, tmp_path: Path
) -> None:
    from app.services import compositor

    src = media["prores"]  # ProRes 422 10 bits
    comp = compositor.Composition(clips=[compositor.ClipLayer(alpha_clip, 0.5, 1.5, "overlay")])
    args = compositor.build_args(src, tmp_path / "x.mov", _plan(320, 180, prores=True), comp, None)
    graph = args[args.index("-filter_complex") + 1]
    assert "format=yuv444p10le" in graph and "format=yuva444p10le" in graph
    out = tmp_path / "x.mov"
    compositor.compose(src, out, _plan(320, 180, prores=True), comp, None, 2.0)
    v = next(s for s in _ffprobe(out)["streams"] if s["codec_type"] == "video")
    assert v["pix_fmt"] == "yuv422p10le"


def test_custom_path_validation_is_linear_time() -> None:
    from app.services import animation_spec

    start = time.monotonic()
    for bad in ("M " + "1" * 400 + "x", "M 0." + "9" * 500 + " A", "M" + " 1" * 290 + " Q"):
        assert not animation_spec.valid_path(bad)
    assert time.monotonic() - start < 0.5
    assert animation_spec.valid_path(
        "M 0.1 0.2 L 0.5,0.6 C 0.1 0.1 0.2 0.2 0.3 0.3 Q .5 .5 .6 .6 Z"
    )
    assert not animation_spec.valid_path("M 0 0 L 1")  # L necesita x e y


def test_horizontal_frames_use_free_side_columns() -> None:
    from app.services.animation_spec import safe_region

    face = {"x": 0.38, "y": 0.15, "w": 0.24, "h": 0.4}
    region, notes = safe_region(
        {"x": 0.05, "y": 0.1, "w": 0.9, "h": 0.3}, "overlay_top", [face], (0.78, 0.9), False,
        aspect=16 / 9,
    )  # fmt: skip
    assert region["x"] + region["w"] <= face["x"] or region["x"] >= face["x"] + face["w"]
    assert region["h"] >= 0.3 and region["y"] + region["h"] <= 0.78
    assert notes


def test_voice_is_not_delayed_by_the_sfx_mix(
    app_home: Path, media: dict[str, Path], alpha_clip: Path, tmp_path: Path
) -> None:
    import numpy as np

    from app.services import compositor

    src = media["hevc"]  # audio de ruido (no periódico): la correlación no es ambigua

    def pcm(p: Path) -> np.ndarray:
        raw = subprocess.run(
            [FFMPEG, "-v", "error", "-i", str(p), "-vn", "-ac", "1", "-ar", "8000", "-f", "s16le", "-"],
            check=True, capture_output=True,
        ).stdout  # fmt: skip
        return np.frombuffer(raw, dtype=np.int16).astype(np.float64)

    comp = compositor.Composition(
        clips=[compositor.ClipLayer(alpha_clip, 0.2, 1.2, "overlay")],
        sfx=[compositor.SfxCue("click", 1.5)],
    )
    out = tmp_path / "mix.mp4"
    compositor.compose(src, out, _plan(360, 640), comp, None, 2.0)
    a, b = pcm(src)[:12000], pcm(out)[:12000]
    n = min(len(a), len(b))
    corr = np.correlate(b[:n], a[:n], "full")
    lag = int(np.argmax(corr)) - (n - 1)
    assert abs(lag) <= 1  # ≤ 0,125 ms (el limitador compensa su anticipación)
