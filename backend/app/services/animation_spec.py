"""Compilador: intervención aprobada → especificación de animación (AnimationSpec v1).

La especificación es el contrato que interpreta el motor de Remotion (`renderer/src/spec.ts`).
Se construye solo a partir de:

- la intervención **aprobada** (contrato `plans/approved_vN.json`), sin inventar otras;
- la transcripción con la que se aprobó (tiempos de palabra medidos) para sincronizar cada
  elemento con el momento en que se menciona;
- las zonas protegidas medidas (rostros) y la franja real de subtítulos;
- el estilo y los parámetros del preset (paleta, easing, densidad).

Opcionalmente, Claude afina cada animación con el lenguaje declarativo de `animation_direction`
(plantilla, textos en pantalla, palabra de cada aparición, estados y primitivas); aquí se valida
y se traduce a fotogramas. Nunca se ejecuta nada de lo que diga el modelo.
"""

from __future__ import annotations

import hashlib
import re
import unicodedata
from typing import Any

from app import styles
from app.domain.edit_config import EditConfig
from app.services import layout_engine
from app.services.layout_engine import Zone

SPEC_VERSION = 1

# Plantillas por estilo y su descripción para Claude: vienen del registro de estilos.
TEMPLATES: dict[str, list[str]] = {sid: list(st.templates) for sid, st in styles.REGISTRY.items()}
TEMPLATE_DESC: dict[str, str] = {
    t: d for st in styles.REGISTRY.values() for t, d in st.templates.items()
}

# Iconos permitidos (lucide, ISC). Claude solo puede elegir de esta lista.
ICONS = sorted(
    {
        "Workflow",
        "Bot",
        "Brain",
        "Database",
        "Mail",
        "Wrench",
        "MessageCircle",
        "CircleCheck",
        "Calendar",
        "Lightbulb",
        "TriangleAlert",
        "Repeat",
        "Settings",
        "FileText",
        "Folder",
        "Code",
        "Zap",
        "User",
        "Users",
        "DollarSign",
        "ChartLine",
        "Search",
        "Clock",
        "Rocket",
        "Target",
        "Layers",
        "Cpu",
        "Cloud",
        "Link",
        "Send",
        "Smartphone",
        "Hand",
        "Heart",
        "Star",
        "Trophy",
        "Timer",
        "ListChecks",
        "Puzzle",
        "Sparkles",
        "Eye",
        "Lock",
        "Key",
        "Bell",
        "ShoppingCart",
        "Camera",
        "Video",
        "Mic",
        "Globe",
        "House",
        "Briefcase",
        "GraduationCap",
        "BookOpen",
        "PenTool",
        "Hammer",
        "Gauge",
        "Infinity",
        "RefreshCw",
        "ArrowRight",
        "Check",
        "X",
        "Plus",
        "Minus",
        "Play",
        "Download",
        "Upload",
        "Filter",
        "Shield",
        "Monitor",
        "Laptop",
        "Server",
        "Network",
        "GitBranch",
        "Calculator",
        "Box",
        "CircleHelp",
        "MousePointerClick",
        "Inbox",
        "Receipt",
        "Wallet",
        "Building2",
        "Store",
        "Truck",
        "Package",
        "Megaphone",
        "Image",
        "Palette",
        "Music",
        "Headphones",
        "Coffee",
        "Smile",
        "Frown",
        "ThumbsUp",
        "Flag",
        "Map",
        "MapPin",
        "Compass",
        "Hourglass",
        "Ban",
        "CircleX",
        "Gift",
        "Handshake",
        "Scale",
        "Sprout",
    }
)

