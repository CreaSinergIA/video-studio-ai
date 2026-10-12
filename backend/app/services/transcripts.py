"""Edición de transcripciones y exportación a TXT/SRT/VTT.

Reglas de sincronización al corregir:
- Si una palabra se corrige 1:1 (misma cantidad de palabras), conserva sus tiempos medidos.
- Si cambia la estructura (palabras añadidas, quitadas o divididas), las palabras nuevas
  reciben tiempos **estimados** (marcados ``timing="estimated"``) dentro del tramo que
  ocupaban las originales, y el segmento queda marcado ``needs_timing_review``. El usuario
  decide: realinear con el audio (alineación forzada local) o ajustar los tiempos a mano.
  Nunca se presentan tiempos estimados como medidos.
"""

from __future__ import annotations

import copy
import difflib
import itertools
import re
import threading
import unicodedata
from typing import Any

from sqlalchemy import select, update
from sqlalchemy.orm import Session

from app.models import MediaAsset, Transcript, new_id

TIMING_LABELS = {
    "asr": "Medido (Whisper)",
    "refined": "Medido (ajuste acústico)",
    "aligned": "Medido (realineado)",
    "manual": "Manual",
    "estimated": "Estimado — revisar",
}


class TranscriptError(Exception):
    def __init__(self, code: str, message: str, status_code: int = 409) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.status_code = status_code


def _norm(word: str) -> str:
    word = unicodedata.normalize("NFC", word.lower())
    return re.sub(r"[^\w]", "", word)


def get_transcript(session: Session, transcript_id: str) -> Transcript:
    t = session.get(Transcript, transcript_id)
    if t is None:
        raise TranscriptError("transcript_not_found", "La transcripción no existe.", 404)
    return t


def active_for_asset(session: Session, asset_id: str) -> Transcript | None:
    return session.scalar(
        select(Transcript)
        .where(Transcript.asset_id == asset_id, Transcript.is_active.is_(True))
        .order_by(Transcript.created_at.desc())
    )


def versions_for_asset(session: Session, asset_id: str) -> list[Transcript]:
    return list(
        session.scalars(
            select(Transcript)
            .where(Transcript.asset_id == asset_id)
            .order_by(Transcript.created_at.desc())
        )
    )


def activate(session: Session, transcript: Transcript) -> None:
    session.execute(
        update(Transcript).where(Transcript.asset_id == transcript.asset_id).values(is_active=False)
    )
    transcript.is_active = True


_EDIT_LOCK = threading.Lock()


def editable(session: Session, transcript: Transcript) -> Transcript:
    """Devuelve la versión corregida (la crea a partir de la original si hace falta)."""
    if transcript.kind == "edited":
        return transcript
    with _EDIT_LOCK:
        return _editable_locked(session, transcript)


def _editable_locked(session: Session, transcript: Transcript) -> Transcript:
    existing = session.scalar(
        select(Transcript)
        .where(Transcript.parent_id == transcript.id, Transcript.kind == "edited")
        .order_by(Transcript.created_at.desc())
    )
    if existing is not None:
        activate(session, existing)
        return existing
    edited = Transcript(
        id=new_id("trn"),
        asset_id=transcript.asset_id,
        kind="edited",
        parent_id=transcript.id,
        is_active=True,
        status=transcript.status,
        engine=transcript.engine,
        model=transcript.model,
        language=transcript.language,
        params_hash=transcript.params_hash,
        segments=copy.deepcopy(transcript.segments),
        stats={**(transcript.stats or {}), "edited_from": transcript.id},
    )
    session.add(edited)
    session.flush()
    activate(session, edited)
    session.commit()  # visible para peticiones concurrentes (protegidas por el candado)
    return edited


def _find_segment(t: Transcript, segment_id: str) -> tuple[int, dict[str, Any]]:
    for i, seg in enumerate(t.segments):
        if seg["id"] == segment_id:
            return i, seg
    raise TranscriptError("segment_not_found", "El segmento no existe.", 404)


def _next_word_id(t: Transcript) -> int:
    ids = [int(w["id"][1:]) for seg in t.segments for w in seg["words"] if w["id"][1:].isdigit()]
    return max(ids, default=0) + 1


def _commit_segments(t: Transcript, segments: list[dict[str, Any]]) -> None:
    # Reasignar la lista completa para que SQLAlchemy detecte el cambio del JSON.
    t.segments = segments
    stats = dict(t.stats or {})
    stats["words"] = sum(len(s["words"]) for s in segments)
    stats["estimated_words"] = sum(
        1 for s in segments for w in s["words"] if w.get("timing") == "estimated"
    )
    t.stats = stats


