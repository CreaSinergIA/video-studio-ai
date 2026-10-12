"""Validación y corrección controlada de las propuestas de Claude (Fase 3).

Nada de lo que devuelve el modelo se usa sin pasar por aquí:

- **Tiempos**: si la intervención está anclada a palabras medidas, el tiempo sale de esas
  palabras (no de los segundos que escribió el modelo); si no, se acotan a la duración.
- **Referencias**: segmentos, escenas y fragmento de transcripción se recalculan a partir de
  los tiempos; los fotogramas citados deben existir.
- **Estilo**: elementos, entradas, salidas, easing y transiciones ajenos al estilo se sustituyen
  por equivalentes del estilo (y se informa).
- **Zonas protegidas**: rostros medidos en los fotogramas del tramo y franjas de subtítulos.
- **Conflictos**: animaciones a pantalla completa solapadas, superposiciones que compiten por
  la misma zona y densidad excesiva.

Cada corrección queda registrada en ``warnings`` de la intervención y en ``validation`` del
documento. Nunca se ejecuta nada de lo que diga el modelo: solo se interpretan datos.
"""

from __future__ import annotations

from bisect import bisect_left
from typing import Any

from app.domain.edit_plan import (
    FULLSCREEN_TYPES,
    PASSIVE_TYPES,
    Element,
    PlanDocument,
    PlanIntervention,
    ProposalIntervention,
    Region,
    StatusEvent,
)
from app.models import new_id, utcnow
from app.services import plan_styles
from app.services.plan_context import PlanInputs, transcript_fingerprint

LEAD = 0.12  # la intervención entra un poco antes de la primera palabra
HOLD = 0.25  # y se mantiene un poco después de la última
MIN_DURATION = 0.4
MIN_TRANSITION = 0.15
MODEL_DRIFT = 1.0  # diferencia tolerada entre los segundos del modelo y las palabras ancladas
SNAP_TO_CUT = 0.2
# Solape tolerado entre intervenciones consecutivas: es el relevo que generan los márgenes
# LEAD/HOLD alrededor de las palabras (≈ 0,37 s), no un conflicto real.
HANDOFF = 0.45


def _overlap(a0: float, a1: float, b0: float, b1: float) -> float:
    return max(0.0, min(a1, b1) - max(a0, b0))


def _intersect(a: Region, b: Region) -> float:
    w = max(0.0, min(a.x + a.w, b.x + b.w) - max(a.x, b.x))
    h = max(0.0, min(a.y + a.h, b.y + b.h) - max(a.y, b.y))
    return w * h


