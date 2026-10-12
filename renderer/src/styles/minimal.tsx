import React from 'react'
import { useCurrentFrame } from 'remotion'
import type { AnimationSpec, Item } from '../spec'
import { Stroke } from '../lib/draw'
import { arrange, headline, inset, visibleItems, type Rect, insetP } from '../lib/layout'
import { EASE, appear, clamp01, entryStart, envelope, fitFont, lerpRect, p, px, unit, wrap } from '../lib/motion'
import { measure } from '../lib/measure'
import { breakText, fitBlock, fitLines } from '../lib/textfit'

const F = (weight: number) => ({ family: 'VSA Inter', weight })

/**
 * MINIMAL MOTION — gramática: tipografía protagonista y espacio negativo. Una idea por plano,
 * palabras que emergen de una máscara al ser dichas, contraste de pesos, reglas finas que se
 * trazan. Movimiento suave (ease-in-out / muelle sutil), nada brilla ni vibra.
 */

const SANS = 'VSA Inter'

function ease(spec: AnimationSpec) {
  return spec.easing === 'spring' ? EASE.out : EASE.smooth
}

/**
 * Placa de Minimal Motion (Fase 4.1). Entrada editorial: una línea fina se traza, la placa se
 * abre desde ella y las palabras emergen de la máscara. Salida: las palabras suben y salen por
 * la máscara, la placa se cierra sobre la línea y la línea se recoge. Continuidad: si la
 * animación anterior seguía en pantalla, la placa se transforma desde su región; si la
 * siguiente la continúa, la placa se queda y solo cambia el texto.
 */
function Plate({ spec, r: R, children, plate = true }: { spec: AnimationSpec; r: Rect; children: React.ReactNode; plate?: boolean }) {
  const frame = useCurrentFrame()
  const u = unit(spec)
  const pal = spec.palette
  const E = Math.max(8, spec.entryFrames)
  const X = Math.max(8, spec.exitFrames)
  const D = spec.durationInFrames
  const s0 = entryStart(spec, true)
  const chainIn = spec.chainIn ? px(spec, spec.chainIn) : null
  const chainOut = Boolean(spec.chainOut)
  const morph = chainIn ? p(frame, 0, E, EASE.inOut) : 1
  const line = chainIn || !plate ? 1 : p(frame, s0, E * 0.45, EASE.smooth)
  const open = chainIn || !plate ? 1 : p(frame, s0 + E * 0.3, E * 0.7, EASE.smooth)
  // Salida escalonada: primero sale el texto, luego se cierra la placa y al final se recoge la línea.
  const textOut = p(frame, D - X, X * (chainOut || !plate ? 1 : 0.45), EASE.in)
  const close = chainOut || !plate ? 0 : p(frame, D - X * 0.6, X * 0.42, EASE.inOut)
  const retract = chainOut || !plate ? 0 : p(frame, D - X * 0.25, X * 0.25, EASE.in)
  const r = chainIn ? lerpRect(chainIn, R, morph) : R
  const cy = r.y + r.h / 2
  const h = r.h * open * (1 - close)
  const id = `mclip-${spec.id}`
  const lineX0 = r.x + r.w * retract
  const lineW = r.w * line * (1 - retract)
  if (plate && retract >= 0.999) return null
  return (
    <g>
      <defs>
        <clipPath id={id}>
          {plate ? (
            <rect x={r.x} y={cy - h / 2} width={r.w} height={Math.max(0.5, h)} rx={Math.min(26 * u, h / 2)} />
          ) : (
            <rect x={0} y={0} width={spec.width} height={spec.height} />
          )}
        </clipPath>
      </defs>
      {plate && <rect x={r.x} y={cy - h / 2} width={r.w} height={Math.max(0, h)} rx={Math.min(26 * u, h / 2)} fill={pal.surface} opacity={0.86} />}
      <g clipPath={`url(#${id})`}>
        <g style={{ translate: `0px ${-textOut * 36 * u}px` }} opacity={1 - textOut}>
          {children}
        </g>
      </g>
      {plate && (open < 1 || close > 0) && lineW > 0.5 && (
        <rect x={lineX0} y={cy - 1 * u} width={lineW} height={2 * u} fill={pal.accent} />
      )}
    </g>
  )
}