def update_segment_text(
    session: Session, transcript: Transcript, segment_id: str, new_text: str
) -> Transcript:
    new_text = " ".join(new_text.split())
    if not new_text:
        raise TranscriptError("empty_text", "El segmento no puede quedar vacío.", 422)
    t = editable(session, transcript)
    segments = copy.deepcopy(t.segments)
    idx, seg = _find_segment(t, segment_id)
    seg = segments[idx]
    old = seg["words"]
    new_tokens = new_text.split(" ")
    matcher = difflib.SequenceMatcher(
        a=[_norm(w["text"]) for w in old], b=[_norm(x) for x in new_tokens], autojunk=False
    )
    next_id = _next_word_id(t)
    words: list[dict[str, Any]] = []
    structural = False
    for op, a0, a1, b0, b1 in matcher.get_opcodes():
        if op in ("equal",) or (op == "replace" and a1 - a0 == b1 - b0):
            for k in range(b1 - b0):
                w = dict(old[a0 + k])
                text = new_tokens[b0 + k]
                if text != w["text"]:
                    w["original_text"] = w.get("original_text") or w["text"]
                    w["text"] = text
                    w["edited"] = True
                words.append(w)
            continue
        if op == "delete":
            structural = True
            continue
        # insert o replace con distinto número de palabras → tiempos estimados
        structural = True
        if a1 > a0:
            span_start, span_end = old[a0]["start"], old[a1 - 1]["end"]
        else:
            prev_end = words[-1]["end"] if words else seg["start"]
            nxt = old[a0]["start"] if a0 < len(old) else seg["end"]
            span_start, span_end = prev_end, max(nxt, prev_end + 0.05)
        count = b1 - b0
        step = (span_end - span_start) / count if count else 0
        for k in range(count):
            words.append(
                {
                    "id": f"w{next_id:06d}",
                    "text": new_tokens[b0 + k],
                    "start": round(span_start + step * k, 3),
                    "end": round(span_start + step * (k + 1), 3),
                    "probability": None,
                    "timing": "estimated",
                    "edited": True,
                    "original_text": None,
                }
            )
            next_id += 1
    seg["words"] = words
    seg["text"] = " ".join(w["text"] for w in words)
    seg["edited"] = True
    seg["needs_timing_review"] = bool(seg.get("needs_timing_review")) or structural
    if words:
        seg["start"], seg["end"] = words[0]["start"], words[-1]["end"]
    _commit_segments(t, segments)
    return t


def update_word_times(
    session: Session,
    transcript: Transcript,
    segment_id: str,
    times: list[dict[str, Any]],
    duration: float,
) -> Transcript:
    """Ajuste manual explícito de tiempos (palabras y, por extensión, el segmento)."""
    t = editable(session, transcript)
    segments = copy.deepcopy(t.segments)
    idx, _ = _find_segment(t, segment_id)
    seg = segments[idx]
    by_id = {w["id"]: w for w in seg["words"]}
    for item in times:
        w = by_id.get(item["id"])
        if w is None:
            raise TranscriptError("word_not_found", "Palabra inexistente en el segmento.", 404)
        start, end = float(item["start"]), float(item["end"])
        if not (0 <= start < end <= duration + 0.01):
            raise TranscriptError("invalid_times", f"Tiempos no válidos para «{w['text']}».", 422)
        w["start"], w["end"], w["timing"] = round(start, 3), round(end, 3), "manual"
    words = seg["words"]
    for a, b in itertools.pairwise(words):
        if b["start"] < a["start"] or b["start"] < a["end"] - 0.001:
            raise TranscriptError(
                "overlap",
                f"«{b['text']}» empieza antes de que termine «{a['text']}». Ordena los tiempos.",
                422,
            )
    seg["start"], seg["end"] = words[0]["start"], words[-1]["end"]
    seg["needs_timing_review"] = any(w["timing"] == "estimated" for w in words)
    _commit_segments(t, segments)
    return t


