import React from 'react'
import { random, useCurrentFrame } from 'remotion'
import type { AnimationSpec, Item } from '../spec'
import { DrawPaths, Icon, PaperTexture, roughPaths } from '../lib/draw'
import { arrange, headline, insetP, visibleItems, type Rect } from '../lib/layout'
import { EASE, appear, clamp01, entryStart, envelope, fitFont, p, px, sp, unit, wrap } from '../lib/motion'
import { breakText, fitLines } from '../lib/textfit'
import { measure } from '../lib/measure'

const FH = { family: 'VSA Caveat', weight: 700 }

/**
 * CREATIVE EXPLAINER — gramática: ilustración que explica. Tarjetas de papel con borde a mano,
 * esquemas, iconos y personajes que se DIBUJAN (trazo a trazo), rótulos manuscritos, flechas
 * curvas y marcas de rotulador. Movimiento orgánico con muelle y pequeños rebotes.
 */

const HAND = 'VSA Caveat'
const ROUND = 'VSA Poppins'

function ink(spec: AnimationSpec) {
  return spec.palette.text
}

/** Tarjeta de papel con sombra y borde dibujado a mano. */
function Card({ spec, r, children, card = true }: { spec: AnimationSpec; r: Rect; children: React.ReactNode; card?: boolean }) {
  const frame = useCurrentFrame()
  const u = unit(spec)
  const { inP, outP } = envelope(spec, frame, true)
  const s0 = entryStart(spec, true)
  const pal = spec.palette
  const pop = spec.entry === 'pop' || spec.entry === 'scale' || spec.easing === 'spring' || spec.easing === 'bounce'
  const s = pop ? Math.min(1.04, sp(frame, spec.fps, s0, { damping: 11, stiffness: 150 })) : 0.94 + 0.06 * inP
  const morphOut = spec.exit === 'morph' || spec.exit === 'scale' ? 1 - 0.4 * outP : 1
  const tilt = card ? -1.2 + (random(`tilt-${spec.seed}`) - 0.5) * 1.2 : 0
  const border = roughPaths('rect', [r.x, r.y, r.w, r.h], { seed: spec.seed, stroke: ink(spec), strokeWidth: 2.4 * u, roughness: 1.1 })
  return (
    <g
      opacity={clamp01(inP * 1.6) * (1 - outP)}
      style={{ transformOrigin: `${r.x + r.w / 2}px ${r.y + r.h / 2}px`, scale: String(s * morphOut), rotate: `${tilt}deg` }}
    >
      {card && (
        <>
          <rect x={r.x + 8 * u} y={r.y + 10 * u} width={r.w} height={r.h} rx={10 * u} fill="#000" opacity={0.18} />
          <rect x={r.x} y={r.y} width={r.w} height={r.h} rx={10 * u} fill={pal.bg} />
          <svg x={r.x} y={r.y} width={r.w} height={r.h} overflow="hidden">
            <PaperTexture w={r.w} h={r.h} seed={spec.seed} color={pal.bg} />
          </svg>
          <DrawPaths paths={border} progress={p(frame, s0, spec.entryFrames + spec.fps * 0.3, EASE.out)} />
        </>
      )}
      {children}
    </g>
  )
}

/** Texto manuscrito que se escribe de izquierda a derecha. */
function HandText({
  spec,
  text,
  x,
  y,
  size,
  cue,
  color,
  anchor = 'middle',
  weight = 700,
}: {
  spec: AnimationSpec
  text: string
  x: number
  y: number
  size: number
  cue: number
  color: string
  anchor?: 'start' | 'middle'
  weight?: number
}) {
  const frame = useCurrentFrame()
  const k = p(frame, cue, Math.max(6, Math.min(spec.fps * 1.1, text.length * 1.6)), EASE.linear)
  const w = measure(text, FH, size) + size * 0.3
  const x0 = anchor === 'middle' ? x - w / 2 : x
  const id = `hw-${spec.id}-${Math.round(x)}-${Math.round(y)}`
  return (
    <g>
      <defs>
        <clipPath id={id}>
          <rect x={x0 - size * 0.2} y={y - size * 1.1} width={w * k + size * 0.2} height={size * 1.6} />
        </clipPath>
      </defs>
      <text x={x} y={y} textAnchor={anchor} fontFamily={HAND} fontWeight={weight} fontSize={size} fill={color} clipPath={`url(#${id})`}>
        {text}
      </text>
    </g>
  )
}

