"""Lectura de metadatos reales con ffprobe y validación de formato."""

from __future__ import annotations

from pathlib import Path

import pytest

from app.config import get_settings
from app.services.media_probe import MediaValidationError, looks_like_iso_bmff, probe_file


@pytest.fixture(scope="module")
def ffprobe() -> str:
    return get_settings().ffprobe


def test_horizontal_mp4(media: dict[str, Path], ffprobe: str) -> None:
    info = probe_file(ffprobe, media["horizontal"])
    assert info.container == "mp4"
    assert (info.display_width, info.display_height) == (640, 360)
    assert info.orientation == "horizontal"
    assert info.fps == 30 and (info.fps_num, info.fps_den) == (30, 1)
    assert info.video_codec == "h264"
    assert info.has_audio and info.audio_tracks[0].codec == "aac"
    assert info.browser_playable
    assert 2.9 < info.duration < 3.2


def test_vertical_mp4(media: dict[str, Path], ffprobe: str) -> None:
    info = probe_file(ffprobe, media["vertical"])
    assert info.orientation == "vertical"
    assert (info.display_width, info.display_height) == (360, 640)
    assert info.fps == 25


def test_rotation_metadata_makes_vertical(media: dict[str, Path], ffprobe: str) -> None:
    info = probe_file(ffprobe, media["rotated"])
    assert info.container == "mov"
    assert (info.width, info.height) == (640, 360)
    assert info.rotation in (90, 270)
    assert (info.display_width, info.display_height) == (360, 640)
    assert info.orientation == "vertical"


def test_prores_requires_proxy(media: dict[str, Path], ffprobe: str) -> None:
    info = probe_file(ffprobe, media["prores"])
    assert info.video_codec == "prores"
    assert info.audio_tracks[0].codec.startswith("pcm")
    assert not info.browser_playable


def test_hevc_60fps(media: dict[str, Path], ffprobe: str) -> None:
    info = probe_file(ffprobe, media["hevc"])
    assert info.video_codec == "hevc"
    assert info.fps == 60
    assert info.orientation == "vertical"
    assert info.browser_playable


def test_silent(media: dict[str, Path], ffprobe: str) -> None:
    info = probe_file(ffprobe, media["silent"])
    assert not info.has_audio
    assert info.browser_playable


@pytest.mark.parametrize("name", ["fake", "disguised", "truncated"])
def test_invalid_files_rejected(media: dict[str, Path], ffprobe: str, name: str) -> None:
    with pytest.raises(MediaValidationError):
        probe_file(ffprobe, media[name])


def test_extension_must_be_mp4_or_mov(media: dict[str, Path], ffprobe: str) -> None:
    with pytest.raises(MediaValidationError) as exc:
        probe_file(ffprobe, media["horizontal"], "clip.avi")
    assert exc.value.code == "unsupported_extension"


def test_iso_bmff_signature(media: dict[str, Path]) -> None:
    assert looks_like_iso_bmff(media["horizontal"].read_bytes()[:12])
    assert looks_like_iso_bmff(media["prores"].read_bytes()[:12])
    assert not looks_like_iso_bmff(media["disguised"].read_bytes()[:12])
    assert not looks_like_iso_bmff(b"esto no es")
