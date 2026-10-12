"""Fase 5 · Matriz de material (render real, VSA_TEST_REMOTION=1): cada caso recorre el flujo
completo con Claude simulado (análisis → plan → aprobación → animaciones → exportación) y la
exportación se verifica (duración, tamaño, orientación, audio y muestreo de negros) sin tocar el
original. Los videos se generan con FFmpeg de forma reproducible."""

from __future__ import annotations

import subprocess
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from tests.conftest import FFMPEG, configure, sha256, upload, wait_idle
from tests.test_phase3 import _seed_transcript, _use_fake, fake_cli  # noqa: F401
from tests.test_phase4 import _ffprobe, engine_home  # noqa: F401


def _ff(*args: str) -> None:
    subprocess.run([FFMPEG, "-hide_banner", "-loglevel", "error", "-y", *args], check=True)


def _make(d: Path, case: str) -> Path:
    """Material de prueba: (nombre, generador)."""
    out = d / f"{case}.mp4"
    tone = ["-f", "lavfi", "-i", "sine=frequency=330:duration=600"]
    enc = ["-c:v", "libx264", "-pix_fmt", "yuv420p", "-c:a", "aac", "-shortest"]
    if case == "vertical_sin_cortes":
        _ff("-f", "lavfi", "-i", "testsrc2=size=720x1280:rate=30:duration=8", *tone, *enc, str(out))
    elif case == "horizontal_con_cortes":
        _ff("-f", "lavfi", "-i", "testsrc2=size=1920x1080:rate=25:duration=4",
            "-f", "lavfi", "-i", "smptehdbars=size=1920x1080:rate=25:duration=4", *tone,
            "-filter_complex", "[0][1]concat=n=2:v=1:a=0[v]", "-map", "[v]", "-map", "2:a", *enc, str(out))  # fmt: skip
    elif case == "grabacion_de_pantalla":
        # Interfaz estática con texto y un cursor que se mueve (grabación de pantalla sintética).
        _ff("-f", "lavfi", "-i", "color=c=0xF4F5F7:size=1920x1080:rate=30:duration=6", *tone,
            "-vf", "drawbox=x=0:y=0:w=1920:h=90:color=0x1F2937:t=fill,drawbox=x=120:y=200:w=700:h=500:color=0xDDE3EA:t=fill,"
                   "drawbox=x='200+t*150':y=400:w=24:h=24:color=black:t=fill", *enc, str(out))  # fmt: skip
    elif case == "camara_y_pantalla":
        _ff("-f", "lavfi", "-i", "testsrc2=size=1280x720:rate=30:duration=3",
            "-f", "lavfi", "-i", "color=c=0xF4F5F7:size=1280x720:rate=30:duration=3",
            "-f", "lavfi", "-i", "mandelbrot=size=1280x720:rate=30", *tone,
            "-filter_complex", "[2]trim=duration=3,setpts=PTS-STARTPTS[m];[0][1][m]concat=n=3:v=1:a=0[v]",
            "-map", "[v]", "-map", "3:a", *enc, str(out))  # fmt: skip
    elif case == "largo_3min":
        _ff(
            "-f",
            "lavfi",
            "-i",
            "testsrc2=size=1280x720:rate=30:duration=180",
            *tone,
            *enc,
            str(out),
        )
    elif case == "4k_corto":
        _ff(
            "-f", "lavfi", "-i", "testsrc2=size=3840x2160:rate=30:duration=3", *tone, *enc, str(out)
        )
    elif case == "vertical_60fps":
        _ff(
            "-f", "lavfi", "-i", "testsrc2=size=1080x1920:rate=60:duration=4", *tone, *enc, str(out)
        )
    else:
        raise ValueError(case)
    return out


CASES = [
    ("vertical_sin_cortes", "motion_tech", "classic"),
    ("horizontal_con_cortes", "minimal_motion", "dynamic"),
    ("grabacion_de_pantalla", "creative_explainer", "classic"),
    ("camara_y_pantalla", "motion_tech", "dynamic"),
    ("largo_3min", "minimal_motion", "classic"),
    ("4k_corto", "creative_explainer", "classic"),
    ("vertical_60fps", "creative_explainer", "dynamic"),
]


@pytest.mark.parametrize(("case", "style", "subs"), CASES, ids=[c[0] for c in CASES])
def test_full_flow_matrix(
    engine_home: Path,
    client: TestClient,
    disk: Path,
    fake_cli: Any,
    tmp_path: Path,
    case: str,
    style: str,
    subs: str,
) -> None:
    _use_fake(client, fake_cli["cli"])
    src = _make(tmp_path, case)
    configure(client, disk)
    res = upload(client, src)
    assert res.status_code == 201, res.text
    wait_idle()
    pid, asset = res.json()["project"]["id"], res.json()["asset"]
    r = client.post(f"/api/projects/{pid}/analyze", json={"transcribe": False, "visual": True})
    assert r.status_code == 202, r.text
    wait_idle(600)
    _seed_transcript(asset["id"])
    cfg = client.get(f"/api/projects/{pid}").json()["config"]
    cfg["style"]["id"] = style
    cfg["subtitles"]["mode"] = subs
    assert client.patch(f"/api/projects/{pid}", json={"config": cfg}).status_code == 200
    stored = next(p for p in (disk / "projects").rglob("originals/*") if p.name == src.name)
    before = sha256(stored)
    r = client.post(f"/api/projects/{pid}/plan/generate", json={"style": style})
    assert r.status_code == 202, r.text
    wait_idle(300)
    client.post(f"/api/projects/{pid}/plan/bulk", json={"status": "accepted"})
    plan = client.get(f"/api/projects/{pid}/plan").json()["plan"]
    for c in plan["document"]["validation"].get("conflicts") or []:
        client.patch(
            f"/api/projects/{pid}/plan/interventions/{c['b']}", json={"status": "rejected"}
        )
    r = client.post(f"/api/projects/{pid}/plan/approve", json={})
    assert r.status_code == 200, r.text
    r = client.post(f"/api/projects/{pid}/animations/prepare", json={"use_claude": True})
    assert r.status_code == 202, r.text
    wait_idle(900)
    st = client.get(f"/api/projects/{pid}/animations").json()
    animated = [i for i in st["items"] if i["status"] != "kept"]
    assert animated and all(i["status"] == "ready" for i in animated), st
    r = client.post(f"/api/projects/{pid}/exports", json={"with_animations": True})
    assert r.status_code == 202, r.text
    wait_idle(900)
    ex = client.get(f"/api/projects/{pid}/exports").json()[0]
    assert ex["status"] == "succeeded", ex
    check = ex["settings"]["verification"]
    assert check["ok"] and not check["warnings"], check
    info = _ffprobe(disk / ex["file_rel"])
    v = next(s for s in info["streams"] if s["codec_type"] == "video")
    src_info = _ffprobe(src)
    sv = next(s for s in src_info["streams"] if s["codec_type"] == "video")
    assert (v["width"], v["height"]) == (sv["width"], sv["height"])  # orientación y tamaño
    assert v["avg_frame_rate"] == sv["avg_frame_rate"]
    assert abs(float(info["format"]["duration"]) - float(src_info["format"]["duration"])) < 0.15
    assert any(s["codec_type"] == "audio" for s in info["streams"])
    assert sha256(stored) == before
