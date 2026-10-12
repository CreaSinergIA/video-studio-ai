/**
 * Medición real de texto con la tipografía cargada (canvas 2D en el navegador de render).
 * Es determinista: mismas fuentes, mismo motor, mismo resultado en cada fotograma.
 */
let ctx: CanvasRenderingContext2D | null = null

export type Font = { family: string; weight: number }

/**
 * Fase 5: tamaño relativo de los textos de la animación en curso (`params.textScale` de la
 * especificación, 0,8–1,4). Lo fija la raíz del clip antes de renderizar sus hijos; cada clip se
 * renderiza con una sola especificación, así que es estable en todos sus fotogramas. Multiplica
 * el tamaño MÁXIMO de cada texto: el espacio disponible sigue mandando (1 = estilo aprobado).
 */
let textScale = 1
export function setTextScale(value: unknown) {
  const v = Number(value)
  textScale = Number.isFinite(v) && v > 0 ? Math.min(1.4, Math.max(0.8, v)) : 1
}
export const scaled = (base: number) => base * textScale

export function measure(text: string, font: Font, size: number, tracking = 0): number {
  if (typeof document === 'undefined') return text.length * size * 0.56
  if (!ctx) ctx = document.createElement('canvas').getContext('2d')
  if (!ctx) return text.length * size * 0.56
  ctx.font = `${font.weight} ${size}px "${font.family}"`
  return ctx.measureText(text).width + tracking * Math.max(0, Array.from(text).length - 1)
}

/** Mayor tamaño (≤ base) con el que el texto cabe en `maxWidth`. */
export function fit(text: string, font: Font, maxWidth: number, base0: number, min = 12): number {
  const base = scaled(base0)
  if (!text) return base
  const w = measure(text, font, base)
  if (w <= maxWidth) return base
  return Math.max(min, (base * maxWidth) / w)
}