def apply_alignment(
    session: Session,
    transcript: Transcript,
    aligned: dict[str, list[dict[str, Any]]],
    expected_text: dict[str, str] | None = None,
) -> tuple[Transcript, list[str]]:
    """Sustituye las palabras de los segmentos realineados por tiempos medidos.

    Las palabras se emparejan en orden (difflib) con las anteriores para conservar ids e
    historial de corrección; las repetidas no comparten id. Si el texto del segmento cambió
    mientras se realineaba (``expected_text``), ese segmento se omite para no pisar la
    edición. Devuelve la transcripción y los ids omitidos.
    """
    t = editable(session, transcript)
    segments = copy.deepcopy(t.segments)
    next_id = _next_word_id(t)
    skipped: list[str] = []
    for seg in segments:
        new_words = aligned.get(seg["id"])
        if not new_words:
            continue
        if expected_text is not None and seg["text"] != expected_text.get(seg["id"]):
            skipped.append(seg["id"])
            continue
        old = seg["words"]
        matcher = difflib.SequenceMatcher(
            a=[_norm(w["text"]) for w in old],
            b=[_norm(w["text"]) for w in new_words],
            autojunk=False,
        )
        prev_for: dict[int, dict[str, Any]] = {}
        for op, a0, a1, b0, b1 in matcher.get_opcodes():
            if op == "equal" or (op == "replace" and a1 - a0 == b1 - b0):
                for k in range(b1 - b0):
                    prev_for[b0 + k] = old[a0 + k]
        words = []
        for k, w in enumerate(new_words):
            prev = prev_for.get(k)
            words.append(
                {
                    "id": prev["id"] if prev else f"w{next_id:06d}",
                    "text": w["text"],
                    "start": w["start"],
                    "end": w["end"],
                    "probability": w.get("probability"),
                    "timing": "aligned",
                    "edited": bool(prev and prev.get("edited")) or prev is None,
                    "original_text": prev.get("original_text") if prev else None,
                }
            )
            if not prev:
                next_id += 1
        seg["words"] = words
        seg["text"] = " ".join(w["text"] for w in words)
        seg["start"], seg["end"] = words[0]["start"], words[-1]["end"]
        seg["needs_timing_review"] = False
    _commit_segments(t, segments)
    return t, skipped


def set_reviewed(
    session: Session, transcript: Transcript, segment_id: str, reviewed: bool
) -> Transcript:
    t = editable(session, transcript)
    segments = copy.deepcopy(t.segments)
    idx, _ = _find_segment(t, segment_id)
    segments[idx]["reviewed"] = reviewed
    _commit_segments(t, segments)
    return t


# ---------------------------------------------------------------------------
# Exportación de texto
# ---------------------------------------------------------------------------


def _ts(seconds: float, sep: str) -> str:
    ms = round(max(0.0, seconds) * 1000)
    h, rem = divmod(ms, 3_600_000)
    m, rem = divmod(rem, 60_000)
    s, ms = divmod(rem, 1000)
    return f"{h:02d}:{m:02d}:{s:02d}{sep}{ms:03d}"


def caption_cues(
    segments: list[dict[str, Any]], max_chars: int = 42, max_lines: int = 2, max_dur: float = 6.0
) -> list[tuple[float, float, list[str]]]:
    """Agrupa palabras en subtítulos estándar (≤ 2 líneas de 42 caracteres, ≤ 6 s), cortando
    en puntuación y pausas. Usa los tiempos por palabra."""
    cues: list[tuple[float, float, list[str]]] = []
    for seg in segments:
        lines: list[str] = [""]
        start = None
        prev_end = None
        for w in seg["words"]:
            text = w["text"]
            if start is None:
                start = w["start"]
            line = lines[-1]
            candidate = f"{line} {text}".strip()
            pause = prev_end is not None and w["start"] - prev_end > 0.7
            too_long = w["end"] - start > max_dur
            if (len(candidate) > max_chars or pause or too_long) and line:
                if len(lines) < max_lines and not pause and not too_long:
                    lines.append(text)
                else:
                    cues.append((start, prev_end or w["start"], lines))
                    lines, start = [text], w["start"]
            else:
                lines[-1] = candidate
            prev_end = w["end"]
            if text.endswith((".", "?", "!", "…")) and lines[-1]:
                cues.append((start, w["end"], lines))
                lines, start = [""], None
        if start is not None and any(lines):
            cues.append((start, prev_end or start, [ln for ln in lines if ln]))
    return [(a, max(b, a + 0.3), ls) for a, b, ls in cues if ls]


def to_txt(segments: list[dict[str, Any]]) -> str:
    return "\n".join(seg["text"] for seg in segments) + "\n"


def to_srt(segments: list[dict[str, Any]]) -> str:
    out = []
    for i, (a, b, lines) in enumerate(caption_cues(segments), 1):
        out.append(f"{i}\n{_ts(a, ',')} --> {_ts(b, ',')}\n" + "\n".join(lines) + "\n")
    return "\n".join(out)


def to_vtt(segments: list[dict[str, Any]]) -> str:
    out = ["WEBVTT", ""]
    for a, b, lines in caption_cues(segments):
        out.append(f"{_ts(a, '.')} --> {_ts(b, '.')}\n" + "\n".join(lines) + "\n")
    return "\n".join(out)


def media_duration(session: Session, transcript: Transcript) -> float:
    asset = session.get(MediaAsset, transcript.asset_id)
    return asset.duration if asset else 0.0
