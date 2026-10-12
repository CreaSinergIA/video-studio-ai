"""Pruebas de la Fase 4.1: mezcla de efectos, zonas seguras de redes sociales y continuidad.

Sin red y sin motor de render (salvo la composición FFmpeg real con clips sintéticos)."""

from __future__ import annotations

import subprocess
from pathlib import Path
from typing import Any

import numpy as np
import pytest

from tests.conftest import FFMPEG

SR = 48000


def _pcm(path: Path) -> np.ndarray:
    raw = subprocess.run(
        [FFMPEG, "-v", "error", "-i", str(path), "-vn", "-ac", "1", "-ar", str(SR), "-f", "f32le", "-"],
        check=True, capture_output=True,
    ).stdout  # fmt: skip
    return np.frombuffer(raw, dtype=np.float32).astype(np.float64)


def _db(x: np.ndarray) -> float:
    return float(20 * np.log10(np.sqrt(np.mean(x**2)) + 1e-12))


def _rms100_max(x: np.ndarray) -> float:
    n = int(SR * 0.1)
    c = np.cumsum(np.concatenate([[0.0], x**2]))
    return float(10 * np.log10(np.max((c[n:] - c[:-n]) / n) + 1e-12))


def _ebur(path: Path) -> tuple[float, float]:
    err = subprocess.run(
        [FFMPEG, "-nostdin", "-i", str(path), "-vn", "-af", "ebur128=peak=true", "-f", "null", "-"],
        capture_output=True, text=True,
    ).stderr  # fmt: skip
    tail = err[err.rfind("Summary:") :]
    return float(tail.split("I:")[1].split()[0]), float(tail.split("Peak:")[1].split()[0])


@pytest.fixture(scope="module")
def voice(tmp_path_factory: pytest.TempPathFactory) -> Path:
    """Voz sintética (habla real del sistema si existe `say`; si no, ruido modulado) de 6 s."""
    d = tmp_path_factory.mktemp("voz")
    out = d / "voz.mov"
    wav = d / "voz.aiff"
    try:
        subprocess.run(["say", "-v", "Paulina", "-o", str(wav),
                        "Las herramientas ya existen. Solo tienes que entender cuál es tu problema."],
                       check=True, timeout=60)  # fmt: skip
        src = ["-i", str(wav)]
    except (OSError, subprocess.SubprocessError):
        src = ["-f", "lavfi", "-i", "anoisesrc=d=6:a=0.3,volume='0.5+0.5*sin(2*PI*3*t)':eval=frame"]
    subprocess.run(
        [FFMPEG, "-v", "error", "-y", "-f", "lavfi", "-i", "color=c=gray:s=320x568:d=6:r=30", *src,
         "-af", "loudnorm=I=-12:TP=-1.0", "-ar", "48000", "-ac", "2", "-shortest",
         "-c:v", "libx264", "-pix_fmt", "yuv420p", "-c:a", "pcm_s24le", "-t", "6", str(out)],
        check=True,
    )  # fmt: skip
    return out


def _plan(w: int, h: int):
    from app.services.exporter import ExportPlan

    return ExportPlan(w, h, "original", "mov", "h264", "software", ["-c:v", "libx264", "-crf", "30"],
                      "yuv420p", ["-map", "0:a?", "-c:a", "pcm_s24le"], [], 0)  # fmt: skip


def _mix(voice: Path, tmp: Path, intensity: str, kinds: list[str]) -> tuple[Path, list[Any]]:
    from app.services import compositor

    cues = [compositor.SfxCue(k, 0.8 + i * 1.2) for i, k in enumerate(kinds)]
    lufs, tp = _ebur(voice)
    comp = compositor.Composition(
        sfx=cues, sfx_volume=70, sfx_intensity=intensity, voice_lufs=lufs, voice_tp=tp
    )
    out = tmp / f"mix-{intensity}.mov"
    compositor.compose(voice, out, _plan(320, 568), comp, None, 6.0)
    return out, cues


