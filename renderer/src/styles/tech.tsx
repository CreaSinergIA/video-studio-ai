import React from 'react'
import { useCurrentFrame } from 'remotion'
import type { AnimationSpec, Item } from '../spec'
import { Grid, Icon, Particles, Stroke, scramble, typed } from '../lib/draw'
import { arrange, headline, inset, visibleItems, type Rect, insetP } from '../lib/layout'
import { EASE, appear, clamp01, envelope, fitFont, lerpRect, p, px, sp, unit } from '../lib/motion'
import { measure } from '../lib/measure'
import { breakText, fitLines } from '../lib/textfit'

const F_DISPLAY = { family: 'VSA Montserrat', weight: 800 }
const F_MONO = { family: 'VSA Mono', weight: 600 }

/**
 * MOTION TECH — gramática: retícula modular, paneles HUD con esquinas en corchete, datos en
 * monoespaciada que se descodifican, nodos que se activan y conectores con paquetes de datos.
 * Movimiento preciso con easing exponencial; aperturas por escaneo; acentos con glitch.
 */

const MONO = 'VSA Mono'
const DISPLAY = 'VSA Montserrat'

function glow(color: string, r: number) {
  return `drop-shadow(0 0 ${r}px ${color})`
}

/** Esquinas tipo HUD que encajan desde fuera. */
function Brackets({ r, color, k, size, width }: { r: Rect; color: string; k: number; size: number; width: number }) {
  const off = (1 - k) * size * 1.6
  const s = size
  const c = [
    `M ${r.x - off} ${r.y - off + s} V ${r.y - off} H ${r.x - off + s}`,
    `M ${r.x + r.w + off - s} ${r.y - off} H ${r.x + r.w + off} V ${r.y - off + s}`,
    `M ${r.x + r.w + off} ${r.y + r.h + off - s} V ${r.y + r.h + off} H ${r.x + r.w + off - s}`,
    `M ${r.x - off + s} ${r.y + r.h + off} H ${r.x - off} V ${r.y + r.h + off - s}`,
  ]
  return (
    <g stroke={color} strokeWidth={width} fill="none" opacity={clamp01(k * 1.4)} strokeLinecap="square">
      {c.map((d) => (
        <path key={d} d={d} />
      ))}
    </g>
  )
}

/**
 * Contenedor de Motion Tech (Fase 4.1): se CONSTRUYE en vez de aparecer.
 * Entrada: el marco se traza desde las esquinas, los corchetes convergen con muelle y el cuerpo
 * se despliega desde una línea central con bordes de luz; leve elevación (profundidad).
 * Salida: el cuerpo se pliega a una línea que se contrae hacia el centro y los corchetes se
 * cierran sobre ese punto. Continuidad: si la animación anterior seguía en pantalla, el
 * contenedor se transforma desde su región (sin salir y volver a entrar); si la siguiente lo
 * continúa, no sale y solo se retira el contenido.
 */
