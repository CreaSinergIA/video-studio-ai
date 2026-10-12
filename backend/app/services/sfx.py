"""Biblioteca local de efectos de sonido (Fase 4), generada por programa.

Todos los sonidos se sintetizan aquí (ruido filtrado, osciladores y envolventes) con semilla
fija: son originales, deterministas y sin restricciones de licencia. No se descarga ni se
incorpora material de terceros. Se escriben una vez en la caché de la app (WAV 48 kHz estéreo).
"""

from __future__ import annotations

import wave
from pathlib import Path
from typing import Final

import numpy as np

from app.config import get_settings

SR: Final = 48_000
VERSION: Final = 2  # v2 (Fase 4.1): normalización por energía y variantes
KINDS: Final = (
    "whoosh",
    "swoosh",
    "pop",
    "click",
    "ding",
    "typing",
    "glitch",
    "riser",
    "impact",
    "paper",
)
LABELS: Final = {
    "whoosh": "Whoosh (movimiento amplio)",
    "swoosh": "Transición suave",
    "pop": "Pop",
    "click": "Clic digital",
    "ding": "Confirmación",
    "typing": "Tecleo / conexión de datos",
    "glitch": "Activación tecnológica",
    "riser": "Subida (anticipación)",
    "impact": "Impacto ligero",
    "paper": "Papel / trazo",
}


def _t(seconds: float) -> np.ndarray:
    return np.arange(int(SR * seconds)) / SR


def _onepole_lp(x: np.ndarray, cutoff: np.ndarray | float) -> np.ndarray:
    """Filtro paso bajo de un polo con frecuencia de corte variable en el tiempo."""
    c = np.broadcast_to(np.asarray(cutoff, dtype=np.float64), x.shape)
    a = 1.0 - np.exp(-2 * np.pi * c / SR)
    y = np.empty_like(x)
    acc = 0.0
    for i in range(len(x)):
        acc += a[i] * (x[i] - acc)
        y[i] = acc
    return y


def _env(n: int, attack: float, release: float) -> np.ndarray:
    t = np.arange(n) / SR
    att = np.clip(t / max(attack, 1e-4), 0, 1)
    rel = np.exp(-np.maximum(0, t - attack) / max(release, 1e-4))
    return att * rel


def _whoosh(rng: np.random.Generator, dur: float, lo: float, hi: float) -> np.ndarray:
    t = _t(dur)
    x = rng.standard_normal(len(t))
    shape = np.sin(np.pi * np.clip(t / dur, 0, 1)) ** 1.6
    cutoff = lo + (hi - lo) * shape
    hp = x - _onepole_lp(x, 150.0)
    return _onepole_lp(hp, cutoff) * shape


# Nivel de referencia de todas las muestras: energía de su ventana más fuerte (RMS de 100 ms).
# Normalizar por pico (v1) dejaba los transitorios cortos con muy poca energía audible.
TARGET_RMS_DBFS: Final = -16.0
PEAK_CEILING_DBFS: Final = -1.0
VARIANTS: Final = 3
# Equilibrio por tipo (dB sobre el nivel común): los «tics» de interfaz van por debajo de los
# movimientos amplios y de los impactos.
BALANCE_DB: Final = {
    "whoosh": 0.0,
    "swoosh": -1.0,
    "pop": -1.5,
    "click": -1.5,
    "ding": -2.0,
    "typing": -2.0,
    "glitch": -2.0,
    "riser": -2.0,
    "impact": 0.0,
    "paper": -1.5,
}


def short_rms_db(y: np.ndarray, window: float = 0.1) -> float:
    """Energía (dBFS) de la ventana más fuerte de `window` segundos."""
    m = y if y.ndim == 1 else y.mean(axis=1)
    n = max(1, int(SR * window))
    if len(m) <= n:
        return float(20 * np.log10(np.sqrt(np.mean(m**2)) + 1e-12))
    c = np.cumsum(np.concatenate([[0.0], m.astype(np.float64) ** 2]))
    best = float(np.max((c[n:] - c[:-n]) / n))
    return float(10 * np.log10(best + 1e-12))


def _normalize(y: np.ndarray) -> np.ndarray:
    gain = 10 ** ((TARGET_RMS_DBFS - short_rms_db(y)) / 20)
    y = y * gain
    peak = float(np.max(np.abs(y))) or 1.0
    ceiling = 10 ** (PEAK_CEILING_DBFS / 20)
    if peak > ceiling:  # transitorios muy agudos: manda el techo de pico
        y = y * (ceiling / peak)
    return y


def synth(kind: str, variant: int = 0) -> np.ndarray:
    """Efecto sintetizado. `variant` (0–2) cambia la semilla y ligeramente el tono y la
    duración, para que los efectos repetidos no suenen idénticos."""
    y = _synth(kind, variant % VARIANTS)
    return _normalize(y.astype(np.float64)).astype(np.float32)


