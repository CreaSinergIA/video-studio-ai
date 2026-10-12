import React from 'react'
import { AbsoluteFill, useCurrentFrame } from 'remotion'
import type { AnimationSpec, Primitive } from './spec'
import { DrawPaths, roughPaths, Stroke } from './lib/draw'
import { EASE, clamp01, envelope, p, sp, unit } from './lib/motion'
import { setTextScale } from './lib/measure'
import { HandText } from './styles/explainer'
import { STYLES } from './styles/registry'

/**
 * Composición declarativa (sin código): primitivas validadas por el backend que Claude puede
 * combinar cuando la biblioteca no tiene un recurso adecuado. Se pintan con la misma gramática
 * del estilo (trazo a mano en Creative Explainer, trazo limpio en los demás).
 */
function CustomLayer({ spec }: { spec: AnimationSpec }) {
  const frame = useCurrentFrame()
  const u = unit(spec)
  const W = spec.width
  const H = spec.height
  const hand = spec.style === 'creative_explainer'
  return (
    <g>
      {spec.custom.map((pr: Primitive, i) => {
        const color = spec.palette[pr.color]
        const k = p(frame, pr.cue, spec.fps * 0.5, EASE.out)
        const gone = pr.exitCue != null ? 1 - p(frame, pr.exitCue, spec.fps * 0.3, EASE.in) : 1
        const x = pr.x * W
        const y = pr.y * H
        const w = (pr.w ?? 0) * W
        const h = (pr.h ?? 0) * H
        const sw = pr.stroke * u
        const op = (pr.enter === 'fade' ? k : k > 0 ? 1 : 0) * gone
        const pop = pr.enter === 'pop' ? Math.min(1.1, sp(frame, spec.fps, pr.cue)) : 1
        const slide = pr.enter === 'slide' ? (1 - k) * 30 * u : 0
        const style = { transformOrigin: `${x + w / 2}px ${y + h / 2}px`, scale: String(pr.enter === 'pop' ? pop : 1), translate: `0px ${slide}px` }
        const drawP = pr.enter === 'draw' ? k : 1
        if (pr.type === 'text') {
          const size = Math.max(14 * u, h || 48 * u)
          if (hand) return <g key={i} opacity={op} style={style}><HandText spec={spec} text={pr.text ?? ''} x={x} y={y} size={size} cue={pr.cue} color={color} anchor="start" /></g>
          return (
            <text key={i} x={x} y={y} fontFamily={spec.style === 'motion_tech' ? 'VSA Mono' : 'VSA Inter'} fontWeight={700} fontSize={size} fill={color} opacity={op} style={style}>
              {pr.text}
            </text>
          )
        }
        if (hand) {
          const kind = pr.type === 'rect' ? 'rect' : pr.type === 'ellipse' ? 'ellipse' : pr.type === 'path' ? 'path' : pr.type === 'arrow' ? 'arrow' : 'line'
          const args =
            kind === 'rect' ? [x, y, w, h] : kind === 'ellipse' ? [x + w / 2, y + h / 2, w, h] : [x, y, (pr.x2 ?? pr.x) * W, (pr.y2 ?? pr.y) * H]
          const d = pr.d ? scalePath(pr.d, W, H) : undefined
          const paths = roughPaths(kind, args, { seed: spec.seed + i * 17, stroke: color, strokeWidth: sw, fill: pr.fill ? color : undefined, d })
          return <g key={i} opacity={gone} style={style}><DrawPaths paths={paths} progress={drawP} /></g>
        }
        let d = ''
        if (pr.type === 'rect') d = `M ${x} ${y} h ${w} v ${h} h ${-w} Z`
        else if (pr.type === 'ellipse') d = `M ${x} ${y + h / 2} a ${w / 2} ${h / 2} 0 1 0 ${w} 0 a ${w / 2} ${h / 2} 0 1 0 ${-w} 0`
        else if (pr.type === 'path') d = scalePath(pr.d ?? '', W, H)
        else d = `M ${x} ${y} L ${(pr.x2 ?? pr.x) * W} ${(pr.y2 ?? pr.y) * H}`
        return (
          <g key={i} opacity={gone} style={style}>
            {pr.fill && <path d={d} fill={color} opacity={clamp01(k) * 0.9} />}
            <Stroke d={d} progress={drawP} color={color} width={sw} />
            {pr.type === 'arrow' && <ArrowHead x1={x} y1={y} x2={(pr.x2 ?? pr.x) * W} y2={(pr.y2 ?? pr.y) * H} color={color} size={sw * 5} k={drawP} />}
          </g>
        )
      })}
    </g>
  )
}