function TechContainer({ spec, r: R, children, panel = true }: { spec: AnimationSpec; r: Rect; children: React.ReactNode; panel?: boolean }) {
  const frame = useCurrentFrame()
  const u = unit(spec)
  const pal = spec.palette
  const E = Math.max(6, spec.entryFrames)
  const X = Math.max(6, spec.exitFrames)
  const D = spec.durationInFrames
  const chainIn = spec.chainIn ? px(spec, spec.chainIn) : null
  const chainOut = Boolean(spec.chainOut)
  // Entrada
  const morph = chainIn ? p(frame, 0, E, EASE.inOut) : 1
  const draw = chainIn ? 1 : p(frame, 0, E * 0.55, EASE.expo)
  const unfold = chainIn ? 1 : p(frame, E * 0.2, E * 0.8, EASE.expo)
  const bracketK = chainIn ? 1 : Math.min(1.06, sp(frame, spec.fps, 0, { damping: 13, stiffness: 140 }))
  // Salida
  // Salida escalonada: el contenido se retira, el cuerpo se pliega y la línea se contrae.
  const contentOut = p(frame, D - X, X * (chainOut ? 1 : 0.42), EASE.in)
  const fold = chainOut ? 0 : p(frame, D - X * 0.62, X * 0.42, EASE.in)
  const shrink = chainOut ? 0 : p(frame, D - X * 0.3, X * 0.3, EASE.in)
  const contentIn = chainIn ? p(frame, E * 0.45, E * 0.55, EASE.out) : clamp01(unfold * 1.4 - 0.2)
  const r = chainIn ? lerpRect(chainIn, R, morph) : R
  const cy = r.y + r.h / 2
  const cx = r.x + r.w / 2
  const visH = r.h * unfold * (1 - fold)
  const visW = r.w * (1 - shrink)
  const lift = (1 - unfold) + fold
  const id = `clip-${spec.id}`
  const perim = `M ${r.x} ${r.y + r.h * 0.5} V ${r.y} H ${r.x + r.w} V ${r.y + r.h} H ${r.x} Z`
  const bracketRect = { x: cx - (visW / 2), y: cy - Math.max(visH, 2 * u) / 2, w: visW, h: Math.max(visH, 2 * u) }
  const gone = shrink >= 0.999
  if (gone) return null
  return (
    <g style={{ transformOrigin: `${cx}px ${cy}px`, scale: String(1 - 0.035 * lift), translate: `0px ${lift * 8 * u}px` }}>
      <defs>
        <clipPath id={id}>
          <rect x={cx - visW / 2 - 8 * u} y={cy - visH / 2} width={visW + 16 * u} height={Math.max(0.5, visH)} />
        </clipPath>
        <linearGradient id={`${id}-edge`} x1="0" x2="1" y1="0" y2="0">
          <stop offset="0" stopColor={pal.accent} stopOpacity={0} />
          <stop offset="0.5" stopColor={pal.highlight} stopOpacity={1} />
          <stop offset="1" stopColor={pal.accent} stopOpacity={0} />
        </linearGradient>
      </defs>
      {panel && (
        // Sombra de elevación: el panel «flota» sobre el video.
        <rect x={r.x + 6 * u} y={cy - visH / 2 + 14 * u} width={visW} height={Math.max(0, visH)} rx={8 * u} fill="#000" opacity={0.28 * unfold * (1 - fold)} style={{ filter: `blur(${14 * u}px)` }} />
      )}
      <g clipPath={`url(#${id})`}>
        {panel && (
          <>
            <rect x={r.x} y={r.y} width={r.w} height={r.h} rx={6 * u} fill={pal.surface} opacity={0.82} />
            <svg x={r.x} y={r.y} width={r.w} height={r.h} overflow="hidden">
              <Grid w={r.w} h={r.h} step={34 * u} color={pal.accent} opacity={spec.params.grid_overlay === false ? 0 : 0.07} offset={frame * 0.25 * u} />
            </svg>
          </>
        )}
        <g opacity={contentIn * (1 - contentOut)} style={{ translate: `0px ${(1 - contentIn) * 10 * u - contentOut * 14 * u}px` }}>
          {children}
        </g>
      </g>
      {panel && (
        <>
          <Stroke d={perim} progress={draw * (1 - fold)} color={pal.accent} width={1.4 * u} opacity={0.55} />
          {/* Bordes de luz del despliegue / pliegue */}
          {(unfold < 1 || fold > 0) && (
            <>
              <rect x={cx - visW / 2} y={cy - visH / 2 - 1.5 * u} width={visW} height={3 * u} fill={`url(#${id}-edge)`} style={{ filter: glow(pal.accent, 10 * u) }} />
              <rect x={cx - visW / 2} y={cy + visH / 2 - 1.5 * u} width={visW} height={3 * u} fill={`url(#${id}-edge)`} style={{ filter: glow(pal.accent, 10 * u) }} />
            </>
          )}
          <Brackets r={inset(chainIn || fold > 0 ? bracketRect : r, -6 * u)} color={pal.accent} k={bracketK * (1 - shrink)} size={22 * u} width={3 * u} />
        </>
      )}
    </g>
  )
}

function stateColor(spec: AnimationSpec, it: Item, frame: number) {
  const on = it.stateCue !== undefined && frame >= it.stateCue
  if (it.state === 'negated' && on) return spec.palette.secondary
  if (it.state === 'highlight' && on) return spec.palette.highlight
  if (it.state === 'done' && on) return spec.palette.accent
  return spec.palette.text
}

function Strike({ x, y, w, progress, color, u }: { x: number; y: number; w: number; progress: number; color: string; u: number }) {
  return <Stroke d={`M ${x} ${y} L ${x + w} ${y}`} progress={progress} color={color} width={4 * u} cap="butt" />
}

// ---------------------------------------------------------------------------