def test_sfx_are_clearly_present_under_the_voice(
    app_home: Path, voice: Path, tmp_path: Path
) -> None:
    """Fase 4.1 (P0): los efectos se oyen (no 28–40 dB bajo la voz como en la Fase 4) sin
    superar a la voz, y la intensidad los separa de forma ordenada."""
    from app.services import sfx

    kinds = ["whoosh", "pop", "impact", "riser"]
    from app.services.compositor import ceiling_trim_db

    lufs, vtp = _ebur(voice)
    v = _pcm(voice) * 10 ** (ceiling_trim_db(vtp) / 20)  # la mezcla aplica el ajuste de techo
    levels: dict[str, list[float]] = {}
    for intensity in ("soft", "balanced", "strong"):
        out, cues = _mix(voice, tmp_path, intensity, kinds)
        m = _pcm(out)
        n = min(len(v), len(m))
        diff = m[:n] - v[:n]
        rel = []
        for c in cues:
            a = int(c.at * SR)
            seg = diff[a : a + len(sfx.synth(c.kind))]
            rel.append(_rms100_max(seg) - lufs)
        levels[intensity] = rel
        _, tp = _ebur(out)
        assert tp <= -0.9  # Fase 5: techo de pico verdadero de −1 dBTP (tolerancia de medida)
    for r in levels["balanced"]:
        assert -16.0 <= r <= -5.0, levels
    assert all(
        s < b < st
        for s, b, st in zip(levels["soft"], levels["balanced"], levels["strong"], strict=True)
    )


def test_voice_is_untouched_outside_the_effects(
    app_home: Path, voice: Path, tmp_path: Path
) -> None:
    from app.services.compositor import ceiling_trim_db

    out, cues = _mix(voice, tmp_path, "balanced", ["pop", "whoosh"])
    # Fase 5: el ajuste de techo es una ganancia fija; fuera de los efectos, la voz es idéntica
    # salvo por esa ganancia (el limitador no actúa sobre ella).
    v, m = _pcm(voice) * 10 ** (ceiling_trim_db(_ebur(voice)[1]) / 20), _pcm(out)
    n = min(len(v), len(m))
    mask = np.ones(n, dtype=bool)
    for c in cues:
        a = int(c.at * SR)
        mask[max(0, a - 2400) : a + SR] = False
    resid = _db(m[:n][mask] - v[:n][mask]) - _db(v[:n][mask])
    assert resid < -55  # prácticamente idéntica (el limitador solo actúa sobre excesos)


def test_sfx_density_and_variants() -> None:
    from app.services import compositor
    from app.services.animations import thin_sfx

    cues = [compositor.SfxCue("pop", 1.0), compositor.SfxCue("click", 1.1),  # demasiado juntos
            compositor.SfxCue("pop", 1.8),  # mismo tipo a < 1,2 s
            compositor.SfxCue("pop", 2.6), compositor.SfxCue("whoosh", 3.0),
            compositor.SfxCue("pop", 4.2)]  # fmt: skip
    kept = thin_sfx(cues)
    assert [(c.kind, c.at) for c in kept] == [
        ("pop", 1.0),
        ("pop", 2.6),
        ("whoosh", 3.0),
        ("pop", 4.2),
    ]
    assert [c.variant for c in kept if c.kind == "pop"] == [0, 1, 2]


def test_gain_follows_voice_and_user_controls() -> None:
    from app.services import compositor

    base = compositor.Composition(voice_lufs=-12.0, sfx_volume=70, sfx_intensity="balanced")
    g = compositor.sfx_gain_db("whoosh", base)
    assert compositor.sfx_gain_db(
        "whoosh", compositor.Composition(voice_lufs=-20.0)
    ) == pytest.approx(g - 8)
    louder = compositor.Composition(voice_lufs=-12.0, sfx_volume=100, sfx_intensity="balanced")
    assert compositor.sfx_gain_db("whoosh", louder) > g
    assert compositor.sfx_gain_db("click", base) < g  # los «tics» van por debajo


# ---------------------------------------------------------------------------
# Zonas seguras
# ---------------------------------------------------------------------------

FACE = {"x": 0.28, "y": 0.27, "w": 0.44, "h": 0.22}