# Palabras → icono (heurística del compilador cuando Claude no lo indica).
ICON_WORDS = {
    "automat": "Workflow",
    "agente": "Bot",
    "ia": "Brain",
    "inteligencia": "Brain",
    "dato": "Database",
    "correo": "Mail",
    "email": "Mail",
    "herramienta": "Wrench",
    "mensaje": "MessageCircle",
    "whatsapp": "MessageCircle",
    "chat": "MessageCircle",
    "calendario": "Calendar",
    "idea": "Lightbulb",
    "curios": "Lightbulb",
    "miedo": "TriangleAlert",
    "alerta": "TriangleAlert",
    "repet": "Repeat",
    "bucle": "Repeat",
    "configur": "Settings",
    "document": "FileText",
    "carpeta": "Folder",
    "codigo": "Code",
    "programa": "Code",
    "rapid": "Zap",
    "accion": "Zap",
    "persona": "User",
    "cliente": "Users",
    "equipo": "Users",
    "dinero": "DollarSign",
    "venta": "ShoppingCart",
    "vendedor": "Store",
    "contador": "Calculator",
    "freelancer": "Laptop",
    "diseñ": "PenTool",
    "dueño": "Briefcase",
    "negocio": "Briefcase",
    "buscar": "Search",
    "busca": "Search",
    "tiempo": "Clock",
    "hora": "Timer",
    "objetivo": "Target",
    "meta": "Target",
    "proceso": "Workflow",
    "flujo": "Workflow",
    "conect": "Link",
    "enviar": "Send",
    "telefono": "Smartphone",
    "movil": "Smartphone",
    "app": "Smartphone",
    "problema": "CircleHelp",
    "pregunta": "CircleHelp",
    "resultado": "CircleCheck",
    "listo": "CircleCheck",
    "tarea": "ListChecks",
    "lista": "ListChecks",
    "regla": "Filter",
    "seguridad": "Shield",
    "computadora": "Monitor",
    "servidor": "Server",
    "nube": "Cloud",
    "factura": "Receipt",
    "comentario": "MessageCircle",
    "comparte": "Send",
    "sigue": "Bell",
}

DECORATION = {"background", "grid", "particles", "spotlight"}
LINKISH = {"connector", "arrow"}


def _norm(s: str) -> str:
    s = unicodedata.normalize("NFKD", s.lower())
    return re.sub(r"[^a-z0-9ñ ]", "", "".join(c for c in s if not unicodedata.combining(c)))


def seed_of(text: str) -> int:
    return int(hashlib.sha256(text.encode()).hexdigest()[:8], 16) % 2_000_000 + 1


# ---------------------------------------------------------------------------
# Paletas y tipografía por estilo (desde los parámetros del preset)
# ---------------------------------------------------------------------------


def palette(config: EditConfig, style: str) -> dict[str, str]:
    return styles.get(style).palette(config)


def style_params(config: EditConfig, style: str) -> dict[str, Any]:
    return dict(getattr(config.style, style).model_dump(mode="json"))


# ---------------------------------------------------------------------------
# Geometría segura
# ---------------------------------------------------------------------------


def _intersects(a: dict[str, float], b: dict[str, float]) -> float:
    w = max(0.0, min(a["x"] + a["w"], b["x"] + b["w"]) - max(a["x"], b["x"]))
    h = max(0.0, min(a["y"] + a["h"], b["y"] + b["h"]) - max(a["y"], b["y"]))
    return w * h


DEFAULT_REGIONS = {
    "overlay_top": {"x": 0.05, "y": 0.04, "w": 0.9, "h": 0.24},
    "overlay_bottom": {"x": 0.05, "y": 0.74, "w": 0.9, "h": 0.2},
    "overlay_left": {"x": 0.03, "y": 0.25, "w": 0.38, "h": 0.5},
    "overlay_right": {"x": 0.59, "y": 0.25, "w": 0.38, "h": 0.5},
    "overlay_corner": {"x": 0.62, "y": 0.04, "w": 0.34, "h": 0.2},
    "center": {"x": 0.12, "y": 0.3, "w": 0.76, "h": 0.4},
}

_ZONE_KIND = {
    "face": "el rostro",
    "subtitles": "los subtítulos",
    "ui": "la interfaz de la red social",
    "occupied": "otra animación",
    "pip": "el recuadro de la persona",
}


def place_region(
    region: dict[str, float] | None,
    layout: str,
    zones: list[Zone],
    *,
    allow_cover: bool,
    aspect: float,
    min_short: float,
    n_items: int = 1,
) -> tuple[dict[str, float], list[str], list[dict[str, str]]]:
    """Región de contenido informativo fuera de todas las zonas protegidas (rostro, subtítulos,
    interfaz social, otras animaciones). Devuelve (región, notas, avisos). Un aviso significa
    que no hay una solución legible y la intervención necesita revisión."""
    notes: list[str] = []
    warnings: list[dict[str, str]] = []
    r = (
        dict(region)
        if region
        else dict(DEFAULT_REGIONS.get(layout, DEFAULT_REGIONS["overlay_top"]))
    )
    r["x"] = min(max(r["x"], 0.0), 0.95)
    r["y"] = min(max(r["y"], 0.0), 0.95)
    r["w"] = min(max(r["w"], 0.05), 1.0 - r["x"])
    r["h"] = min(max(r["h"], 0.05), 1.0 - r["y"])
    if allow_cover:
        return r, notes, warnings
    conflicts = layout_engine.overlaps(r, zones)
    legib = layout_engine.legibility(r, aspect)
    if not conflicts and legib >= min_short * 1.4:
        return r, notes, warnings
    best, _ = layout_engine.place(
        r, zones, aspect=aspect, min_short=min_short, keep_if_free=False, n_items=n_items
    )
    if not conflicts:
        # Libre pero estrecha o baja: solo se cambia si la alternativa es claramente más legible.
        if best is not None and layout_engine.legibility(best, aspect) > legib * 1.15:
            notes.append(
                "Región ampliada o recolocada para que el texto sea legible "
                f"({r['w']:.2f}×{r['h']:.2f} → {best['w']:.2f}×{best['h']:.2f})."
            )
            return best, notes, warnings
        return r, notes, warnings
    what = sorted({_ZONE_KIND.get(z.kind, z.kind) for z in conflicts})
    if best is None:
        names = "; ".join(z.label for z in conflicts)
        warnings.append({
            "code": "no_safe_space",
            "message": (
                "No hay espacio legible fuera de las zonas protegidas: la animación invade "
                f"{', '.join(what)} ({names}). Revisa la intervención o cámbiala a pantalla "
                "completa en el plan."
            ),
        })  # fmt: skip
        return r, notes, warnings
    notes.append(
        f"Región desplazada para no tapar {', '.join(what)} "
        f"(x={best['x']:.2f}, y={best['y']:.2f}, {best['w']:.2f}×{best['h']:.2f})."
    )
    return best, notes, warnings


