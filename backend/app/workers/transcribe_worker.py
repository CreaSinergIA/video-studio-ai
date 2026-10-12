"""Proceso aislado de reconocimiento de voz (MLX Whisper o faster-whisper).

Se ejecuta como ``python -m app.workers.transcribe_worker <peticion.json>`` desde la cola de
tareas. Escribe progreso como líneas JSON en stdout y el resultado en el archivo indicado.

Modos:
- ``transcribe``: transcribe tramos del WAV (planificados por silencios) con marcas por
  palabra (alineación DTW sobre la atención cruzada de Whisper).
- ``align``: alineación forzada de un texto dado (segmentos corregidos) contra su audio.

Motor (``engine`` en la petición): ``mlx-whisper`` (Apple Silicon) o ``faster-whisper``
(CTranslate2: CPU INT8 o GPU NVIDIA con CUDA si está disponible; si la GPU falla al cargar, se
repite en la CPU). Ambos producen el mismo formato.

Ejecutarlo en un proceso propio libera la memoria del modelo al terminar, permite cancelar
de inmediato y aísla al servidor de fallos del motor.
"""

from __future__ import annotations

import json
import os
import sys
import time
from typing import Any

os.environ.setdefault("HF_HUB_OFFLINE", "1")  # nunca acceder a la red durante el proceso


def emit(kind: str, **data: Any) -> None:
    sys.stdout.write(json.dumps({"type": kind, **data}, ensure_ascii=False) + "\n")
    sys.stdout.flush()


def _patch_progress(on_frames: Any) -> None:
    """Sustituye la barra tqdm interna de mlx_whisper para conocer el avance real."""
    import mlx_whisper  # noqa: F401  (registra el submódulo)

    # ``mlx_whisper.transcribe`` es también el nombre de la función exportada: se toma el
    # módulo desde sys.modules.
    t = sys.modules["mlx_whisper.transcribe"]

    class _Bar:
        def __init__(self, total: int = 0, **_: Any) -> None:
            self.total = total or 1
            self.n = 0

        def __enter__(self) -> _Bar:
            return self

        def __exit__(self, *args: Any) -> None:
            return None

        def update(self, n: int) -> None:
            self.n += n
            on_frames(min(1.0, self.n / self.total))

    t.tqdm.tqdm = _Bar


def run_transcribe(req: dict[str, Any]) -> dict[str, Any]:
    import mlx_whisper

    from app.services.audio import read_samples

    chunks: list[list[float]] = req["chunks"]
    total = sum(b - a for a, b in chunks) or 1.0
    done = 0.0
    state = {"chunk": (0.0, 0.0)}

    def frames_progress(fraction: float) -> None:
        a, b = state["chunk"]
        emit("progress", value=round((done + (b - a) * fraction) / total, 4))

    _patch_progress(frames_progress)
    language = None if req.get("language") in (None, "auto") else req["language"]
    segments: list[dict[str, Any]] = []
    languages: dict[str, float] = {}
    started = time.time()
    for a, b in chunks:
        state["chunk"] = (a, b)
        audio = read_samples(req["wav"], a, b)
        result = mlx_whisper.transcribe(
            audio,
            path_or_hf_repo=req["model_dir"],
            word_timestamps=True,
            language=language,
            condition_on_previous_text=False,
            hallucination_silence_threshold=2.0,
            verbose=False,
        )
        lang = result.get("language")
        if lang:
            languages[lang] = languages.get(lang, 0.0) + (b - a)
        for seg in result.get("segments", []):
            words = [
                {
                    "text": w["word"].strip(),
                    "start": round(float(w["start"]) + a, 3),
                    "end": round(float(w["end"]) + a, 3),
                    "probability": round(float(w.get("probability", 0.0)), 4),
                }
                for w in seg.get("words", [])
                if w.get("word", "").strip()
            ]
            if not words:
                continue
            segments.append(
                {
                    "text": seg.get("text", "").strip(),
                    "words": words,
                    "language": lang,
                    "avg_logprob": round(float(seg.get("avg_logprob", 0.0)), 4),
                    "no_speech_prob": round(float(seg.get("no_speech_prob", 0.0)), 4),
                }
            )
        done += b - a
        emit("progress", value=round(done / total, 4))
    return {
        "segments": segments,
        "languages": languages,
        "elapsed": round(time.time() - started, 2),
    }


