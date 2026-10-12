"""Fixtures: videos reales generados con FFmpeg, app aislada (directorio de datos temporal)."""

from __future__ import annotations

import hashlib
import os
import shutil
import subprocess
from collections.abc import Iterator
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

FFMPEG = shutil.which("ffmpeg") or "/opt/homebrew/bin/ffmpeg"


def _ff(*args: str) -> None:
    subprocess.run([FFMPEG, "-hide_banner", "-loglevel", "error", "-y", *args], check=True)


@pytest.fixture(scope="session")
def media(tmp_path_factory: pytest.TempPathFactory) -> dict[str, Path]:
    d = tmp_path_factory.mktemp("media")
    files = {
        "horizontal": d / "Horizontal Clip.mp4",
        "vertical": d / "vertical_clip.mp4",
        "rotated": d / "iphone_portrait.MOV",
        "prores": d / "prores_master.mov",
        "hevc": d / "hevc_vertical.mov",
        "silent": d / "sin audio.mp4",
    }
    _ff("-f", "lavfi", "-i", "testsrc2=size=640x360:rate=30:duration=3",
        "-f", "lavfi", "-i", "sine=frequency=440:duration=3",
        "-c:v", "libx264", "-pix_fmt", "yuv420p", "-c:a", "aac", "-shortest",
        str(files["horizontal"]))  # fmt: skip
    _ff("-f", "lavfi", "-i", "testsrc2=size=360x640:rate=25:duration=3",
        "-f", "lavfi", "-i", "sine=frequency=660:duration=3",
        "-c:v", "libx264", "-pix_fmt", "yuv420p", "-c:a", "aac", "-shortest",
        str(files["vertical"]))  # fmt: skip
    _ff("-display_rotation:v:0", "90", "-i", str(files["horizontal"]), "-c", "copy",
        str(files["rotated"]))  # fmt: skip
    _ff("-f", "lavfi", "-i", "smptehdbars=size=320x180:rate=24:duration=2",
        "-f", "lavfi", "-i", "sine=frequency=330:duration=2",
        "-c:v", "prores_ks", "-profile:v", "0", "-c:a", "pcm_s16le", "-shortest",
        str(files["prores"]))  # fmt: skip
    _ff("-f", "lavfi", "-i", "testsrc=size=360x640:rate=60:duration=2",
        "-f", "lavfi", "-i", "anoisesrc=d=2:a=0.2",
        "-c:v", "libx265", "-pix_fmt", "yuv420p", "-tag:v", "hvc1",
        "-x265-params", "log-level=none",
        "-c:a", "aac", "-shortest", str(files["hevc"]))  # fmt: skip
    _ff("-f", "lavfi", "-i", "mandelbrot=size=320x240:rate=24", "-t", "2",
        "-c:v", "libx264", "-pix_fmt", "yuv420p", str(files["silent"]))  # fmt: skip
    fake = d / "fake.mp4"
    fake.write_text("esto no es un video")
    disguised = d / "disguised.mp4"
    _ff("-f", "lavfi", "-i", "testsrc2=size=320x180:rate=24:duration=1", "-c:v", "libx264",
        "-f", "matroska", str(disguised))  # fmt: skip
    truncated = d / "truncated.mp4"
    truncated.write_bytes(files["horizontal"].read_bytes()[:20_000])
    files.update(fake=fake, disguised=disguised, truncated=truncated)
    return files


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


@pytest.fixture
def app_home(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    home = tmp_path / "home"
    monkeypatch.setenv("VSA_HOME", str(home))
    monkeypatch.setenv("VSA_ENV", "test")
    monkeypatch.setenv("VSA_FRONTEND_DIST", str(tmp_path / "no-dist"))
    # Modelos de transcripción compartidos entre pruebas (evita descargas repetidas).
    models = os.environ.get("VSA_TEST_MODELS_DIR")
    if models:
        monkeypatch.setenv("VSA_MODELS_DIR", models)
    else:
        monkeypatch.delenv("VSA_MODELS_DIR", raising=False)
    from app.config import get_settings

    get_settings.cache_clear()
    yield home
    get_settings.cache_clear()


def make_client() -> TestClient:
    from app.main import create_app

    return TestClient(create_app(), base_url="http://127.0.0.1", headers={"x-vsa-client": "1"})


@pytest.fixture
def client(app_home: Path) -> Iterator[TestClient]:
    with make_client() as c:
        yield c


@pytest.fixture
def disk(tmp_path: Path) -> Path:
    """Simula un disco: existe la carpeta padre, la raíz la crea la app."""
    parent = tmp_path / "disk"
    parent.mkdir()
    return parent / "VideoStudio"


def configure(client: TestClient, root: Path) -> dict:
    res = client.post("/api/storage/configure", json={"path": str(root)})
    assert res.status_code == 200, res.text
    return res.json()


def upload(client: TestClient, path: Path, **params) -> object:
    with open(path, "rb") as fh:
        data = fh.read()
    return client.post(
        "/api/imports/upload",
        params={"filename": path.name, **params},
        content=data,
        headers={"content-type": "application/octet-stream"},
    )


def wait_idle(timeout: float = 90) -> None:
    from app.jobs.runner import runner

    assert runner.wait_idle(timeout), "las tareas no terminaron a tiempo"