function Panel({ spec }: { spec: AnimationSpec }) {
  const frame = useCurrentFrame()
  const u = unit(spec)
  const R = px(spec, spec.region)
  const pal = spec.palette
  const pad = Math.min(26 * u, Math.min(R.w, R.h) * 0.08)
  const inner = inset(R, pad)
  const title = headline(spec)
  const rows = visibleItems(spec.items).filter((i) => i.text && i.text !== title)
  const label = (spec.label ?? 'SYS').toUpperCase()
  const titleItem = spec.items.find((i) => i.text === title)
  const tCue = titleItem?.cue ?? Math.round(spec.entryFrames * 0.6)
  const labelSize = 18 * u
  const titleSize = fitFont(title.toUpperCase(), inner.w, 72 * u, 0.62, 22 * u, F_DISPLAY)
  const titleY = inner.y + labelSize + 22 * u + titleSize
  const rowH = Math.min(64 * u, (inner.h - (titleY - inner.y) - 10 * u) / Math.max(1, rows.length))
  const rowSize = Math.min(34 * u, rowH * 0.66)
  const cursorOn = Math.floor(frame / (spec.fps / 2)) % 2 === 0
  const titleP = p(frame, tCue, Math.round(spec.fps * 0.7), EASE.expo)
  const titleItemColor = titleItem ? stateColor(spec, titleItem, frame) : pal.text
  return (
    <TechContainer spec={spec} r={R}>
      <text x={inner.x} y={inner.y + labelSize} fontFamily={MONO} fontSize={labelSize} fill={pal.accent} letterSpacing={2 * u}>
        {`> ${typed(label, p(frame, 2, spec.fps * 0.5))}`}
        {cursorOn ? '▌' : ''}
      </text>
      {/* Cabecera modular: indicadores de estado y línea de progreso del módulo */}
      {[0, 1, 2].map((k) => (
        <circle key={k} cx={inner.x + inner.w - k * 16 * u - 6 * u} cy={inner.y + labelSize * 0.6} r={4 * u} fill={k === 0 ? pal.accent : pal.muted} opacity={k === 0 ? 0.6 + 0.4 * Math.sin(frame / 6) : 0.5} />
      ))}
      <rect x={inner.x} y={inner.y + labelSize + 8 * u} width={inner.w * p(frame, 0, spec.durationInFrames, EASE.linear)} height={1.5 * u} fill={pal.accent} opacity={0.5} />
      <text x={inner.x} y={titleY} fontFamily={DISPLAY} fontWeight={800} fontSize={titleSize} fill={titleItemColor} style={{ filter: glow(pal.accent, 6 * u * titleP) }}>
        {scramble(title.toUpperCase(), titleP, frame, spec.seed)}
      </text>
      {titleItem?.state === 'negated' && titleItem.stateCue !== undefined && (
        <Strike x={inner.x} y={titleY - titleSize * 0.35} w={Math.min(inner.w, measure(title.toUpperCase(), F_DISPLAY, titleSize))} progress={p(frame, titleItem.stateCue, spec.fps * 0.35, EASE.expo)} color={pal.secondary} u={u} />
      )}
      {rows.map((it, i) => {
        const y = titleY + 18 * u + rowH * (i + 0.75)
        const a = appear(spec, frame, it.cue)
        const color = stateColor(spec, it, frame)
        const txt = `▸ ${it.text?.toUpperCase() ?? ''}`
        const sc = fitFont(txt, inner.w - 50 * u, rowSize, 0.6, 12 * u, F_MONO)
        const done = it.state === 'done' && it.stateCue !== undefined && frame >= it.stateCue
        return (
          <g key={it.id} opacity={clamp01(a * 1.5)} style={{ translate: `${(1 - clamp01(a)) * -20 * u}px 0px` }}>
            <text x={inner.x} y={y} fontFamily={MONO} fontSize={sc} fill={color}>
              {typed(txt, clamp01(a * 1.2))}
            </text>
            {done && (
              <g transform={`translate(${inner.x + inner.w - 34 * u}, ${y - sc})`}>
                <Icon name="CircleCheck" size={sc * 1.25} color={pal.accent} progress={p(frame, it.stateCue!, spec.fps * 0.4)} stroke={2.4} />
              </g>
            )}
            {it.state === 'negated' && it.stateCue !== undefined && (
              <Strike x={inner.x} y={y - sc * 0.35} w={Math.min(inner.w, measure(txt, F_MONO, sc))} progress={p(frame, it.stateCue, spec.fps * 0.3, EASE.expo)} color={pal.secondary} u={u} />
            )}
          </g>
        )
      })}
    </TechContainer>
  )
}

/** Conector tipo circuito (horizontal → vertical → horizontal con esquinas redondeadas). */
function circuit(x1: number, y1: number, x2: number, y2: number, rr: number) {
  if (Math.abs(y2 - y1) < 2) return { d: `M ${x1} ${y1} L ${x2} ${y2}`, pts: [[x1, y1], [x2, y2]] as [number, number][] }
  if (Math.abs(x2 - x1) < 2) return { d: `M ${x1} ${y1} L ${x2} ${y2}`, pts: [[x1, y1], [x2, y2]] as [number, number][] }
  const mx = (x1 + x2) / 2
  const sx = Math.sign(x2 - x1)
  const sy = Math.sign(y2 - y1)
  const c = Math.min(rr, Math.abs(y2 - y1) / 2, Math.abs(mx - x1))
  const d = `M ${x1} ${y1} H ${mx - sx * c} Q ${mx} ${y1} ${mx} ${y1 + sy * c} V ${y2 - sy * c} Q ${mx} ${y2} ${mx + sx * c} ${y2} H ${x2}`
  return { d, pts: [[x1, y1], [mx, y1], [mx, y2], [x2, y2]] as [number, number][] }
}

/** Punto a fracción `t` del recorrido de una polilínea. */
function along(pts: [number, number][], t: number): [number, number] {
  const seg = pts.slice(1).map((q, i) => Math.hypot(q[0] - pts[i][0], q[1] - pts[i][1]))
  let rest = clamp01(t) * seg.reduce((a, b) => a + b, 0)
  for (let i = 0; i < seg.length; i++) {
    if (rest <= seg[i] || i === seg.length - 1) {
      const k = seg[i] ? rest / seg[i] : 0
      return [pts[i][0] + (pts[i + 1][0] - pts[i][0]) * k, pts[i][1] + (pts[i + 1][1] - pts[i][1]) * k]
    }
    rest -= seg[i]
  }
  return pts[pts.length - 1]
}

/**
 * Nodos en una franja baja y ancha (p. ej. entre la interfaz de la red social y el rostro):
 * «chips» con el icono a la izquierda y la etiqueta al lado, mucho más legibles que nodos con
 * la etiqueta debajo. Conectores con paquetes entre chips.
 */