def run_align(req: dict[str, Any]) -> dict[str, Any]:
    import mlx.core as mx
    import numpy as np
    from mlx_whisper.audio import HOP_LENGTH, N_SAMPLES, SAMPLE_RATE, log_mel_spectrogram
    from mlx_whisper.load_models import load_model
    from mlx_whisper.timing import find_alignment, merge_punctuations
    from mlx_whisper.tokenizer import get_tokenizer

    from app.services.audio import read_samples

    model = load_model(req["model_dir"], dtype=mx.float16)
    out: list[dict[str, Any]] = []
    items = req["segments"]
    for i, seg in enumerate(items):
        start = max(0.0, float(seg["start"]) - 0.25)
        end = min(start + 29.5, float(seg["end"]) + 0.25)
        audio = read_samples(req["wav"], start, end)
        num_frames = len(audio) // HOP_LENGTH
        audio = np.pad(audio, (0, max(0, N_SAMPLES - len(audio))))[:N_SAMPLES]
        mel = log_mel_spectrogram(mx.array(audio), n_mels=model.dims.n_mels)
        tokenizer = get_tokenizer(
            model.is_multilingual,
            num_languages=model.num_languages,
            language=seg.get("language") or "es",
            task="transcribe",
        )
        text_tokens = tokenizer.encode(" " + seg["text"].strip())
        alignment = find_alignment(model, tokenizer, text_tokens, mel, num_frames)
        merge_punctuations(alignment, "\"'“¿([{-¡", "\"'.。,，!！?？:：”)]}、")
        words = [
            {
                "text": w.word.strip(),
                "start": round(start + float(w.start), 3),
                "end": round(start + float(w.end), 3),
                "probability": round(float(w.probability), 4),
            }
            for w in alignment
            if w.word.strip()
        ]
        out.append({"id": seg["id"], "words": words})
        emit("progress", value=round((i + 1) / len(items), 4))
    _ = SAMPLE_RATE
    return {"segments": out}


# ---------------------------------------------------------------------------
# faster-whisper (Windows, Linux, Mac Intel)
# ---------------------------------------------------------------------------

PREPEND = "\"'“¿([{-¡"
APPEND = "\"'.。,，!！?？:：”)]}、"


def _cuda_dll_dirs() -> None:
    """Windows: hace visibles las DLL de CUDA instaladas con el complemento opcional."""
    if sys.platform != "win32":
        return
    import importlib.util

    for package in ("nvidia.cublas", "nvidia.cudnn"):
        spec = importlib.util.find_spec(package)
        for location in (spec.submodule_search_locations or []) if spec else []:
            bin_dir = os.path.join(location, "bin")
            if os.path.isdir(bin_dir):
                os.add_dll_directory(bin_dir)
                os.environ["PATH"] = bin_dir + os.pathsep + os.environ.get("PATH", "")


def _fw_model(model_dir: str) -> Any:
    _cuda_dll_dirs()
    from faster_whisper import WhisperModel

    from app.platform.transcription import preferred_device

    device, compute = preferred_device()
    threads = _cpu_threads()
    if device == "cuda":
        try:
            model = WhisperModel(model_dir, device="cuda", compute_type=compute)
            emit("device", value="cuda")
            return model
        except Exception as exc:  # bibliotecas CUDA ausentes o incompatibles: CPU
            emit("device", value="cpu", fallback=f"{type(exc).__name__}: {exc}"[:300])
    else:
        emit("device", value="cpu")
    return WhisperModel(model_dir, device="cpu", compute_type="int8", cpu_threads=threads)


def _cpu_threads() -> int:
    env = os.environ.get("VSA_ASR_THREADS")
    if env and env.isdigit():
        return max(1, int(env))
    try:
        import psutil

        physical = psutil.cpu_count(logical=False) or 0
    except Exception:
        physical = 0
    # Deja un núcleo libre para que el panel y el sistema sigan respondiendo.
    return max(1, (physical or os.cpu_count() or 2) - 1)


