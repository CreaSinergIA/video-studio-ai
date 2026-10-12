"""Fase 2 con medios reales: transcripción, análisis, subtítulos y exportación.

Las pruebas de transcripción usan voz sintetizada con macOS (``say``) construida palabra a
palabra, de modo que se conocen los tiempos **exactos** de cada palabra (verdad de referencia).
Requieren un modelo MLX instalado en ``VSA_TEST_MODELS_DIR`` (si no, se omiten con motivo).
"""

from __future__ import annotations

import array
import hashlib
import itertools
import json
import os
import shutil
import statistics
import subprocess
import tempfile
import time
import wave
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from tests.conftest import FFMPEG, configure, sha256, upload, wait_idle

SR = 16000
ES_VOICE = "Eddy (Español (España))"
EN_VOICE = "Eddy (Inglés (EE. UU.))"
CANDIDATE_MODELS = ("large-v3-turbo-q4", "large-v3-turbo")


def _have_voice(voice: str) -> bool:
    if not shutil.which("say"):
        return False
    out = subprocess.run(["say", "-v", "?"], capture_output=True, text=True).stdout
    return voice.split(" (")[0] in out and voice.split("(", 1)[1][:6] in out


def _installed_model() -> str | None:
    """Primer modelo instalado en VSA_TEST_MODELS_DIR (el ligero primero, por velocidad)."""
    d = os.environ.get("VSA_TEST_MODELS_DIR")
    if not d:
        return None
    return next(
        (m for m in CANDIDATE_MODELS if (Path(d) / "asr" / m / "vsa-model.json").is_file()), None
    )


MODEL = _installed_model() or CANDIDATE_MODELS[0]


def _models_ready() -> bool:
    return _installed_model() is not None


needs_asr = pytest.mark.skipif(
    not (_models_ready() and _have_voice(ES_VOICE)),
    reason="Requiere VSA_TEST_MODELS_DIR con un modelo MLX instalado y voces de macOS",
)


def _ff(*args: str) -> None:
    subprocess.run([FFMPEG, "-hide_banner", "-loglevel", "error", "-y", *args], check=True)


def _say(text: str, voice: str, path: Path) -> array.array:
    subprocess.run(
        [
            "say",
            "-v",
            voice,
            "-o",
            str(path),
            "--file-format=WAVE",
            f"--data-format=LEI16@{SR}",
            text,
        ],
        check=True,
    )
    with wave.open(str(path)) as w:
        a = array.array("h")
        a.frombytes(w.readframes(w.getnframes()))
    i, j = 0, len(a)
    while i < j and abs(a[i]) < 300:
        i += 1
    while j > i and abs(a[j - 1]) < 300:
        j -= 1
    return a[i:j]