function shapeFor(it: Item, i: number): 'rect' | 'ellipse' {
  return it.kind === 'diagram_node' && i % 2 === 1 ? 'ellipse' : 'rect'
}

function itemInk(spec: AnimationSpec, it: Item, frame: number) {
  const on = it.stateCue !== undefined && frame >= it.stateCue
  if (it.state === 'negated' && on) return spec.palette.muted
  if (it.role === 'primary') return spec.palette.accent
  return ink(spec)
}

/** Garabato de tachado (zigzag a mano). */
function Scribble({ spec, x, y, w, h, cue }: { spec: AnimationSpec; x: number; y: number; w: number; h: number; cue: number }) {
  const frame = useCurrentFrame()
  const u = unit(spec)
  const pts: string[] = []
  const n = 6
  for (let i = 0; i <= n; i++) pts.push(`${x + (w / n) * i} ${y + (i % 2 ? -h : h) * 0.35}`)
  const paths = roughPaths('path', [], { seed: spec.seed + Math.round(x), stroke: spec.palette.accent, strokeWidth: 3.5 * u, d: `M ${pts.join(' L ')}` })
  return <DrawPaths paths={paths} progress={p(frame, cue, spec.fps * 0.45, EASE.linear)} />
}

// ---------------------------------------------------------------------------