/** Palabras que suben desde detrás de una máscara (una por cue). */
function MaskLine({
  spec,
  words,
  x,
  y,
  size,
  weight,
  color,
  anchor = 'start',
  tracking = 0,
}: {
  spec: AnimationSpec
  words: { text: string; cue: number }[]
  x: number
  y: number
  size: number
  weight: number
  color: string
  anchor?: 'start' | 'middle'
  tracking?: number
}) {
  const frame = useCurrentFrame()
  const u = unit(spec)
  const space = measure(' ', F(weight), size)
  const widths = words.map((w) => measure(w.text, F(weight), size, tracking * unit(spec)) + space)
  const total = widths.reduce((a, b) => a + b, 0) - space
  let cx = anchor === 'middle' ? x - total / 2 : x
  const id = `ml-${spec.id}-${Math.round(y)}`
  return (
    <g>
      <defs>
        <clipPath id={id}>
          <rect x={0} y={y - size * 1.08} width={spec.width} height={size * 1.5} />
        </clipPath>
      </defs>
      <g clipPath={`url(#${id})`}>
        {words.map((w, i) => {
          const k = p(frame, w.cue, spec.fps * 0.55, ease(spec))
          const node = (
            <text key={i} x={cx} y={y + (1 - k) * size * 1.1} fontFamily={SANS} fontWeight={weight} fontSize={size} fill={color} letterSpacing={tracking * u} opacity={k > 0 ? 1 : 0}>
              {w.text}
            </text>
          )
          cx += widths[i]
          return node
        })}
      </g>
    </g>
  )
}

/** Reparte los cues de un texto por palabras a partir del cue de su elemento. */
function wordsOf(spec: AnimationSpec, text: string, cue: number) {
  const step = Math.round(spec.fps * 0.09)
  return text.split(/\s+/).filter(Boolean).map((t, i) => ({ text: t, cue: cue + i * step }))
}

function itemColor(spec: AnimationSpec, it: Item, frame: number) {
  const on = it.stateCue !== undefined && frame >= it.stateCue
  if (it.state === 'negated' && on) return spec.palette.muted
  if ((it.state === 'highlight' || it.role === 'primary') && (on || it.state !== 'highlight')) return it.role === 'primary' ? spec.palette.accent : spec.palette.highlight
  return spec.palette.text
}

// ---------------------------------------------------------------------------

/** Rótulo superior: la etiqueta, o el título si no repite lo que ya dicen los elementos. */
function eyebrowOf(spec: AnimationSpec, items: Item[]) {
  if (spec.label) return spec.label
  const t = (spec.title ?? '').toLowerCase().trim()
  if (!t || items.some((i) => (i.text ?? '').toLowerCase().includes(t))) return null
  return spec.title ?? null
}

interface Group {
  items: Item[]
  text: string
  words: { text: string; cue: number }[]
  primary: boolean
}

/** Agrupa palabras clave secundarias cortas y seguidas en una sola línea («A · B · C»). */
function groupsOf(spec: AnimationSpec, items: Item[]): Group[] {
  const anyPrimary = items.some((i) => i.role === 'primary')
  const short = (it: Item) => it.role !== 'primary' && it.state === 'normal' && (it.text ?? '').split(/\s+/).length <= 2 && (it.text ?? '').length <= 18
  const out: Group[] = []
  for (const it of items) {
    const primary = it.role === 'primary' || !anyPrimary
    const last = out[out.length - 1]
    const words = wordsOf(spec, it.text ?? '', it.cue)
    if (last && !primary && !last.primary && short(it) && last.items.every(short)) {
      last.items.push(it)
      last.text += ` · ${it.text}`
      last.words.push({ text: '·', cue: it.cue }, ...words)
    } else out.push({ items: [it], text: it.text ?? '', words, primary })
  }
  return out
}