@pytest.mark.parametrize("platform", ["universal", "instagram_reels", "tiktok"])
@pytest.mark.parametrize("size", [(1080, 1920), (1440, 2560)])
def test_overlays_stay_out_of_platform_ui(platform: str, size: tuple[int, int]) -> None:
    from app.services import layout_engine as L
    from app.services.animation_spec import place_region

    w, h = size
    ui = L.ui_zones(platform, w, h)
    assert ui
    zones = ui + L.face_zones([FACE]) + L.subtitle_zone((0.62, 0.72))
    for template, n in (("min.statement", 1), ("tech.nodes", 4), ("exp.icons", 3)):
        region, notes, warnings = place_region(
            {"x": 0.05, "y": 0.02, "w": 0.9, "h": 0.26}, "overlay_top", zones,
            allow_cover=False, aspect=w / h, min_short=L.min_legibility(template, n),
        )  # fmt: skip
        assert not warnings, warnings
        assert not L.overlaps(region, zones), (platform, template, region)
        assert L.legibility(region, w / h) >= L.min_legibility(template, n)
        assert notes  # la recolocación queda explicada


def test_profiles_differ_and_universal_is_the_union() -> None:
    from app.services import layout_engine as L

    ig = L.ui_zones("instagram_reels", 1080, 1920)
    tt = L.ui_zones("tiktok", 1080, 1920)
    uni = L.ui_zones("universal", 1080, 1920)
    assert {z.id for z in uni} == {z.id for z in ig} | {z.id for z in tt}
    top = lambda zs: max(z.y + z.h for z in zs if z.y == 0 and z.w == 1)  # noqa: E731
    assert top(ig) > top(tt)  # la cabecera de Reels es más alta
    assert L.ui_zones("none", 1080, 1920) == []
    assert L.ui_zones("universal", 1920, 1080) == []  # horizontal: no aplica
    assert L.platform_payload("tiktok")["sources"]


def test_no_legible_space_is_reported_not_squeezed() -> None:
    from app.services import layout_engine as L
    from app.services.animation_spec import place_region

    # Rostro enorme + subtítulos altos + interfaz: no cabe un diagrama legible.
    zones = (
        L.ui_zones("universal", 1080, 1920)
        + L.face_zones([{"x": 0.1, "y": 0.14, "w": 0.8, "h": 0.5}])
        + L.subtitle_zone((0.64, 0.75))
    )
    region, _, warnings = place_region(
        {"x": 0.05, "y": 0.02, "w": 0.9, "h": 0.26}, "overlay_top", zones,
        allow_cover=False, aspect=1080 / 1920, min_short=L.min_legibility("tech.nodes", 4),
    )  # fmt: skip
    assert warnings and warnings[0]["code"] == "no_safe_space"
    assert "pantalla completa" in warnings[0]["message"]
    assert region["h"] >= 0.2  # no se encoge hasta volverlo ilegible


def test_simultaneous_animations_do_not_overlap() -> None:
    from app.services import layout_engine as L
    from app.services.animation_spec import place_region

    ui = L.ui_zones("universal", 1080, 1920)
    first = {"x": 0.06, "y": 0.15, "w": 0.88, "h": 0.1}
    occ = [L.Zone("occ", "Otra animación", **first, kind="occupied")]
    region, _, warnings = place_region(
        dict(first), "overlay_top", ui + L.face_zones([FACE]) + occ,
        allow_cover=False, aspect=1080 / 1920, min_short=0.075,
    )  # fmt: skip
    assert not warnings and not L.overlaps(region, occ)


def test_fullscreen_content_and_pip_avoid_ui() -> None:
    from app.domain.edit_config import EditConfig
    from app.services import animation_spec
    from app.services import layout_engine as L
    from tests.test_phase4 import CLOCK_WORDS, _clock, _iv

    ui = L.ui_zones("universal", 1080, 1920)
    iv = _iv(type="fullscreen_animation", protected_regions=[FACE],
             composition={"layout": "picture_in_picture", "background": "style_background"})  # fmt: skip
    out, _ = animation_spec.compile_intervention(
        iv, plan_version=1, style="creative_explainer", config=EditConfig(), clock=_clock(CLOCK_WORDS),
        width=1080, height=1920, fps=30.0, subtitle_band=(0.62, 0.72), ui_zones=ui,
    )  # fmt: skip
    spec = out["spec"]
    assert not L.overlaps(spec["region"], ui)
    assert spec["pip"]["y"] >= 0.14  # bajo la cabecera de Reels