function NodesCompact({ spec, box, R }: { spec: AnimationSpec; box: Rect; R: Rect }) {
  const frame = useCurrentFrame()
  const u = unit(spec)
  const pal = spec.palette
  const items = visibleItems(spec.items)
  const n = Math.max(1, items.length)
  // Con 4 o más elementos, dos filas: cada chip tiene el doble de ancho para su etiqueta.
  const rows = n >= 4 ? 2 : 1
  const cols = Math.ceil(n / rows)
  const slotW = box.w / cols
  const rowH = box.h / rows
  const gap = 10 * u
  const r = Math.min(rowH * 0.34, slotW * 0.14)
  const labelW = slotW - r * 2.6 - gap * 2
  const labelSize = Math.min(
    ...items.map((it) => fitLines((it.text ?? '').toUpperCase(), F_MONO, labelW, Math.min(rowH * 0.3, 34 * u), 12 * u, 2).size),
  )
  const cell = (i: number) => ({ col: i % cols, row: Math.floor(i / cols) })
  const cyOf = (i: number) => box.y + rowH * (cell(i).row + 0.5)
  const iconX = (i: number) => box.x + slotW * cell(i).col + r * 1.25
  return (
    <TechContainer spec={spec} r={R}>
      {items.slice(1).map((it, i) => {
        if (cell(i + 1).row !== cell(i).row) return null
        const cy = cyOf(i)
        const x1 = box.x + slotW * (cell(i).col + 1) - gap * 0.6
        const x2 = iconX(i + 1) - r * 1.3
        // Con enlaces dirigidos (Fase 5), el conector aparece en la palabra del enlace.
        const ln = spec.links.find((l) => (l.from === items[i].id && l.to === it.id) || (l.from === it.id && l.to === items[i].id))
        const cue = ln?.cue ?? it.cue
        const dp = p(frame, cue - spec.fps * 0.2, spec.fps * 0.45, EASE.expo)
        const t = (((frame - cue) / (spec.fps * 0.9)) % 1 + 1) % 1
        return (
          <g key={`l${it.id}`}>
            <Stroke d={`M ${x1 - (x1 - x2) * 0} ${cy} L ${x2} ${cy}`} progress={dp} color={pal.accent} width={2.4 * u} />
            {dp >= 1 && <circle cx={x1 + (x2 - x1) * t} cy={cy} r={4 * u} fill={pal.highlight} style={{ filter: glow(pal.accent, 8 * u) }} />}
          </g>
        )
      })}
      {spec.links.map((l, k) => {
        // Enlaces entre fichas no contiguas: pulso de conexión en la ficha de destino.
        const ia = items.findIndex((x) => x.id === l.from)
        const ib = items.findIndex((x) => x.id === l.to)
        if (ia < 0 || ib < 0 || (Math.abs(ia - ib) === 1 && cell(ia).row === cell(ib).row)) return null
        const q = p(frame, l.cue, spec.fps * 0.6, EASE.out)
        if (q <= 0 || q >= 1) return null
        return (
          <circle
            key={`k${k}`}
            cx={iconX(ib)}
            cy={cyOf(ib)}
            r={r * (1.1 + q * 0.9)}
            fill="none"
            stroke={pal.highlight}
            strokeWidth={2.2 * u}
            opacity={1 - q}
            style={{ filter: glow(pal.accent, 6 * u) }}
          />
        )
      })}
      {items.map((it, i) => {
        const a = appear(spec, frame, it.cue)
        const color = stateColor(spec, it, frame)
        const pop = Math.min(1.12, sp(frame, spec.fps, it.cue, { damping: 11, stiffness: 160 }))
        const cx = iconX(i)
        const cy = cyOf(i)
        const lines = breakText((it.text ?? '').toUpperCase(), F_MONO, labelSize, labelW)
        const ly = cy - ((lines.length - 1) * labelSize * 1.12) / 2 + labelSize * 0.36
        return (
          <g key={it.id} opacity={clamp01(a * 2)}>
            <g style={{ transformOrigin: `${cx}px ${cy}px`, scale: String(0.4 + 0.6 * pop) }}>
              <circle cx={cx} cy={cy} r={r * 1.2} fill="none" stroke={pal.accent} strokeWidth={1.2 * u} strokeDasharray={`${5 * u} ${7 * u}`} opacity={0.5} style={{ transformOrigin: `${cx}px ${cy}px`, rotate: `${(frame - it.cue) * 0.6}deg` }} />
              <circle cx={cx} cy={cy} r={r} fill={pal.bg} fillOpacity={0.9} />
              <Stroke d={`M ${cx} ${cy - r} A ${r} ${r} 0 1 1 ${cx - 0.01} ${cy - r}`} progress={p(frame, it.cue, spec.fps * 0.45, EASE.expo)} color={color} width={2.6 * u} />
              <g transform={`translate(${cx - r * 0.55}, ${cy - r * 0.55})`}>
                <Icon name={it.icon ?? 'Cpu'} size={r * 1.1} color={color} progress={p(frame, it.cue + 3, spec.fps * 0.5)} stroke={1.8} />
              </g>
            </g>
            {lines.map((ln, li) => (
              <text key={li} x={cx + r * 1.35 + gap * 0.4} y={ly + li * labelSize * 1.12} fontFamily={MONO} fontWeight={600} fontSize={labelSize} fill={color} letterSpacing={0.6 * u}>
                {scramble(ln, p(frame, it.cue + 4 + li * 3, spec.fps * 0.45), frame, spec.seed + i * 5 + li)}
              </text>
            ))}
            {it.state === 'negated' && it.stateCue !== undefined && (
              <Stroke d={`M ${cx - r} ${cy + r} L ${cx + r} ${cy - r}`} progress={p(frame, it.stateCue, spec.fps * 0.3)} color={pal.secondary} width={4 * u} />
            )}
          </g>
        )
      })}
    </TechContainer>
  )
}