def _synth(kind: str, variant: int) -> np.ndarray:
    rng = np.random.default_rng(abs(hash_kind(kind)) + 1009 * variant)
    vary = (1.0, 0.94, 1.07)[variant]  # tono/duración relativos de la variante
    if kind == "whoosh":
        y = _whoosh(rng, 0.55 * vary, 300 * vary, 5000 * vary)
    elif kind == "swoosh":
        y = _whoosh(rng, 0.32 * vary, 600 * vary, 7000 * vary) * 0.8
    elif kind == "pop":
        t = _t(0.12)
        f = (650 * np.exp(-t * 28) + 160) * vary
        y = np.sin(2 * np.pi * np.cumsum(f) / SR) * _env(len(t), 0.002, 0.035)
        y[:120] += rng.standard_normal(120) * 0.25 * np.linspace(1, 0, 120)
    elif kind == "click":
        t = _t(0.05)
        y = np.sin(2 * np.pi * 3200 * vary * t) * _env(len(t), 0.0005, 0.006)
        y[:90] += rng.standard_normal(90) * 0.5 * np.linspace(1, 0, 90)
    elif kind == "ding":
        t = _t(0.9)
        y = (
            np.sin(2 * np.pi * 1318.5 * vary * t)
            + 0.5 * np.sin(2 * np.pi * 1975.5 * vary * t)
            + 0.2 * np.sin(2 * np.pi * 2637 * vary * t)
        )
        y *= _env(len(t), 0.003, 0.28)
    elif kind == "typing":
        y = np.zeros(int(SR * 0.5))
        for i in range(7):
            at = int(SR * (0.02 + i * 0.065 + rng.uniform(-0.012, 0.012)))
            n = int(SR * 0.025)
            tt = np.arange(n) / SR
            burst = (
                rng.standard_normal(n) * 0.6 + np.sin(2 * np.pi * rng.uniform(1800, 2600) * tt)
            ) * _env(n, 0.0005, 0.005)
            y[at : at + n] += burst[: len(y) - at] * rng.uniform(0.6, 1.0)
    elif kind == "glitch":
        y = np.zeros(int(SR * 0.3))
        pos = 0
        while pos < len(y):
            n = int(SR * rng.uniform(0.012, 0.04))
            if rng.random() < 0.7:
                tt = np.arange(n) / SR
                sq = np.sign(np.sin(2 * np.pi * rng.uniform(180, 1400) * tt))
                crushed = np.round(sq * 4) / 4
                y[pos : pos + n] = crushed[: len(y) - pos] * rng.uniform(0.3, 0.8)
            pos += n + int(SR * rng.uniform(0.0, 0.015))
        y *= _env(len(y), 0.002, 0.16)
    elif kind == "riser":
        t = _t(0.9)
        f = 180 * vary * (7 ** (t / 0.9))
        tone = np.sin(2 * np.pi * np.cumsum(f) / SR) * 0.35
        noise = _onepole_lp(rng.standard_normal(len(t)), 800 + 6000 * (t / 0.9))
        y = (tone + noise) * (t / 0.9) ** 2 * np.clip((0.9 - t) / 0.03, 0, 1)
    elif kind == "impact":
        t = _t(0.45)
        f = (90 * np.exp(-t * 6) + 42) * vary
        body = np.sin(2 * np.pi * np.cumsum(f) / SR) * _env(len(t), 0.002, 0.12)
        thump = _onepole_lp(rng.standard_normal(len(t)), 900.0) * _env(len(t), 0.001, 0.03)
        y = body + thump * 0.8
    elif kind == "paper":
        t = _t(0.45)
        x = rng.standard_normal(len(t))
        bp = _onepole_lp(x, 6000.0) - _onepole_lp(x, 1200.0)
        mod = np.abs(np.sin(2 * np.pi * 9 * t + rng.uniform(0, 6))) ** 2
        y = bp * mod * np.sin(np.pi * t / 0.45)
    else:
        raise ValueError(f"Efecto desconocido: {kind}")
    return np.asarray(y, dtype=np.float64)


def hash_kind(kind: str) -> int:
    return sum((i + 1) * ord(c) for i, c in enumerate(kind)) * 7919 + VERSION


def library_dir() -> Path:
    d = get_settings().home / "cache" / "sfx" / f"v{VERSION}"
    d.mkdir(parents=True, exist_ok=True)
    return d


def path_for(kind: str, variant: int = 0) -> Path:
    """Ruta del efecto (lo genera la primera vez)."""
    if kind not in KINDS:
        raise ValueError(f"Efecto desconocido: {kind}")
    variant %= VARIANTS
    p = library_dir() / (f"{kind}.wav" if variant == 0 else f"{kind}-{variant}.wav")
    if not p.is_file():
        y = synth(kind, variant)
        stereo = np.repeat((np.clip(y, -1, 1) * 32767).astype(np.int16)[:, None], 2, axis=1)
        tmp = p.with_suffix(".tmp")
        with wave.open(str(tmp), "wb") as w:
            w.setnchannels(2)
            w.setsampwidth(2)
            w.setframerate(SR)
            w.writeframes(stereo.tobytes())
        tmp.replace(p)
    return p


def catalog() -> list[dict[str, object]]:
    return [
        {"kind": k, "label": LABELS[k], "duration": round(len(synth(k)) / SR, 3)} for k in KINDS
    ]
