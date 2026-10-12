import type { AnimationSpec, Item } from '../spec'

export type Slot = { cx: number; cy: number; w: number; h: number }
export type Rect = { x: number; y: number; w: number; h: number }

/** Distribuye `n` elementos dentro de una caja según la disposición pedida. */
/** `textWeight` < 1: los elementos llevan etiquetas de texto y el ancho de la celda vale más que
 *  su alto (p. ej. 0,75 → con 3 bocetos, 2 + 1 centrado en vez de 3 columnas estrechas). */
export function arrange(n: number, box: Rect, arrangement: AnimationSpec['arrangement'], textWeight = 1): Slot[] {
  if (n <= 0) return []
  let mode = arrangement
  const aspect = box.w / Math.max(1, box.h)
  if (mode === 'auto') {
    mode = n <= 1 ? 'row' : aspect > 1.5 ? 'row' : aspect < 0.75 ? 'column' : n > 3 ? 'grid' : 'row'
  }
  // La disposición pedida se adapta a la forma real de la caja: un radial necesita un espacio
  // casi cuadrado y una columna, uno alto; si no, los elementos quedarían diminutos.
  if (mode === 'radial' && (aspect > 1.6 || aspect < 0.6)) mode = aspect > 1 ? 'row' : 'column'
  if (mode === 'column' && aspect > 2.2) mode = 'row'
  if (mode === 'row' && aspect < 0.45) mode = 'column'
  // Una fila de 4+ elementos con celdas estrechas y altas: mejor en rejilla (2×2, 2×3…).
  if (mode === 'row' && n >= (textWeight < 1 ? 3 : 4) && box.w / n / Math.max(1, box.h) < 0.55) mode = 'grid'
  if (mode === 'row') {
    const w = box.w / n
    return Array.from({ length: n }, (_, i) => ({ cx: box.x + w * (i + 0.5), cy: box.y + box.h / 2, w, h: box.h }))
  }
  if (mode === 'column') {
    const h = box.h / n
    return Array.from({ length: n }, (_, i) => ({ cx: box.x + box.w / 2, cy: box.y + h * (i + 0.5), w: box.w, h }))
  }
  if (mode === 'radial') {
    if (n === 1) return [{ cx: box.x + box.w / 2, cy: box.y + box.h / 2, w: box.w, h: box.h }]
    const cx = box.x + box.w / 2
    const cy = box.y + box.h / 2
    const r = Math.min(box.w, box.h) * 0.36
    const out: Slot[] = [{ cx, cy, w: box.w * 0.34, h: box.h * 0.34 }]
    for (let i = 0; i < n - 1; i++) {
      const a = -Math.PI / 2 + (i * 2 * Math.PI) / (n - 1)
      out.push({ cx: cx + Math.cos(a) * r * (box.w / Math.min(box.w, box.h)), cy: cy + Math.sin(a) * r, w: box.w * 0.28, h: box.h * 0.28 })
    }
    return out
  }
  // Rejilla con la celda de lado menor más grande; a igualdad, la que deja menos huecos (4 → 2×2).
  let cols = 1
  let best = -1
  for (let c = 1; c <= n; c++) {
    const r = Math.ceil(n / c)
    const score = Math.min((box.w / c) * textWeight, box.h / r) - (c * r - n) * 0.01
    if (score > best + 1e-6) {
      best = score
      cols = c
    }
  }
  const rows = Math.ceil(n / cols)
  const w = box.w / cols
  const h = box.h / rows
  return Array.from({ length: n }, (_, i) => {
    const row = Math.floor(i / cols)
    // La última fila incompleta se centra.
    const inRow = row === rows - 1 ? n - row * cols : cols
    return { cx: box.x + (box.w - inRow * w) / 2 + w * ((i % cols) + 0.5), cy: box.y + h * (row + 0.5), w, h }
  })
}

/** Elementos visibles (sin decoración) en orden de aparición. */
export function visibleItems(items: Item[]) {
  return items.filter((i) => i.role !== 'decoration').sort((a, b) => a.cue - b.cue)
}

/** Primer texto disponible (titular). */
export function headline(spec: AnimationSpec) {
  if (spec.title) return spec.title
  const prim = spec.items.find((i) => i.role === 'primary' && i.text)
  return prim?.text ?? spec.items.find((i) => i.text)?.text ?? ''
}

export function inset(r: Rect, pad: number): Rect {
  return { x: r.x + pad, y: r.y + pad, w: Math.max(1, r.w - pad * 2), h: Math.max(1, r.h - pad * 2) }
}

/** Margen interior proporcional: en cajas bajas (franjas entre la interfaz y el rostro) un
 *  margen fijo se comería buena parte del alto útil. */
export function pad(box: Rect, base: number) {
  return Math.min(base, Math.min(box.w, box.h) * 0.08)
}

/** Recorte interior con margen proporcional. */
export function insetP(r: Rect, base: number): Rect {
  return inset(r, pad(r, base))
}