function Sketch({ spec }: { spec: AnimationSpec }) {
  const frame = useCurrentFrame()
  const u = unit(spec)
  const R = px(spec, spec.region)
  const pal = spec.palette
  const items = visibleItems(spec.items)
  const box = insetP(R, 36 * u)
  const slots = arrange(items.length, box, spec.arrangement, spec.mode === 'fullscreen' ? 0.75 : 1)
  const pos = new Map(items.map((it, i) => [it.id, slots[i]]))
  const links = spec.links.length ? spec.links : items.slice(1).map((it, i) => ({ from: items[i].id, to: it.id, cue: it.cue }))
  const big = spec.mode === 'fullscreen' ? 1.7 : 1
  // A pantalla completa la franja útil puede ser baja (zonas de la interfaz social): las fichas
  // aprovechan más su celda para que las etiquetas sigan siendo legibles.
  const cell = spec.mode === 'fullscreen' ? { w: 0.86, h: 0.8 } : { w: 0.8, h: 0.62 }
  const nodeW = (s: { w: number }) => Math.min(s.w * cell.w, 300 * big * u)
  const nodeH = (s: { h: number }) => Math.min(s.h * cell.h, 190 * big * u)
  // Tamaño común de etiqueta: el mayor con el que todas caben en 3 líneas dentro de su nodo.
  const labelSize = Math.min(
    ...items.map((it, i) => {
      const w = nodeW(slots[i])
      const h = nodeH(slots[i])
      const room = h - (it.icon ? Math.min(h * 0.42, 70 * big * u) : 0)
      const f = fitLines(it.text ?? '', FH, w * 0.85, 52 * big * u, 16 * u, 3)
      return Math.min(f.size, room / (f.lines.length * 1.02))
    }),
    52 * big * u,
  )
  return (
    <Card spec={spec} r={R} card={spec.mode !== 'fullscreen'}>
      {links.map((l, i) => {
        const a = pos.get(l.from)
        const b = pos.get(l.to)
        if (!a || !b) return null
        const ang = Math.atan2(b.cy - a.cy, b.cx - a.cx)
        const ra = Math.min(nodeW(a), nodeH(a)) * 0.55
        const rb = Math.min(nodeW(b), nodeH(b)) * 0.6
        const x1 = a.cx + Math.cos(ang) * ra
        const y1 = a.cy + Math.sin(ang) * ra
        const x2 = b.cx - Math.cos(ang) * rb
        const y2 = b.cy - Math.sin(ang) * rb
        const paths = roughPaths('arrow', [x1, y1, x2, y2], { seed: spec.seed + 31 * i, stroke: pal.accent, strokeWidth: 3 * u, roughness: 1.3 })
        return <DrawPaths key={i} paths={paths} progress={p(frame, l.cue - spec.fps * 0.2, spec.fps * 0.5, EASE.out)} />
      })}
      {items.map((it, i) => {
        const s = slots[i]
        const w = nodeW(s)
        const h = nodeH(s)
        const k = appear(spec, frame, it.cue)
        const kind = shapeFor(it, i)
        const fill = it.role === 'primary' ? pal.highlight : undefined
        const outline = roughPaths(kind, kind === 'rect' ? [s.cx - w / 2, s.cy - h / 2, w, h] : [s.cx, s.cy, w, h], {
          seed: spec.seed + 7 * i + 1,
          stroke: ink(spec),
          strokeWidth: 2.6 * u,
          fill,
        })
        const label = it.text ?? ''
        const fs = labelSize
        const lines = breakText(label, FH, fs, w * 0.85)
        const iconSize = it.icon ? Math.min(h * 0.42, 70 * big * u) : 0
        const blockH = iconSize + lines.length * fs * 1.0
        const top = s.cy - blockH / 2
        return (
          <g key={it.id} style={{ transformOrigin: `${s.cx}px ${s.cy}px`, scale: String(0.85 + 0.15 * clamp01(k)) }} opacity={k > 0 ? 1 : 0}>
            <DrawPaths paths={outline} progress={p(frame, it.cue, spec.fps * 0.6, EASE.out)} />
            {it.icon && (
              <g transform={`translate(${s.cx - iconSize / 2}, ${top})`}>
                <Icon name={it.icon} size={iconSize} color={itemInk(spec, it, frame)} progress={p(frame, it.cue + 4, spec.fps * 0.7)} stroke={2} wobble={4} seed={spec.seed + i} />
              </g>
            )}
            {lines.map((ln, j) => (
              <HandText key={j} spec={spec} text={ln} x={s.cx} y={top + iconSize + fs * (j + 0.85)} size={fs} cue={it.cue + 6 + j * 4} color={itemInk(spec, it, frame)} />
            ))}
            {it.state === 'negated' && it.stateCue !== undefined && <Scribble spec={spec} x={s.cx - w * 0.4} y={s.cy} w={w * 0.8} h={h * 0.5} cue={it.stateCue} />}
          </g>
        )
      })}
    </Card>
  )
}

/**
 * Iconos en una franja baja y ancha (entre la interfaz de la red social y el rostro): fichas con
 * la mancha y el icono dibujado a la izquierda y el rótulo manuscrito al lado; con 4 o más, en
 * dos filas. Flechas de rotulador entre fichas de la misma fila.
 */