function Nodes({ spec }: { spec: AnimationSpec }) {
  const frame = useCurrentFrame()
  const u = unit(spec)
  const R = px(spec, spec.region)
  const pal = spec.palette
  const items = visibleItems(spec.items)
  const box = insetP(R, 24 * u)
  if (items.length >= 2 && box.w / Math.max(1, box.h) > 3.2 && spec.arrangement !== 'column') {
    return <NodesCompact spec={spec} box={box} R={R} />
  }
  const labelSpace = 64 * u
  const slots = arrange(items.length, { ...box, h: box.h - labelSpace }, spec.arrangement)
  const radius = Math.max(16 * u, Math.min((spec.mode === 'fullscreen' ? 120 : 84) * u, ...slots.map((s) => Math.min(s.w * 0.3, (s.h - 40 * u) * 0.45))))
  const pos = new Map(items.map((it, i) => [it.id, slots[i]]))
  const links = spec.links.length
    ? spec.links
    : items.slice(1).map((it, i) => ({ from: items[i].id, to: it.id, cue: it.cue }))
  // Etiquetas: tamaño común, el mayor que cabe en 2 líneas en el ancho de cada nodo.
  const labelSize = Math.min(
    30 * u,
    ...items.map((it, i) => fitLines((it.text ?? '').toUpperCase(), F_MONO, Math.max(slots[i].w * 0.96, radius * 2.4), 30 * u, 13 * u, 2).size),
  )
  return (
    <TechContainer spec={spec} r={R}>
      {links.map((l, i) => {
        const a = pos.get(l.from)
        const b = pos.get(l.to)
        if (!a || !b) return null
        const horiz = Math.abs(b.cx - a.cx) >= Math.abs(b.cy - a.cy)
        const x1 = horiz ? a.cx + Math.sign(b.cx - a.cx) * radius : a.cx
        const y1 = horiz ? a.cy : a.cy + Math.sign(b.cy - a.cy) * radius
        const x2 = horiz ? b.cx - Math.sign(b.cx - a.cx) * radius : b.cx
        const y2 = horiz ? b.cy : b.cy - Math.sign(b.cy - a.cy) * radius
        const { d, pts } = circuit(x1, y1, x2, y2, 18 * u)
        const dp = p(frame, l.cue - spec.fps * 0.2, spec.fps * 0.55, EASE.expo)
        const period = spec.fps * 1.2
        return (
          <g key={`${l.from}-${l.to}-${i}`}>
            <Stroke d={d} progress={1} color={pal.muted} width={1.4 * u} opacity={0.25 * clamp01(dp * 3)} />
            <Stroke d={d} progress={dp} color={pal.accent} width={2.6 * u} opacity={0.9} />
            {dp >= 1 &&
              [0, 0.5].map((o) => {
                const t = (((frame - l.cue) / period + o) % 1 + 1) % 1
                return [0, 0.035, 0.07].map((lag, k) => {
                  const [x, y] = along(pts, t - lag)
                  return <circle key={`${o}-${k}`} cx={x} cy={y} r={(4.6 - k * 1.2) * u} fill={k ? pal.accent : pal.highlight} opacity={k ? 0.55 - k * 0.15 : 1} style={k ? undefined : { filter: glow(pal.accent, 8 * u) }} />
                })
              })}
          </g>
        )
      })}
      {items.map((it, i) => {
        const s = slots[i]
        const a = appear(spec, frame, it.cue)
        const color = stateColor(spec, it, frame)
        const pop = Math.min(1.12, sp(frame, spec.fps, it.cue, { damping: 11, stiffness: 160 }))
        const r = radius * (it.role === 'primary' ? 1.15 : 1)
        const lbl = (it.text ?? '').toUpperCase()
        const lines = breakText(lbl, F_MONO, labelSize, Math.max(s.w * 0.96, r * 2.4))
        const spin = (frame - it.cue) * 0.6
        const flash = clamp01(1 - (frame - it.cue) / (spec.fps * 0.35))
        return (
          <g key={it.id} opacity={clamp01(a * 2)}>
            <g style={{ transformOrigin: `${s.cx}px ${s.cy}px`, scale: String(0.4 + 0.6 * pop) }}>
              <circle cx={s.cx} cy={s.cy + 6 * u} r={r} fill="#000" opacity={0.3} style={{ filter: `blur(${8 * u}px)` }} />
              <circle cx={s.cx} cy={s.cy} r={r * 1.22} fill="none" stroke={pal.accent} strokeWidth={1.4 * u} strokeDasharray={`${6 * u} ${9 * u}`} opacity={0.5} style={{ transformOrigin: `${s.cx}px ${s.cy}px`, rotate: `${spin}deg` }} />
              <circle cx={s.cx} cy={s.cy} r={r} fill={pal.bg} fillOpacity={0.9} />
              <circle cx={s.cx} cy={s.cy} r={r} fill={pal.accent} opacity={0.35 * flash} />
              <Stroke d={`M ${s.cx} ${s.cy - r} A ${r} ${r} 0 1 1 ${s.cx - 0.01} ${s.cy - r}`} progress={p(frame, it.cue, spec.fps * 0.45, EASE.expo)} color={color} width={3 * u} />
              <g transform={`translate(${s.cx - r * 0.55}, ${s.cy - r * 0.55})`} style={{ filter: glow(pal.accent, 4 * u) }}>
                <Icon name={it.icon ?? 'Cpu'} size={r * 1.1} color={color} progress={p(frame, it.cue + 3, spec.fps * 0.5)} stroke={1.8} />
              </g>
            </g>
            {lines.map((ln, li) => (
              <text key={li} x={s.cx} y={s.cy + r * 1.22 + labelSize * (1.1 + li * 1.15) + 8 * u} textAnchor="middle" fontFamily={MONO} fontWeight={600} fontSize={labelSize} fill={color} letterSpacing={1 * u}>
                {scramble(ln, p(frame, it.cue + 4 + li * 3, spec.fps * 0.45), frame, spec.seed + i * 5 + li)}
              </text>
            ))}
            {it.state === 'negated' && it.stateCue !== undefined && (
              <Stroke d={`M ${s.cx - r} ${s.cy + r} L ${s.cx + r} ${s.cy - r}`} progress={p(frame, it.stateCue, spec.fps * 0.3)} color={pal.secondary} width={5 * u} />
            )}
          </g>
        )
      })}
    </TechContainer>
  )
}