function Statement({ spec }: { spec: AnimationSpec }) {
  const frame = useCurrentFrame()
  const u = unit(spec)
  const R = px(spec, spec.region)
  const pal = spec.palette
  const full = spec.mode === 'fullscreen'
  const box = inset(R, (full ? 64 : 40) * u)
  const items = visibleItems(spec.items).filter((i) => i.text)
  const eyebrow = eyebrowOf(spec, items)
  const labelH = eyebrow ? 44 * u : 0
  const avail = box.h - labelH
  const groups = groupsOf(spec, items)
  const paras = groups.map((g) => ({ text: g.text, font: F(g.primary ? 800 : 400), scale: g.primary ? 1 : 0.62 }))
  const fit = fitBlock(paras, box.w, avail, (full ? 170 : 120) * u, 22 * u)
  const center = spec.params.whitespace === 'airy' && box.w < spec.width * 0.7
  const anchor = center ? 'middle' : 'start'
  const x = center ? box.x + box.w / 2 : box.x
  let top = box.y + labelH + Math.max(0, (avail - fit.height) / 2)
  const rows: { g: Group; text: string; words: { text: string; cue: number }[]; size: number; y: number }[] = []
  fit.out.forEach((o, k) => {
    if (k) top += o.size * 0.28
    let w0 = 0
    for (const text of o.lines) {
      const n = text.split(/\s+/).filter(Boolean).length
      rows.push({ g: groups[k], text, words: groups[k].words.slice(w0, w0 + n), size: o.size, y: top + o.size * 0.92 })
      w0 += n
      top += o.size * 1.16
    }
  })
  return (
    <Plate spec={spec} r={R} plate={!full}>
      {eyebrow && (
        <text x={x} y={box.y + 22 * u} textAnchor={anchor} fontFamily={SANS} fontWeight={600} fontSize={22 * u} letterSpacing={5 * u} fill={pal.muted} opacity={p(frame, 0, spec.fps * 0.6, EASE.smooth)}>
          {eyebrow.toUpperCase()}
        </text>
      )}
      {!full && rows.length > 0 && (
        // Regla editorial: crece al aparecer el primer concepto y acompaña al bloque de texto.
        <rect x={box.x - 18 * u} y={rows[0].y - rows[0].size} width={3 * u} height={(rows[rows.length - 1].y - rows[0].y + rows[0].size * 1.1) * p(frame, Math.min(...items.map((it) => it.cue)), spec.fps * 0.8, EASE.smooth)} fill={pal.accent} opacity={0.85} />
      )}
      {rows.map((l, i) => {
        const s = l.size
        const it = l.g.items[0]
        const color = itemColor(spec, it, frame)
        const lineW = Math.min(box.w, measure(l.text, F(l.g.primary ? 800 : 400), s, l.g.primary ? -1.5 * u : 0))
        const neg = it.state === 'negated' && it.stateCue !== undefined
        const ux = center ? x - lineW / 2 : x
        const hl = it.state === 'highlight' && it.stateCue !== undefined ? p(frame, it.stateCue, spec.fps * 0.45, EASE.smooth) : 0
        return (
          <g key={i}>
            {hl > 0 && <rect x={ux - 6 * u} y={l.y - s * 0.42} width={(lineW + 12 * u) * hl} height={s * 0.5} fill={pal.accent} opacity={0.28} />}
            <MaskLine spec={spec} words={l.words} x={x} y={l.y} size={s} weight={l.g.primary ? 800 : 400} color={color} anchor={anchor} tracking={l.g.primary ? -1.5 : 0} />
            {l.g.primary && it.role === 'primary' && <Stroke d={`M ${ux} ${l.y + s * 0.22} L ${ux + lineW} ${l.y + s * 0.22}`} progress={p(frame, it.cue + spec.fps * 0.35, spec.fps * 0.7, EASE.smooth)} color={pal.accent} width={3 * u} cap="butt" />}
            {neg && <Stroke d={`M ${ux} ${l.y - s * 0.32} L ${ux + lineW} ${l.y - s * 0.32}`} progress={p(frame, it.stateCue!, spec.fps * 0.5, EASE.smooth)} color={pal.secondary} width={2.5 * u} cap="butt" />}
          </g>
        )
      })}
    </Plate>
  )
}

const NUM_W = 58