class Validator:
    def __init__(self, inputs: PlanInputs) -> None:
        self.inputs = inputs
        self.duration = inputs.duration
        self.words = {w["id"]: w for w in inputs.words}
        self.word_starts = [w["start"] for w in inputs.words]
        self.frames = {f.id: f for f in inputs.frames}
        self.scene_starts = [sc["start"] for sc in inputs.scenes if sc["start"] > 0]
        self.eff = plan_styles.adjusted(plan_styles.RULES[inputs.style], inputs.config)
        self.segment_fp: dict[str, str] = transcript_fingerprint(inputs.transcript)["segments"]

    def basis(self, segment_ids: list[str]) -> dict[str, str]:
        return {sid: self.segment_fp[sid] for sid in segment_ids if sid in self.segment_fp}

    # -- tiempo -----------------------------------------------------------------

    def _timing(
        self,
        kind: str,
        anchor_from: str | None,
        anchor_to: str | None,
        start_s: float,
        end_s: float,
        notes: list[str],
    ) -> tuple[float, float, str, str | None, str | None]:
        """Tiempo de una intervención y sus anclas válidas (en orden temporal)."""
        d = self.duration
        w0 = self.words.get(anchor_from or "")
        w1 = self.words.get(anchor_to or "")
        if anchor_from and w0 is None:
            notes.append(f"La palabra de anclaje {anchor_from} no existe; se usan los segundos.")
        if anchor_to and w1 is None and w0 is not None:
            notes.append(f"La palabra final {anchor_to} no existe; se ancla solo a {w0['id']}.")
        w1 = w1 or w0
        a_from = a_to = None
        if w0 is not None and w1 is not None:
            if w1["start"] < w0["start"]:
                w0, w1 = w1, w0
            a_from, a_to = w0["id"], w1["id"]
            start = max(0.0, w0["start"] - LEAD)
            end = min(d, w1["end"] + HOLD)
            if abs(start - start_s) > MODEL_DRIFT or abs(end - end_s) > MODEL_DRIFT:
                notes.append(
                    f"Tiempo ajustado a las palabras ancladas ({start:.2f}–{end:.2f} s; antes "
                    f"{start_s:.2f}–{end_s:.2f} s)."
                )
            timing = "word_anchored"
        else:
            start, end, timing = start_s, end_s, "model_seconds"
        repaired = False
        if start >= d:
            start, repaired = max(0.0, d - 2.0), True
        start = max(0.0, start)
        end = min(d, end)
        min_len = MIN_TRANSITION if kind == "transition" else MIN_DURATION
        if end - start < min_len:
            end = min(d, start + max(min_len, 1.0 if kind != "transition" else 0.4))
            if end - start < min_len:
                start = max(0.0, end - min_len)
            repaired = True
        # Encajar con un corte de escena cercano (sobre todo transiciones).
        k = bisect_left(self.scene_starts, start - SNAP_TO_CUT)
        near_cut = k < len(self.scene_starts) and abs(self.scene_starts[k] - start) <= SNAP_TO_CUT
        if near_cut and (kind == "transition" or timing != "word_anchored"):
            start = max(0.0, self.scene_starts[k] - (0.1 if kind == "transition" else 0.0))
        if repaired:
            notes.append(
                f"Tiempo corregido para que quede dentro del video ({start:.2f}–{end:.2f} s)."
            )
            if timing == "model_seconds":
                timing = "repaired"
        return round(start, 3), round(end, 3), timing, a_from, a_to

    def retime(self, i: PlanIntervention) -> list[str]:
        """Recalcula tiempo y referencias medidas de una intervención existente con los datos
        actuales (transcripción y análisis). Devuelve las notas de la corrección."""
        notes: list[str] = []
        start, end, timing, a_from, a_to = self._timing(
            i.type, i.anchor_from_word, i.anchor_to_word, i.start, i.end, notes
        )
        segment_ids, excerpt = self._segments(start, end)
        i.start, i.end, i.anchor_from_word, i.anchor_to_word = start, end, a_from, a_to
        if timing != "word_anchored" and i.timing == "word_anchored":
            i.timing = "repaired"
        elif timing == "word_anchored":
            i.timing = "word_anchored"
        i.segment_ids, i.transcript_excerpt = segment_ids, excerpt
        i.scene_indices = self._scenes(start, end)
        i.frame_ids = self._frames(i.frame_ids, start, end, notes)
        i.protected_regions = self._faces(start, end) if i.avoid_face else []
        i.basis_segments = self.basis(segment_ids)
        i.basis_analysis = self.inputs.analysis_id
        return notes

    # -- referencias ---------------------------------------------------------------

    def _segments(self, start: float, end: float) -> tuple[list[str], str]:
        t = self.inputs.transcript
        if t is None:
            return [], ""
        ids = [s["id"] for s in t.segments if _overlap(start, end, s["start"], s["end"]) > 0.05]
        k = bisect_left(self.word_starts, start - 0.05)
        excerpt = []
        for w in self.inputs.words[k:]:
            if w["start"] > end:
                break
            if w["end"] <= end + 0.05:
                excerpt.append(w["text"])
        return ids, " ".join(excerpt)[:400]

    def _scenes(self, start: float, end: float) -> list[int]:
        return [
            sc["index"]
            for sc in self.inputs.scenes
            if _overlap(start, end, sc["start"], sc["end"]) > 0.01
        ]

    def _frames(self, wanted: list[str], start: float, end: float, notes: list[str]) -> list[str]:
        valid = [f for f in wanted if f in self.frames]
        bad = [f for f in wanted if f not in self.frames]
        if bad:
            notes.append(f"Fotogramas de referencia inexistentes descartados: {', '.join(bad)}.")
        if not valid and self.inputs.frames:
            mid = (start + end) / 2
            ordered = sorted(self.inputs.frames, key=lambda f: abs(f.t - mid))
            valid = [f.id for f in ordered[:2]]
        return valid[:6]

    def _faces(self, start: float, end: float) -> list[Region]:
        frames = [f for f in self.inputs.frames if start - 1.0 <= f.t <= end + 1.0 and f.faces]
        if not frames:
            mid = (start + end) / 2
            near = sorted(
                (f for f in self.inputs.frames if f.faces is not None), key=lambda f: abs(f.t - mid)
            )
            frames = [f for f in near[:1] if f.faces]
        regions: list[Region] = []
        for f in frames:
            for face in f.faces or []:
                x, y, w, h = face["box"]
                pad_w, pad_h = w * 0.15, h * 0.15
                x0, y0 = max(0.0, x - pad_w), max(0.0, y - pad_h)
                x1, y1 = min(1.0, x + w + pad_w), min(1.0, y + h + pad_h)
                if x1 > x0 and y1 > y0:
                    regions.append(
                        Region(
                            x=round(x0, 4), y=round(y0, 4), w=round(x1 - x0, 4), h=round(y1 - y0, 4)
                        )
                    )
        # Fusionar en una sola caja por grupo cercano (rostros del mismo presentador).
        if len(regions) > 1:
            x0 = min(r.x for r in regions)
            y0 = min(r.y for r in regions)
            x1 = max(r.x + r.w for r in regions)
            y1 = max(r.y + r.h for r in regions)
            if (x1 - x0) * (y1 - y0) < 0.45:
                return [
                    Region(x=round(x0, 4), y=round(y0, 4), w=round(x1 - x0, 4), h=round(y1 - y0, 4))
                ]
        return regions[:4]

    # -- estilo -------------------------------------------------------------------

    def _style(self, p: ProposalIntervention, notes: list[str]) -> tuple[list[Element], Any, Any]:
        rules = self.eff["rules"]
        allowed = set(self.eff["elements"])
        elements: list[Element] = []
        for el in p.elements:
            if el.kind in allowed:
                elements.append(el)
                continue
            sub = rules.element_fallback.get(el.kind)
            if sub and sub in allowed:
                elements.append(el.model_copy(update={"kind": sub}))
                notes.append(f"Elemento «{el.kind}» ajeno a {rules.name}: sustituido por «{sub}».")
            else:
                notes.append(f"Elemento «{el.kind}» ajeno a {rules.name}: descartado.")
        motion = p.motion
        changes: dict[str, str] = {}
        if motion.entry not in self.eff["entries"]:
            changes["entry"] = rules.default_entry
        if motion.exit not in self.eff["exits"]:
            changes["exit"] = rules.default_exit
        if motion.easing not in self.eff["easings"]:
            changes["easing"] = rules.default_easing
        if changes:
            notes.append(
                "Movimiento adaptado al estilo: "
                + ", ".join(f"{k} {getattr(motion, k)}→{v}" for k, v in changes.items())
                + "."
            )
            motion = motion.model_copy(update=changes)
        trans = p.transitions
        tchanges = {}
        fallback = "cut" if "cut" in self.eff["transitions"] else "none"
        for key in ("into", "out"):
            if getattr(trans, key) not in self.eff["transitions"]:
                tchanges[key] = fallback
        if tchanges:
            notes.append("Transición ajena al estilo sustituida por un corte.")
            trans = trans.model_copy(update=tchanges)
        return elements, motion, trans

    # -- intervención -------------------------------------------------------------

    def materialize(
        self,
        p: ProposalIntervention,
        *,
        iid: str | None = None,
        origin: str = "generated",
        previous: PlanIntervention | None = None,
    ) -> PlanIntervention:
        notes: list[str] = []
        start, end, timing, a_from, a_to = self._timing(
            p.type, p.anchor_from_word, p.anchor_to_word, p.start, p.end, notes
        )
        segment_ids, excerpt = self._segments(start, end)
        scenes = self._scenes(start, end)
        frame_ids = self._frames(p.frame_ids, start, end, notes)
        elements, motion, transitions = self._style(p, notes)
        sfx = list(p.sfx)
        if not self.eff["sfx"]["sfx_enabled"] and sfx:
            sfx = []
            notes.append("Efectos de sonido descartados: están desactivados en las preferencias.")
        fixed = []
        for cue in sfx:
            at = min(max(cue.at, start - 0.5), end + 0.5, self.duration)
            if abs(at - cue.at) > 0.01:
                notes.append(f"Efecto «{cue.kind}» movido a {at:.2f} s para quedar en su tramo.")
            fixed.append(cue.model_copy(update={"at": round(max(0.0, at), 3)}))
        protected = self._faces(start, end) if p.avoid_face else []
        region = p.composition.region
        if region is not None and p.type not in PASSIVE_TYPES and p.type not in FULLSCREEN_TYPES:
            for face in protected:
                if _intersect(region, face) > 0.2 * face.w * face.h:
                    notes.append("La composición propuesta tapa un rostro detectado en este tramo.")
                    break
            if p.subtitles == "keep":
                for z in self.inputs.subtitle_zones:
                    if _overlap(start, end, z["start"], z["end"]) <= 0:
                        continue
                    band = Region(
                        x=0, y=min(z["y"], 0.99), w=1, h=max(0.01, min(z["h"], 1 - z["y"]))
                    )
                    if _intersect(region, band) > 0.0:
                        notes.append(
                            "Coincide con la franja de los subtítulos (se mantienen visibles)."
                        )
                        break
        if self.inputs.config.animations.placement == "discrete" and p.type in FULLSCREEN_TYPES:
            notes.append(
                "Las preferencias piden intervenciones discretas y esta es a pantalla completa."
            )
        now = utcnow().isoformat()
        history = list(previous.status_history) if previous else []
        history.append(StatusEvent(status="proposed", at=now, note=origin))
        return PlanIntervention(
            id=iid or new_id("iv"),
            start=start,
            end=end,
            anchor_from_word=a_from,
            anchor_to_word=a_to,
            timing=timing,
            segment_ids=segment_ids,
            transcript_excerpt=excerpt,
            scene_indices=scenes,
            frame_ids=frame_ids,
            type=p.type,
            goal=p.goal,
            visual_description=p.visual_description,
            style=self.inputs.style,
            composition=p.composition,
            elements=elements,
            motion=motion,
            transitions=transitions,
            sfx=fixed,
            intensity=p.intensity,
            avoid_face=p.avoid_face,
            protected_regions=protected,
            subtitles=p.subtitles,
            rationale=p.rationale,
            evidence=p.evidence,
            confidence=p.confidence,
            status="proposed",
            status_history=history,
            origin=origin,
            revision=(previous.revision + 1) if previous else 1,
            warnings=notes,
            basis_segments=self.basis(segment_ids),
            basis_analysis=self.inputs.analysis_id,
        )

    # -- plan --------------------------------------------------------------------

    def check(self, doc: PlanDocument) -> PlanDocument:
        doc.interventions.sort(key=lambda i: (i.start, i.end))
        conflicts: list[dict[str, Any]] = []
        live = [
            i for i in doc.interventions if i.status != "rejected" and i.type not in PASSIVE_TYPES
        ]
        for a_i, a in enumerate(live):
            for b in live[a_i + 1 :]:
                if b.start >= a.end:
                    break
                ov = _overlap(a.start, a.end, b.start, b.end)
                if ov <= HANDOFF or "transition" in (a.type, b.type):
                    continue
                reason = None
                if a.type in FULLSCREEN_TYPES or b.type in FULLSCREEN_TYPES:
                    reason = "Una animación a pantalla completa se solapa con otra intervención."
                elif a.composition.region and b.composition.region:
                    if _intersect(a.composition.region, b.composition.region) > 0.02:
                        reason = "Dos superposiciones ocupan la misma zona al mismo tiempo."
                elif a.composition.layout == b.composition.layout:
                    reason = "Dos superposiciones con la misma disposición coinciden en el tiempo."
                if reason:
                    conflicts.append(
                        {"a": a.id, "b": b.id, "seconds": round(ov, 2), "reason": reason}
                    )
        ids = [i.id for i in doc.interventions]
        errors = []
        if len(ids) != len(set(ids)):
            errors.append("Hay identificadores de intervención duplicados.")
        for i in doc.interventions:
            if not (0 <= i.start < i.end <= self.duration + 1e-6):
                errors.append(f"{i.id}: tiempo fuera del video.")
        visible = [i for i in live if i.type != "transition"]
        minutes = max(self.duration / 60, 0.25)
        density = round(len(visible) / minutes, 2)
        target = self.eff["density_per_minute"]
        warnings = []
        if density > target * 1.5:
            warnings.append(
                f"Densidad alta: {density} intervenciones visibles por minuto "
                f"(preferencia ≈ {target})."
            )
        preserve = {s.scene_index for s in doc.understanding.scenes if s.policy == "preserve"}
        for i in live:
            if i.type in ("fullscreen_animation", "overlay_motion", "diagram") and preserve & set(
                i.scene_indices
            ):
                warnings.append(f"{i.id}: interviene en una escena marcada para preservar.")
        repairs = sum(len(i.warnings) for i in doc.interventions)
        doc.validation = {
            "checked_at": utcnow().isoformat(),
            "errors": errors,
            "warnings": warnings,
            "conflicts": conflicts,
            "density_per_minute": density,
            "density_target": target,
            "interventions_with_notes": sum(1 for i in doc.interventions if i.warnings),
            "notes_total": repairs,
        }
        return doc


def approval_problems(doc: PlanDocument, stale_ids: set[str]) -> list[str]:
    """Motivos que impiden aprobar el plan (vacío = se puede aprobar)."""
    problems = list(doc.validation.get("errors") or [])
    pending = [i.id for i in doc.interventions if i.status in ("proposed", "needs_changes")]
    if pending:
        problems.append(f"{len(pending)} intervención(es) sin decidir (acepta o rechaza cada una).")
    accepted = {i.id for i in doc.interventions if i.status == "accepted"}
    if not accepted:
        problems.append("No hay ninguna intervención aceptada.")
    for c in doc.validation.get("conflicts") or []:
        if c["a"] in accepted and c["b"] in accepted:
            problems.append(f"Conflicto entre {c['a']} y {c['b']}: {c['reason']}")
    stale = stale_ids & accepted
    if stale:
        problems.append(
            f"{len(stale)} intervención(es) aceptada(s) quedaron obsoletas tras cambiar la "
            "transcripción o el análisis."
        )
    return problems
