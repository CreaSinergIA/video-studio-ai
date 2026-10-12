"""Composición segura (Fase 4.1): zonas protegidas y colocación de las animaciones.

Una animación informativa debe quedar fuera de todo lo que no se puede tapar o no se verá:

- rostro (ojos y boca incluidos) con un pequeño margen;
- subtítulos;
- interfaz de la red social de destino (Instagram Reels, TikTok o Universal = ambas);
- otras animaciones visibles al mismo tiempo.

Todo se trabaja en coordenadas normalizadas (0–1), independientes de la resolución. Las zonas
de la interfaz son **conservadoras** y están documentadas con sus fuentes en ``SOURCES`` (más abajo)
(«Composición y Render»): las plataformas no publican una única zona exacta y cambia según el
dispositivo y la longitud del texto de la publicación.

Solo las animaciones informativas se colocan con estas reglas. Los fondos a pantalla completa y
los elementos decorativos (retículas, partículas, corchetes) pueden llegar a los bordes.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any, Literal

import numpy as np

Platform = Literal["universal", "instagram_reels", "tiktok", "none"]
PLATFORM_NAMES: dict[str, str] = {
    "universal": "Universal (Reels + TikTok)",
    "instagram_reels": "Instagram Reels",
    "tiktok": "TikTok",
    "none": "Sin interfaz social",
}


@dataclass(frozen=True)
class Zone:
    id: str
    label: str
    x: float
    y: float
    w: float
    h: float
    kind: str = "ui"  # ui | face | subtitles | occupied | pip

    def rect(self) -> dict[str, float]:
        return {"x": self.x, "y": self.y, "w": self.w, "h": self.h}


# Perfiles para 9:16 (1080×1920 de referencia). Valores conservadores a partir de las guías
# publicadas (márgenes de anuncios y contenido de Meta y TikTok y guías de terceros de 2026).
_TIKTOK = (
    Zone("tt_top", "TikTok · barra superior (Siguiendo / Para ti, búsqueda)", 0.0, 0.0, 1.0, 0.08),
    Zone("tt_right", "TikTok · columna de interacciones (perfil, me gusta, comentarios, guardar, compartir)", 0.87, 0.33, 0.13, 0.55),
    Zone("tt_bottom", "TikTok · usuario, descripción, música y barra de progreso", 0.0, 0.75, 1.0, 0.25),
    Zone("tt_left", "TikTok · margen izquierdo", 0.0, 0.0, 0.04, 1.0),
)  # fmt: skip
_INSTAGRAM = (
    Zone("ig_top", "Instagram · cabecera de Reels, cámara y nombre", 0.0, 0.0, 1.0, 0.14),
    Zone("ig_right", "Instagram · me gusta, comentar, compartir, guardar y audio", 0.80, 0.45, 0.20, 0.55),
    Zone("ig_bottom", "Instagram · nombre, descripción, audio y acciones", 0.0, 0.65, 1.0, 0.35),
    Zone("ig_left", "Instagram · margen izquierdo", 0.0, 0.0, 0.06, 1.0),
    Zone("ig_right_margin", "Instagram · margen derecho", 0.94, 0.0, 0.06, 1.0),
)  # fmt: skip
PROFILES: dict[str, tuple[Zone, ...]] = {
    "tiktok": _TIKTOK,
    "instagram_reels": _INSTAGRAM,
    "universal": _TIKTOK + _INSTAGRAM,
    "none": (),
}
SOURCES = [
    "https://www.hopperhq.com/blog/instagram-reel-size/",
    "https://quso.ai/blog/tiktok-dimensions",
    "https://www.trymypost.com/blog/tiktok-ad-specs-2026-safe-zones",
]


def ui_zones(platform: str, width: int, height: int) -> list[Zone]:
    """Zonas de la interfaz social. Solo aplican a videos verticales (Reels y TikTok)."""
    if height <= width * 1.1:
        return []
    return list(PROFILES.get(platform, ()))


def platform_payload(platform: str) -> dict[str, Any]:
    return {
        "id": platform,
        "name": PLATFORM_NAMES.get(platform, platform),
        "zones": [asdict(z) for z in PROFILES.get(platform, ())],
        "sources": SOURCES,
    }


# ---------------------------------------------------------------------------
# Colocación
# ---------------------------------------------------------------------------

GRID = 100


def _occupancy(blockers: list[dict[str, float]]) -> np.ndarray:
    occ = np.zeros((GRID, GRID), dtype=np.int32)
    for b in blockers:
        x0 = int(np.floor(max(0.0, b["x"]) * GRID))
        y0 = int(np.floor(max(0.0, b["y"]) * GRID))
        x1 = int(np.ceil(min(1.0, b["x"] + b["w"]) * GRID))
        y1 = int(np.ceil(min(1.0, b["y"] + b["h"]) * GRID))
        if x1 > x0 and y1 > y0:
            occ[y0:y1, x0:x1] = 1
    return occ


def overlaps(region: dict[str, float], zones: list[Zone], tolerance: float = 0.002) -> list[Zone]:
    out = []
    for z in zones:
        w = max(0.0, min(region["x"] + region["w"], z.x + z.w) - max(region["x"], z.x))
        h = max(0.0, min(region["y"] + region["h"], z.y + z.h) - max(region["y"], z.y))
        if w * h > tolerance:
            out.append(z)
    return out


def legibility(region: dict[str, float], aspect: float) -> float:
    """Lado corto de la región en unidades del alto del encuadre (independiente de la
    resolución): cuanto mayor, más grande puede ser el texto."""
    return min(region["w"] * aspect, region["h"])


def min_legibility(template: str, n_items: int) -> float:
    """Lado corto mínimo para que el contenido siga siendo legible en un móvil."""
    if template.endswith((".type", ".statement")) and n_items <= 2:
        return 0.06
    if n_items >= 3 or template.endswith(
        (".nodes", ".sketch", ".icons", ".pipeline", ".list", ".steps", ".checklist")
    ):
        return 0.09
    return 0.075


def place(
    desired: dict[str, float],
    zones: list[Zone],
    *,
    aspect: float,
    min_short: float,
    keep_if_free: bool = True,
    n_items: int = 1,
) -> tuple[dict[str, float] | None, float]:
    """Mejor región libre de todas las zonas. Prueba el tamaño aprobado, reducciones moderadas
    (nunca por debajo de `min_short`), franjas a lo ancho y columnas. Devuelve (región, puntuación)
    o (None, 0) si no hay ninguna región legible libre."""
    if keep_if_free and not overlaps(desired, zones) and legibility(desired, aspect) >= min_short:
        return dict(desired), 1.0
    area_weight = 0.6 + 0.4 * min(max(n_items, 1), 5)
    occ = _occupancy([z.rect() for z in zones])
    integral = np.zeros((GRID + 1, GRID + 1), dtype=np.int64)
    integral[1:, 1:] = occ.cumsum(0).cumsum(1)
    dw, dh = desired["w"], desired["h"]
    cx, cy = desired["x"] + dw / 2, desired["y"] + dh / 2
    # Tamaños candidatos: alturas cada 0,01 entre el mínimo legible y el alto aprobado (o 0,3)
    # y anchos desde el aprobado hasta columnas estrechas. Las franjas anchas leen mejor.
    sizes: list[tuple[float, float, float]] = []  # (w, h, preferencia de forma)
    h_max = max(dh, 0.5)
    hs = [float(round(v, 2)) for v in np.arange(max(0.05, min_short), h_max + 1e-6, 0.01)]
    ws = sorted(
        {
            round(min(1.0, v), 2)
            for v in (dw, 0.88, 0.82, 0.76, 0.7, 0.62, 0.55, 0.48, 0.42, 0.36, 0.3)
        },
        reverse=True,
    )
    for w in ws:
        for h in hs:
            pref = 1.0 if (w >= dw * 0.95 and h >= dh * 0.95) else (0.95 if w >= 0.55 else 0.82)
            sizes.append((w, h, pref))
    best: tuple[float, dict[str, float]] | None = None
    for w, h, pref in sizes:
        gw, gh = int(np.ceil(w * GRID)), int(np.ceil(h * GRID))
        if gw < 2 or gh < 2 or gw > GRID or gh > GRID:
            continue
        legib = min(w * aspect, h)
        if legib < min_short:
            continue
        # Celdas ocupadas en cada ventana gh×gw (imagen integral).
        win = integral[gh:, gw:] - integral[:-gh, gw:] - integral[gh:, :-gw] + integral[:-gh, :-gw]
        ys, xs = np.nonzero(win == 0)
        if len(xs) == 0:
            continue
        px = xs / GRID
        py = ys / GRID
        dist = np.abs(px + w / 2 - cx) + np.abs(py + h / 2 - cy)
        # Lado corto (tamaño del texto) + área útil (cabida de varios elementos) − distancia.
        score = legib * pref + area_weight * (w * aspect) * h - 0.15 * dist
        k = int(np.argmax(score))
        if best is None or score[k] > best[0]:
            best = (float(score[k]), {"x": float(px[k]), "y": float(py[k]), "w": w, "h": h})
    if best is None:
        return None, 0.0
    return {k: round(v, 4) for k, v in best[1].items()}, best[0]


def face_zones(faces: list[dict[str, float]], margin: float = 0.015) -> list[Zone]:
    out = []
    for i, f in enumerate(faces):
        out.append(
            Zone(f"face{i}", "Rostro (ojos y boca)", max(0.0, f["x"] - margin), max(0.0, f["y"] - margin),
                 min(1.0, f["w"] + 2 * margin), min(1.0, f["h"] + 2 * margin), kind="face")
        )  # fmt: skip
    return out


def subtitle_zone(band: tuple[float, float] | None) -> list[Zone]:
    if not band:
        return []
    return [Zone("subs", "Subtítulos", 0.0, band[0], 1.0, band[1] - band[0], kind="subtitles")]