function Pipeline({ spec }: { spec: AnimationSpec }) {
  const frame = useCurrentFrame()
  const u = unit(spec)
  const R = px(spec, spec.region)
  const pal = spec.palette
  const items = visibleItems(spec.items)
  const box = insetP(R, 28 * u)
  const n = Math.max(1, items.length)
  const vertical = box.h > box.w * 1.1
  // Horizontal: etiquetas en 1–2 líneas legibles y bloque (número + etiqueta + barra) centrado.
  const segW0 = vertical ? box.w : box.w / n
  const labels = items.map((it) => {
    const t = (it.text ?? '').toUpperCase()
    const one = fitFont(t, segW0 - 20 * u, 34 * u, 0.62, 11 * u, F_DISPLAY)
    if (vertical || one >= 24 * u || !t.includes(' ')) return { lines: [t], size: one }
    return fitLines(t, F_DISPLAY, segW0 - 20 * u, 34 * u, 11 * u, 2)
  })
  const nsH = Math.min(34 * u, box.h * 0.32)
  const ts0 = vertical ? 0 : Math.min(...labels.map((l) => l.size))
  const maxLines = Math.max(...labels.map((l) => l.lines.length))
  const blockH = nsH + 14 * u + maxLines * ts0 * 1.12 + 26 * u + 6 * u
  const top = vertical ? box.y : box.y + Math.max(0, (box.h - blockH) / 2)
  const barY = vertical ? 0 : top + blockH - 6 * u
  return (
    <TechContainer spec={spec} r={R}>
      {!vertical && (
        <>
          <rect x={box.x} y={barY} width={box.w} height={6 * u} fill={pal.muted} opacity={0.35} />
          {items.map((it, i) => {
            const segW = box.w / n
            const fill = p(frame, it.cue - spec.fps * 0.2, spec.fps * 0.6, EASE.expo)
            return <rect key={it.id} x={box.x + segW * i} y={barY} width={segW * fill} height={6 * u} fill={pal.accent} style={{ filter: glow(pal.accent, 6 * u) }} />
          })}
        </>
      )}
      {items.map((it, i) => {
        const a = appear(spec, frame, it.cue)
        const color = stateColor(spec, it, frame)
        const segW = vertical ? box.w : box.w / n
        const segH = vertical ? box.h / n : box.h
        const x = vertical ? box.x : box.x + segW * i
        const y = vertical ? box.y + segH * i : top
        const num = String(i + 1).padStart(2, '0')
        const ns = vertical ? Math.min(34 * u, segH * 0.32) : nsH
        const ts = vertical ? labels[i].size : ts0
        const active = frame >= it.cue
        const done = (it.state === 'done' && it.stateCue !== undefined && frame >= it.stateCue) || (!vertical && i < n - 1 && frame >= items[i + 1].cue)
        return (
          <g key={it.id} opacity={clamp01(0.25 + a)}>
            <text x={x + 8 * u} y={y + ns + (vertical ? 4 * u : 0)} fontFamily={MONO} fontSize={ns} fontWeight={700} fill={active ? pal.accent : pal.muted}>
              {num}
            </text>
            {labels[i].lines.map((line, li) => (
              <text key={li} x={x + 8 * u} y={y + ns + ts + 14 * u + li * ts * 1.12} fontFamily={DISPLAY} fontWeight={700} fontSize={ts} fill={color}>
                {scramble(line, p(frame, it.cue, spec.fps * 0.5), frame, spec.seed + i * 7 + li)}
              </text>
            ))}
            {done && (
              <g transform={`translate(${x + segW - 44 * u}, ${y + 4 * u})`}>
                <Icon name="CircleCheck" size={30 * u} color={pal.accent} progress={1} stroke={2.2} />
              </g>
            )}
            {vertical && <rect x={x} y={y + segH - 3 * u} width={segW * p(frame, it.cue, spec.fps * 0.6, EASE.expo)} height={3 * u} fill={pal.accent} />}
          </g>
        )
      })}
    </TechContainer>
  )
}