function IconsCompact({ spec, box, R }: { spec: AnimationSpec; box: Rect; R: Rect }) {
  const frame = useCurrentFrame()
  const u = unit(spec)
  const pal = spec.palette
  const items = visibleItems(spec.items)
  const n = Math.max(1, items.length)
  const rows = n >= 4 ? 2 : 1
  const cols = Math.ceil(n / rows)
  const slotW = box.w / cols
  const rowH = box.h / rows
  const size = Math.min(rowH * 0.62, slotW * 0.3)
  const labelW = slotW - size * 1.45 - 16 * u
  const labelSize = Math.min(...items.map((it) => fitLines(it.text ?? '', FH, labelW, Math.min(rowH * 0.36, 46 * u), 14 * u, 2).size))
  const cell = (i: number) => ({ col: i % cols, row: Math.floor(i / cols) })
  const cx = (i: number) => box.x + slotW * cell(i).col + size * 0.7
  const cy = (i: number) => box.y + rowH * (cell(i).row + 0.5)
  return (
    <Card spec={spec} r={R} card={spec.mode !== 'fullscreen'}>
      {items.slice(1).map((it, i) => {
        if (cell(i + 1).row !== cell(i).row) return null
        const x1 = box.x + slotW * (cell(i).col + 1) - 14 * u
        const x2 = cx(i + 1) - size * 0.7
        const paths = roughPaths('arrow', [x1 - 4 * u, cy(i), x2, cy(i)], { seed: spec.seed + 13 * i, stroke: pal.accent, strokeWidth: 3 * u })
        return <DrawPaths key={it.id} paths={paths} progress={p(frame, it.cue - spec.fps * 0.25, spec.fps * 0.45)} />
      })}
      {items.map((it, i) => {
        const pop = sp(frame, spec.fps, it.cue, { damping: 10, stiffness: 170 })
        const x = cx(i)
        const y = cy(i)
        const lines = breakText(it.text ?? '', FH, labelSize, labelW)
        const blob = roughPaths('circle', [x, y, size * 1.3], { seed: spec.seed + 5 * i, stroke: 'none', strokeWidth: 0, fill: it.role === 'primary' ? pal.highlight : pal.surface, roughness: 2, solid: true })
        const ty = y - ((lines.length - 1) * labelSize * 1.02) / 2 + labelSize * 0.32
        return (
          <g key={it.id} opacity={pop > 0.02 ? 1 : 0} style={{ transformOrigin: `${x}px ${y}px`, scale: String(0.5 + 0.5 * Math.min(1.08, pop)) }}>
            <DrawPaths paths={blob} progress={1} opacity={0.9} />
            <g transform={`translate(${x - size / 2}, ${y - size / 2})`}>
              <Icon name={it.icon ?? 'Lightbulb'} size={size} color={itemInk(spec, it, frame)} progress={p(frame, it.cue, spec.fps * 0.8)} stroke={1.8} wobble={5} seed={spec.seed + i} />
            </g>
            {lines.map((ln, j) => (
              <HandText key={j} spec={spec} text={ln} x={x + size * 0.8 + 6 * u} y={ty + j * labelSize * 1.02} size={labelSize} cue={it.cue + 8 + j * 4} color={ink(spec)} anchor="start" />
            ))}
            {it.state === 'negated' && it.stateCue !== undefined && <Scribble spec={spec} x={x - size * 0.6} y={y} w={size * 1.2} h={size} cue={it.stateCue} />}
          </g>
        )
      })}
    </Card>
  )
}

