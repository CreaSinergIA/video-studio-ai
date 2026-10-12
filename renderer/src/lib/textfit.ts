import { measure, scaled, type Font } from './measure'

/** Parte un texto en líneas que caben en `w` a `size` (medido con la fuente real). */
export function breakText(text: string, font: Font, size: number, w: number, tracking = 0): string[] {
  const words = text.split(/\s+/).filter(Boolean)
  const lines: string[] = []
  let cur = ''
  for (const word of words) {
    const next = cur ? `${cur} ${word}` : word
    if (cur && measure(next, font, size, tracking) > w) {
      lines.push(cur)
      cur = word
    } else cur = next
  }
  if (cur) lines.push(cur)
  return lines
}

const fits = (lines: string[], font: Font, size: number, w: number, tracking: number) =>
  lines.every((l) => measure(l, font, size, tracking) <= w)

/** Mayor tamaño (≤ base) con el que el texto cabe en `maxLines` líneas de ancho `w`. */
export function fitLines(text: string, font: Font, w: number, base0: number, min: number, maxLines = 2, tracking = 0) {
  const base = scaled(base0)
  for (let size = base; size >= min; size -= Math.max(0.5, base * 0.02)) {
    const lines = breakText(text, font, size, w, tracking)
    if (lines.length <= maxLines && fits(lines, font, size, w, tracking)) return { lines, size }
  }
  return { lines: breakText(text, font, min, w, tracking), size: min }
}

export interface Para {
  text: string
  font: Font
  /** Tamaño relativo al tamaño base del bloque. */
  scale: number
  tracking?: number
}

/**
 * Ajusta un bloque de párrafos a una caja: el mayor tamaño base con el que todos los párrafos,
 * partidos en líneas medidas, caben en `w`×`h` (interlineado `lead`, separación `gap` en em).
 */
export function fitBlock(paras: Para[], w: number, h: number, base: number, min: number, lead = 1.16, gap = 0.28) {
  let size = scaled(base)
  const layout = (s: number) => {
    const out = paras.map((p) => {
      const fs = s * p.scale
      const lines = breakText(p.text, p.font, fs, w, (p.tracking ?? 0) * fs)
      return { lines, size: fs }
    })
    const height = out.reduce((a, o, i) => a + o.lines.length * o.size * lead + (i ? o.size * gap : 0), 0)
    const ok = height <= h && out.every((o, i) => fits(o.lines, paras[i].font, o.size, w, (paras[i].tracking ?? 0) * o.size))
    return { out, height, ok }
  }
  while (size > min) {
    const r = layout(size)
    if (r.ok) return { size, ...r }
    size *= 0.95
  }
  return { size: min, ...layout(min) }
}