function Readout({ spec }: { spec: AnimationSpec }) {
  const frame = useCurrentFrame()
  const u = unit(spec)
  const R = px(spec, spec.region)
  const pal = spec.palette
  const box = insetP(R, 26 * u)
  const n = spec.number ?? { from: 0, to: 100, cue: spec.entryFrames, duration: spec.fps, label: headline(spec) }
  const k = p(frame, n.cue, Math.max(1, n.duration), EASE.expo)
  const value = Math.round(n.from + (n.to - n.from) * k)
  const txt = `${n.prefix ?? ''}${value}${n.suffix ?? ''}`
  const big = fitFont(txt, box.w * 0.9, Math.min(box.h * 0.55, 170 * u), 0.62, 12, F_DISPLAY)
  const label = (n.label ?? headline(spec)).toUpperCase()
  const ticks = 24
  const filled = Math.round(ticks * k)
  return (
    <TechContainer spec={spec} r={R}>
      <text x={box.x} y={box.y + 22 * u} fontFamily={MONO} fontSize={20 * u} fill={pal.accent} letterSpacing={2 * u}>
        {scramble(label, p(frame, 0, spec.fps * 0.6), frame, spec.seed)}
      </text>
      <text x={box.x} y={box.y + 30 * u + big} fontFamily={DISPLAY} fontWeight={800} fontSize={big} fill={pal.text} style={{ filter: glow(pal.accent, 10 * u * k) }}>
        {txt}
      </text>
      {Array.from({ length: ticks }, (_, i) => (
        <rect key={i} x={box.x + (box.w / ticks) * i} y={box.y + box.h - 18 * u} width={box.w / ticks - 4 * u} height={14 * u} fill={i < filled ? pal.accent : pal.muted} opacity={i < filled ? 1 : 0.3} />
      ))}
    </TechContainer>
  )
}

function KineticType({ spec }: { spec: AnimationSpec }) {
  const frame = useCurrentFrame()
  const u = unit(spec)
  const R = px(spec, spec.region)
  const pal = spec.palette
  const items = visibleItems(spec.items).filter((i) => i.text)
  const box = insetP(R, 24 * u)
  const lines = items.length
  const lh = box.h / Math.max(1, lines)
  return (
    <TechContainer spec={spec} r={R} panel={spec.mode !== 'fullscreen'}>
      {items.map((it, i) => {
        const text = (it.text ?? '').toUpperCase()
        const primary = it.role === 'primary'
        const fs = fitFont(text, box.w, Math.min(lh * 0.78, (primary ? 96 : 54) * u), primary ? 0.64 : 0.6, 14 * u, primary ? F_DISPLAY : F_MONO)
        const y = box.y + lh * i + lh / 2 + fs * 0.35
        const a = p(frame, it.cue, spec.fps * 0.55, EASE.expo)
        const color = stateColor(spec, it, frame)
        const neg = it.state === 'negated' && it.stateCue !== undefined && frame >= it.stateCue
        // Negado: se atenúa y se tacha con un barrido limpio (sin vibración ni glitch repetido).
        const negK = neg ? p(frame, it.stateCue ?? 0, spec.fps * 0.3, EASE.expo) : 0
        const hl = primary ? p(frame, it.cue + 2, spec.fps * 0.4, EASE.expo) : 0
        const tw = Math.min(box.w, measure(text, primary ? F_DISPLAY : F_MONO, fs))
        return (
          <g key={it.id} opacity={(a > 0 ? 1 : 0) * (1 - 0.45 * negK)} style={{ translate: `${(1 - a) * -18 * u}px 0px` }}>
            {primary && <rect x={box.x - 8 * u} y={y - fs * 0.95} width={(tw + 16 * u) * hl} height={fs * 1.2} fill={pal.accent} opacity={0.18} />}
            <text x={box.x} y={y} fontFamily={primary ? DISPLAY : MONO} fontWeight={primary ? 800 : 600} fontSize={fs} fill={color}>
              {scramble(text, a, frame, spec.seed + i)}
            </text>
            {it.state === 'negated' && it.stateCue !== undefined && (
              <Strike x={box.x} y={y - fs * 0.35} w={tw} progress={p(frame, it.stateCue, spec.fps * 0.25, EASE.expo)} color={pal.secondary} u={u} />
            )}
          </g>
        )
      })}
    </TechContainer>
  )
}

function Highlight({ spec }: { spec: AnimationSpec }) {
  const frame = useCurrentFrame()
  const u = unit(spec)
  const pal = spec.palette
  const t = spec.target ?? { ...spec.region, cue: 0 }
  const T = px(spec, t)
  const { inP, outP } = envelope(spec, frame)
  const k = p(frame, t.cue, spec.fps * 0.5, EASE.expo)
  const W = spec.width
  const H = spec.height
  const label = headline(spec).toUpperCase()
  const above = T.y > H * 0.18
  const ly = above ? T.y - 70 * u : T.y + T.h + 70 * u
  const lx = Math.min(Math.max(T.x, 20 * u), W - 360 * u)
  const fs = 22 * u
  const vis = inP * (1 - outP)
  const tagP = p(frame, t.cue + spec.fps * 0.2, spec.fps * 0.4, EASE.expo)
  return (
    <g opacity={vis}>
      <path d={`M0 0H${W}V${H}H0Z M${T.x} ${T.y}V${T.y + T.h}H${T.x + T.w}V${T.y}Z`} fill="#000" fillRule="evenodd" opacity={0.32 * k} />
      <Brackets r={T} color={pal.accent} k={k} size={Math.min(T.w, T.h) * 0.28} width={4 * u} />
      <rect x={T.x} y={T.y} width={T.w} height={T.h} fill="none" stroke={pal.accent} strokeOpacity={0.4 * k} strokeWidth={1.5 * u} style={{ filter: glow(pal.accent, 8 * u) }} />
      <Stroke d={`M ${lx + 20 * u} ${above ? ly + 14 * u : ly - 30 * u} L ${T.x + T.w / 2} ${above ? T.y : T.y + T.h}`} progress={tagP} color={pal.accent} width={2 * u} />
      <g opacity={tagP}>
        <rect x={lx} y={ly - fs - 12 * u} width={Math.min(W - lx - 20 * u, measure(label, { family: 'VSA Mono', weight: 700 }, fs) + 32 * u)} height={fs + 22 * u} fill={pal.surface} opacity={0.9} stroke={pal.accent} strokeWidth={1.5 * u} />
        <text x={lx + 16 * u} y={ly} fontFamily={MONO} fontWeight={700} fontSize={fs} fill={pal.accent}>
          {typed(label, tagP * 1.3)}
        </text>
      </g>
    </g>
  )
}

