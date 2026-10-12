"""Audio para el análisis: extracción, detección de voz/silencio y refinamiento de tiempos.

- El audio se extrae a WAV mono 16 kHz (formato de Whisper) en el disco interno, alineado con
  la línea de tiempo del contenedor (``aresample=async=1:first_pts=0``): la muestra 0
  corresponde al instante 0 del video, igual que ``currentTime`` en el reproductor.
- La envolvente de energía (10 ms) se calcula leyendo el WAV por bloques: memoria acotada
  para videos largos.
- El refinamiento acústico ajusta los límites de palabra de Whisper al inicio/fin real de la
  energía *solo cuando hay un silencio medible*; si no lo hay, conserva el tiempo de Whisper.
  Validado contra audio con verdad de referencia (pruebas de desarrollo).
"""

from __future__ import annotations

import contextlib
import subprocess
import wave
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np

from app import limits
from app.platform import processes

SAMPLE_RATE = 16000
HOP_SECONDS = 0.01
_HOP = int(SAMPLE_RATE * HOP_SECONDS)


class AudioError(Exception):
    pass


def extract_audio(ffmpeg: str, src: Path, dest: Path, cancel: Any = None) -> float:
    """Extrae la primera pista de audio a WAV mono 16 kHz. Devuelve la duración en segundos."""
    cmd = [
        ffmpeg,
        "-hide_banner",
        "-nostdin",
        "-y",
        "-loglevel",
        "error",
        "-i",
        str(src),
        "-map",
        "0:a:0",
        "-vn",
        "-sn",
        "-dn",
        "-af",
        "aresample=async=1:first_pts=0",
        "-ac",
        "1",
        "-ar",
        str(SAMPLE_RATE),
        "-c:a",
        "pcm_s16le",
        str(dest),
    ]
    # stderr a un archivo: si FFmpeg escribe muchos avisos no puede bloquearse la tubería.
    err_path = dest.with_suffix(".log")
    err_file = open(err_path, "wb")  # noqa: SIM115
    from app.services.media_tools import Watchdog

    proc = subprocess.Popen(
        cmd, stdout=subprocess.DEVNULL, stderr=err_file, **processes.group_kwargs()
    )
    processes.track(proc)
    watchdog = Watchdog(
        proc,
        cancel=cancel,
        max_seconds=limits.ffmpeg_max_seconds(None),
        stall_seconds=limits.FFMPEG_STALL_SECONDS,
    )
    written = -1
    try:
        while proc.poll() is None:
            with contextlib.suppress(OSError):
                size = dest.stat().st_size
                if size != written:  # el WAV crece: hay avance real
                    written = size
                    watchdog.tick()
            with contextlib.suppress(subprocess.TimeoutExpired):
                proc.wait(timeout=0.25)
    finally:
        watchdog.stop()
        if proc.poll() is None:
            processes.terminate_tree(proc, grace=2)
        processes.untrack(proc)
        err_file.close()
    watchdog.raise_if_stopped()
    if proc.returncode != 0:
        detail = err_path.read_bytes()[-2000:].decode("utf-8", "replace")
        raise AudioError(f"No se pudo extraer el audio: {detail.strip()[-200:]}")
    with wave.open(str(dest)) as w:
        return w.getnframes() / w.getframerate()


def read_samples(path: Path, start: float = 0.0, end: float | None = None) -> np.ndarray:
    """Lee un tramo del WAV como float32 [-1, 1] (solo ese tramo en memoria)."""
    with wave.open(str(path)) as w:
        n = w.getnframes()
        a = max(0, int(start * SAMPLE_RATE))
        b = n if end is None else min(n, int(end * SAMPLE_RATE))
        w.setpos(a)
        data = w.readframes(max(0, b - a))
    return np.frombuffer(data, dtype=np.int16).astype(np.float32) / 32768.0


