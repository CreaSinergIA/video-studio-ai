import { Easing, interpolate, spring } from 'remotion'
import type { AnimationSpec } from '../spec'
import { fit, scaled, type Font } from './measure'

/** Curvas de movimiento con nombre (todas deterministas, función solo del fotograma). */
export const EASE = {
  smooth: Easing.bezier(0.45, 0, 0.2, 1),
  out: Easing.bezier(0.22, 1, 0.36, 1),
  expo: Easing.bezier(0.16, 1, 0.3, 1),
  in: Easing.bezier(0.55, 0, 1, 0.45),
  inOut: Easing.bezier(0.65, 0, 0.35, 1),
  // Anticipación: retrocede un poco antes de avanzar (back-in-out suave).
  anticipate: Easing.bezier(0.6, -0.28, 0.32, 1.4),
  linear: Easing.linear,
}

export function styleEase(spec: AnimationSpec) {
  switch (spec.easing) {
    case 'exponential':
      return EASE.expo
    case 'linear':
      return EASE.linear
    case 'smooth':
      return EASE.smooth
    default:
      return EASE.out
  }
}

/** Progreso 0→1 entre `start` y `start + dur` fotogramas, con curva y límites. */
export function p(frame: number, start: number, dur: number, easing = EASE.out): number {
  if (dur <= 0) return frame >= start ? 1 : 0
  return interpolate(frame, [start, start + dur], [0, 1], {
    easing,
    extrapolateLeft: 'clamp',
    extrapolateRight: 'clamp',
  })
}

/** Muelle físico determinista que arranca en `start`. */
export function sp(
  frame: number,
  fps: number,
  start: number,
  cfg: { damping?: number; stiffness?: number; mass?: number } = {},
) {
  return spring({
    frame: frame - start,
    fps,
    config: { damping: cfg.damping ?? 14, stiffness: cfg.stiffness ?? 140, mass: cfg.mass ?? 0.9 },
  })
}

/** Movimiento propio de cada estilo para la aparición de un elemento. */
export function appear(spec: AnimationSpec, frame: number, cue: number, dur?: number) {
  const fps = spec.fps
  const d = dur ?? Math.round(fps * (spec.style === 'minimal_motion' ? 0.7 : 0.45))
  if (spec.easing === 'spring' || spec.easing === 'bounce') {
    const s = sp(frame, fps, cue, spec.easing === 'bounce' ? { damping: 9, stiffness: 160 } : {})
    return Math.max(0, Math.min(1.25, s))
  }
  return p(frame, cue, d, styleEase(spec))
}

/** Envolvente del clip: entrada al principio y salida al final. */
/**
 * Fotograma en que entra el contenedor. Con `lead`, si el primer concepto se dice bastante
 * después del inicio aprobado, el contenedor entra justo antes de él (sin tarjeta vacía).
 */
export function entryStart(spec: AnimationSpec, lead = false) {
  if (!lead || spec.mode !== 'overlay' || spec.chainIn) return 0
  const cues = spec.items.map((i) => i.cue)
  if (spec.number) cues.push(spec.number.cue)
  if (!cues.length) return 0
  const first = Math.min(...cues)
  const start = first - spec.entryFrames - Math.round(spec.fps * 0.25)
  return start > spec.fps * 0.6 ? start : 0
}

export function envelope(spec: AnimationSpec, frame: number, lead = false) {
  const inP = p(frame, entryStart(spec, lead), Math.max(1, spec.entryFrames), styleEase(spec))
  const outStart = spec.durationInFrames - Math.max(1, spec.exitFrames)
  const outP = p(frame, outStart, Math.max(1, spec.exitFrames), EASE.in)
  return { inP, outP, visible: 1 - outP }
}

/** Unidad de tamaño: 1 = 1 px en un video de 1080 px de lado corto. */
export function unit(spec: AnimationSpec) {
  return Math.min(spec.width, spec.height) / 1080
}

export const clamp01 = (v: number) => Math.max(0, Math.min(1, v))

/** Caja en píxeles a partir de una caja normalizada. */
export function px(spec: AnimationSpec, b: { x: number; y: number; w: number; h: number }) {
  return { x: b.x * spec.width, y: b.y * spec.height, w: b.w * spec.width, h: b.h * spec.height }
}

/** Tamaño de letra que hace caber un texto en un ancho: con la fuente real si se indica
 * (medición en el navegador) o por ancho medio de glifo como respaldo. */
export function fitFont(text: string, maxWidth: number, base: number, ratio = 0.56, min = 12, font?: Font) {
  if (font) return fit(text, font, maxWidth, base, min)
  const len = Math.max(1, text.length)
  return Math.max(min, Math.min(scaled(base), maxWidth / (len * ratio)))
}

/** Parte un texto en líneas de como mucho `maxChars` caracteres. */
export function wrap(text: string, maxChars: number): string[] {
  const words = text.split(/\s+/).filter(Boolean)
  const lines: string[] = []
  let cur = ''
  for (const w of words) {
    if (cur && (cur + ' ' + w).length > maxChars) {
      lines.push(cur)
      cur = w
    } else {
      cur = cur ? `${cur} ${w}` : w
    }
  }
  if (cur) lines.push(cur)
  return lines
}

/** Interpolación de rectángulos (continuidad entre composiciones). */
export function lerpRect(a: { x: number; y: number; w: number; h: number }, b: { x: number; y: number; w: number; h: number }, t: number) {
  return { x: a.x + (b.x - a.x) * t, y: a.y + (b.y - a.y) * t, w: a.w + (b.w - a.w) * t, h: a.h + (b.h - a.h) * t }
}