def safe_region(
    region: dict[str, float] | None,
    layout: str,
    faces: list[dict[str, float]],
    subtitle_band: tuple[float, float] | None,
    allow_cover: bool,
    aspect: float = 9 / 16,
    ui: list[Zone] | None = None,
    min_short: float = 0.075,
) -> tuple[dict[str, float], list[str]]:
    """Compatibilidad: región segura respecto a rostros, subtítulos y (opcional) interfaz."""
    zones = (
        layout_engine.face_zones(faces)
        + layout_engine.subtitle_zone(subtitle_band)
        + list(ui or [])
    )
    r, notes, warnings = place_region(
        region, layout, zones, allow_cover=allow_cover, aspect=aspect, min_short=min_short
    )
    return r, notes + [w["message"] for w in warnings]


# ---------------------------------------------------------------------------
# Sincronía con la voz
# ---------------------------------------------------------------------------


class WordClock:
    """Palabras medidas de la transcripción aprobada (para anclar apariciones)."""

    def __init__(self, segments: list[dict[str, Any]]) -> None:
        self.words = sorted(
            (
                {
                    "id": w["id"],
                    "text": w["text"],
                    "norm": _norm(w["text"]),
                    "start": float(w["start"]),
                    "end": float(w["end"]),
                }
                for s in segments
                for w in s["words"]
            ),
            key=lambda w: w["start"],
        )
        self.by_id = {w["id"]: w for w in self.words}

    def window(self, a: float, b: float) -> list[dict[str, Any]]:
        return [w for w in self.words if a - 0.05 <= w["start"] <= b]

    def match(self, text: str, a: float, b: float, after: float) -> dict[str, Any] | None:
        """Primera palabra del tramo (desde `after`) que coincide con un término del texto."""
        terms = [t for t in _norm(text).split() if len(t) >= 4 or t.isdigit()]
        if not terms:
            terms = [t for t in _norm(text).split() if t]
        for w in self.window(a, b):
            if w["start"] < after - 0.01 or not w["norm"]:
                continue
            for t in terms:
                stem = t[: max(4, len(t) - 2)]
                if w["norm"].startswith(stem) or (
                    len(w["norm"]) >= 4 and t.startswith(w["norm"][: max(4, len(w["norm"]) - 2)])
                ):
                    return w
        return None


def _desc_time(description: str, text: str, a: float, b: float) -> float | None:
    """Segundo citado por Claude junto al elemento en la descripción aprobada, p. ej. «(8.33)»."""
    if not text:
        return None
    pos = _norm(description).find(_norm(text)[:12]) if _norm(text) else -1
    if pos < 0:
        return None
    for m in re.finditer(r"\((\d{1,4}[.,]\d{1,2})\)", description):
        if m.start() >= pos - 5:
            t = float(m.group(1).replace(",", "."))
            if a - 0.2 <= t <= b + 0.2:
                return t
            break
    return None


def pick_icon(text: str, desc: str = "") -> str | None:
    n = _norm(f"{text} {desc}")
    for key, icon in ICON_WORDS.items():
        if key in n:
            return icon
    return None


# ---------------------------------------------------------------------------
# Plantilla por defecto (sin Claude)
# ---------------------------------------------------------------------------


def default_template(style: str, itype: str, kinds: list[str], n_items: int) -> str:
    return styles.get(style).default_template(itype, set(kinds), n_items)