def run_transcribe_fw(req: dict[str, Any]) -> dict[str, Any]:
    from app.services.audio import read_samples

    model = _fw_model(req["model_dir"])
    chunks: list[list[float]] = req["chunks"]
    total = sum(b - a for a, b in chunks) or 1.0
    done = 0.0
    language = None if req.get("language") in (None, "auto") else req["language"]
    segments: list[dict[str, Any]] = []
    languages: dict[str, float] = {}
    started = time.time()
    for a, b in chunks:
        audio = read_samples(req["wav"], a, b)
        seg_iter, info = model.transcribe(
            audio,
            language=language,
            word_timestamps=True,
            condition_on_previous_text=False,
            hallucination_silence_threshold=2.0,
            beam_size=5,
            vad_filter=False,  # los tramos ya vienen planificados por silencios
        )
        lang = info.language
        if lang:
            languages[lang] = languages.get(lang, 0.0) + (b - a)
        span = max(b - a, 1e-6)
        for seg in seg_iter:  # generador: la transcripción avanza al iterar
            emit("progress", value=round((done + min(span, seg.end)) / total, 4))
            words = [
                {
                    "text": w.word.strip(),
                    "start": round(float(w.start) + a, 3),
                    "end": round(float(w.end) + a, 3),
                    "probability": round(float(w.probability), 4),
                }
                for w in (seg.words or [])
                if w.word.strip()
            ]
            if not words:
                continue
            segments.append(
                {
                    "text": seg.text.strip(),
                    "words": words,
                    "language": lang,
                    "avg_logprob": round(float(seg.avg_logprob), 4),
                    "no_speech_prob": round(float(seg.no_speech_prob), 4),
                }
            )
        done += b - a
        emit("progress", value=round(done / total, 4))
    return {
        "segments": segments,
        "languages": languages,
        "elapsed": round(time.time() - started, 2),
    }


def run_align_fw(req: dict[str, Any]) -> dict[str, Any]:
    from faster_whisper.audio import pad_or_trim
    from faster_whisper.tokenizer import Tokenizer
    from faster_whisper.transcribe import merge_punctuations

    from app.services.audio import read_samples

    model = _fw_model(req["model_dir"])
    out: list[dict[str, Any]] = []
    items = req["segments"]
    for i, seg in enumerate(items):
        start = max(0.0, float(seg["start"]) - 0.25)
        end = min(start + 29.5, float(seg["end"]) + 0.25)
        audio = read_samples(req["wav"], start, end)
        features = model.feature_extractor(audio)
        num_frames = min(int(features.shape[-1]), 3000)
        encoder_output = model.encode(pad_or_trim(features))
        tokenizer = Tokenizer(
            model.hf_tokenizer,
            model.model.is_multilingual,
            task="transcribe",
            language=seg.get("language") or "es",
        )
        text_tokens = tokenizer.encode(" " + seg["text"].strip())
        alignment = model.find_alignment(tokenizer, [text_tokens], encoder_output, num_frames)[0]
        merge_punctuations(alignment, PREPEND, APPEND)
        words = [
            {
                "text": w["word"].strip(),
                "start": round(start + float(w["start"]), 3),
                "end": round(start + float(w["end"]), 3),
                "probability": round(float(w["probability"]), 4),
            }
            for w in alignment
            if w["word"].strip()
        ]
        out.append({"id": seg["id"], "words": words})
        emit("progress", value=round((i + 1) / len(items), 4))
    return {"segments": out}


def main() -> int:
    with open(sys.argv[1], encoding="utf-8") as fh:
        req = json.load(fh)
    fw = req.get("engine") == "faster-whisper"
    try:
        if req["mode"] == "align":
            result = run_align_fw(req) if fw else run_align(req)
        else:
            result = run_transcribe_fw(req) if fw else run_transcribe(req)
    except Exception as exc:  # el proceso padre muestra el mensaje
        emit("error", message=f"{type(exc).__name__}: {exc}")
        return 1
    with open(req["out"], "w", encoding="utf-8") as fh:
        json.dump(result, fh, ensure_ascii=False)
    emit("done")
    return 0


if __name__ == "__main__":
    sys.exit(main())
