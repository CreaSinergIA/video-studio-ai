"""Motor de subtítulos: maquetación (pista) y render (exportación).

Una sola fuente de verdad: ``build_track`` calcula bloques, líneas, posición en píxeles de
cada palabra (medida con FreeType sobre los mismos TTF que usa el navegador) y tiempos. La
vista previa del panel dibuja esa pista; la exportación la rasteriza con ``render_state``.
Así la vista previa y el video final coinciden en contenido, cortes de línea y posición.
"""

from __future__ import annotations

import functools
import hashlib
import math
from pathlib import Path
from typing import Any

from PIL import Image, ImageDraw, ImageFilter, ImageFont

from app.domain.edit_config import SubtitleSettings

FONTS_DIR = Path(__file__).resolve().parents[1] / "resources" / "fonts"
TRACK_VERSION = 1

# family → {peso: archivo} (las variables comparten archivo y fijan el eje «wght»).
FONT_FILES: dict[str, dict[str, Any]] = {
    "Inter": {"file": "Inter-Variable.ttf", "variable": True, "weights": (100, 900)},
    "Montserrat": {"file": "Montserrat-Variable.ttf", "variable": True, "weights": (100, 900)},
    "JetBrains Mono": {
        "file": "JetBrainsMono-Variable.ttf",
        "variable": True,
        "weights": (100, 800),
    },
    "Poppins": {
        "static": {
            400: "Poppins-Regular.ttf",
            500: "Poppins-Medium.ttf",
            600: "Poppins-SemiBold.ttf",
            700: "Poppins-Bold.ttf",
            800: "Poppins-ExtraBold.ttf",
            900: "Poppins-Black.ttf",
        }
    },
    "Bebas Neue": {"static": {400: "BebasNeue-Regular.ttf"}},
    "Anton": {"static": {400: "Anton-Regular.ttf"}},
    "DM Serif Display": {"static": {400: "DMSerifDisplay-Regular.ttf"}},
}

ANIM_SECONDS = {"pop": 0.2, "fade": 0.16, "slide_up": 0.22}
FADE_OUT = 0.12
HOLD = 0.35  # el bloque permanece tras la última palabra (si no pisa al siguiente)


def font_file(family: str, weight: int) -> tuple[str, int]:
    """Archivo y peso efectivo (las familias de un solo peso usan su peso real)."""
    spec = FONT_FILES[family]
    if spec.get("variable"):
        lo, hi = spec["weights"]
        return spec["file"], max(lo, min(hi, weight))
    weights = spec["static"]
    best = min(weights, key=lambda w: abs(w - weight))
    return weights[best], best


@functools.lru_cache(maxsize=64)
def load_font(family: str, weight: int, size: int) -> ImageFont.FreeTypeFont:
    name, eff = font_file(family, weight)
    font = ImageFont.truetype(str(FONTS_DIR / name), size)
    if FONT_FILES[family].get("variable"):
        axes = font.get_variation_axes()
        values: list[float] = []
        for axis in axes:
            raw = axis.get("name") or b""
            tag = (raw.decode() if isinstance(raw, bytes) else str(raw)).lower()
            lo, hi = float(axis.get("minimum") or 0), float(axis.get("maximum") or 0)
            if "weight" in tag:
                values.append(float(eff))
            elif "optical" in tag:
                values.append(max(lo, min(hi, float(size))))
            else:
                values.append(float(axis.get("default") or lo))
        font.set_variation_by_axes(values)
    return font


def font_faces() -> list[dict[str, Any]]:
    """Descripción de @font-face para el navegador (mismos archivos que la exportación)."""
    faces = []
    for family, spec in FONT_FILES.items():
        if spec.get("variable"):
            lo, hi = spec["weights"]
            faces.append({"family": f"VSA {family}", "file": spec["file"], "weight": f"{lo} {hi}"})
        else:
            for w, f in spec["static"].items():
                faces.append({"family": f"VSA {family}", "file": f, "weight": str(w)})
    return faces