function Icons({ spec }: { spec: AnimationSpec }) {
  const frame = useCurrentFrame()
  const u = unit(spec)
  const R = px(spec, spec.region)
  const pal = spec.palette
  const items = visibleItems(spec.items)
  const box = insetP(R, 34 * u)
  if (items.length >= 3 && box.w / Math.max(1, box.h) > 3.2 && spec.arrangement !== 'column') {
    return <IconsCompact spec={spec} box={box} R={R} />
  }
  const slots = arrange(items.length, box, spec.arrangement === 'auto' ? (box.w > box.h ? 'row' : 'column') : spec.arrangement)
  const labelSize = Math.min(
    ...items.map((it, i) => fitLines(it.text ?? '', FH, slots[i].w * 0.94, 46 * u, 15 * u, 2).size),
    46 * u,
  )
  return (
    <Card spec={spec} r={R} card={spec.mode !== 'fullscreen'}>
      {items.slice(1).map((it, i) => {
        const a = slots[i]
        const b = slots[i + 1]
        const horiz = Math.abs(b.cx - a.cx) > Math.abs(b.cy - a.cy)
        const gap = horiz ? Math.min(a.w, b.w) * 0.32 : Math.min(a.h, b.h) * 0.32
        const x1 = horiz ? a.cx + gap : a.cx
        const y1 = horiz ? a.cy : a.cy + gap
        const x2 = horiz ? b.cx - gap : b.cx
        const y2 = horiz ? b.cy : b.cy - gap
        const paths = roughPaths('arrow', [x1, y1, x2, y2], { seed: spec.seed + 13 * i, stroke: pal.accent, strokeWidth: 3 * u })
        return <DrawPaths key={it.id} paths={paths} progress={p(frame, it.cue - spec.fps * 0.25, spec.fps * 0.45)} />
      })}
      {items.map((it, i) => {
        const s = slots[i]
        const label = it.text ?? ''
        const fs = labelSize
        const lines = breakText(label, FH, fs, s.w * 0.94)
        const size = Math.min(s.w * 0.5, (s.h - lines.length * fs * 1.05) * 0.62, 180 * u)
        const pop = sp(frame, spec.fps, it.cue, { damping: 10, stiffness: 170 })
        const blob = roughPaths('circle', [s.cx, s.cy - fs * 0.6, size * 1.35], { seed: spec.seed + 5 * i, stroke: 'none', strokeWidth: 0, fill: it.role === 'primary' ? pal.highlight : pal.surface, roughness: 2, solid: true })
        return (
          <g key={it.id} opacity={pop > 0.02 ? 1 : 0} style={{ transformOrigin: `${s.cx}px ${s.cy}px`, scale: String(0.5 + 0.5 * Math.min(1.08, pop)) }}>
            <DrawPaths paths={blob} progress={1} opacity={0.9} />
            <g transform={`translate(${s.cx - size / 2}, ${s.cy - fs * 0.6 - size / 2})`}>
              <Icon name={it.icon ?? 'Lightbulb'} size={size} color={itemInk(spec, it, frame)} progress={p(frame, it.cue, spec.fps * 0.8)} stroke={1.8} wobble={5} seed={spec.seed + i} />
            </g>
            {lines.map((ln, j) => (
              <HandText key={j} spec={spec} text={ln} x={s.cx} y={s.cy + size * 0.55 + fs * (0.4 + j * 1.02)} size={fs} cue={it.cue + 8 + j * 4} color={ink(spec)} />
            ))}
            {it.state === 'negated' && it.stateCue !== undefined && <Scribble spec={spec} x={s.cx - size * 0.6} y={s.cy - fs * 0.6} w={size * 1.2} h={size} cue={it.stateCue} />}
          </g>
        )
      })}
    </Card>
  )
}

