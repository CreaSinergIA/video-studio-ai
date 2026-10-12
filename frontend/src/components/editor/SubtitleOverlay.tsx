import { useEffect, useLayoutEffect, useRef, useState, type CSSProperties } from 'react'
import { subtitleAnchor } from '@/lib/subtitles'
import type { Asset, SubtitleSettings } from '@/lib/types'

const SAMPLE = 'Así se verán tus subtítulos en este video'

function chunk(words: string[], size: number) {
  const lines: string[][] = []
  for (let i = 0; i < words.length; i += size) lines.push(words.slice(i, i + size))
  return lines
}

/**
 * Muestra estática/animada del estilo configurado sobre el fotograma real. Es una vista previa
 * de los parámetros, no una transcripción: el texto es de ejemplo (la transcripción llega en
 * la Fase 2).
 */
export function SubtitleOverlay({
  settings,
  orientation,
  label = true,
}: {
  settings: SubtitleSettings
  orientation?: Asset['orientation']
  label?: boolean
}) {
  const ref = useRef<HTMLDivElement>(null)
  const [box, setBox] = useState({ w: 0, h: 0 })
  const [tick, setTick] = useState(0)

  useLayoutEffect(() => {
    const el = ref.current
    if (!el) return
    const observer = new ResizeObserver(([entry]) => setBox({ w: entry.contentRect.width, h: entry.contentRect.height }))
    observer.observe(el)
    return () => observer.disconnect()
  }, [])

  useEffect(() => {
    const id = setInterval(() => setTick((t) => t + 1), 420)
    return () => clearInterval(id)
  }, [])

  if (!settings.enabled) {
    return (
      <div ref={ref} className="pointer-events-none absolute inset-0 grid place-items-center">
        <span className="rounded-md bg-black/60 px-2 py-1 text-xs text-white/80">Subtítulos desactivados</span>
      </div>
    )
  }

  const words = SAMPLE.split(' ').slice(0, Math.max(settings.max_words_per_line * 2, 4))
  const lines = chunk(words, settings.max_words_per_line).slice(0, 2)
  const shown = lines.flat()
  const scale = Math.min(box.w, box.h) / 1080 || 0
  const fontPx = settings.font_size * scale
  const active = tick % (shown.length + 3)
  const anchor = subtitleAnchor(settings, orientation)
  const cycle = Math.floor(tick / (shown.length + 3))

  const textStyle: CSSProperties = {
    fontFamily: `'${settings.font_family}', sans-serif`,
    fontWeight: settings.font_weight,
    fontSize: fontPx,
    lineHeight: 1.15,
    color: settings.text_color,
    textTransform: settings.uppercase ? 'uppercase' : 'none',
    paintOrder: 'stroke fill',
    WebkitTextStroke: settings.outline_enabled && settings.outline_width > 0 ? `${settings.outline_width * scale * 2}px ${settings.outline_color}` : undefined,
    textShadow: settings.shadow_enabled
      ? `0 ${Math.max(1, settings.shadow_blur * scale * 0.25)}px ${settings.shadow_blur * scale}px ${settings.shadow_color}`
      : undefined,
  }

  const lineStarts = lines.map((_, li) => lines.slice(0, li).reduce((n, l) => n + l.length, 0))
  const blockAnimation =
    settings.animation === 'fade' ? 'vsa-sub-fade' : settings.animation === 'slide_up' ? 'vsa-sub-slide' : undefined
  return (
    <div ref={ref} className="pointer-events-none absolute inset-0 overflow-hidden">
      <div
        key={cycle}
        className={`absolute left-1/2 w-[88%] text-center ${blockAnimation ?? ''}`}
        style={{ top: anchor.top, transform: `translate(-50%, ${anchor.translate})` }}
      >
        {lines.map((line, li) => (
          <div key={li} style={textStyle}>
            {line.map((word, wi) => {
              const i = lineStarts[li] + wi
              const highlighted =
                (settings.animation === 'karaoke' && i <= active) ||
                (settings.animation !== 'karaoke' && i === active)
              const hidden =
                (settings.animation === 'word_by_word' || settings.animation === 'typewriter') && i > active
              const anim = settings.animation === 'pop' && i === active ? 'vsa-sub-pop' : undefined
              return (
                <span
                  key={i}
                  className={anim}
                  style={{
                    display: 'inline-block',
                    marginRight: '0.25em',
                    color: highlighted && settings.animation !== 'none' ? settings.highlight_color : undefined,
                    opacity: hidden ? 0 : 1,
                    transition: 'color 120ms ease, opacity 120ms ease',
                  }}
                >
                  {word}
                </span>
              )
            })}
          </div>
        ))}
      </div>
      {label && (
        <span className="absolute left-2 top-2 rounded bg-black/55 px-1.5 py-0.5 text-[10px] font-medium text-white/80">
          Muestra de estilo · texto de ejemplo
        </span>
      )}
    </div>
  )
}
