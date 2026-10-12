"""Transcripción local: orquesta audio → VAD → Whisper (subproceso) → refinamiento.

Motor según la plataforma: MLX Whisper (Apple Silicon) o faster-whisper (Windows, Linux, Mac
Intel); ver ``app.platform.transcription``.

Caché: cada transcripción ASR guarda un ``params_hash`` (huella del original + modelo +
idioma + versión del proceso). Repetir con los mismos parámetros reutiliza el resultado sin
volver a procesar; cambiar cualquiera de ellos produce una versión nueva.
"""

from __future__ import annotations

import contextlib
import hashlib
import json
import logging
import shutil
import subprocess
import sys
import tempfile
import threading
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any

from sqlalchemy import select, update
from sqlalchemy.orm import Session

from app.config import get_settings
from app.db import BACKEND_DIR, session_scope
from app.domain.preferences import AnalysisPreferences
from app.models import MediaAsset, Transcript, new_id
from app.platform import processes
from app.services import asr_models, audio
from app.services.media_tools import Cancelled
from app.services.storage import atomic_write_json, resolve_inside

log = logging.getLogger(__name__)

PIPELINE_VERSION = "asr-2"  # cambiarla invalida la caché de transcripciones


class TranscriptionError(Exception):
    pass


def params_hash(asset: MediaAsset, model_id: str, language: str) -> str:
    key = json.dumps(
        {"sha": asset.sha256, "model": model_id, "language": language, "v": PIPELINE_VERSION},
        sort_keys=True,
    )
    return hashlib.sha256(key.encode()).hexdigest()


def find_cached(session: Session, asset_id: str, phash: str) -> Transcript | None:
    return session.scalar(
        select(Transcript)
        .where(Transcript.asset_id == asset_id, Transcript.kind == "asr")
        .where(Transcript.params_hash == phash)
        .order_by(Transcript.created_at.desc())
    )


def work_dir() -> Path:
    """Temporales en el disco interno (no en el externo exFAT de bloques de 1 MB)."""
    base = get_settings().home / "cache" / "work"
    base.mkdir(parents=True, exist_ok=True)
    return Path(tempfile.mkdtemp(prefix="asr-", dir=base))


def run_worker(
    request: dict[str, Any],
    on_progress: Callable[[float], None],
    cancel: threading.Event,
) -> dict[str, Any]:
    """Ejecuta el proceso de reconocimiento y devuelve su resultado."""
    tmp = Path(request["out"]).parent
    req_path = tmp / "request.json"
    req_path.write_text(json.dumps(request, ensure_ascii=False), encoding="utf-8")
    proc = subprocess.Popen(
        [sys.executable, "-m", "app.workers.transcribe_worker", str(req_path)],
        cwd=BACKEND_DIR,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        encoding="utf-8",
        errors="replace",
        env={**_env(), "HF_HUB_OFFLINE": "1", "PYTHONIOENCODING": "utf-8"},
        **processes.group_kwargs(),
    )
    processes.track(proc)
    error: str | None = None
    stderr_tail: list[str] = []
    device: dict[str, Any] = {}

    def _drain() -> None:
        assert proc.stderr is not None
        for line in proc.stderr:
            stderr_tail.append(line.rstrip())
            del stderr_tail[:-30]

    drain = threading.Thread(target=_drain, daemon=True)
    drain.start()

    def _watch() -> None:
        while proc.poll() is None:
            if cancel.is_set():
                processes.terminate_tree(proc, grace=2)
                return
            time.sleep(0.2)

    watcher = threading.Thread(target=_watch, daemon=True)
    watcher.start()
    assert proc.stdout is not None
    for line in proc.stdout:
        with contextlib.suppress(ValueError):
            msg = json.loads(line)
            if msg.get("type") == "progress":
                on_progress(float(msg["value"]))
            elif msg.get("type") == "error":
                error = msg.get("message")
            elif msg.get("type") == "device":
                device.update(msg)
    proc.wait()
    processes.untrack(proc)
    drain.join(timeout=2)
    if cancel.is_set():
        raise Cancelled()
    if proc.returncode != 0:
        detail = error or (stderr_tail[-1] if stderr_tail else f"código {proc.returncode}")
        raise TranscriptionError(f"El motor de transcripción falló: {detail}")
    result: dict[str, Any] = json.loads(Path(request["out"]).read_text(encoding="utf-8"))
    if device:
        result["device"] = {k: v for k, v in device.items() if k != "type"}
    return result