# ---------------------------------------------------------------------------
# Continuidad
# ---------------------------------------------------------------------------


def test_sequences_are_linked_within_a_style() -> None:
    from app.services.animations import link_sequences

    def c(iid: str, style: str, a: float, b: float, tpl: str = "x.panel", mode: str = "overlay"):
        return {"iv": {"id": iid, "start": a, "end": b}, "notes": [],
                "spec": {"style": style, "mode": mode, "template": tpl, "durationInFrames": round((b - a) * 30),
                         "region": {"x": 0.1, "y": 0.1, "w": 0.8, "h": 0.2}, "chainIn": None, "chainOut": False}}  # fmt: skip

    seq = [c("a", "motion_tech", 0, 2), c("b", "motion_tech", 2.4, 4), c("d", "motion_tech", 6, 8),
           c("e", "creative_explainer", 10, 12), c("f", "creative_explainer", 12, 14)]  # fmt: skip
    link_sequences(seq, 30.0)
    a, b, d, e, f = seq
    assert a["spec"]["chainOut"] and b["spec"]["chainIn"] == a["spec"]["region"]
    assert (
        a["iv"]["end"] == 2.4 and a["spec"]["durationInFrames"] == 72
    )  # prolongada hasta la siguiente
    assert not b["spec"]["chainOut"] and not d["spec"]["chainIn"]  # hueco de 2 s: sin enlace
    assert not e["spec"]["chainOut"] and not f["spec"]["chainIn"]  # Explainer conserva lo suyo


@pytest.mark.parametrize(
    "face",
    [
        {"x": 0.3, "y": 0.02, "w": 0.4, "h": 0.25},  # rostro pegado arriba
        {"x": 0.0, "y": 0.3, "w": 0.35, "h": 0.25},  # rostro en el borde izquierdo
        {"x": 0.62, "y": 0.55, "w": 0.38, "h": 0.25},  # rostro abajo a la derecha
    ],
)
def test_faces_near_the_edges(face: dict[str, float]) -> None:
    from app.services import layout_engine as L
    from app.services.animation_spec import place_region

    zones = (
        L.ui_zones("universal", 1080, 1920) + L.face_zones([face]) + L.subtitle_zone((0.62, 0.72))
    )
    region, _, warnings = place_region(
        {"x": 0.05, "y": 0.02, "w": 0.9, "h": 0.26}, "overlay_top", zones,
        allow_cover=False, aspect=1080 / 1920, min_short=L.min_legibility("min.list", 3), n_items=3,
    )  # fmt: skip
    if warnings:
        assert warnings[0]["code"] == "no_safe_space"
    else:
        assert not L.overlaps(region, zones)


def test_cta_and_multi_text_compositions_get_room() -> None:
    """Un CTA o una lista de varios textos reciben más área que un titular suelto."""
    from app.services import layout_engine as L

    zones = L.ui_zones("tiktok", 1080, 1920) + L.face_zones([FACE]) + L.subtitle_zone((0.62, 0.72))
    one, _ = L.place(
        {"x": 0.05, "y": 0.4, "w": 0.9, "h": 0.3},
        zones,
        aspect=1080 / 1920,
        min_short=0.06,
        keep_if_free=False,
        n_items=1,
    )
    many, _ = L.place(
        {"x": 0.05, "y": 0.4, "w": 0.9, "h": 0.3},
        zones,
        aspect=1080 / 1920,
        min_short=0.09,
        keep_if_free=False,
        n_items=5,
    )
    assert one and many
    assert many["w"] * many["h"] >= one["w"] * one["h"] * 0.95
    assert not L.overlaps(many, zones)