function List({ spec }: { spec: AnimationSpec }) {
  const frame = useCurrentFrame()
  const u = unit(spec)
  const R = px(spec, spec.region)
  const pal = spec.palette
  const box = insetP(R, 40 * u)
  const items = visibleItems(spec.items).filter((i) => i.text)
  const eyebrow = eyebrowOf(spec, items)
  const top = box.y + (eyebrow ? 48 * u : 0)
  const availH = box.y + box.h - top
  const n = Math.max(1, items.length)
  const gapX = 36 * u
  // Columnas: las que permitan el texto más grande (una lista corta en una placa ancha va en rejilla).
  let best = { cols: 1, size: 0 }
  for (let cols = 1; cols <= Math.min(3, n); cols++) {
    const rows = Math.ceil(n / cols)
    const cellW = (box.w - gapX * (cols - 1)) / cols
    const rowH = availH / rows
    const base = Math.min(rowH * 0.6, 100 * u)
    const size = Math.min(
      ...items.map((it) => {
        const f = fitLines(it.text ?? '', F(it.role === 'primary' ? 700 : 500), cellW - NUM_W * u, base, 14 * u, 2)
        return f.lines.length > 1 ? Math.min(f.size, (rowH * 0.86) / (f.lines.length * 1.12)) : f.size
      }),
    )
    if (size > best.size * 1.08) best = { cols, size }
  }
  const { cols } = best
  const fs = best.size
  const rows = Math.ceil(n / cols)
  const cellW = (box.w - gapX * (cols - 1)) / cols
  const rowH = availH / rows
  const numW = NUM_W * u
  return (
    <Plate spec={spec} r={R} plate={spec.mode !== 'fullscreen'}>
      {eyebrow && (
        <text x={box.x} y={box.y + 24 * u} fontFamily={SANS} fontWeight={600} fontSize={22 * u} letterSpacing={5 * u} fill={pal.muted}>
          {eyebrow.toUpperCase()}
        </text>
      )}
      {items.map((it, i) => {
        const cx = box.x + (i % cols) * (cellW + gapX)
        const y = top + rowH * Math.floor(i / cols)
        const k = appear(spec, frame, it.cue)
        const color = itemColor(spec, it, frame)
        const weight = it.role === 'primary' ? 700 : 500
        const lines = breakText(it.text ?? '', F(weight), fs, cellW - numW)
        const base = y + rowH / 2 + fs * 0.36 - ((lines.length - 1) * fs * 1.12) / 2
        return (
          <g key={it.id} opacity={clamp01(k)} style={{ translate: `${(1 - clamp01(k)) * 24 * u}px 0px` }}>
            <Stroke d={`M ${cx} ${y + 2 * u} L ${cx + cellW} ${y + 2 * u}`} progress={p(frame, it.cue - 4, spec.fps * 0.6, EASE.smooth)} color={pal.muted} width={1.2 * u} opacity={0.6} />
            <text x={cx} y={base} fontFamily={SANS} fontWeight={500} fontSize={Math.min(fs * 0.45, 26 * u)} fill={pal.muted} letterSpacing={2 * u}>
              {String(i + 1).padStart(2, '0')}
            </text>
            {lines.map((line, li) => (
              <text key={li} x={cx + numW} y={base + li * fs * 1.12} fontFamily={SANS} fontWeight={weight} fontSize={fs} fill={color}>
                {line}
              </text>
            ))}
            {it.state === 'negated' && it.stateCue !== undefined && lines.map((line, li) => (
              <Stroke key={`n${li}`} d={`M ${cx + numW} ${base + li * fs * 1.12 - fs * 0.32} l ${measure(line, F(weight), fs)} 0`} progress={p(frame, it.stateCue!, spec.fps * 0.5, EASE.smooth)} color={pal.secondary} width={2 * u} cap="butt" />
            ))}
          </g>
        )
      })}
    </Plate>
  )
}