/**
 * Transición Tech (Fase 4.1): cascada diagonal de módulos. Cada módulo se despliega desde su
 * centro con una onda diagonal y un borde de luz; a mitad cubren el encuadre y se recogen en el
 * mismo orden, de modo que el movimiento continúa en una sola dirección (sin cortes ni fundidos).
 */
function Transition({ spec }: { spec: AnimationSpec }) {
  const frame = useCurrentFrame()
  const u = unit(spec)
  const pal = spec.palette
  const W = spec.width
  const H = spec.height
  const d = spec.durationInFrames
  const cols = W < H ? 6 : 10
  const cw = W / cols
  const rows = Math.ceil(H / cw)
  const span = cols + rows
  const tile = d * 0.34
  const tiles = []
  for (let c = 0; c < cols; c++) {
    for (let r2 = 0; r2 < rows; r2++) {
      const order = (c + r2) / span
      const tin = p(frame, order * d * 0.32, tile, EASE.expo)
      const tout = p(frame, d * 0.5 + order * d * 0.32, tile, EASE.inOut)
      const k = tin * (1 - tout)
      if (k <= 0.001) continue
      const x = c * cw
      const y = r2 * cw
      const sz = cw * k
      const front = tin < 0.98 || (tout > 0.02 && tout < 0.98)
      tiles.push(
        <g key={`${c}-${r2}`}>
          <rect x={x + (cw - sz) / 2} y={y + (cw - sz) / 2} width={sz} height={sz} fill={pal.surface} />
          {front && <rect x={x + (cw - sz) / 2} y={y + (cw - sz) / 2} width={sz} height={sz} fill="none" stroke={pal.accent} strokeWidth={1.6 * u} opacity={0.8} />}
        </g>,
      )
    }
  }
  const mid = p(frame, d * 0.38, d * 0.24, EASE.inOut)
  return (
    <g>
      {tiles}
      {/* Firma del estilo a mitad de la transición: retícula y una línea de datos que cruza */}
      <g opacity={Math.sin(Math.PI * mid)}>
        <svg width={W} height={H}>
          <Grid w={W} h={H} step={cw / 2} color={pal.accent} opacity={0.12} />
        </svg>
        <rect x={0} y={H / 2 - 1.5 * u} width={W * mid} height={3 * u} fill={pal.accent} style={{ filter: glow(pal.accent, 12 * u) }} />
      </g>
    </g>
  )
}

export function TechBackground({ spec }: { spec: AnimationSpec }) {
  const frame = useCurrentFrame()
  const u = unit(spec)
  const pal = spec.palette
  const W = spec.width
  const H = spec.height
  return (
    <g>
      <rect width={W} height={H} fill={pal.bg} />
      <defs>
        <radialGradient id="vign" cx="50%" cy="45%" r="75%">
          <stop offset="55%" stopColor={pal.bg} stopOpacity={0} />
          <stop offset="100%" stopColor="#000" stopOpacity={0.75} />
        </radialGradient>
      </defs>
      <Grid w={W} h={H} step={54 * u} color={pal.accent} opacity={spec.params.grid_overlay === false ? 0.03 : 0.09} offset={frame * 0.4 * u} />
      <Particles w={W} h={H} n={36} color={pal.accent} frame={frame} seed={spec.seed} opacity={0.35} size={2.2 * u} />
      <rect width={W} height={H} fill="url(#vign)" />
    </g>
  )
}

export function TechPipFrame({ spec }: { spec: AnimationSpec }) {
  const frame = useCurrentFrame()
  const u = unit(spec)
  if (!spec.pip) return null
  const P = px(spec, spec.pip)
  const k = p(frame, Math.round(spec.entryFrames * 0.5), spec.fps * 0.5, EASE.expo)
  return (
    <g>
      <Brackets r={inset(P, -10 * u)} color={spec.palette.accent} k={k} size={28 * u} width={3 * u} />
      <text x={P.x} y={P.y - 22 * u} fontFamily={MONO} fontSize={18 * u} fill={spec.palette.accent} opacity={k}>
        ● LIVE
      </text>
    </g>
  )
}

export const TECH: Record<string, React.FC<{ spec: AnimationSpec }>> = {
  'tech.panel': Panel,
  'tech.nodes': Nodes,
  'tech.pipeline': Pipeline,
  'tech.readout': Readout,
  'tech.type': KineticType,
  'tech.highlight': Highlight,
  'tech.transition': Transition,
}
