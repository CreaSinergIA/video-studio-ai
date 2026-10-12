/**
 * Contrato de animación (AnimationSpec v1).
 *
 * Lo compila el backend (`app/services/animation_spec.py`) a partir de una intervención
 * APROBADA del plan de la Fase 3, opcionalmente afinada por Claude con el lenguaje declarativo
 * validado. Aquí solo se interpreta: nunca se ejecuta código recibido.
 *
 * Tiempos: todos los `cue` son fotogramas relativos al inicio del clip, que coincide con el
 * inicio aprobado de la intervención en el video original.
 */

export type StyleId = 'motion_tech' | 'minimal_motion' | 'creative_explainer'

export type Template =
  | 'custom'
  | 'tech.panel'
  | 'tech.nodes'
  | 'tech.pipeline'
  | 'tech.readout'
  | 'tech.type'
  | 'tech.highlight'
  | 'tech.transition'
  | 'min.statement'
  | 'min.list'
  | 'min.compare'
  | 'min.number'
  | 'min.steps'
  | 'min.highlight'
  | 'min.transition'
  | 'exp.sketch'
  | 'exp.icons'
  | 'exp.character'
  | 'exp.checklist'
  | 'exp.highlight'
  | 'exp.transition'

export type Box = { x: number; y: number; w: number; h: number }

export type ItemState = 'normal' | 'negated' | 'done' | 'highlight'

export type Item = {
  id: string
  kind: string // vocabulario de elementos de la Fase 3 (headline, keyword, diagram_node…)
  text?: string | null
  sub?: string | null
  icon?: string | null // nombre de icono lucide permitido
  role: 'primary' | 'secondary' | 'decoration'
  cue: number
  state?: ItemState
  stateCue?: number // fotograma en que cambia de estado (tachado, check…)
}

export type Link = { from: string; to: string; cue: number }

export type Beat = {
  cue: number
  kind: 'pulse' | 'strike' | 'check' | 'flash' | 'glitch' | 'count'
  target?: string | null
}

export type NumberSpec = {
  from: number
  to: number
  cue: number
  duration: number
  prefix?: string
  suffix?: string
  label?: string | null
}

export type Primitive = {
  type: 'rect' | 'ellipse' | 'line' | 'arrow' | 'text' | 'path'
  x: number
  y: number
  w?: number
  h?: number
  x2?: number
  y2?: number
  d?: string // solo comandos M/L/C/Q/Z con coordenadas normalizadas 0–1 (validado)
  text?: string
  color: 'text' | 'accent' | 'secondary' | 'highlight' | 'muted'
  stroke: number
  fill: boolean
  cue: number
  enter: 'draw' | 'fade' | 'pop' | 'slide'
  exitCue?: number | null
}

export type Palette = {
  bg: string
  surface: string
  text: string
  muted: string
  accent: string
  secondary: string
  highlight: string
}

export type AnimationSpec = {
  version: 1
  id: string
  planVersion: number
  style: StyleId
  template: Template
  mode: 'overlay' | 'fullscreen' | 'transition'
  width: number
  height: number
  fps: number
  durationInFrames: number
  region: Box
  pip?: (Box & { shape: 'rounded' | 'circle' }) | null
  background: 'none' | 'dim' | 'style'
  palette: Palette
  fonts: { display: string; body: string; mono: string; hand: string }
  params: Record<string, string | number | boolean>
  intensity: 'low' | 'medium' | 'high'
  easing: 'smooth' | 'exponential' | 'spring' | 'bounce' | 'linear'
  entry: string
  exit: string
  entryFrames: number
  exitFrames: number
  title?: string | null
  label?: string | null
  items: Item[]
  links: Link[]
  beats: Beat[]
  number?: NumberSpec | null
  target?: (Box & { cue: number }) | null
  arrangement: 'row' | 'column' | 'grid' | 'radial' | 'auto'
  custom: Primitive[]
  seed: number
  /** Fase 4.1 · continuidad: la animación anterior seguía en pantalla en esta región; el
   *  contenedor se transforma desde ella en vez de entrar de nuevo. */
  chainIn?: { x: number; y: number; w: number; h: number } | null
  /** Fase 4.1 · continuidad: la siguiente animación continúa este contenedor (no sale). */
  chainOut?: boolean
  /** Fase 5: zona del encuadre (px) que se renderiza; null/ausente = encuadre completo. */
  viewport?: { x: number; y: number; w: number; h: number } | null
}