function ArrowHead({ x1, y1, x2, y2, color, size, k }: { x1: number; y1: number; x2: number; y2: number; color: string; size: number; k: number }) {
  const a = Math.atan2(y2 - y1, x2 - x1)
  const pts = [
    [x2, y2],
    [x2 - size * Math.cos(a - 0.5), y2 - size * Math.sin(a - 0.5)],
    [x2 - size * Math.cos(a + 0.5), y2 - size * Math.sin(a + 0.5)],
  ]
  return <polygon points={pts.map((q) => q.join(',')).join(' ')} fill={color} opacity={k >= 0.98 ? 1 : 0} />
}

/** Convierte un path de coordenadas normalizadas (0–1) a píxeles (comandos ya validados). */
function scalePath(d: string, W: number, H: number) {
  let axis = 0
  return d.replace(/[MLCQZ]|-?\d*\.?\d+/g, (tok) => {
    if (/[MLCQZ]/.test(tok)) {
      axis = 0
      return tok
    }
    const v = parseFloat(tok) * (axis % 2 === 0 ? W : H)
    axis++
    return v.toFixed(2)
  })
}

export const Clip: React.FC<AnimationSpec> = (spec) => {
  // Antes que cualquier hijo: tamaño relativo de los textos de esta animación (Fase 5).
  setTextScale(spec.params?.textScale ?? 1)
  const frame = useCurrentFrame()
  const style = STYLES[spec.style]
  const T = style?.templates[spec.template]
  const { inP, outP } = envelope(spec, frame)
  const fullscreen = spec.mode === 'fullscreen'
  // Fondo de estilo a pantalla completa con entrada y salida propias (regreso al original).
  const bgK = fullscreen ? clamp01(inP * 1.2) * (1 - outP) : 0
  const Bg = style?.Background ?? (() => null)
  const Pip = style?.PipFrame ?? (() => null)
  const W = spec.width
  const H = spec.height
  const wipe = spec.entry === 'mask_reveal' || spec.entry === 'scan_reveal' || spec.entry === 'draw_on'
  return (
    <AbsoluteFill style={{ backgroundColor: 'transparent' }}>
      <svg
        width={W}
        height={H}
        viewBox={`0 0 ${W} ${H}`}
        style={{ position: 'absolute', left: -(spec.viewport?.x ?? 0), top: -(spec.viewport?.y ?? 0) }}
      >
        {spec.background === 'dim' && <rect width={W} height={H} fill="#000" opacity={0.38 * clamp01(inP * 1.5) * (1 - outP)} />}
        {fullscreen && (
          <g opacity={wipe ? 1 - outP : bgK}>
            <defs>
              <clipPath id={`fs-${spec.id}`}>
                <rect x={0} y={0} width={W * (wipe ? inP : 1)} height={H} />
              </clipPath>
            </defs>
            <g clipPath={`url(#fs-${spec.id})`}>
              <Bg spec={spec} />
            </g>
          </g>
        )}
        {spec.pip && fullscreen && (
          // Hueco del picture-in-picture: lo rellena FFmpeg con el video original (mismo tiempo).
          <g opacity={bgK}>
            <Pip spec={spec} />
          </g>
        )}
        {T ? <T spec={spec} /> : null}
        {spec.custom.length > 0 && <CustomLayer spec={spec} />}
      </svg>
    </AbsoluteFill>
  )
}
