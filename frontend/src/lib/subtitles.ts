import type { Asset, SubtitleSettings } from './types'

/**
 * Posición vertical (porcentaje desde arriba) del bloque de subtítulos.
 * Con «auto», en vertical se eleva al tercio inferior para no chocar con la interfaz de las
 * redes sociales; en horizontal va abajo, respetando el margen.
 */
export function subtitleAnchor(s: SubtitleSettings, orientation: Asset['orientation'] | undefined) {
  if (s.auto_position) {
    return orientation === 'vertical'
      ? { top: '68%', translate: '-50%' }
      : { top: `${100 - Math.max(s.margin_percent, 6)}%`, translate: '-100%' }
  }
  if (s.position === 'top') return { top: `${s.margin_percent}%`, translate: '0%' }
  if (s.position === 'middle') return { top: '50%', translate: '-50%' }
  return { top: `${100 - s.margin_percent}%`, translate: '-100%' }
}