def _build_voice(
    phrases: list[str], voice: str, out_wav: Path, gap: float = 0.09, pause: float = 1.2
) -> list[dict[str, Any]]:
    """Concatena palabras sintetizadas con huecos conocidos; devuelve la verdad por palabra."""
    tmp = Path(tempfile.mkdtemp())
    out = array.array("h", [0] * int(0.7 * SR))
    truth = []
    for phrase in phrases:
        for word in phrase.split():
            seg = _say(word.strip("¿?¡!.,;:"), voice, tmp / "w.wav")
            start = len(out) / SR
            out.extend(seg)
            truth.append({"word": word, "start": start, "end": len(out) / SR})
            out.extend([0] * int(gap * SR))
        out.extend([0] * int(pause * SR))
    with wave.open(str(out_wav), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(SR)
        w.writeframes(out.tobytes())
    shutil.rmtree(tmp, ignore_errors=True)
    return truth


@pytest.fixture(scope="session")
def voice_media(tmp_path_factory: pytest.TempPathFactory) -> dict[str, Any]:
    if not (_have_voice(ES_VOICE) and _have_voice(EN_VOICE)):
        pytest.skip("Voces de síntesis de macOS no disponibles")
    d = tmp_path_factory.mktemp("voice")
    es_truth = _build_voice(
        ["¿Qué tal? Hoy vamos a editar un vídeo increíble.",
         "La transcripción automática debe ser precisa, rápida y fiable."],
        ES_VOICE, d / "es.wav",
    )  # fmt: skip
    en_truth = _build_voice(
        ["Welcome back to the channel.", "Today we are testing local speech recognition."],
        EN_VOICE, d / "en.wav",
    )  # fmt: skip
    dur_es = es_truth[-1]["end"] + 1.3
    # Vertical con un corte a mitad (dos patrones distintos), voz en español.
    _ff("-f", "lavfi", "-i", f"testsrc2=s=360x640:r=30:d={dur_es / 2:.3f}",
        "-f", "lavfi", "-i", f"smptehdbars=s=360x640:r=30:d={dur_es / 2:.3f}",
        "-i", str(d / "es.wav"),
        "-filter_complex", "[0][1]concat=n=2:v=1:a=0,format=yuv420p[v]",
        "-map", "[v]", "-map", "2:a", "-c:v", "libx264", "-c:a", "aac", "-shortest",
        str(d / "voz_es_vertical.mp4"))  # fmt: skip
    # Horizontal MOV en inglés, sin cortes.
    _ff("-f", "lavfi", "-i", "testsrc2=s=640x360:r=25:d=12", "-i", str(d / "en.wav"),
        "-map", "0:v", "-map", "1:a", "-c:v", "libx264", "-pix_fmt", "yuv420p", "-c:a", "aac",
        "-shortest", str(d / "voice_en.mov"))  # fmt: skip
    # Mismo español con ruido rosa.
    _ff("-i", str(d / "voz_es_vertical.mp4"), "-f", "lavfi", "-i", "anoisesrc=c=pink:a=0.05:d=60",
        "-filter_complex", "[0:a][1:a]amix=inputs=2:duration=first:normalize=0[a]",
        "-map", "0:v", "-map", "[a]", "-c:v", "copy", "-c:a", "aac", str(d / "ruido_es.mp4"))  # fmt: skip
    # Audio en silencio digital (pista presente, sin voz).
    _ff("-f", "lavfi", "-i", "testsrc2=s=320x240:r=24:d=5", "-f", "lavfi",
        "-i", "anullsrc=r=44100:cl=stereo", "-t", "5", "-c:v", "libx264", "-pix_fmt", "yuv420p",
        "-c:a", "aac", str(d / "silencio.mp4"))  # fmt: skip
    # Rotación por metadatos (vertical en pantalla, codificado horizontal).
    _ff("-f", "lavfi", "-i", "testsrc2=s=640x360:r=30:d=3", "-f", "lavfi",
        "-i", "smptehdbars=s=640x360:r=30:d=3", "-filter_complex",
        "[0][1]concat=n=2:v=1:a=0,format=yuv420p", "-c:v", "libx264", str(d / "rot_src.mp4"))  # fmt: skip
    _ff("-display_rotation:v:0", "90", "-i", str(d / "rot_src.mp4"), "-c", "copy",
        str(d / "rotado.mov"))  # fmt: skip
    # 4K vertical breve con voz (para exportación 4K y 1080p).
    _ff("-f", "lavfi", "-i", "testsrc2=s=2160x3840:r=30:d=4", "-i", str(d / "es.wav"),
        "-map", "0:v", "-map", "1:a", "-t", "4", "-c:v", "libx264", "-preset", "ultrafast",
        "-pix_fmt", "yuv420p", "-c:a", "aac", str(d / "vertical_4k.mp4"))  # fmt: skip
    return {
        "dir": d,
        "es": d / "voz_es_vertical.mp4",
        "en": d / "voice_en.mov",
        "noisy": d / "ruido_es.mp4",
        "silence": d / "silencio.mp4",
        "rotated": d / "rotado.mov",
        "uhd": d / "vertical_4k.mp4",
        "es_truth": es_truth,
        "en_truth": en_truth,
        "cut_at": round(dur_es / 2, 3),
    }


def _import(client: TestClient, path: Path) -> tuple[str, dict[str, Any]]:
    res = upload(client, path)
    assert res.status_code == 201, res.text
    wait_idle()
    body = res.json()
    return body["project"]["id"], body["asset"]


def _analyze(client: TestClient, pid: str, **body: Any) -> dict[str, Any]:
    res = client.post(f"/api/projects/{pid}/analyze", json=body)
    assert res.status_code == 202, res.text
    wait_idle(600)
    return client.get(f"/api/projects/{pid}/analysis").json()


def _use_model(client: TestClient) -> None:
    prefs = client.get("/api/settings/analysis").json()
    prefs["transcription_model"] = MODEL
    assert client.put("/api/settings/analysis", json=prefs).status_code == 200


def _norm(w: str) -> str:
    import re
    import unicodedata

    return re.sub(r"[^\w]", "", unicodedata.normalize("NFC", w.lower()))


def _timing_errors(
    truth: list[dict[str, Any]], words: list[dict[str, Any]]
) -> tuple[list[float], list[float], float]:
    import difflib

    a = [_norm(t["word"]) for t in truth]
    b = [_norm(w["text"]) for w in words]
    sm = difflib.SequenceMatcher(a=a, b=b, autojunk=False)
    starts, ends, matched = [], [], 0
    for blk in sm.get_matching_blocks():
        for k in range(blk.size):
            t, w = truth[blk.a + k], words[blk.b + k]
            starts.append(abs(w["start"] - t["start"]))
            ends.append(abs(w["end"] - t["end"]))
            matched += 1
    return starts, ends, matched / len(truth)


# ---------------------------------------------------------------------------
# Transcripción
# ---------------------------------------------------------------------------


@needs_asr
def test_spanish_transcription_word_timestamps(client: TestClient, disk: Path, voice_media) -> None:
    configure(client, disk)
    _use_model(client)
    pid, asset = _import(client, voice_media["es"])
    state = _analyze(client, pid, visual=False)
    t = state["transcript"]
    assert t["status"] == "ready" and t["language"] == "es"
    words = [w for seg in t["segments"] for w in seg["words"]]
    text = " ".join(w["text"] for w in words).lower()
    for expected in ("hoy", "vamos", "editar", "vídeo", "increíble", "transcripción", "automática"):
        assert expected in text, (expected, text)
    starts, ends, coverage = _timing_errors(voice_media["es_truth"], words)
    assert coverage >= 0.85, coverage
    # Tiempos por palabra medidos (verdad de referencia exacta): mediana < 40 ms.
    assert statistics.median(starts) < 0.04, sorted(starts)
    assert statistics.median(ends) < 0.04, sorted(ends)
    # Marcas verificables: orden y límites dentro del video.
    assert all(a["end"] <= b["start"] + 1e-6 for a, b in itertools.pairwise(words))
    assert all(0 <= w["start"] < w["end"] <= asset["duration"] + 0.05 for w in words)
    assert all(w["timing"] in ("asr", "refined") for w in words)
    # Silencios y voz detectados.
    voice = t["stats"]["voice"]
    assert voice["silences"] and 0.3 < voice["speech_ratio"] < 0.95
    # Caché: repetir con los mismos parámetros reutiliza el resultado.
    client.post(f"/api/projects/{pid}/analyze", json={"visual": False})
    wait_idle(120)
    jobs = client.get("/api/jobs").json()
    last = next(j for j in jobs if j["kind"] == "transcribe")
    assert last["result"]["reused"] is True
    # Copia JSON en transcripts/ del proyecto.
    project = client.get(f"/api/projects/{pid}").json()
    assert (disk / project["dir_rel"] / "transcripts" / f"{t['id']}.json").is_file()


@needs_asr
def test_english_mov_transcription(client: TestClient, disk: Path, voice_media) -> None:
    configure(client, disk)
    _use_model(client)
    pid, _ = _import(client, voice_media["en"])
    t = _analyze(client, pid, visual=False)["transcript"]
    assert t["language"] == "en"
    words = [w for seg in t["segments"] for w in seg["words"]]
    starts, _, coverage = _timing_errors(voice_media["en_truth"], words)
    assert coverage >= 0.85
    assert statistics.median(starts) < 0.04


@needs_asr
def test_noisy_audio_still_transcribes(client: TestClient, disk: Path, voice_media) -> None:
    configure(client, disk)
    _use_model(client)
    pid, _ = _import(client, voice_media["noisy"])
    t = _analyze(client, pid, visual=False)["transcript"]
    words = [w for seg in t["segments"] for w in seg["words"]]
    starts, _, coverage = _timing_errors(voice_media["es_truth"], words)
    assert coverage >= 0.8
    assert statistics.median(starts) < 0.06


@needs_asr
def test_silence_and_missing_audio(client: TestClient, disk: Path, voice_media, media) -> None:
    configure(client, disk)
    _use_model(client)
    pid, _ = _import(client, voice_media["silence"])
    t = _analyze(client, pid, visual=False)["transcript"]
    assert t["status"] == "no_speech" and t["segments"] == []
    pid2, _ = _import(client, media["silent"])  # sin pista de audio
    t2 = _analyze(client, pid2, visual=False)["transcript"]
    assert t2["status"] == "no_audio"


@needs_asr
def test_transcript_corrections_and_realign(client: TestClient, disk: Path, voice_media) -> None:
    configure(client, disk)
    _use_model(client)
    pid, _ = _import(client, voice_media["es"])
    original = _analyze(client, pid, visual=False)["transcript"]
    seg = original["segments"][0]
    first = seg["words"][0]
    # 1) Corrección 1:1 (puntuación/mayúsculas): conserva los tiempos medidos.
    new_text = seg["text"].replace(first["text"], first["text"].upper(), 1)
    edited = client.patch(
        f"/api/transcripts/{original['id']}/segments/{seg['id']}", json={"text": new_text}
    ).json()
    assert edited["kind"] == "edited" and edited["parent_id"] == original["id"]
    w0 = edited["segments"][0]["words"][0]
    assert w0["start"] == first["start"] and w0["timing"] != "estimated"
    assert w0["original_text"] == first["text"] and w0["edited"] is True
    # 2) Cambio estructural (palabra añadida): tiempos estimados y revisión pendiente.
    words = edited["segments"][0]["text"].split()
    words.insert(2, "realmente")
    edited = client.patch(
        f"/api/transcripts/{edited['id']}/segments/{seg['id']}", json={"text": " ".join(words)}
    ).json()
    s0 = edited["segments"][0]
    assert s0["needs_timing_review"] is True
    assert any(w["timing"] == "estimated" and w["text"] == "realmente" for w in s0["words"])
    # 3) Realinear con el audio: tiempos medidos de nuevo.
    res = client.post(f"/api/transcripts/{edited['id']}/realign", json={"segment_ids": [seg["id"]]})
    assert res.status_code == 202
    wait_idle(300)
    state = client.get(f"/api/projects/{pid}/analysis").json()
    s0 = state["transcript"]["segments"][0]
    assert s0["needs_timing_review"] is False
    assert all(w["timing"] == "aligned" for w in s0["words"])
    assert "realmente" in s0["text"]
    # 4) Ajuste manual explícito con validación.
    w = s0["words"][0]
    bad = client.put(
        f"/api/transcripts/{state['transcript']['id']}/segments/{seg['id']}/times",
        json={"words": [{"id": w["id"], "start": 5.0, "end": 4.0}]},
    )
    assert bad.status_code == 422
    ok = client.put(
        f"/api/transcripts/{state['transcript']['id']}/segments/{seg['id']}/times",
        json={"words": [{"id": w["id"], "start": w["start"], "end": w["end"]}]},
    ).json()
    assert ok["segments"][0]["words"][0]["timing"] == "manual"
    # 5) La original sigue intacta y se puede reactivar.
    versions = state["versions"]
    assert {v["kind"] for v in versions} == {"asr", "edited"}
    restored = client.post(f"/api/transcripts/{original['id']}/activate").json()
    assert restored["segments"][0]["text"] == seg["text"]
    # 6) Exportaciones de texto.
    srt = client.get(f"/api/transcripts/{ok['id']}/export", params={"format": "srt"})
    assert srt.status_code == 200 and "-->" in srt.text and "," in srt.text.split("-->")[0]
    vtt = client.get(f"/api/transcripts/{ok['id']}/export", params={"format": "vtt"}).text
    assert vtt.startswith("WEBVTT") and "realmente" in vtt
    txt = client.get(f"/api/transcripts/{ok['id']}/export", params={"format": "txt"}).text
    assert "transcripción" in txt.lower()


# ---------------------------------------------------------------------------
# Análisis visual
# ---------------------------------------------------------------------------


def test_scene_detection_and_frames(client: TestClient, disk: Path, voice_media) -> None:
    configure(client, disk)
    pid, _ = _import(client, voice_media["es"])
    state = _analyze(client, pid, transcribe=False)
    v = state["visual"]
    assert [s["transition_in"] for s in v["scenes"]] == ["start", "cut"]
    assert abs(v["scenes"][1]["start"] - voice_media["cut_at"]) < 0.05
    frames = state["frames"]
    assert frames and all(f["width"] and f["height"] > f["width"] for f in frames)
    reasons = {f["reason"] for f in frames}
    assert {"scene_start", "scene_mid"} <= reasons
    # Cada fotograma pertenece a su escena y su archivo existe.
    for f in frames:
        sc = v["scenes"][f["scene_index"]]
        assert sc["start"] - 1e-3 <= f["t"] <= sc["end"] + 1e-3
        assert client.get(f["url"]).status_code == 200
    # Captura bajo demanda con caché.
    a = client.post(f"/api/projects/{pid}/frames", json={"t": 1.5}).json()
    b = client.post(f"/api/projects/{pid}/frames", json={"t": 1.5}).json()
    assert a["id"] == b["id"] and a["reason"] == "on_demand"
    # Caché de análisis: repetir reutiliza; cambiar parámetros invalida.
    client.post(f"/api/projects/{pid}/analyze", json={"transcribe": False})
    wait_idle()
    assert next(j for j in client.get("/api/jobs").json() if j["kind"] == "analyze_visual")[
        "result"
    ]["reused"]
    prefs = client.get("/api/settings/analysis").json()
    prefs["frame_interval_seconds"] = 2
    client.put("/api/settings/analysis", json=prefs)
    client.post(f"/api/projects/{pid}/analyze", json={"transcribe": False})
    wait_idle()
    assert not next(j for j in client.get("/api/jobs").json() if j["kind"] == "analyze_visual")[
        "result"
    ]["reused"]
    # Paquete para la Fase 3.
    bundle = client.get(f"/api/projects/{pid}/bundle").json()
    assert bundle["video"]["orientation"] == "vertical" and bundle["scenes"]
    assert (
        disk / client.get(f"/api/projects/{pid}").json()["dir_rel"] / "analysis" / "bundle.json"
    ).is_file()


def test_rotated_and_horizontal_analysis(client: TestClient, disk: Path, voice_media) -> None:
    configure(client, disk)
    pid, asset = _import(client, voice_media["rotated"])
    assert asset["orientation"] == "vertical"
    v = _analyze(client, pid, transcribe=False)
    assert [s["transition_in"] for s in v["visual"]["scenes"]] == ["start", "cut"]
    assert abs(v["visual"]["scenes"][1]["start"] - 3.0) < 0.05
    f = v["frames"][0]
    assert f["height"] > f["width"], "los fotogramas se extraen con la rotación aplicada"
    pid2, _ = _import(client, voice_media["en"])
    v2 = _analyze(client, pid2, transcribe=False)["visual"]
    assert len(v2["scenes"]) == 1 and v2["transitions"] == []


# ---------------------------------------------------------------------------
# Subtítulos (maquetación)
# ---------------------------------------------------------------------------


def _segments(n_words: int = 40) -> list[dict[str, Any]]:
    words = []
    texts = [
        "Esto",
        "es",
        "una",
        "prueba",
        "de",
        "subtítulos",
        "con",
        "acentos:",
        "canción,",
        "ñandú,",
        "pingüino",
        "y",
        "¿preguntas?",
        "largas",
    ]
    for i in range(n_words):
        words.append(
            {"id": f"w{i}", "text": texts[i % len(texts)], "start": i * 0.4, "end": i * 0.4 + 0.35}
        )
    return [{"words": words}]


@pytest.mark.parametrize(("w", "h"), [(1080, 1920), (1920, 1080), (1440, 2560)])
def test_track_layout_inside_frame(w: int, h: int) -> None:
    from app.domain.edit_config import SubtitleSettings
    from app.services.subtitles import build_track

    for position, auto in [("top", False), ("middle", False), ("bottom", False), ("bottom", True)]:
        for mode in ("classic", "dynamic"):
            s = SubtitleSettings(position=position, auto_position=auto, mode=mode, max_lines=2,
                                 max_words_per_line=4, font_size=96)  # fmt: skip
            track = build_track(_segments(), s, w, h)
            assert track["blocks"]
            for b in track["blocks"]:
                assert b["top"] >= 0 and b["top"] + b["height"] <= h
                assert len(b["lines"]) <= 2
                for line in b["lines"]:
                    assert len(line["words"]) <= 4
                    for word in line["words"]:
                        assert word["x"] >= 0 and word["x"] + word["w"] <= w
            # Bloques ordenados y sin solaparse.
            assert all(
                a["end"] <= b["start"]
                for a, b in zip(track["blocks"], track["blocks"][1:], strict=False)
            )


def test_auto_position_avoids_face() -> None:
    from app.domain.edit_config import SubtitleSettings
    from app.services.subtitles import build_track

    face_low = {"status": "single", "union_box": [0.25, 0.45, 0.5, 0.3],
                "lowest_mouth_y": 0.68, "highest_eye_y": 0.55}  # fmt: skip
    scenes = [{"index": 0, "start": 0, "end": 100, "faces": face_low}]
    s = SubtitleSettings(auto_position=True)
    track = build_track(_segments(12), s, 1080, 1920, scenes)
    for b in track["blocks"]:
        top, bottom = b["top"] / 1920, (b["top"] + b["height"]) / 1920
        assert not (top < 0.68 + 0.015 and bottom > 0.68 - 0.06), "tapa la boca"
        assert not (top < 0.55 + 0.03 and bottom > 0.55 - 0.03), "tapa los ojos"
        assert b["position_source"] == "auto-faces"
    # Sin rostros: posición segura por defecto (vertical ~68 %).
    plain = build_track(_segments(12), s, 1080, 1920, [])
    assert plain["blocks"][0]["position_source"] == "auto-default"
    centers = {round((b["top"] + b["height"] / 2) / 1920, 2) for b in plain["blocks"]}
    assert len(centers) <= 2, "posición estable (sin saltos)"


def test_state_matches_between_word_changes() -> None:
    from app.domain.edit_config import SubtitleSettings
    from app.services.subtitles import block_at, build_track, change_times, state_at

    track = build_track(
        _segments(8), SubtitleSettings(mode="dynamic", animation="karaoke"), 1080, 1920
    )
    b = track["blocks"][0]
    words = [w for line in b["lines"] for w in line["words"]]
    st = state_at(track, b, words[1]["start"] + 0.01)
    assert [x["highlight"] for x in st["words"][:3]] == [True, True, False]
    assert block_at(track, -1) is None
    assert all(t >= 0 for t in change_times(track, 30))


# ---------------------------------------------------------------------------
# Exportación
# ---------------------------------------------------------------------------


def _export(client: TestClient, pid: str, **settings: Any) -> dict[str, Any]:
    body = {"resolution": "original", "fps": "original", "format": "mp4_h264", "quality": "high",
            "encoder": "hardware", **settings}  # fmt: skip
    res = client.post(f"/api/projects/{pid}/exports", json={"settings": body})
    assert res.status_code == 202, res.text
    wait_idle(600)
    return next(
        e for e in client.get(f"/api/projects/{pid}/exports").json() if e["id"] == res.json()["id"]
    )


def _probe(path: Path) -> dict[str, Any]:
    out = subprocess.run(
        ["ffprobe", "-v", "error", "-print_format", "json", "-show_streams", "-show_format", str(path)],
        capture_output=True, text=True,
    ).stdout  # fmt: skip
    return json.loads(out)


def _gray_frame(path: Path, t: float, width: int = 180) -> Any:
    import numpy as np

    raw = subprocess.run(
        [FFMPEG, "-hide_banner", "-loglevel", "error", "-ss", f"{t}", "-i", str(path),
         "-frames:v", "1", "-vf", f"scale={width}:-2,format=gray", "-f", "rawvideo", "-"],
        capture_output=True, check=True,
    ).stdout  # fmt: skip
    return np.frombuffer(raw, np.uint8).reshape(-1, width).astype(np.float32)


def _band_difference(a: Path, b: Path, t: float, region: tuple[float, float]) -> float:
    """Diferencia media (0–255) en una franja vertical entre dos videos en el instante ``t``."""
    fa, fb = _gray_frame(a, t), _gray_frame(b, t)
    h = min(len(fa), len(fb))
    lo, hi = int(region[0] * h), int(region[1] * h)
    return float(abs(fa[lo:hi] - fb[lo:hi]).mean())


@pytest.mark.parametrize("key", ["es", "rotated"])
def test_export_with_subtitles_original_and_1080(
    client: TestClient, disk: Path, voice_media, key: str
) -> None:
    configure(client, disk)
    source = voice_media[key]
    before = sha256(source)
    pid, asset = _import(client, source)
    if _models_ready() and key == "es":
        _use_model(client)
        _analyze(client, pid, visual=False)
    exp = _export(client, pid)
    assert exp["status"] == "succeeded", exp
    out = disk / exp["file_rel"]
    info = _probe(out)
    v = next(s for s in info["streams"] if s["codec_type"] == "video")
    assert (v["width"], v["height"]) == (asset["display_width"], asset["display_height"])
    assert "side_data_list" not in v or all(
        "rotation" not in sd for sd in v.get("side_data_list", [])
    )
    src_info = _probe(disk / asset["file_rel"])
    assert abs(float(info["format"]["duration"]) - float(src_info["format"]["duration"])) < 0.1
    audio = [s for s in info["streams"] if s["codec_type"] == "audio"]
    if asset["has_audio"]:
        assert audio and abs(float(audio[0]["start_time"]) - float(v["start_time"])) < 0.05
    if _models_ready() and key == "es":
        # Subtítulos realmente integrados: tinta blanca en la franja inferior durante la voz.
        first = voice_media["es_truth"][0]["start"] + 0.2
        with_subs = _band_difference(out, disk / asset["file_rel"], first, (0.55, 0.85))
        elsewhere = _band_difference(out, disk / asset["file_rel"], first, (0.05, 0.35))
        assert with_subs > 3 * elsewhere + 1.0, (with_subs, elsewhere)
    assert sha256(source) == before
    # 1080p desde un original de 640 px: se rechaza (no se reescala hacia arriba).
    res = client.post(f"/api/projects/{pid}/exports",
                      json={"settings": {"resolution": "1080p", "fps": "original", "format": "mp4_h264",
                                         "quality": "high", "encoder": "hardware"}})  # fmt: skip
    assert res.status_code == 422 and res.json()["code"] == "upscale_not_allowed"


def test_export_4k_1080p_hevc_prores(client: TestClient, disk: Path, voice_media) -> None:
    configure(client, disk)
    pid, asset = _import(client, voice_media["uhd"])
    assert (asset["display_width"], asset["display_height"]) == (2160, 3840)
    for settings, dims, codec in [
        ({"resolution": "4k"}, (2160, 3840), "h264"),
        ({"resolution": "1080p"}, (1080, 1920), "h264"),
        ({"resolution": "1080p", "format": "mp4_hevc"}, (1080, 1920), "hevc"),
        ({"resolution": "1080p", "format": "mov_prores", "fps": 30}, (1080, 1920), "prores"),
        ({"resolution": "1080p", "encoder": "software", "quality": "max"}, (1080, 1920), "h264"),
    ]:
        exp = _export(client, pid, **settings)
        assert exp["status"] == "succeeded", (settings, exp)
        v = next(s for s in _probe(disk / exp["file_rel"])["streams"] if s["codec_type"] == "video")
        assert (v["width"], v["height"]) == dims and v["codec_name"] == codec, (settings, v)


def test_export_cancel_error_and_retry(client: TestClient, disk: Path, voice_media) -> None:
    from app.jobs.runner import runner

    configure(client, disk)
    pid, asset = _import(client, voice_media["uhd"])
    res = client.post(f"/api/projects/{pid}/exports", json={"settings": {
        "resolution": "4k", "fps": "original", "format": "mov_prores", "quality": "max",
        "encoder": "software"}})  # fmt: skip
    exp = res.json()
    deadline = time.monotonic() + 30
    while time.monotonic() < deadline:
        job = client.get(f"/api/jobs/{exp['job_id']}").json()
        if job["status"] == "running" and job["progress"] > 0.05:
            break
        time.sleep(0.2)
    client.post(f"/api/jobs/{exp['job_id']}/cancel")
    wait_idle(120)
    cancelled = next(
        e for e in client.get(f"/api/projects/{pid}/exports").json() if e["id"] == exp["id"]
    )
    assert cancelled["status"] == "cancelled"
    exports_dir = disk / client.get(f"/api/projects/{pid}").json()["dir_rel"] / "exports"
    assert not [p for p in exports_dir.iterdir() if not p.name.startswith("._")], (
        "sin archivos a medias"
    )
    # Error de procesamiento: el original desaparece del almacenamiento.
    stored = disk / asset["file_rel"]
    hidden = stored.with_name("oculto.bak")
    stored.chmod(0o644)
    stored.rename(hidden)
    failed = _export(client, pid, resolution="1080p")
    assert failed["status"] == "failed" and failed["error"]
    hidden.rename(stored)
    # Reintento seguro del trabajo fallido.
    retry = client.post(f"/api/jobs/{failed['job_id']}/retry")
    assert retry.status_code == 202
    wait_idle(300)
    again = next(
        e for e in client.get(f"/api/projects/{pid}/exports").json() if e["id"] == failed["id"]
    )
    assert again["status"] == "succeeded"
    assert runner.max_workers >= 1


def test_export_rules_hdr_and_plan(client: TestClient, disk: Path, media) -> None:
    from app.domain.edit_config import ExportSettings
    from app.models import MediaAsset
    from app.services.exporter import ExportError, plan_export

    asset = MediaAsset(display_width=1080, display_height=1920, duration=10, bit_rate=10_000_000,
                       color_transfer="arib-std-b67", bit_depth=10, has_audio=False, probe={},
                       audio_tracks=[])  # fmt: skip
    with pytest.raises(ExportError) as exc:
        plan_export(asset, ExportSettings(format="mp4_h264"))
    assert exc.value.code == "hdr_requires_hevc"
    plan = plan_export(asset, ExportSettings(format="mp4_hevc"))
    assert plan.pix_fmt == "yuv420p10le" and any("HDR" in w for w in plan.warnings)
    configure(client, disk)
    pid, _ = _import(client, media["prores"])
    res = client.post(f"/api/projects/{pid}/exports/plan", json={}).json()
    assert res["ok"] and res["plan"]["video_codec"] == "h264"
    assert any("AAC" in w for w in res["plan"]["warnings"]), "PCM no cabe en MP4: se avisa"


def test_heavy_jobs_run_one_at_a_time() -> None:
    from app.jobs.runner import REGISTRY

    assert all(
        REGISTRY[k].heavy for k in ("transcribe", "analyze_visual", "export", "align_segments")
    )
    assert not REGISTRY["ingest"].heavy and not REGISTRY["download_model"].heavy


def test_asr_model_catalog_is_pinned() -> None:
    from app.services.asr_models import CATALOG

    for spec in CATALOG.values():
        assert len(spec.revision) == 40
        assert all(len(f.sha256) == 64 for f in spec.files)
    assert hashlib.sha256(b"").hexdigest()


# ---------------------------------------------------------------------------
# Regresiones de la revisión de código de la Fase 2
# ---------------------------------------------------------------------------


def test_alignment_keeps_unique_ids_for_repeated_words() -> None:
    from types import SimpleNamespace

    from app.services import transcripts as ts

    seg = {"id": "s1", "start": 0, "end": 3, "text": "the cat and the dog", "edited": False,
           "reviewed": False, "needs_timing_review": True,
           "words": [{"id": f"w{i}", "text": t, "start": i * 0.5, "end": i * 0.5 + 0.4,
                      "timing": "estimated", "edited": False, "original_text": None,
                      "probability": None}
                     for i, t in enumerate(["the", "cat", "and", "the", "dog"])]}  # fmt: skip
    fake = SimpleNamespace(kind="edited", segments=[seg], stats={})
    aligned = {"s1": [{"text": t, "start": i * 0.5, "end": i * 0.5 + 0.3}
                      for i, t in enumerate(["the", "cat", "and", "the", "dog"])]}  # fmt: skip
    t, skipped = ts.apply_alignment(None, fake, aligned, {"s1": "the cat and the dog"})  # type: ignore[arg-type]
    ids = [w["id"] for w in t.segments[0]["words"]]
    assert len(set(ids)) == 5 and ids == ["w0", "w1", "w2", "w3", "w4"] and not skipped
    # Si el texto cambió mientras se realineaba, no se pisa la edición.
    _, skipped = ts.apply_alignment(None, fake, aligned, {"s1": "otro texto"})  # type: ignore[arg-type]
    assert skipped == ["s1"]


def test_blocks_never_overlap_even_with_overlapping_words() -> None:
    from app.domain.edit_config import SubtitleSettings
    from app.services.subtitles import build_track

    words = [{"id": "a", "text": "Hola.", "start": 0.0, "end": 2.0},
             {"id": "b", "text": "Mundo.", "start": 1.0, "end": 1.5}]  # fmt: skip
    track = build_track([{"words": words}], SubtitleSettings(), 1080, 1920)
    blocks = track["blocks"]
    assert all(a["end"] <= b["start"] for a, b in itertools.pairwise(blocks))
    assert all(b["end"] > b["start"] for b in blocks)


def test_overlay_timestamps_are_exact(tmp_path: Path) -> None:
    from app.domain.edit_config import SubtitleSettings
    from app.services.exporter import render_overlay
    from app.services.subtitles import build_track

    words = [{"id": f"w{i}", "text": t, "start": 0.013 + i * 0.137, "end": 0.013 + i * 0.137 + 0.12}
             for i, t in enumerate(["uno", "dos", "tres", "cuatro"])]  # fmt: skip
    track = build_track(
        [{"words": words}], SubtitleSettings(mode="dynamic", animation="none"), 320, 240
    )
    listing = render_overlay(track, tmp_path, 30, 2.0)
    assert listing is not None
    out = subprocess.run(
        ["ffprobe", "-v", "error", "-f", "concat", "-safe", "0", "-i", str(listing),
         "-show_entries", "frame=pts_time", "-of", "csv=p=0"],
        capture_output=True, text=True, check=True,
    ).stdout.split()  # fmt: skip
    pts = [round(float(x), 3) for x in out]
    for w in words:
        assert round(w["start"], 3) in pts, (w["start"], pts)


def test_scaled_export_layout_matches_preview() -> None:
    from app.domain.edit_config import SubtitleSettings
    from app.services.subtitles import build_track, scale_track

    preview = build_track(_segments(30), SubtitleSettings(font_size=90), 2160, 3840)
    scaled = scale_track(preview, 1080, 1920)
    for a, b in zip(preview["blocks"], scaled["blocks"], strict=True):
        assert [[w["text"] for w in ln["words"]] for ln in a["lines"]] == [
            [w["text"] for w in ln["words"]] for ln in b["lines"]
        ]
        assert abs(b["top"] - a["top"] / 2) < 1


def test_cancelling_queued_export_closes_the_export(client: TestClient, disk: Path, media) -> None:
    from app.jobs.runner import runner

    configure(client, disk)
    pid, _ = _import(client, media["horizontal"])
    runner.stop()  # la tarea queda en cola sin empezar
    try:
        exp = client.post(f"/api/projects/{pid}/exports", json={}).json()
        client.post(f"/api/jobs/{exp['job_id']}/cancel")
        rows = client.get(f"/api/projects/{pid}/exports").json()
        assert rows[0]["status"] == "cancelled"
    finally:
        runner.start()


@needs_asr
def test_reanalyze_keeps_corrected_version_active(
    client: TestClient, disk: Path, voice_media
) -> None:
    configure(client, disk)
    _use_model(client)
    pid, _ = _import(client, voice_media["es"])
    t = _analyze(client, pid, visual=False)["transcript"]
    seg = t["segments"][0]
    client.patch(
        f"/api/transcripts/{t['id']}/segments/{seg['id']}", json={"text": seg["text"] + " sí"}
    )
    again = _analyze(client, pid, visual=False)["transcript"]
    assert again["kind"] == "edited" and again["segments"][0]["text"].endswith("sí")