function Character({ spec }: { spec: AnimationSpec }) {
  const frame = useCurrentFrame()
  const u = unit(spec)
  const R = px(spec, spec.region)
  const pal = spec.palette
  const box = insetP(R, 30 * u)
  const items = visibleItems(spec.items).filter((i) => i.text)
  const charW = Math.min(box.w * 0.34, box.h * 0.55)
  const cx = box.x + charW / 2
  const base = box.y + box.h
  const headR = charW * 0.24
  const headY = base - charW * 1.35
  const firstCue = items[0]?.cue ?? spec.entryFrames
  const wave = frame > firstCue ? Math.sin((frame - firstCue) / (spec.fps * 0.18)) * 18 * clamp01((frame - firstCue) / spec.fps) : 0
  const blink = Math.floor(frame / (spec.fps * 2.4)) !== Math.floor((frame + 4) / (spec.fps * 2.4)) ? 0.15 : 1
  const draw = p(frame, 0, spec.entryFrames + spec.fps * 0.5, EASE.out)
  const s1 = spec.seed
  const body = roughPaths('rect', [cx - charW * 0.28, headY + headR * 1.05, charW * 0.56, charW * 0.62], { seed: s1 + 1, stroke: ink(spec), strokeWidth: 3 * u, fill: pal.accent })
  const head = roughPaths('circle', [cx, headY, headR * 2], { seed: s1 + 2, stroke: ink(spec), strokeWidth: 3 * u, fill: pal.highlight })
  const armA = (-120 + wave) * (Math.PI / 180)
  const shoulderY = headY + headR * 1.4
  const arm1 = roughPaths('line', [cx + charW * 0.26, shoulderY, cx + charW * 0.26 + Math.cos(armA) * charW * 0.42, shoulderY + Math.sin(armA) * charW * 0.42], { seed: s1 + 3, stroke: ink(spec), strokeWidth: 4 * u })
  const arm2 = roughPaths('line', [cx - charW * 0.26, shoulderY, cx - charW * 0.4, shoulderY + charW * 0.38], { seed: s1 + 4, stroke: ink(spec), strokeWidth: 4 * u })
  const legs = [
    ...roughPaths('line', [cx - charW * 0.12, headY + headR * 1.05 + charW * 0.62, cx - charW * 0.16, base], { seed: s1 + 5, stroke: ink(spec), strokeWidth: 4 * u }),
    ...roughPaths('line', [cx + charW * 0.12, headY + headR * 1.05 + charW * 0.62, cx + charW * 0.16, base], { seed: s1 + 6, stroke: ink(spec), strokeWidth: 4 * u }),
  ]
  // Bocadillo con el contenido dicho.
  const bx = box.x + charW * 0.9
  const bw = box.x + box.w - bx
  const bh = Math.min(box.h * 0.8, 120 * u + items.length * 70 * u)
  const by = Math.max(box.y, headY - bh * 0.7)
  const bubble = roughPaths('ellipse', [bx + bw / 2, by + bh / 2, bw, bh], { seed: s1 + 7, stroke: ink(spec), strokeWidth: 2.6 * u, fill: '#FFFFFF', solid: true })
  const tail = roughPaths('line', [bx + bw * 0.12, by + bh * 0.78, cx + charW * 0.3, headY - headR * 0.2], { seed: s1 + 8, stroke: ink(spec), strokeWidth: 2.6 * u })
  const bubbleK = p(frame, firstCue - spec.fps * 0.3, spec.fps * 0.5, EASE.out)
  return (
    <Card spec={spec} r={R} card={spec.mode !== 'fullscreen'}>
      <DrawPaths paths={[...legs, ...body, ...arm2]} progress={draw} />
      <DrawPaths paths={arm1} progress={draw} />
      <DrawPaths paths={head} progress={draw} />
      <g opacity={draw}>
        <ellipse cx={cx - headR * 0.35} cy={headY - headR * 0.1} rx={headR * 0.09} ry={headR * 0.13 * blink} fill={ink(spec)} />
        <ellipse cx={cx + headR * 0.35} cy={headY - headR * 0.1} rx={headR * 0.09} ry={headR * 0.13 * blink} fill={ink(spec)} />
        <path d={`M ${cx - headR * 0.35} ${headY + headR * 0.35} Q ${cx} ${headY + headR * 0.65} ${cx + headR * 0.35} ${headY + headR * 0.35}`} stroke={ink(spec)} strokeWidth={3 * u} fill="none" strokeLinecap="round" />
      </g>
      <g opacity={bubbleK} style={{ transformOrigin: `${bx}px ${by + bh}px`, scale: String(0.7 + 0.3 * bubbleK) }}>
        <DrawPaths paths={[...bubble, ...tail]} progress={bubbleK} />
        {items.map((it, i) => {
          const lines = wrap(it.text ?? '', 18)
          const fs = Math.min(...lines.map((ln) => fitFont(ln, bw * 0.7, 46 * u, 0.46, 16 * u, FH)))
          const y0 = by + bh * 0.22 + i * (bh * 0.66) / Math.max(1, items.length) + fs
          return lines.map((ln, j) => <HandText key={`${it.id}-${j}`} spec={spec} text={ln} x={bx + bw / 2} y={y0 + j * fs * 1.0} size={fs} cue={it.cue + j * 5} color={itemInk(spec, it, frame)} />)
        })}
      </g>
    </Card>
  )
}