# ---------------------------------------------------------------------------
# Maquetación
# ---------------------------------------------------------------------------


def _hex(color: str, alpha: int = 255) -> tuple[int, int, int, int]:
    c = color.lstrip("#")
    return int(c[0:2], 16), int(c[2:4], 16), int(c[4:6], 16), alpha


def _words(segments: list[dict[str, Any]]) -> list[dict[str, Any]]:
    out = []
    for si, seg in enumerate(segments):
        for w in seg.get("words", []):
            if w["text"].strip():
                out.append({**w, "segment": si})
    out.sort(key=lambda w: w["start"])
    return out


def _group_blocks(words: list[dict[str, Any]], s: SubtitleSettings) -> list[list[dict[str, Any]]]:
    max_words = s.max_words_per_line * s.max_lines
    max_dur = 3.5 if s.mode == "dynamic" else 5.0
    blocks: list[list[dict[str, Any]]] = []
    cur: list[dict[str, Any]] = []
    for w in words:
        if cur:
            prev = cur[-1]
            pause = w["start"] - prev["end"] > 0.5
            sentence = prev["text"].endswith((".", "?", "!", "…", ":"))
            soft = prev["text"].endswith((",", ";")) and len(cur) >= s.max_words_per_line
            too_long = w["end"] - cur[0]["start"] > max_dur
            if len(cur) >= max_words or pause or sentence or soft or too_long:
                blocks.append(cur)
                cur = []
        cur.append(w)
    if cur:
        blocks.append(cur)
    return blocks


def _split_lines(
    words: list[dict[str, Any]],
    widths: list[float],
    space: float,
    s: SubtitleSettings,
    max_width: float,
) -> list[list[int]] | None:
    """Reparte palabras en ≤ max_lines líneas equilibradas; None si no caben."""
    n = len(words)

    def width(a: int, b: int) -> float:
        return sum(widths[a:b]) + space * max(0, b - a - 1)

    if n <= s.max_words_per_line and width(0, n) <= max_width:
        return [list(range(n))]
    best: list[list[int]] | None = None
    best_cost = math.inf
    if s.max_lines >= 2:
        for k in range(1, n):
            if k > s.max_words_per_line or n - k > s.max_words_per_line:
                continue
            w1, w2 = width(0, k), width(k, n)
            if max(w1, w2) <= max_width and abs(w1 - w2) < best_cost:
                best, best_cost = [list(range(k)), list(range(k, n))], abs(w1 - w2)
    if best is None and s.max_lines >= 3:
        for a in range(1, n):
            for b in range(a + 1, n):
                parts = [(0, a), (a, b), (b, n)]
                if any(y - x > s.max_words_per_line for x, y in parts):
                    continue
                ws = [width(x, y) for x, y in parts]
                if max(ws) <= max_width and max(ws) - min(ws) < best_cost:
                    best = [list(range(x, y)) for x, y in parts]
                    best_cost = max(ws) - min(ws)
    return best


def _scene_at(scenes: list[dict[str, Any]], t: float) -> dict[str, Any] | None:
    for sc in scenes:
        if sc["start"] <= t < sc["end"]:
            return sc
    return scenes[-1] if scenes else None


def safe_band(platform: str | None, width: int, height: int) -> tuple[float, float, float] | None:
    """Zona libre de la interfaz de la plataforma: (arriba, abajo, ancho máximo) normalizados.
    None si no hay interfaz (horizontal o «sin interfaz»)."""
    from app.services import layout_engine

    if not platform:
        return None
    zones = layout_engine.ui_zones(platform, width, height)
    if not zones:
        return None
    top = max([z.y + z.h for z in zones if z.y <= 0.001 and z.w > 0.5] or [0.0])
    bottom = min([z.y for z in zones if z.y + z.h >= 0.999 and z.w > 0.5] or [1.0])
    # Columnas laterales (acciones a la derecha, márgenes): el texto centrado no debe llegar.
    right = min([z.x for z in zones if z.x > 0.5 and z.w <= 0.5] or [1.0])
    left = max([z.x + z.w for z in zones if z.x < 0.001 and z.w <= 0.5] or [0.0])
    half = max(0.2, min(0.5 - left, right - 0.5) - 0.01)
    return top, bottom, 2 * half