# ---------------------------------------------------------------------------
# Compilación
# ---------------------------------------------------------------------------


def _free_span(lo: float, hi: float, band: tuple[float, float] | None) -> tuple[float, float]:
    """Mayor franja vertical libre entre `lo` y `hi` que no pisa la franja de subtítulos."""
    spans = [(lo, hi)]
    if band and band[0] < hi and band[1] > lo:
        spans = [(lo, band[0] - 0.02), (band[1] + 0.02, hi)]
    y0, y1 = max(spans, key=lambda sp: sp[1] - sp[0])
    return round(y0, 4), round(max(0.08, y1 - y0), 4)


def _fullscreen_content(
    lo: float,
    hi: float,
    band: tuple[float, float] | None,
    ui: list[Zone],
    pip: dict[str, Any] | None,
    aspect: float,
) -> dict[str, float]:
    """Región del contenido informativo a pantalla completa: la mayor zona libre entre `lo` y
    `hi` sin subtítulos, interfaz social ni el recuadro de la persona (el fondo sí ocupa todo)."""
    y0, h0 = _free_span(lo, hi, band)
    desired = {"x": 0.06, "y": y0, "w": 0.88, "h": h0}
    zones = list(ui) + layout_engine.subtitle_zone(band)
    if pip:
        zones.append(
            Zone(
                "pip", "Recuadro de la persona", pip["x"], pip["y"], pip["w"], pip["h"], kind="pip"
            )
        )
    if not layout_engine.overlaps(desired, zones):
        return desired
    best, _ = layout_engine.place(desired, zones, aspect=aspect, min_short=0.1, keep_if_free=False)
    return best or desired