function Checklist({ spec }: { spec: AnimationSpec }) {
  const frame = useCurrentFrame()
  const u = unit(spec)
  const R = px(spec, spec.region)
  const pal = spec.palette
  const box = insetP(R, 36 * u)
  const items = visibleItems(spec.items).filter((i) => i.text)
  const titleH = spec.label ? 60 * u : 0
  const rowH = (box.h - titleH) / Math.max(1, items.length)
  return (
    <Card spec={spec} r={R}>
      {spec.label && <HandText spec={spec} text={spec.label} x={box.x} y={box.y + 44 * u} size={50 * u} cue={0} color={pal.accent} anchor="start" />}
      {items.map((it, i) => {
        const y = box.y + titleH + rowH * i + rowH / 2
        const bs = Math.min(rowH * 0.55, 54 * u)
        const boxP = roughPaths('rect', [box.x, y - bs / 2, bs, bs], { seed: spec.seed + i * 3, stroke: ink(spec), strokeWidth: 2.6 * u })
        const checkCue = it.state === 'done' && it.stateCue !== undefined ? it.stateCue : it.cue + spec.fps * 0.3
        const check = roughPaths('path', [], { seed: spec.seed + i * 3 + 1, stroke: pal.accent, strokeWidth: 5 * u, d: `M ${box.x + bs * 0.15} ${y} L ${box.x + bs * 0.42} ${y + bs * 0.32} L ${box.x + bs * 1.1} ${y - bs * 0.6}` })
        const fs = fitFont(it.text ?? '', box.w - bs * 2, Math.min(rowH * 0.62, 56 * u), 0.46, 16 * u, FH)
        const neg = it.state === 'negated'
        return (
          <g key={it.id} opacity={frame >= it.cue - 3 ? 1 : 0}>
            <DrawPaths paths={boxP} progress={p(frame, it.cue - 3, spec.fps * 0.35)} />
            {!neg && <DrawPaths paths={check} progress={p(frame, checkCue, spec.fps * 0.35)} />}
            <HandText spec={spec} text={it.text ?? ''} x={box.x + bs * 1.6} y={y + fs * 0.32} size={fs} cue={it.cue} color={itemInk(spec, it, frame)} anchor="start" />
            {neg && it.stateCue !== undefined && <Scribble spec={spec} x={box.x + bs * 1.5} y={y} w={Math.min(box.w - bs * 2, measure(it.text ?? '', FH, fs))} h={fs * 0.6} cue={it.stateCue} />}
          </g>
        )
      })}
    </Card>
  )
}

function Highlight({ spec }: { spec: AnimationSpec }) {
  const frame = useCurrentFrame()
  const u = unit(spec)
  const pal = spec.palette
  const t = spec.target ?? { ...spec.region, cue: 0 }
  const T = px(spec, t)
  const { inP, outP } = envelope(spec, frame)
  const ring = roughPaths('ellipse', [T.x + T.w / 2, T.y + T.h / 2, T.w * 1.25, T.h * 1.45], { seed: spec.seed, stroke: pal.accent, strokeWidth: 5 * u, roughness: 1.6 })
  const label = headline(spec)
  const below = T.y + T.h + 140 * u < spec.height * 0.92
  const ly = below ? T.y + T.h * 1.25 + 90 * u : T.y - T.h * 0.25 - 50 * u
  const lx = Math.min(Math.max(T.x + T.w / 2, 160 * u), spec.width - 160 * u)
  const arrow = roughPaths('arrow', [lx, below ? ly - 50 * u : ly + 16 * u, T.x + T.w / 2, below ? T.y + T.h * 1.2 : T.y - T.h * 0.2], { seed: spec.seed + 1, stroke: pal.accent, strokeWidth: 3.5 * u })
  return (
    <g opacity={inP * (1 - outP)}>
      <DrawPaths paths={ring} progress={p(frame, t.cue, spec.fps * 0.6, EASE.out)} />
      <DrawPaths paths={arrow} progress={p(frame, t.cue + spec.fps * 0.35, spec.fps * 0.4)} />
      <g style={{ paintOrder: 'stroke' }}>
        <HandText spec={spec} text={label} x={lx} y={ly} size={52 * u} cue={t.cue + spec.fps * 0.5} color={pal.accent} />
      </g>
    </g>
  )
}