def _auto_center(
    height: int,
    width: int,
    block_h: float,
    faces: dict[str, Any] | None,
    margin: float,
    band: tuple[float, float] | None = None,
) -> tuple[float, str]:
    """Centro vertical del bloque en modo automático.

    Vertical: preferencia ~68 % de la altura (por debajo del rostro típico, por encima de la
    interfaz de redes). Horizontal: zona inferior segura. Si hay rostros medidos, se elige la
    posición candidata que no tape ojos ni boca y más cerca de la preferida."""
    vertical = height > width
    preferred = 0.68 * height if vertical else height - max(margin, 0.06 * height) - block_h / 2
    lo = max(margin, 0.05 * height) + block_h / 2
    hi = (0.86 * height if vertical else height - max(margin, 0.04 * height)) - block_h / 2
    if band is not None:
        # Zona segura de la plataforma (con un pequeño respiro respecto a la interfaz).
        lo = band[0] * height + 0.01 * height + block_h / 2
        hi = band[1] * height - 0.01 * height - block_h / 2
        if lo > hi:
            return -1.0, "safe-no-space"
        # Lo más abajo posible dentro de la zona (lejos del rostro, cerca de donde se lee).
        preferred = hi
    if not faces or faces.get("status") in (None, "unknown", "none") or not faces.get("union_box"):
        return min(max(preferred, lo), hi), ("safe-platform" if band else "auto-default")
    _x, y, _w, h = faces["union_box"]
    face_top, face_bottom = y * height, (y + h) * height
    eyes = (faces.get("highest_eye_y") or y + h * 0.35) * height
    mouth = (faces.get("lowest_mouth_y") or y + h * 0.75) * height
    best, best_cost = preferred, math.inf
    steps = 40
    for k in range(steps + 1):
        c = lo + (hi - lo) * k / steps
        top, bottom = c - block_h / 2, c + block_h / 2
        cost = abs(c - preferred) / height
        # Penalizaciones: tapar boca u ojos (graves) o el resto del rostro (leve).
        if top < mouth + 0.015 * height and bottom > mouth - 0.06 * height:
            cost += 5
        if top < eyes + 0.03 * height and bottom > eyes - 0.03 * height:
            cost += 5
        overlap = max(0.0, min(bottom, face_bottom) - max(top, face_top))
        cost += 2 * overlap / max(1.0, block_h)
        if cost < best_cost:
            best, best_cost = c, cost
    if band is not None:
        # En la zona segura no se acepta tapar ojos ni boca: si no hay sitio, se informa.
        return (best, "safe-platform") if best_cost < 5 else (-1.0, "safe-no-space")
    return best, "auto-faces"