function Compare({ spec }: { spec: AnimationSpec }) {
  const frame = useCurrentFrame()
  const u = unit(spec)
  const R = px(spec, spec.region)
  const pal = spec.palette
  const box = insetP(R, 40 * u)
  const items = visibleItems(spec.items).filter((i) => i.text).slice(0, 2)
  const vertical = box.h > box.w * 1.15
  const firstCue = items[0]?.cue ?? 0
  return (
    <Plate spec={spec} r={R} plate={spec.mode !== 'fullscreen'}>
      {vertical ? (
        <Stroke d={`M ${box.x} ${box.y + box.h / 2} l ${box.w} 0`} progress={p(frame, firstCue, spec.fps * 0.8, EASE.smooth)} color={pal.muted} width={1.2 * u} />
      ) : (
        <Stroke d={`M ${box.x + box.w / 2} ${box.y} l 0 ${box.h}`} progress={p(frame, firstCue, spec.fps * 0.8, EASE.smooth)} color={pal.muted} width={1.2 * u} />
      )}
      {items.map((it, i) => {
        const cell: Rect = vertical
          ? { x: box.x, y: box.y + (box.h / 2) * i, w: box.w, h: box.h / 2 }
          : { x: box.x + (box.w / 2) * i, y: box.y, w: box.w / 2, h: box.h }
        const lines = wrap(it.text ?? '', 14)
        const fs = Math.min(...lines.map((l) => fitFont(l, cell.w - 40 * u, Math.min(cell.h / (lines.length + 1), 76 * u), 0.55, 16 * u, F(800))))
        const color = itemColor(spec, it, frame)
        const neg = it.state === 'negated' && it.stateCue !== undefined && frame >= it.stateCue
        const cx = cell.x + cell.w / 2
        const y0 = cell.y + cell.h / 2 - (lines.length * fs * 1.15) / 2 + fs
        return (
          <g key={it.id} opacity={neg ? 0.55 : 1}>
            {it.sub && (
              <text x={cx} y={y0 - fs * 1.1} textAnchor="middle" fontFamily={SANS} fontWeight={600} fontSize={16 * u} letterSpacing={4 * u} fill={pal.muted} opacity={p(frame, it.cue, spec.fps * 0.5)}>
                {it.sub.toUpperCase()}
              </text>
            )}
            {lines.map((l, j) => (
              <MaskLine key={j} spec={spec} words={wordsOf(spec, l, it.cue + j * 3)} x={cx} y={y0 + j * fs * 1.15} size={fs} weight={it.role === 'primary' ? 800 : 500} color={color} anchor="middle" />
            ))}
            {it.state === 'negated' && it.stateCue !== undefined && (
              <Stroke d={`M ${cx - cell.w * 0.32} ${y0 + ((lines.length - 1) * fs * 1.15) / 2 - fs * 0.3} l ${cell.w * 0.64} 0`} progress={p(frame, it.stateCue, spec.fps * 0.5, EASE.smooth)} color={pal.secondary} width={2.5 * u} cap="butt" />
            )}
          </g>
        )
      })}
    </Plate>
  )
}

function NumberBig({ spec }: { spec: AnimationSpec }) {
  const frame = useCurrentFrame()
  const u = unit(spec)
  const R = px(spec, spec.region)
  const pal = spec.palette
  const box = insetP(R, 36 * u)
  const n = spec.number ?? { from: 0, to: 100, cue: 0, duration: spec.fps, label: headline(spec) }
  const k = p(frame, n.cue, Math.max(1, n.duration), EASE.smooth)
  const txt = `${n.prefix ?? ''}${Math.round(n.from + (n.to - n.from) * k)}${n.suffix ?? ''}`
  const r = Math.min(box.w, box.h) * 0.42
  const cx = box.x + box.w / 2
  const cy = box.y + box.h / 2 - 10 * u
  const fs = fitFont(txt, r * 1.5, r * 0.75, 0.55, 12, F(250))
  return (
    <Plate spec={spec} r={R} plate={spec.mode !== 'fullscreen'}>
      <circle cx={cx} cy={cy} r={r} fill="none" stroke={pal.muted} strokeWidth={1.2 * u} opacity={0.35} />
      <Stroke d={`M ${cx} ${cy - r} A ${r} ${r} 0 1 1 ${cx - 0.01} ${cy - r}`} progress={k * 0.999} color={pal.accent} width={3 * u} />
      <text x={cx} y={cy + fs * 0.35} textAnchor="middle" fontFamily={SANS} fontWeight={250} fontSize={fs} fill={pal.text} letterSpacing={-2 * u}>
        {txt}
      </text>
      {n.label && (
        <text x={cx} y={cy + r + 40 * u} textAnchor="middle" fontFamily={SANS} fontWeight={600} fontSize={20 * u} letterSpacing={4 * u} fill={pal.muted} opacity={p(frame, n.cue + spec.fps * 0.3, spec.fps * 0.6)}>
          {n.label.toUpperCase()}
        </text>
      )}
    </Plate>
  )
}