function Transition({ spec }: { spec: AnimationSpec }) {
  const frame = useCurrentFrame()
  const u = unit(spec)
  const pal = spec.palette
  const d = spec.durationInFrames
  const W = spec.width
  const H = spec.height
  const a = p(frame, 0, d * 0.5, EASE.inOut)
  const b = p(frame, d * 0.5, d * 0.5, EASE.inOut)
  const x = -W * 1.1 + a * W * 1.1 + b * W * 1.15
  const sweep = roughPaths('path', [], { seed: spec.seed, stroke: pal.accent, strokeWidth: 60 * u, d: `M ${-W * 0.1} ${H * 0.55} C ${W * 0.3} ${H * 0.35}, ${W * 0.6} ${H * 0.7}, ${W * 1.1} ${H * 0.45}`, roughness: 2.5 })
  return (
    <g>
      <g style={{ translate: `${x}px 0px`, rotate: '-4deg', transformOrigin: `${W / 2}px ${H / 2}px` }}>
        <rect x={-W * 0.05} y={-H * 0.1} width={W * 1.1} height={H * 1.2} fill={pal.bg} />
        <PaperTexture w={W} h={H} seed={spec.seed} color={pal.bg} />
      </g>
      <DrawPaths paths={sweep} progress={clamp01(a * 1.2) * (1 - b)} opacity={0.85} />
    </g>
  )
}

export function ExplainerBackground({ spec }: { spec: AnimationSpec }) {
  const frame = useCurrentFrame()
  const u = unit(spec)
  const W = spec.width
  const H = spec.height
  const frameP = roughPaths('rect', [30 * u, 30 * u, W - 60 * u, H - 60 * u], { seed: spec.seed + 99, stroke: spec.palette.text, strokeWidth: 3 * u, roughness: 1.2 })
  return (
    <g>
      <PaperTexture w={W} h={H} seed={spec.seed} color={spec.palette.bg} />
      <DrawPaths paths={frameP} progress={p(frame, 0, spec.fps * 0.8)} opacity={0.5} />
    </g>
  )
}

export function ExplainerPipFrame({ spec }: { spec: AnimationSpec }) {
  const frame = useCurrentFrame()
  const u = unit(spec)
  if (!spec.pip) return null
  const P = px(spec, spec.pip)
  const ring =
    spec.pip.shape === 'circle'
      ? roughPaths('ellipse', [P.x + P.w / 2, P.y + P.h / 2, P.w * 1.06, P.h * 1.06], { seed: spec.seed + 50, stroke: spec.palette.text, strokeWidth: 4 * u })
      : roughPaths('rect', [P.x - 8 * u, P.y - 8 * u, P.w + 16 * u, P.h + 16 * u], { seed: spec.seed + 50, stroke: spec.palette.text, strokeWidth: 4 * u })
  return <DrawPaths paths={ring} progress={p(frame, spec.entryFrames, spec.fps * 0.6)} />
}

export const EXPLAINER: Record<string, React.FC<{ spec: AnimationSpec }>> = {
  'exp.sketch': Sketch,
  'exp.icons': Icons,
  'exp.character': Character,
  'exp.checklist': Checklist,
  'exp.highlight': Highlight,
  'exp.transition': Transition,
}

export { HandText, ROUND }