def energy_envelope(path: Path, block_seconds: float = 60.0) -> np.ndarray:
    """Energía RMS en dB por ventana de 10 ms, leyendo el archivo por bloques."""
    out: list[np.ndarray] = []
    with wave.open(str(path)) as w:
        block = int(block_seconds * SAMPLE_RATE) // _HOP * _HOP
        carry = np.zeros(0, dtype=np.float32)
        while True:
            data = w.readframes(block)
            if not data:
                break
            x = np.concatenate([carry, np.frombuffer(data, np.int16).astype(np.float32) / 32768])
            usable = len(x) // _HOP * _HOP
            frames = x[:usable].reshape(-1, _HOP)
            out.append(20 * np.log10(np.sqrt(np.mean(frames**2, axis=1)) + 1e-9))
            carry = x[usable:]
        if len(carry):
            out.append(np.array([20 * np.log10(np.sqrt(np.mean(carry**2)) + 1e-9)]))
    return np.concatenate(out) if out else np.zeros(0)


@dataclass
class VoiceActivity:
    """Resultado de la detección de voz (umbral adaptativo sobre la energía)."""

    threshold_db: float
    noise_floor_db: float
    speech: list[tuple[float, float]]
    silences: list[tuple[float, float]]
    duration: float

    @property
    def speech_seconds(self) -> float:
        return sum(b - a for a, b in self.speech)

    def to_dict(self) -> dict[str, Any]:
        return {
            "threshold_db": round(self.threshold_db, 1),
            "noise_floor_db": round(self.noise_floor_db, 1),
            "speech": [[round(a, 3), round(b, 3)] for a, b in self.speech],
            "silences": [[round(a, 3), round(b, 3)] for a, b in self.silences],
            "speech_seconds": round(self.speech_seconds, 2),
            "speech_ratio": round(self.speech_seconds / self.duration, 4) if self.duration else 0,
        }


def speech_mask(db: np.ndarray) -> tuple[np.ndarray, float, float]:
    """Marcos con voz: 15 dB sobre el ruido de fondo (percentil 10) y no más de 35 dB por
    debajo del nivel de pico de la voz (percentil 95), con techo de -50 dBFS para que las
    grabaciones flojas no pierdan voz y el silencio digital no cuente como voz."""
    if len(db) == 0:
        return np.zeros(0, dtype=bool), -90.0, -50.0
    floor = float(np.percentile(db, 10))
    peak = float(np.percentile(db, 95))
    thr = max(floor + 15.0, min(-50.0, peak - 35.0))
    return db > thr, floor, thr


def detect_voice(
    db: np.ndarray, min_speech: float = 0.12, min_silence: float = 0.35
) -> VoiceActivity:
    mask, floor, thr = speech_mask(db)
    duration = len(db) * HOP_SECONDS
    runs: list[list[float]] = []
    start = None
    for i, v in enumerate(mask):
        if v and start is None:
            start = i
        elif not v and start is not None:
            runs.append([start * HOP_SECONDS, i * HOP_SECONDS])
            start = None
    if start is not None:
        runs.append([start * HOP_SECONDS, len(mask) * HOP_SECONDS])
    # Unir huecos breves y descartar ráfagas muy cortas (clics).
    merged: list[list[float]] = []
    for r in runs:
        if merged and r[0] - merged[-1][1] < min_silence:
            merged[-1][1] = r[1]
        else:
            merged.append(r)
    speech = [(a, b) for a, b in merged if b - a >= min_speech]
    silences: list[tuple[float, float]] = []
    cursor = 0.0
    for a, b in speech:
        if a - cursor >= min_silence:
            silences.append((cursor, a))
        cursor = b
    if duration - cursor >= min_silence:
        silences.append((cursor, duration))
    return VoiceActivity(thr, floor, speech, silences, duration)