function Steps({ spec }: { spec: AnimationSpec }) {
  const frame = useCurrentFrame()
  const u = unit(spec)
  const R = px(spec, spec.region)
  const pal = spec.palette
  const box = insetP(R, 40 * u)
  const items = visibleItems(spec.items).filter((i) => i.text)
  const vertical = box.h > box.w * 1.15
  const slots = arrange(items.length, box, vertical ? 'column' : 'row')
  const labels = items.map((it, i) =>
    fitLines(it.text ?? '', F(700), vertical ? box.w - 80 * u : slots[i].w * 0.9, Math.min(56 * u, (vertical ? slots[i].h * 0.4 : box.h * 0.3)), 14 * u, 2),
  )
  const fs = Math.min(...labels.map((l) => l.size))
  const maxLines = Math.max(1, ...labels.map((l) => l.lines.length))
  const blockH = 18 * u + 30 * u + maxLines * fs * 1.15
  const lineY = vertical ? 0 : box.y + Math.max(9 * u, (box.h - blockH) / 2 + 9 * u)
  const lineX = vertical ? box.x + 30 * u : 0
  const first = slots[0]
  const last = slots[slots.length - 1]
  return (
    <Plate spec={spec} r={R} plate={spec.mode !== 'fullscreen'}>
      {first && last && (
        <Stroke
          d={vertical ? `M ${lineX} ${first.cy} L ${lineX} ${last.cy}` : `M ${first.cx} ${lineY} L ${last.cx} ${lineY}`}
          progress={p(frame, items[0].cue, Math.max(1, (items[items.length - 1].cue - items[0].cue) + spec.fps * 0.4), EASE.smooth)}
          color={pal.muted}
          width={1.5 * u}
        />
      )}
      {items.map((it, i) => {
        const s = slots[i]
        const k = appear(spec, frame, it.cue)
        const dx = vertical ? lineX : s.cx
        const dy = vertical ? s.cy : lineY
        const lines = breakText(it.text ?? '', F(700), fs, vertical ? box.w - 80 * u : s.w * 0.9)
        const y0 = vertical ? dy + fs * 0.35 - ((lines.length - 1) * fs * 1.15) / 2 : dy + 30 * u + fs
        return (
          <g key={it.id}>
            <circle cx={dx} cy={dy} r={9 * u} fill={frame >= it.cue ? pal.accent : pal.surface} stroke={pal.accent} strokeWidth={2 * u} style={{ scale: String(0.6 + 0.4 * clamp01(k)), transformOrigin: `${dx}px ${dy}px` }} />
            <g opacity={clamp01(k)} style={{ translate: `0px ${(1 - clamp01(k)) * 12 * u}px` }}>
              {lines.map((line, li) => (
                <text key={li} x={vertical ? dx + 34 * u : dx} y={y0 + li * fs * 1.15} textAnchor={vertical ? 'start' : 'middle'} fontFamily={SANS} fontWeight={it.role === 'primary' ? 700 : 500} fontSize={fs} fill={itemColor(spec, it, frame)}>
                  {line}
                </text>
              ))}
            </g>
          </g>
        )
      })}
    </Plate>
  )
}