def _env() -> dict[str, str]:
    import os

    return dict(os.environ)


def build_segments(raw_segments: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Normaliza los segmentos del motor al formato persistido (ids estables)."""
    out: list[dict[str, Any]] = []
    wid = 0
    for seg in raw_segments:
        words = []
        for w in seg["words"]:
            wid += 1
            words.append(
                {
                    "id": f"w{wid:06d}",
                    "text": w["text"],
                    "start": w["start"],
                    "end": w["end"],
                    "probability": w.get("probability"),
                    "timing": w.get("timing", "asr"),
                    "edited": False,
                    "original_text": None,
                }
            )
        if not words:
            continue
        out.append(
            {
                "id": f"s{len(out) + 1:04d}",
                "start": words[0]["start"],
                "end": words[-1]["end"],
                "text": " ".join(w["text"] for w in words),
                "language": seg.get("language"),
                "avg_logprob": seg.get("avg_logprob"),
                "no_speech_prob": seg.get("no_speech_prob"),
                "edited": False,
                "reviewed": False,
                "needs_timing_review": False,
                "words": words,
            }
        )
    return out


def postprocess(
    raw_segments: list[dict[str, Any]], db: Any
) -> tuple[list[dict[str, Any]], dict[str, int]]:
    """Quita palabras en silencio absoluto (alucinaciones) y refina límites acústicos."""
    flat = [w for seg in raw_segments for w in seg["words"]]
    # Orden temporal estricto (los tramos se procesan en orden; por seguridad).
    flat.sort(key=lambda w: w["start"])
    drop = set(audio.words_in_silence(flat, db))
    kept_ids = {id(w) for i, w in enumerate(flat) if i not in drop}
    for seg in raw_segments:
        seg["words"] = [w for w in seg["words"] if id(w) in kept_ids]
    ordered = [w for seg in raw_segments for w in seg["words"]]
    before = [(w["start"], w["end"]) for w in ordered]
    changed = audio.refine_word_times(ordered, db)
    for w, (s, e) in zip(ordered, before, strict=True):
        w["timing"] = "refined" if (w["start"], w["end"]) != (s, e) else "asr"
    return build_segments(raw_segments), {"dropped_in_silence": len(drop), "refined": changed}


def transcribe_asset(
    asset: MediaAsset,
    root: Path,
    prefs: AnalysisPreferences,
    *,
    on_stage: Callable[[str, float, float], None],
    on_progress: Callable[[float], None],
    cancel: threading.Event,
) -> dict[str, Any]:
    """Transcribe y persiste. Devuelve un resumen (incluye si se reutilizó la caché)."""
    settings = get_settings()
    phash = params_hash(asset, prefs.transcription_model, prefs.language)
    with session_scope() as s:
        cached = find_cached(s, asset.id, phash)
        if cached is not None:
            # Si el usuario ya corrigió esa transcripción, la versión corregida sigue activa.
            edited = s.scalar(
                select(Transcript)
                .where(Transcript.parent_id == cached.id, Transcript.kind == "edited")
                .order_by(Transcript.updated_at.desc())
            )
            target = edited or cached
            _activate(s, asset.id, target.id)
            return {"transcript_id": target.id, "reused": True, "status": cached.status}

    base_stats: dict[str, Any] = {
        "model": prefs.transcription_model,
        "language_setting": prefs.language,
        "pipeline": PIPELINE_VERSION,
    }
    if not asset.has_audio:
        tid = _save(asset, root, phash, prefs, "no_audio", [], base_stats, None)
        return {"transcript_id": tid, "reused": False, "status": "no_audio"}

    spec = asr_models.require_usable(prefs.transcription_model)
    model_path = asr_models.installed_path(prefs.transcription_model)
    base_stats["engine"] = spec.engine
    src = resolve_inside(root, asset.file_rel)
    tmp = work_dir()
    try:
        on_stage("Extrayendo audio", 0.0, 0.05)
        wav = tmp / "audio.wav"
        duration = audio.extract_audio(settings.ffmpeg, src, wav, cancel)
        on_stage("Detectando voz y silencios", 0.05, 0.1)
        db = audio.energy_envelope(wav)
        va = audio.detect_voice(db)
        chunks = audio.plan_chunks(va)
        stats = {
            **base_stats,
            "duration": round(duration, 3),
            "voice": va.to_dict(),
            "chunks": [[round(a, 3), round(b, 3)] for a, b in chunks],
        }
        if not chunks:
            tid = _save(asset, root, phash, prefs, "no_speech", [], stats, None)
            return {"transcript_id": tid, "reused": False, "status": "no_speech"}
        on_stage("Transcribiendo con Whisper", 0.1, 0.92)
        started = time.time()
        result = run_worker(
            {
                "mode": "transcribe",
                "engine": spec.engine,
                "wav": str(wav),
                "model_dir": str(model_path),
                "language": prefs.language,
                "chunks": chunks,
                "out": str(tmp / "result.json"),
            },
            on_progress,
            cancel,
        )
        on_stage("Ajustando tiempos por palabra", 0.92, 1.0)
        segments, post = postprocess(result["segments"], db)
        languages: dict[str, float] = result.get("languages") or {}
        language = max(languages, key=lambda k: languages[k]) if languages else None
        elapsed = time.time() - started
        stats.update(
            {
                **post,
                "languages": {k: round(v, 2) for k, v in languages.items()},
                "words": sum(len(seg["words"]) for seg in segments),
                "segments": len(segments),
                "asr_seconds": round(elapsed, 2),
                "realtime_factor": round(duration / elapsed, 2) if elapsed else None,
                **({"device": result["device"]} if result.get("device") else {}),
            }
        )
        status = "ready" if segments else "no_speech"
        tid = _save(asset, root, phash, prefs, status, segments, stats, language)
        return {"transcript_id": tid, "reused": False, "status": status, **post}
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def _activate(session: Session, asset_id: str, transcript_id: str) -> None:
    session.execute(
        update(Transcript).where(Transcript.asset_id == asset_id).values(is_active=False)
    )
    session.execute(update(Transcript).where(Transcript.id == transcript_id).values(is_active=True))


def _save(
    asset: MediaAsset,
    root: Path,
    phash: str,
    prefs: AnalysisPreferences,
    status: str,
    segments: list[dict[str, Any]],
    stats: dict[str, Any],
    language: str | None,
) -> str:
    transcript = Transcript(
        id=new_id("trn"),
        asset_id=asset.id,
        kind="asr",
        is_active=True,
        status=status,
        engine=asr_models.get_spec(prefs.transcription_model).engine,
        model=prefs.transcription_model,
        language=language,
        params_hash=phash,
        segments=segments,
        stats=stats,
    )
    with session_scope() as s:
        s.add(transcript)
        s.flush()
        _activate(s, asset.id, transcript.id)
    write_snapshot(root, asset, transcript)
    return transcript.id


def write_snapshot(root: Path, asset: MediaAsset, transcript: Transcript) -> None:
    """Copia JSON en ``transcripts/`` del proyecto (portabilidad y consumo en la Fase 3)."""
    try:
        project_dir = resolve_inside(root, asset.file_rel).parents[1]
        atomic_write_json(
            project_dir / "transcripts" / f"{transcript.id}.json",
            {
                "id": transcript.id,
                "asset_id": asset.id,
                "kind": transcript.kind,
                "parent_id": transcript.parent_id,
                "engine": transcript.engine,
                "model": transcript.model,
                "language": transcript.language,
                "status": transcript.status,
                "stats": transcript.stats,
                "segments": transcript.segments,
            },
        )
    except OSError as exc:
        log.warning("No se pudo guardar la copia de la transcripción: %s", exc)