def compile_intervention(
    iv: dict[str, Any],
    *,
    plan_version: int,
    style: str,
    config: EditConfig,
    clock: WordClock,
    width: int,
    height: int,
    fps: float,
    subtitle_band: tuple[float, float] | None,
    direction: dict[str, Any] | None = None,
    ui_zones: list[Zone] | None = None,
    occupied: list[Zone] | None = None,
) -> tuple[dict[str, Any], list[str]]:
    """Devuelve ({spec, pip_src, warnings}, notas). `direction` es la dirección validada de
    Claude (opcional); `ui_zones`, la interfaz de la red social de destino; `occupied`, las
    regiones de otras animaciones visibles a la vez."""
    notes: list[str] = []
    warnings: list[dict[str, str]] = []
    ui = list(ui_zones or [])
    start, end = float(iv["start"]), float(iv["end"])
    dur = max(0.2, end - start)
    frames = max(4, round(dur * fps))
    itype = iv["type"]
    comp = iv.get("composition") or {}
    layout = comp.get("layout", "overlay_top")
    mode = (
        "transition"
        if itype == "transition"
        else "fullscreen"
        if (itype == "fullscreen_animation" or layout == "fullscreen")
        else "overlay"
    )
    bg_map = {
        "original_video": "none",
        "dimmed_video": "dim",
        "blurred_video": "dim",
        "style_background": "style",
    }
    background = (
        "style"
        if mode == "fullscreen"
        else bg_map.get(comp.get("background", "original_video"), "none")
    )
    motion = iv.get("motion") or {}

    def f(t: float) -> int:
        return max(0, min(frames - 1, round((t - start) * fps)))

    # Elementos aprobados → elementos animables, sincronizados con sus palabras.
    raw = [e for e in iv.get("elements", []) if e.get("kind") not in DECORATION]
    nodes = [e for e in raw if e.get("kind") not in LINKISH]
    items: list[dict[str, Any]] = []
    after = start - 0.2
    entry_end = max(1, round(float(motion.get("entry_seconds", 0.4)) * fps))
    desc = iv.get("visual_description", "")
    for k, e in enumerate(nodes):
        text = (e.get("text") or "").strip() or None
        w = clock.match(text, start - 0.3, end, after) if text else None
        if w is not None:
            t = w["start"]
            after = t
        else:
            t2 = _desc_time(desc, text or "", start, end)
            t = t2 if t2 is not None else None
        items.append(
            {
                "id": f"e{k}",
                "kind": e.get("kind", "label"),
                "text": text,
                "sub": None,
                "icon": pick_icon(text or "", e.get("description", "")),
                "role": e.get("role", "primary")
                if e.get("role") in ("primary", "secondary", "decoration")
                else "secondary",
                "_t": t,
            }
        )
    # Sin palabra medida: se sitúa entre los vecinos sincronizados (orden aprobado).
    known = [i for i, it in enumerate(items) if it["_t"] is not None]
    for i, it in enumerate(items):
        if it["_t"] is not None:
            continue
        prev = max((j for j in known if j < i), default=None)
        nxt = min((j for j in known if j > i), default=None)
        lo = items[prev]["_t"] if prev is not None else start + entry_end / fps
        hi = items[nxt]["_t"] if nxt is not None else min(end - 0.4, lo + 0.6 * (len(items) - i))
        gap_n = (
            (nxt - prev)
            if (prev is not None and nxt is not None)
            else (len(items) - (prev if prev is not None else -1))
        )
        idx = i - (prev if prev is not None else -1)
        it["_t"] = lo + (hi - lo) * idx / max(1, gap_n)
        notes.append(
            f"«{it['text'] or it['kind']}» sin palabra medida: se sitúa entre los elementos "
            "sincronizados."
        )
    for it in items:
        it["cue"] = f(max(start, it.pop("_t")))
    template = default_template(style, itype, [e.get("kind", "") for e in raw], len(items))

    faces = [dict(r) for r in iv.get("protected_regions", [])] if iv.get("avoid_face", True) else []
    band = (
        None
        if iv.get("subtitles") in ("hide", "integrate", "move_top", "move_bottom")
        else subtitle_band
    )
    zones = (
        layout_engine.face_zones(faces)
        + layout_engine.subtitle_zone(band)
        + ui
        + list(occupied or [])
    )
    region, rnotes, rwarn = place_region(
        comp.get("region"),
        layout,
        zones,
        allow_cover=mode != "overlay" or itype in ("screen_highlight",),
        aspect=width / height,
        min_short=layout_engine.min_legibility(template, len(items)),
        n_items=len(items),
    )
    notes += rnotes
    warnings += rwarn
    ui_top = max((z.y + z.h for z in ui if z.y <= 0.001 and z.w >= 0.9), default=0.0)
    ui_bottom = min((z.y for z in ui if z.y + z.h >= 0.999 and z.w >= 0.9), default=1.0)
    pip = None
    if mode == "fullscreen" and layout in ("picture_in_picture", "split_screen") and faces:
        fx = min(f_["x"] for f_ in faces)
        fy = min(f_["y"] for f_ in faces)
        fx2 = max(f_["x"] + f_["w"] for f_ in faces)
        fy2 = max(f_["y"] + f_["h"] for f_ in faces)
        cx, cy = (fx + fx2) / 2, (fy + fy2) / 2
        s = max(fx2 - fx, fy2 - fy) * 1.5
        if height > width:
            # En vertical, el PiP deja sitio al contenido sobre los subtítulos (más aún si la
            # interfaz de la red social ocupa arriba y abajo).
            s = min(s, styles.get(style).fullscreen_pip_max_with_ui if ui else 0.3)
        pw, ph = (s * height / width, s) if height > width else (s, s * width / height)
        pip = {
            "x": round(max(0.03, 0.5 - pw / 2), 4),
            "y": round(max(0.06, ui_top + 0.01), 4),
            "w": round(min(0.94, pw), 4),
            "h": round(min(0.4, ph), 4),
            "shape": styles.get(style).pip_shape,
            "src": {
                "x": round(cx - pw / 2, 4),
                "y": round(cy - ph / 2, 4),
                "w": round(pw, 4),
                "h": round(ph, 4),
            },
        }
        gap = styles.get(style).fullscreen_gap_with_ui if ui else 0.04
        region = _fullscreen_content(
            pip["y"] + pip["h"] + gap, min(0.93, ui_bottom - 0.01), band, ui, pip, width / height
        )
    elif mode == "fullscreen":
        region = _fullscreen_content(
            max(0.12, ui_top + 0.01), min(0.9, ui_bottom - 0.01), band, ui, None, width / height
        )
    if mode == "fullscreen" and band:
        notes.append("Contenido a pantalla completa fuera de la franja de subtítulos.")

    easing = motion.get("easing", "smooth")
    entry, exit_ = motion.get("entry", "fade"), motion.get("exit", "fade")
    spec: dict[str, Any] = {
        "version": SPEC_VERSION,
        "id": iv["id"],
        "planVersion": plan_version,
        "style": style,
        "template": template,
        "mode": mode,
        "width": width,
        "height": height,
        "fps": fps,
        "durationInFrames": frames,
        "region": region,
        "pip": {k: v for k, v in pip.items() if k != "src"} if pip else None,
        "background": background,
        "palette": palette(config, style),
        "fonts": dict(styles.get(style).fonts),
        "params": style_params(config, style),
        "intensity": iv.get("intensity", "medium"),
        "easing": easing,
        "entry": entry,
        "exit": exit_,
        "entryFrames": max(
            1, min(frames // 3, round(float(motion.get("entry_seconds", 0.4)) * fps))
        ),
        "exitFrames": max(1, min(frames // 3, round(float(motion.get("exit_seconds", 0.3)) * fps))),
        "title": None,
        "label": None,
        "items": items,
        "links": [],
        "beats": [],
        "number": None,
        "target": None,
        "arrangement": "auto",
        "custom": [],
        "seed": seed_of(iv["id"]),
    }
    if template.endswith(".highlight"):
        tgt = comp.get("region") or {"x": 0.3, "y": 0.3, "w": 0.4, "h": 0.2}
        spec["target"] = {**tgt, "cue": items[0]["cue"] if items else spec["entryFrames"]}
        spec["title"] = next((it["text"] for it in items if it["text"]), None)
    if template.endswith(".readout") or template.endswith(".number"):
        num = next(
            (it for it in items if it["kind"] == "number_counter"), items[0] if items else None
        )
        digits = re.findall(r"\d+(?:[.,]\d+)?", num["text"] or "") if num else []
        if num and digits:
            to = float(digits[0].replace(",", "."))
            txt = num["text"] or ""
            pre, _, suf = txt.partition(digits[0])
            spec["number"] = {
                "from": 0,
                "to": int(to) if to.is_integer() else to,
                "cue": num["cue"],
                "duration": max(6, round(fps * 0.9)),
                "prefix": pre.strip()[:6],
                "suffix": suf.strip()[:10],
                "label": next((it["text"] for it in items if it is not num and it["text"]), None),
            }
        else:
            spec["template"] = template.replace(".readout", ".panel").replace(
                ".number", ".statement"
            )
    pip_src = pip["src"] if pip else None
    if direction:
        # La dirección sustituye los elementos compilados: sus avisos de sincronía ya no aplican.
        notes = [n for n in notes if "sin palabra medida" not in n]
        dnotes = apply_direction(
            spec,
            direction,
            clock,
            start,
            end,
            fps,
            None if spec["mode"] == "fullscreen" else subtitle_band,
        )
        notes += dnotes
    tgt = spec.get("target")
    if tgt and ui:
        hidden = layout_engine.overlaps(tgt, ui)
        if hidden:
            warnings.append({
                "code": "target_under_ui",
                "message": (
                    "La zona resaltada del video queda bajo la interfaz de la red social ("
                    + "; ".join(z.label for z in hidden)
                    + "): puede no verse al publicar."
                ),
            })  # fmt: skip
    if mode == "overlay" and ui and not warnings:
        hidden = layout_engine.overlaps(spec["region"], ui)
        if hidden:
            warnings.append({
                "code": "content_under_ui",
                "message": "El contenido invade la interfaz: " + "; ".join(z.label for z in hidden),
            })  # fmt: skip
    return {"spec": spec, "pip_src": pip_src, "warnings": warnings}, notes


# ---------------------------------------------------------------------------
# Dirección de Claude (lenguaje declarativo validado)
# ---------------------------------------------------------------------------

_PATH_CHARS = re.compile(r"[MLCQZ0-9.,\s-]*")
_PATH_TOKEN = re.compile(r"[MLCQZ]|-?(?:\d+(?:\.\d*)?|\.\d+)")
_PATH_ARGS = {"M": 2, "L": 2, "C": 6, "Q": 4, "Z": 0}


def valid_path(d: str) -> bool:
    """Trazo normalizado (0–1) con órdenes M L C Q Z y números. Validación en tiempo lineal
    (sin expresiones regulares con retroceso): caracteres permitidos, tokens y aridad."""
    if len(d) > 600 or not _PATH_CHARS.fullmatch(d):
        return False
    tokens = _PATH_TOKEN.findall(d)
    if "".join(tokens) != re.sub(r"[\s,]", "", d) or not tokens or tokens[0] != "M":
        return False
    i = 0
    while i < len(tokens):
        cmd = tokens[i]
        if cmd not in _PATH_ARGS:
            return False
        i += 1
        nums: list[float] = []
        while i < len(tokens) and tokens[i] not in _PATH_ARGS:
            nums.append(float(tokens[i]))
            i += 1
        n = _PATH_ARGS[cmd]
        if (n == 0 and nums) or (n and (not nums or len(nums) % n)):
            return False
        if any(not 0.0 <= v <= 1.0 for v in nums):
            return False
    return True


def _plain(text: str | None) -> str:
    return " ".join(re.sub(r"[^\w\s]", " ", (text or "").lower()).split())


def _tidy_items(items: list[dict[str, Any]], notes: list[str]) -> list[dict[str, Any]]:
    """Quita elementos vacíos de contenido y fusiona textos repetidos dentro de otro."""
    out = []
    for it in items:
        if not it["icon"] and not re.search(r"\w", it["text"] or ""):
            notes.append(f"Elemento «{it['text']}» sin contenido legible: descartado.")
            continue
        out.append(it)
    keep = []
    for it in out:
        mine = _plain(it["text"])
        host = next(
            (
                o
                for o in out
                if o is not it
                and mine
                and len(_plain(o["text"])) > len(mine)
                and f" {mine} " in f" {_plain(o['text'])} "
            ),
            None,
        )
        if host is None:
            keep.append(it)
            continue
        if host["state"] == "normal":
            host["state"] = "highlight"
            host["stateCue"] = it.get("stateCue", it["cue"])
        notes.append(
            f"«{it['text']}» repetía parte de «{host['text']}»: se resalta ese elemento "
            "en vez de duplicarlo."
        )
    return keep


def apply_direction(
    spec: dict[str, Any],
    d: dict[str, Any],
    clock: WordClock,
    start: float,
    end: float,
    fps: float,
    subtitle_band: tuple[float, float] | None = None,
) -> list[str]:
    """Aplica la dirección validada de Claude a la especificación (sin ejecutar nada)."""
    notes: list[str] = []
    frames = spec["durationInFrames"]

    def cue(word_id: str | None, fallback: int, after: float | None = None) -> int:
        w = clock.by_id.get(word_id or "")
        if w is None and word_id and not re.fullmatch(r"w\d+", word_id):
            # Claude a veces devuelve la palabra en vez de su id: se busca dentro del tramo.
            w = clock.match(
                word_id, start - 0.3, end + 0.05, start - 0.3 if after is None else after
            )
        if w is None:
            if word_id:
                notes.append(f"Palabra {word_id} no está en el tramo: se usa el orden aprobado.")
            return fallback
        if not (start - 0.5 <= w["start"] <= end + 0.05):
            notes.append(f"Palabra {word_id} fuera del tramo aprobado: se ignora.")
            return fallback
        return max(0, min(frames - 1, round((w["start"] - start) * fps)))

    allowed = TEMPLATES[spec["style"]]
    tpl = d.get("template")
    if tpl in allowed and not (spec["mode"] == "transition") ^ tpl.endswith(".transition"):
        spec["template"] = tpl
    elif tpl:
        notes.append(
            f"Plantilla «{tpl}» no válida para {spec['style']}/{spec['mode']}: "
            f"se mantiene {spec['template']}."
        )
    for key in ("title", "label"):
        if isinstance(d.get(key), str):
            spec[key] = d[key][:60]
    if d.get("arrangement") in ("row", "column", "grid", "radial", "auto"):
        spec["arrangement"] = d["arrangement"]
    scale = d.get("text_scale")
    if isinstance(scale, int | float) and abs(float(scale) - 1.0) > 1e-3:
        # Solo si difiere de 1: las direcciones anteriores conservan exactamente su especificación.
        spec["params"]["textScale"] = round(min(1.4, max(0.8, float(scale))), 2)
    items: list[dict[str, Any]] = []
    old = spec["items"]
    for k, it in enumerate(d.get("items") or []):
        if not isinstance(it, dict) or (not it.get("text") and not it.get("icon")):
            continue
        fb = (
            old[k]["cue"]
            if k < len(old)
            else (int(items[-1]["cue"]) + round(fps * 0.4) if items else spec["entryFrames"])
        )
        icon = it.get("icon") if it.get("icon") in ICONS else None
        state = (
            it.get("state")
            if it.get("state") in ("normal", "negated", "done", "highlight")
            else "normal"
        )
        prev = start + items[-1]["cue"] / fps - 0.05 if items else None
        item_cue = cue(it.get("cue_word"), fb, prev)
        entry: dict[str, Any] = {
            "id": f"d{k}",
            "kind": str(it.get("kind") or "label")[:20],
            "text": (it.get("text") or None) and str(it["text"])[:48],
            "sub": (it.get("sub") or None) and str(it["sub"])[:24],
            "icon": icon,
            "role": it.get("role")
            if it.get("role") in ("primary", "secondary", "decoration")
            else "secondary",
            "cue": item_cue,
            "state": state,
        }
        if state != "normal":
            entry["stateCue"] = cue(
                it.get("state_word"), min(frames - 1, item_cue + round(fps * 0.6))
            )
        items.append(entry)
    items = _tidy_items(items, notes)
    if items:
        spec["items"] = items[:8]
    ids = {i["id"] for i in spec["items"]}
    links = []
    for ln in d.get("links") or []:
        a, b = f"d{ln.get('from')}", f"d{ln.get('to')}"
        if a in ids and b in ids:
            links.append(
                {
                    "from": a,
                    "to": b,
                    "cue": cue(
                        ln.get("cue_word"), next(i["cue"] for i in spec["items"] if i["id"] == b)
                    ),
                }
            )
    spec["links"] = links
    num = d.get("number")
    if isinstance(num, dict) and isinstance(num.get("to"), (int, float)):
        spec["number"] = {
            "from": float(num.get("from") or 0),
            "to": float(num["to"]),
            "cue": cue(num.get("cue_word"), spec["entryFrames"]),
            "duration": max(6, round(fps * 0.9)),
            "prefix": str(num.get("prefix") or "")[:6],
            "suffix": str(num.get("suffix") or "")[:10],
            "label": (num.get("label") or None) and str(num["label"])[:40],
        }
    custom = []
    for pr in (d.get("custom") or [])[:12]:
        if not isinstance(pr, dict) or pr.get("type") not in (
            "rect",
            "ellipse",
            "line",
            "arrow",
            "text",
            "path",
        ):
            continue
        vals = {k: pr.get(k) for k in ("x", "y", "w", "h", "x2", "y2")}
        if any(
            v is not None and not (isinstance(v, (int, float)) and 0 <= v <= 1)
            for v in vals.values()
        ):
            notes.append("Primitiva con coordenadas fuera del encuadre: descartada.")
            continue
        if pr["type"] == "path" and not (isinstance(pr.get("d"), str) and valid_path(pr["d"])):
            notes.append("Trazo personalizado con órdenes no permitidas: descartado.")
            continue
        ys = [v for v in (pr.get("y"), pr.get("y2")) if isinstance(v, (int, float))]
        if pr.get("h") is not None and pr.get("y") is not None:
            ys.append(float(pr["y"]) + float(pr["h"]))
        if subtitle_band and ys and min(ys) < subtitle_band[1] and max(ys) > subtitle_band[0]:
            notes.append(f"Primitiva «{pr['type']}» invadía la zona de subtítulos: descartada.")
            continue
        fill = bool(pr.get("fill"))
        custom.append(
            {
                "type": pr["type"],
                "x": float(pr.get("x") or 0),
                "y": float(pr.get("y") or 0),
                "w": pr.get("w"),
                "h": pr.get("h"),
                "x2": pr.get("x2"),
                "y2": pr.get("y2"),
                "d": pr.get("d"),
                "text": (pr.get("text") or None) and str(pr["text"])[:48],
                "color": pr.get("color")
                if pr.get("color") in ("text", "accent", "secondary", "highlight", "muted")
                else "accent",
                "stroke": min(12.0, max(1.0, float(pr.get("stroke") or 3))),
                "fill": fill,
                "cue": cue(pr.get("cue_word"), spec["entryFrames"]),
                "enter": pr.get("enter")
                if pr.get("enter") in ("draw", "fade", "pop", "slide")
                else "draw",
                "exitCue": None,
            }
        )
    if custom and not items and spec["mode"] != "transition":
        # Composición propia: solo primitivas validadas (sin plantilla debajo).
        spec["template"], spec["items"], spec["links"], spec["number"] = "custom", [], [], None
        notes.append("Composición propia de Claude con primitivas validadas.")
    elif custom and spec["items"]:
        # Las primitivas libres no conocen la maqueta de la plantilla y pueden tapar sus textos:
        # solo se admiten como composición propia (sin elementos de plantilla).
        notes.append(
            f"{len(custom)} primitiva(s) propias descartadas: la plantilla ya tiene contenido "
            "y podrían taparlo."
        )
        custom = []
    spec["custom"] = custom
    return notes


def entry_start(spec: dict[str, Any]) -> int:
    """Fotograma de entrada del contenedor (espejo de `entryStart` del renderizador).

    Las tarjetas (Explainer) y placas (Minimal) superpuestas entran justo antes del primer
    concepto dicho si este llega bastante después del inicio aprobado; Tech muestra su título
    desde el principio. Se usa para que el efecto de entrada suene cuando entra el contenedor."""
    lead = styles.get(spec["style"]).container_leads and not spec["template"].endswith(
        (".highlight", ".transition")
    )
    if not lead or spec["mode"] != "overlay" or spec["template"] == "custom" or spec.get("chainIn"):
        return 0
    cues = [int(i["cue"]) for i in spec["items"]]
    if spec.get("number"):
        cues.append(int(spec["number"]["cue"]))
    if not cues:
        return 0
    start = min(cues) - int(spec["entryFrames"]) - round(float(spec["fps"]) * 0.25)
    return start if start > float(spec["fps"]) * 0.6 else 0