def build_track(
    segments: list[dict[str, Any]],
    s: SubtitleSettings,
    width: int,
    height: int,
    scenes: list[dict[str, Any]] | None = None,
    platform: str | None = None,
) -> dict[str, Any]:
    """Pista de subtítulos. ``platform``: red social de destino; solo se usa si
    ``s.safe_area == "platform"`` (zona libre de la interfaz)."""
    scale = min(width, height) / 1080
    font_px = max(8, round(s.font_size * scale))
    font = load_font(s.font_family, s.font_weight, font_px)
    ascent, descent = font.getmetrics()
    line_h = round((ascent + descent) * 1.08)
    outline = round(s.outline_width * scale) if s.outline_enabled else 0
    sband = safe_band(platform, width, height) if s.safe_area == "platform" else None
    max_width = width * (min(0.88, sband[2]) if sband else 0.88) - 2 * outline
    # El contorno ensancha cada palabra hacia ambos lados: se suma al espacio entre palabras.
    space = font.getlength(" ") + 1.5 * outline
    margin = s.margin_percent / 100 * height
    words = _words(segments)
    if s.uppercase:
        for w in words:
            w["display"] = w["text"].upper()
    raw_blocks = _group_blocks(words, s) if s.enabled else []
    blocks: list[dict[str, Any]] = []
    queue = list(raw_blocks)
    while queue:
        group = queue.pop(0)
        texts = [w.get("display", w["text"]) for w in group]
        widths = [font.getlength(t) for t in texts]
        lines = _split_lines(group, widths, space, s, max_width)
        if lines is None:
            if len(group) == 1:  # palabra más ancha que el cuadro: se deja en su línea
                lines = [[0]]
            else:
                half = max(1, len(group) // 2)
                queue[0:0] = [group[:half], group[half:]]
                continue
        blocks.append({"words": group, "texts": texts, "widths": widths, "lines": lines})
    # Tiempos y posición por escena (estable dentro de cada escena).
    positions: dict[tuple[int, int], tuple[float, str]] = {}
    out_blocks = []
    last_center: float | None = None
    for bi, b in enumerate(blocks):
        group = b["words"]
        start = group[0]["start"]
        nxt = blocks[bi + 1]["words"][0]["start"] if bi + 1 < len(blocks) else math.inf
        end = min(group[-1]["end"] + HOLD, nxt - 0.02)
        end = max(end, min(start + 0.4, nxt - 0.02), min(group[-1]["end"], nxt - 0.02))
        end = max(end, start + 0.01)  # nunca vacío ni solapado con el siguiente bloque
        block_h = len(b["lines"]) * line_h
        if not s.auto_position:
            if s.position == "top":
                center, source = margin + block_h / 2, "manual"
            elif s.position == "middle":
                center, source = height / 2, "manual"
            else:
                center, source = height - margin - block_h / 2, "manual"
        else:
            sc = _scene_at(scenes or [], (start + group[-1]["end"]) / 2)
            key = sc["index"] if sc else -1
            # En la zona segura cada altura de bloque tiene su posición (que no invada la
            # interfaz); fuera de ella, una por escena como hasta ahora.
            pkey = (key, len(b["lines"]) if sband else 0)
            if pkey not in positions:
                positions[pkey] = _auto_center(
                    height,
                    width,
                    block_h,
                    (sc or {}).get("faces"),
                    margin,
                    (sband[0], sband[1]) if sband else None,
                )
                if positions[pkey][1] == "safe-no-space":
                    # Sin sitio seguro en esta escena: se conserva la posición automática
                    # habitual (no se tapa el rostro) y se informa para que el usuario elija.
                    c0, _ = _auto_center(height, width, block_h, (sc or {}).get("faces"), margin)
                    positions[pkey] = (c0, "safe-no-space")
            center, source = positions[pkey]
            # Evitar saltos pequeños entre escenas (< 4 % de la altura), salvo que el bloque
            # saliera de la zona segura de la plataforma.
            if last_center is not None and abs(center - last_center) < 0.04 * height:
                inside = sband is None or (
                    last_center - block_h / 2 >= sband[0] * height
                    and last_center + block_h / 2 <= sband[1] * height
                )
                if inside or source == "safe-no-space":
                    center = last_center
        # Nunca fuera del encuadre.
        center = min(max(center, block_h / 2 + 2), height - block_h / 2 - 2)
        last_center = center
        top = center - block_h / 2
        lines_out = []
        for li, idxs in enumerate(b["lines"]):
            lw = sum(b["widths"][i] for i in idxs) + space * (len(idxs) - 1)
            x = (width - lw) / 2
            baseline = top + li * line_h + (line_h - (ascent + descent)) / 2 + ascent
            items = []
            for i in idxs:
                w = group[i]
                items.append(
                    {
                        "id": w["id"],
                        "text": b["texts"][i],
                        "start": w["start"],
                        "end": w["end"],
                        "x": round(x, 2),
                        "w": round(b["widths"][i], 2),
                    }
                )
                x += b["widths"][i] + space
            lines_out.append(
                {"baseline": round(baseline, 2), "width": round(lw, 2), "words": items}
            )
        out_blocks.append(
            {
                "id": f"b{bi + 1:04d}",
                "start": round(start, 3),
                "end": round(end, 3),
                "top": round(top, 2),
                "height": block_h,
                "position_source": source,
                "lines": lines_out,
            }
        )
    name, eff_weight = font_file(s.font_family, s.font_weight)
    outside = sum(1 for ob in out_blocks if ob["position_source"] == "safe-no-space")
    return {
        "version": TRACK_VERSION,
        "width": width,
        "height": height,
        "safe_area": {
            "mode": s.safe_area,
            "platform": platform,
            "band": [round(sband[0], 4), round(sband[1], 4)] if sband else None,
            "status": ("off" if not sband else ("no_space" if outside else "ok")),
            "blocks_without_space": outside,
            "blocks": len(out_blocks),
            # Franja vertical que ocupan los subtítulos (para explicar el resultado).
            "range": (
                [
                    round(min(ob["top"] for ob in out_blocks) / height, 4),
                    round(max(ob["top"] + ob["height"] for ob in out_blocks) / height, 4),
                ]
                if out_blocks
                else None
            ),
        },
        "enabled": s.enabled,
        "mode": s.mode,
        "animation": s.animation,
        "font": {
            "family": s.font_family,
            "css_family": f"VSA {s.font_family}",
            "file": name,
            "weight": eff_weight,
            "size": font_px,
            "ascent": ascent,
            "descent": descent,
            "line_height": line_h,
        },
        "style": {
            "text_color": s.text_color,
            "highlight_color": s.highlight_color,
            "outline_color": s.outline_color,
            "outline": outline,
            "shadow": s.shadow_enabled,
            "shadow_color": s.shadow_color,
            "shadow_blur": round(s.shadow_blur * scale, 2) if s.shadow_enabled else 0,
            "shadow_offset": round(max(1.0, s.shadow_blur * scale * 0.25), 2)
            if s.shadow_enabled
            else 0,
        },
        "blocks": out_blocks,
    }


def scale_track(track: dict[str, Any], width: int, height: int) -> dict[str, Any]:
    """Escala geométricamente una pista a otra resolución de salida (1080p/4K) conservando
    exactamente la maquetación de la vista previa (mismos cortes de línea y posiciones)."""
    if width == track["width"] and height == track["height"]:
        return track
    f = width / track["width"]
    fy = height / track["height"]
    font = dict(track["font"])
    font["size"] = max(8, round(font["size"] * f))
    font["ascent"] = round(font["ascent"] * f)
    font["descent"] = round(font["descent"] * f)
    font["line_height"] = round(font["line_height"] * f)
    style = dict(track["style"])
    style["outline"] = round(style["outline"] * f)
    style["shadow_blur"] = round(style["shadow_blur"] * f, 2)
    style["shadow_offset"] = round(style["shadow_offset"] * f, 2)
    blocks = []
    for b in track["blocks"]:
        lines = [
            {
                "baseline": round(line["baseline"] * fy, 2),
                "width": round(line["width"] * f, 2),
                "words": [
                    {**w, "x": round(w["x"] * f, 2), "w": round(w["w"] * f, 2)}
                    for w in line["words"]
                ],
            }
            for line in b["lines"]
        ]
        blocks.append(
            {**b, "top": round(b["top"] * fy, 2), "height": round(b["height"] * fy), "lines": lines}
        )
    return {
        **track,
        "width": width,
        "height": height,
        "font": font,
        "style": style,
        "blocks": blocks,
    }


# ---------------------------------------------------------------------------
# Estado en un instante (común a vista previa y exportación)
# ---------------------------------------------------------------------------


def _ease_out_back(x: float) -> float:
    c1, c3 = 1.70158, 2.70158
    return 1 + c3 * (x - 1) ** 3 + c1 * (x - 1) ** 2


def block_at(track: dict[str, Any], t: float) -> dict[str, Any] | None:
    for b in track["blocks"]:
        if b["start"] <= t < b["end"]:
            return b
    return None


def state_at(track: dict[str, Any], block: dict[str, Any], t: float) -> dict[str, Any]:
    """Estado visual del bloque en ``t``: opacidad, desplazamiento, escala y por palabra
    (visible, resaltada, escala, caracteres visibles)."""
    mode, anim = track["mode"], track["animation"]
    since = t - block["start"]
    alpha, dy, block_scale = 1.0, 0.0, 1.0
    entrance = anim if (mode == "classic" or anim in ("fade", "slide_up")) else None
    if entrance == "fade" and since < ANIM_SECONDS["fade"]:
        alpha = since / ANIM_SECONDS["fade"]
    elif entrance == "slide_up" and since < ANIM_SECONDS["slide_up"]:
        p = since / ANIM_SECONDS["slide_up"]
        alpha, dy = p, (1 - (1 - (1 - p) ** 3)) * track["font"]["line_height"] * 0.45
    elif entrance == "pop" and mode == "classic" and since < ANIM_SECONDS["pop"]:
        block_scale = 0.85 + 0.15 * _ease_out_back(since / ANIM_SECONDS["pop"])
    if anim == "fade" and block["end"] - t < FADE_OUT:
        alpha = min(alpha, max(0.0, (block["end"] - t) / FADE_OUT))
    words = [w for line in block["lines"] for w in line["words"]]
    active = None
    if mode == "dynamic":
        for i, w in enumerate(words):
            nxt = words[i + 1]["start"] if i + 1 < len(words) else block["end"]
            if w["start"] <= t < max(nxt, w["end"]):
                active = i
        if active is None and t >= words[-1]["start"]:
            active = len(words) - 1
    states = []
    for i, w in enumerate(words):
        visible, highlight, scale, chars = True, False, 1.0, None
        if mode == "dynamic":
            if anim in ("word_by_word", "typewriter") and w["start"] > t:
                visible = False
            if anim == "karaoke":
                highlight = w["start"] <= t
            elif anim != "none" or active == i:
                highlight = active == i
            if anim == "pop" and active == i and t - w["start"] < ANIM_SECONDS["pop"]:
                p = max(0.0, (t - w["start"]) / ANIM_SECONDS["pop"])
                scale = 1 + 0.12 * math.sin(math.pi * p)
            if anim == "typewriter" and active == i:
                dur = max(0.05, w["end"] - w["start"])
                chars = max(
                    1, min(len(w["text"]), math.ceil(len(w["text"]) * (t - w["start"]) / dur))
                )
        states.append(
            {"visible": visible, "highlight": highlight, "scale": round(scale, 3), "chars": chars}
        )
    return {
        "alpha": round(alpha, 3),
        "dy": round(dy, 2),
        "scale": round(block_scale, 3),
        "words": states,
    }


def change_times(track: dict[str, Any], fps: float) -> list[float]:
    """Instantes en los que cambia la imagen de los subtítulos (para la exportación)."""
    times: set[float] = set()
    step = 1.0 / max(1.0, fps)
    for b in track["blocks"]:
        times.update((b["start"], b["end"]))
        words = [w for line in b["lines"] for w in line["words"]]
        anim, mode = track["animation"], track["mode"]
        for dur_key in ("fade", "slide_up", "pop"):
            if anim == dur_key and (mode == "classic" or dur_key != "pop"):
                d = ANIM_SECONDS[dur_key]
                times.update(b["start"] + k * step for k in range(int(d / step) + 1))
        if anim == "fade":
            times.update(b["end"] - FADE_OUT + k * step for k in range(int(FADE_OUT / step) + 1))
        if mode == "dynamic":
            for w in words:
                times.add(w["start"])
                if anim == "pop":
                    times.update(
                        w["start"] + k * step for k in range(int(ANIM_SECONDS["pop"] / step) + 1)
                    )
                if anim == "typewriter":
                    n = max(1, len(w["text"]))
                    dur = max(0.05, w["end"] - w["start"])
                    times.update(w["start"] + dur * c / n for c in range(n))
    return sorted(t for t in times if t >= 0)


def state_key(block: dict[str, Any] | None, state: dict[str, Any] | None) -> str:
    if block is None or state is None:
        return "empty"
    raw = f"{block['id']}|{state}"
    return hashlib.sha1(raw.encode()).hexdigest()


# ---------------------------------------------------------------------------
# Render (exportación)
# ---------------------------------------------------------------------------


def render_state(
    track: dict[str, Any], block: dict[str, Any], state: dict[str, Any]
) -> Image.Image:
    """Imagen RGBA a tamaño de salida con el bloque en el estado dado."""
    W, H = track["width"], track["height"]
    f = track["font"]
    st = track["style"]
    font = load_font(f["family"], f["weight"], f["size"])
    # Se trabaja solo en la franja del bloque (el desenfoque a 4K completo sería muy lento).
    margin = int(st["outline"] + st["shadow_blur"] * 2 + st["shadow_offset"] + f["size"] * 0.6)
    y0 = max(0, int(block["top"] - margin))
    y1 = min(H, math.ceil(block["top"] + block["height"] + state["dy"] + margin))
    band_h = max(1, y1 - y0)
    text_layer = Image.new("RGBA", (W, band_h), (0, 0, 0, 0))
    shadow_layer = Image.new("RGBA", (W, band_h), (0, 0, 0, 0)) if st["shadow"] else None
    words = [w for line in block["lines"] for w in line["words"]]
    baselines = [line["baseline"] for line in block["lines"] for _ in line["words"]]
    outline = st["outline"]
    text_rgba, hi_rgba = _hex(st["text_color"]), _hex(st["highlight_color"])
    outline_rgba = _hex(st["outline_color"])
    dy = state["dy"]
    for w, base, ws in zip(words, baselines, state["words"], strict=True):
        if not ws["visible"]:
            continue
        text = w["text"] if ws["chars"] is None else w["text"][: ws["chars"]]
        color = hi_rgba if ws["highlight"] else text_rgba
        pad = outline + 4 + int(f["size"] * 0.3)
        tile_w = math.ceil(w["w"]) + 2 * pad
        tile_h = f["ascent"] + f["descent"] + 2 * pad
        tile = Image.new("RGBA", (tile_w, tile_h), (0, 0, 0, 0))
        ImageDraw.Draw(tile).text(
            (pad, pad + f["ascent"]),
            text,
            font=font,
            fill=color,
            anchor="ls",
            stroke_width=outline,
            stroke_fill=outline_rgba,
        )
        scale = ws["scale"] * state["scale"]
        ox, oy = w["x"] - pad, base + dy - f["ascent"] - pad - y0
        if abs(scale - 1) > 1e-3:
            nw, nh = max(1, round(tile_w * scale)), max(1, round(tile_h * scale))
            cx, cy = ox + tile_w / 2, oy + tile_h / 2
            tile = tile.resize((nw, nh), Image.Resampling.LANCZOS)
            ox, oy = cx - nw / 2, cy - nh / 2
        text_layer.alpha_composite(tile, (round(ox), round(oy)))
        if shadow_layer is not None:
            sh = Image.new("RGBA", tile.size, _hex(st["shadow_color"], 0))
            sh.putalpha(tile.getchannel("A").point(lambda a: int(a * 0.85)))
            off = st["shadow_offset"]
            shadow_layer.alpha_composite(sh, (round(ox), round(oy + off)))
    if shadow_layer is not None and st["shadow_blur"] > 0:
        shadow_layer = shadow_layer.filter(ImageFilter.GaussianBlur(st["shadow_blur"] / 2))
    band = shadow_layer if shadow_layer is not None else Image.new("RGBA", (W, band_h))
    band.alpha_composite(text_layer)
    if state["alpha"] < 1:
        band.putalpha(band.getchannel("A").point(lambda v: int(v * state["alpha"])))
    out = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    out.paste(band, (0, y0))
    return out
