import React from 'react'
import { random } from 'remotion'
import rough from 'roughjs'
import * as lucide from 'lucide'
import { clamp01 } from './motion'

// ---------------------------------------------------------------------------
// Iconos (lucide, ISC): trazos que se dibujan con pathLength normalizado.
// ---------------------------------------------------------------------------

type IconNode = [string, Record<string, string>][]
const ICONS = lucide as unknown as Record<string, IconNode>

/** Solo se admiten iconos que existen en lucide (validado también en el backend). */
export function iconNode(name: string | null | undefined): IconNode | null {
  if (!name) return null
  const node = ICONS[name]
  return Array.isArray(node) ? node : null
}

export function Icon({
  name,
  size,
  color,
  stroke = 2,
  progress = 1,
  wobble = 0,
  seed = 1,
}: {
  name: string
  size: number
  color: string
  stroke?: number
  progress?: number
  wobble?: number
  seed?: number
}) {
  const node = iconNode(name) ?? iconNode('Sparkles')!
  const pr = clamp01(progress)
  return (
    <svg width={size} height={size} viewBox="0 0 24 24" fill="none" style={{ overflow: 'visible' }}>
      {node.map(([tag, attrs], i) => {
        // Cada trazo empieza un poco después del anterior: se «dibuja» en orden.
        const local = clamp01(pr * (1 + node.length * 0.25) - i * 0.25)
        const jitter = wobble ? (random(`${seed}-${i}`) - 0.5) * wobble : 0
        const props: Record<string, unknown> = {
          ...attrs,
          key: i,
          stroke: color,
          strokeWidth: stroke,
          strokeLinecap: 'round',
          strokeLinejoin: 'round',
          pathLength: 1,
          strokeDasharray: 1,
          strokeDashoffset: 1 - local,
          transform: jitter ? `rotate(${jitter} 12 12)` : undefined,
        }
        return React.createElement(tag, props)
      })}
    </svg>
  )
}

// ---------------------------------------------------------------------------
// Trazos a mano alzada (rough.js con semilla: mismo dibujo en cada fotograma).
// ---------------------------------------------------------------------------

const gen = rough.generator()
type RoughPath = { d: string; stroke: string; strokeWidth: number; fill?: string }

const cache = new Map<string, RoughPath[]>()

export function roughPaths(
  kind: 'rect' | 'ellipse' | 'line' | 'arrow' | 'circle' | 'path',
  a: number[],
  opts: { seed: number; stroke: string; strokeWidth: number; roughness?: number; fill?: string; d?: string; solid?: boolean },
): RoughPath[] {
  const key = JSON.stringify([kind, a, opts])
  const hit = cache.get(key)
  if (hit) return hit
  const o = {
    seed: Math.max(1, Math.floor(opts.seed) % 2147483646),
    stroke: opts.stroke,
    strokeWidth: opts.strokeWidth,
    roughness: opts.roughness ?? 1.4,
    bowing: 1.2,
    fill: opts.fill,
    fillStyle: (opts.solid ? 'solid' : 'hachure') as 'solid' | 'hachure',
    hachureGap: opts.strokeWidth * 4,
    fillWeight: opts.strokeWidth * 0.6,
    disableMultiStroke: false,
  }
  let d
  if (kind === 'rect') d = gen.rectangle(a[0], a[1], a[2], a[3], o)
  else if (kind === 'ellipse') d = gen.ellipse(a[0], a[1], a[2], a[3], o)
  else if (kind === 'circle') d = gen.circle(a[0], a[1], a[2], o)
  else if (kind === 'path') d = gen.path(opts.d ?? '', o)
  else d = gen.line(a[0], a[1], a[2], a[3], o)
  const out: RoughPath[] = gen.toPaths(d).map((pi) => ({
    d: pi.d,
    stroke: pi.stroke,
    strokeWidth: pi.strokeWidth,
    fill: pi.fill === 'none' ? undefined : pi.fill,
  }))
  if (kind === 'arrow') {
    // Punta de flecha dibujada a mano.
    const [x1, y1, x2, y2] = a
    const ang = Math.atan2(y2 - y1, x2 - x1)
    const L = Math.max(10, opts.strokeWidth * 6)
    for (const s of [-1, 1]) {
      const hx = x2 - L * Math.cos(ang + s * 0.5)
      const hy = y2 - L * Math.sin(ang + s * 0.5)
      for (const pi of gen.toPaths(gen.line(x2, y2, hx, hy, o))) {
        out.push({ d: pi.d, stroke: pi.stroke, strokeWidth: pi.strokeWidth })
      }
    }
  }
  cache.set(key, out)
  return out
}

