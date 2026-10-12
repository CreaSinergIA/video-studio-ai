import { useLayoutEffect, useRef, useState, type CSSProperties } from 'react'
import { blockAt, stateAt } from '@/lib/subtitleState'
import type { SubtitleTrack } from '@/lib/types'

function hexAlpha(hex: string, alpha: number) {
  const n = parseInt(hex.slice(1), 16)
  return `rgba(${(n >> 16) & 255}, ${(n >> 8) & 255}, ${n & 255}, ${alpha})`
}

/**
 * Dibuja la pista de subtítulos calculada por el backend en el instante `time`. Trabaja en
 * píxeles del video (mismas posiciones, tamaños y fuentes que la exportación) y se escala al
 * tamaño mostrado. Sin kerning ni ligaduras, igual que el render de exportación (FreeType).
 */
export function TrackOverlay({ track, time }: { track: SubtitleTrack; time: number }) {
  const ref = useRef<HTMLDivElement>(null)
  const [scale, setScale] = useState(0)

  useLayoutEffect(() => {
    const el = ref.current
    if (!el) return
    const observer = new ResizeObserver(([entry]) => setScale(entry.contentRect.width / track.width))
    observer.observe(el)
    return () => observer.disconnect()
  }, [track.width])

  const block = track.enabled ? blockAt(track, time) : null
  const state = block ? stateAt(track, block, time) : null
  const { font, style } = track
  const items = block
    ? block.lines.flatMap((line) => line.words.map((w) => ({ w, baseline: line.baseline })))
    : []

  const base: CSSProperties = {
    position: 'absolute',
    fontFamily: `'${font.css_family}', sans-serif`,
    fontWeight: font.weight,
    fontSize: font.size,
    lineHeight: `${font.ascent + font.descent}px`,
    whiteSpace: 'pre',
    // Sin las características tipográficas de la interfaz (cv11/ss01 de Inter): el render
    // de exportación (FreeType) usa los glifos por defecto de cada fuente.
    fontFeatureSettings: 'normal',
    fontKerning: 'none',
    fontVariantLigatures: 'none',
    fontSynthesis: 'none',
    paintOrder: 'stroke fill',
    WebkitTextStroke: style.outline > 0 ? `${style.outline * 2}px ${style.outline_color}` : undefined,
    textShadow: style.shadow
      ? `0 ${style.shadow_offset}px ${style.shadow_blur}px ${hexAlpha(style.shadow_color, 0.85)}`
      : undefined,
  }

  return (
    <div ref={ref} className="pointer-events-none absolute inset-0 overflow-hidden" aria-hidden>
      {block && state && scale > 0 && (
        <div
          style={{
            position: 'absolute',
            left: 0,
            top: 0,
            width: track.width,
            height: track.height,
            transform: `scale(${scale})`,
            transformOrigin: '0 0',
            opacity: state.alpha,
          }}
        >
          {items.map(({ w, baseline }, i) => {
            const ws = state.words[i]
            if (!ws?.visible) return null
            const text = ws.chars === null ? w.text : Array.from(w.text).slice(0, ws.chars).join('')
            const s = ws.scale * state.scale
            return (
              <span
                key={w.id + i}
                style={{
                  ...base,
                  left: w.x,
                  top: baseline + state.dy - font.ascent,
                  color: ws.highlight ? style.highlight_color : style.text_color,
                  transform: s !== 1 ? `scale(${s})` : undefined,
                  transformOrigin: `${w.w / 2}px ${(font.ascent + font.descent) / 2}px`,
                }}
              >
                {text}
              </span>
            )
          })}
        </div>
      )}
    </div>
  )
}