function Highlight({ spec }: { spec: AnimationSpec }) {
  const frame = useCurrentFrame()
  const u = unit(spec)
  const pal = spec.palette
  const t = spec.target ?? { ...spec.region, cue: 0 }
  const T = px(spec, t)
  const { inP, outP } = envelope(spec, frame)
  const k = p(frame, t.cue, spec.fps * 0.7, EASE.smooth)
  const label = headline(spec)
  const below = T.y + T.h + 80 * u < spec.height * 0.9
  const pad = 10 * u
  const rr = 18 * u
  const x = T.x - pad
  const y = T.y - pad
  const w = T.w + pad * 2
  const h = T.h + pad * 2
  const d = `M ${x + rr} ${y} H ${x + w - rr} Q ${x + w} ${y} ${x + w} ${y + rr} V ${y + h - rr} Q ${x + w} ${y + h} ${x + w - rr} ${y + h} H ${x + rr} Q ${x} ${y + h} ${x} ${y + h - rr} V ${y + rr} Q ${x} ${y} ${x + rr} ${y} Z`
  return (
    <g opacity={inP * (1 - outP)}>
      <Stroke d={d} progress={k} color={pal.accent} width={2.5 * u} />
      <text x={x} y={below ? y + h + 40 * u : y - 18 * u} fontFamily={SANS} fontWeight={600} fontSize={24 * u} fill={pal.text} opacity={p(frame, t.cue + spec.fps * 0.4, spec.fps * 0.5)} style={{ paintOrder: 'stroke', stroke: 'rgba(0,0,0,0.55)', strokeWidth: 6 * u }}>
        {label}
      </text>
    </g>
  )
}

/**
 * Transición Minimal (Fase 4.1): franjas horizontales que cruzan el encuadre escalonadas, en
 * un solo sentido (entran por la izquierda, cubren y salen por la derecha) con una regla de
 * acento en el borde de avance. Movimiento continuo y suave, sin fundidos.
 */
function Transition({ spec }: { spec: AnimationSpec }) {
  const frame = useCurrentFrame()
  const u = unit(spec)
  const pal = spec.palette
  const W = spec.width
  const H = spec.height
  const d = spec.durationInFrames
  if (spec.params.transition === 'fade') {
    const a = p(frame, 0, d / 2, EASE.inOut)
    const b = p(frame, d / 2, d / 2, EASE.inOut)
    return <rect width={W} height={H} fill={pal.bg} opacity={Math.min(a, 1 - b)} />
  }
  const n = 7
  const bh = H / n
  return (
    <g>
      {Array.from({ length: n }, (_, i) => {
        const delay = (Math.abs(i - (n - 1) / 2) / n) * d * 0.28
        const a = p(frame, delay, d * 0.42, EASE.inOut)
        const b = p(frame, d * 0.5 + delay, d * 0.42, EASE.inOut)
        const x = (a - 1) * W + b * W
        return (
          <g key={i}>
            <rect x={x} y={bh * i - 0.5} width={W} height={bh + 1} fill={i % 2 ? pal.surface : pal.bg} />
            <rect x={x + (b > 0 ? 0 : W - 3 * u)} y={bh * i} width={3 * u} height={bh} fill={pal.accent} opacity={a > 0 && b < 1 ? 0.9 : 0} />
          </g>
        )
      })}
    </g>
  )
}

export function MinimalBackground({ spec }: { spec: AnimationSpec }) {
  const pal = spec.palette
  return (
    <g>
      <defs>
        <linearGradient id="mbg" x1="0" y1="0" x2="0" y2="1">
          <stop offset="0" stopColor={pal.bg} />
          <stop offset="1" stopColor={pal.surface} />
        </linearGradient>
      </defs>
      <rect width={spec.width} height={spec.height} fill="url(#mbg)" />
    </g>
  )
}

export function MinimalPipFrame({ spec }: { spec: AnimationSpec }) {
  const frame = useCurrentFrame()
  const u = unit(spec)
  if (!spec.pip) return null
  const P = px(spec, spec.pip)
  const k = p(frame, spec.entryFrames, spec.fps * 0.6, EASE.smooth)
  return <rect x={P.x - 6 * u} y={P.y - 6 * u} width={P.w + 12 * u} height={P.h + 12 * u} rx={spec.pip.shape === 'circle' ? P.w : 24 * u} fill="none" stroke={spec.palette.accent} strokeWidth={2 * u} opacity={k} />
}

export const MINIMAL: Record<string, React.FC<{ spec: AnimationSpec }>> = {
  'min.statement': Statement,
  'min.list': List,
  'min.compare': Compare,
  'min.number': NumberBig,
  'min.steps': Steps,
  'min.highlight': Highlight,
  'min.transition': Transition,
}