/** Dibuja trazos con progreso 0→1 (cada trazo en orden, como una mano). */
export function DrawPaths({ paths, progress, opacity = 1 }: { paths: RoughPath[]; progress: number; opacity?: number }) {
  const n = Math.max(1, paths.length)
  return (
    <g opacity={opacity}>
      {paths.map((pa, i) => {
        const local = clamp01(progress * n - i)
        if (pa.fill) return <path key={i} d={pa.d} fill={pa.fill} opacity={local} />
        return (
          <path
            key={i}
            d={pa.d}
            fill="none"
            stroke={pa.stroke}
            strokeWidth={pa.strokeWidth}
            strokeLinecap="round"
            strokeLinejoin="round"
            pathLength={1}
            strokeDasharray={1}
            strokeDashoffset={1 - local}
          />
        )
      })}
    </g>
  )
}

/** Trazo limpio (geométrico) que se dibuja de inicio a fin. */
export function Stroke({
  d,
  progress,
  color,
  width,
  opacity = 1,
  cap = 'round',
}: {
  d: string
  progress: number
  color: string
  width: number
  opacity?: number
  cap?: 'round' | 'butt' | 'square'
}) {
  return (
    <path
      d={d}
      fill="none"
      stroke={color}
      strokeWidth={width}
      strokeLinecap={cap}
      pathLength={1}
      strokeDasharray={1}
      strokeDashoffset={1 - clamp01(progress)}
      opacity={opacity}
    />
  )
}

// ---------------------------------------------------------------------------
// Fondos y texturas deterministas
// ---------------------------------------------------------------------------

export function Grid({
  w,
  h,
  step,
  color,
  opacity,
  offset = 0,
}: {
  w: number
  h: number
  step: number
  color: string
  opacity: number
  offset?: number
}) {
  const lines: React.ReactNode[] = []
  const o = offset % step
  for (let x = -step + o; x <= w + step; x += step) lines.push(<line key={`v${x}`} x1={x} y1={0} x2={x} y2={h} />)
  for (let y = -step + o; y <= h + step; y += step) lines.push(<line key={`h${y}`} x1={0} y1={y} x2={w} y2={y} />)
  return (
    <g stroke={color} strokeWidth={1} opacity={opacity}>
      {lines}
    </g>
  )
}

export function PaperTexture({ w, h, seed, color }: { w: number; h: number; seed: number; color: string }) {
  const id = `paper-${seed}`
  return (
    <>
      <defs>
        <filter id={id} x="0" y="0" width="100%" height="100%">
          <feTurbulence type="fractalNoise" baseFrequency="0.9" numOctaves="3" seed={seed % 1000} />
          <feColorMatrix type="saturate" values="0" />
          <feComponentTransfer>
            <feFuncA type="linear" slope="0.06" />
          </feComponentTransfer>
        </filter>
      </defs>
      <rect width={w} height={h} fill={color} />
      <rect width={w} height={h} filter={`url(#${id})`} />
    </>
  )
}

/** Partículas que derivan suavemente (posiciones sembradas, no aleatorias por fotograma). */
export function Particles({
  w,
  h,
  n,
  color,
  frame,
  seed,
  opacity,
  size,
}: {
  w: number
  h: number
  n: number
  color: string
  frame: number
  seed: number
  opacity: number
  size: number
}) {
  return (
    <g>
      {Array.from({ length: n }, (_, i) => {
        const x0 = random(`${seed}-px-${i}`) * w
        const y0 = random(`${seed}-py-${i}`) * h
        const v = 0.15 + random(`${seed}-pv-${i}`) * 0.5
        const y = (((y0 - frame * v * size * 0.3) % h) + h) % h
        const tw = 0.4 + 0.6 * Math.abs(Math.sin((frame + i * 13) / 18))
        return <circle key={i} cx={x0} cy={y} r={size * (0.5 + random(`${seed}-pr-${i}`))} fill={color} opacity={opacity * tw} />
      })}
    </g>
  )
}

// ---------------------------------------------------------------------------
// Texto
// ---------------------------------------------------------------------------

const GLYPHS = 'ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789<>/[]{}#$%&*+=?'

/** Texto que se «descodifica» carácter a carácter (Motion Tech). */
export function scramble(text: string, progress: number, frame: number, seed: number) {
  const pr = clamp01(progress)
  const solved = Math.floor(text.length * pr)
  let out = ''
  for (let i = 0; i < text.length; i++) {
    const ch = text[i]
    if (i < solved || ch === ' ') out += ch
    else if (i < solved + 4 && pr > 0) out += GLYPHS[Math.floor(random(`${seed}-${i}-${Math.floor(frame / 2)}`) * GLYPHS.length)]
    else out += ' '
  }
  return out
}

/** Escritura con cursor (texto parcial). */
export function typed(text: string, progress: number) {
  const chars = Array.from(text)
  return chars.slice(0, Math.round(chars.length * clamp01(progress))).join('')
}