def plan_chunks(
    va: VoiceActivity, target: float = 240.0, max_len: float = 300.0
) -> list[tuple[float, float]]:
    """Divide el audio en tramos de ~4 min cortando en silencios (nunca dentro de una palabra
    si hay un silencio disponible). Los tramos sin voz se omiten."""
    if not va.speech:
        return []
    chunks: list[tuple[float, float]] = []
    start = max(0.0, va.speech[0][0] - 0.3)
    while start < va.duration:
        if va.duration - start <= max_len:
            chunks.append((start, va.duration))
            break
        ideal = start + target
        cuts = [(a + b) / 2 for a, b in va.silences if start + 30 < (a + b) / 2 < start + max_len]
        cut = min(cuts, key=lambda c: abs(c - ideal)) if cuts else start + max_len
        chunks.append((start, cut))
        start = cut
    # Omitir tramos sin voz detectada.
    return [(a, b) for a, b in chunks if any(sa < b and sb > a for sa, sb in va.speech)]


def refine_word_times(words: list[dict[str, Any]], db: np.ndarray) -> int:
    """Ajusta in situ ``start``/``end`` de cada palabra a los límites acústicos medidos.

    Devuelve cuántos límites se ajustaron. Reglas (todas basadas en evidencia del audio):
    - Inicio: si en el inicio de Whisper hay silencio, se avanza al primer marco con voz; si
      hay voz que continúa desde antes (cola de la palabra anterior) seguida de ≥30 ms de
      silencio, se avanza al siguiente arranque de voz, siempre dentro de la propia palabra.
    - Fin: se lleva al último marco con voz antes del inicio de la palabra siguiente, si tras
      él hay ≥30 ms de silencio.
    """
    mask, _, _ = speech_mask(db)
    n = len(mask)
    if n == 0 or not words:
        return 0
    gap = 3

    def fr(t: float) -> int:
        return max(0, min(n - 1, round(t / HOP_SECONDS)))

    changed = 0
    for w in words:
        s, e = float(w["start"]), float(w["end"])
        a, b = fr(s), fr(max(e, s + 0.05))
        new_s = s
        if not mask[a]:
            on = next((k for k in range(a, b + 1) if mask[k]), None)
            if on is not None and (on - a) * HOP_SECONDS <= 0.8:
                new_s = on * HOP_SECONDS
        else:
            limit = min(b, a + int(0.35 / HOP_SECONDS))
            run, k, found = 0, a, None
            while k <= limit:
                run = run + 1 if not mask[k] else 0
                if run >= gap:
                    found = next((j for j in range(k + 1, b + 1) if mask[j]), None)
                    break
                k += 1
            if (
                found is not None
                and found * HOP_SECONDS <= e - 0.06
                and mask[max(0, a - 2) : a].any()
            ):
                new_s = found * HOP_SECONDS
        if abs(new_s - s) > 1e-6:
            changed += 1
        w["start"] = round(new_s, 3)
    for i, w in enumerate(words):
        s, e = w["start"], float(w["end"])
        nxt = words[i + 1]["start"] if i + 1 < len(words) else e + 0.4
        hi = fr(min(nxt, e + 0.4)) - 1
        off = next((k for k in range(hi, fr(s), -1) if mask[k]), None)
        new_e = e
        if off is not None and not mask[off + 1 : min(n, off + 1 + gap)].any():
            new_e = (off + 1) * HOP_SECONDS
        if i + 1 < len(words):
            new_e = min(new_e, nxt)
        new_e = max(new_e, s + 0.02)
        if abs(new_e - e) > 1e-6:
            changed += 1
        w["end"] = round(new_e, 3)
    return changed


def words_in_silence(
    words: list[dict[str, Any]], db: np.ndarray, margin_db: float = 6.0
) -> list[int]:
    """Índices de palabras cuyo intervalo completo está en silencio (posibles alucinaciones
    de Whisper sobre tramos sin voz, p. ej. «Subtítulos por la comunidad de Amara.org»)."""
    mask, floor, _ = speech_mask(db)
    n = len(db)
    out = []
    for i, w in enumerate(words):
        a = max(0, int(w["start"] / HOP_SECONDS))
        b = min(n, max(a + 1, int(w["end"] / HOP_SECONDS)))
        if a >= n:
            out.append(i)
            continue
        if not mask[a:b].any() and float(np.max(db[a:b])) < floor + margin_db:
            out.append(i)
    return out
