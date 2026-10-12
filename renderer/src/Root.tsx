import React from 'react'
import { Composition } from 'remotion'
import { Clip } from './Clip'
import { ensureFonts } from './lib/fonts'
import type { AnimationSpec } from './spec'

ensureFonts()

/** Especificación de ejemplo SOLO para Remotion Studio (desarrollo); nunca se exporta. */
const SAMPLE: AnimationSpec = {
  version: 1,
  id: 'muestra',
  planVersion: 0,
  style: 'motion_tech',
  template: 'tech.nodes',
  mode: 'overlay',
  width: 1080,
  height: 1920,
  fps: 30,
  durationInFrames: 150,
  region: { x: 0.05, y: 0.05, w: 0.9, h: 0.24 },
  pip: null,
  background: 'none',
  palette: { bg: '#05070D', surface: '#0B1220', text: '#E2E8F0', muted: '#64748B', accent: '#22D3EE', secondary: '#A78BFA', highlight: '#F0FDFF' },
  fonts: { display: 'VSA Montserrat', body: 'VSA Inter', mono: 'VSA Mono', hand: 'VSA Caveat' },
  params: {},
  intensity: 'medium',
  easing: 'exponential',
  entry: 'scan_reveal',
  exit: 'scan_out',
  entryFrames: 12,
  exitFrames: 10,
  title: 'Muestra',
  label: 'demo',
  items: [
    { id: 'a', kind: 'diagram_node', text: 'Datos', icon: 'Database', role: 'secondary', cue: 10 },
    { id: 'b', kind: 'diagram_node', text: 'Agente', icon: 'Bot', role: 'primary', cue: 40 },
    { id: 'c', kind: 'diagram_node', text: 'Acción', icon: 'Zap', role: 'secondary', cue: 70 },
  ],
  links: [],
  beats: [],
  number: null,
  target: null,
  arrangement: 'auto',
  custom: [],
  seed: 7,
}

export const Root: React.FC = () => (
  <Composition
    id="Clip"
    component={Clip as unknown as React.FC<Record<string, unknown>>}
    defaultProps={SAMPLE as unknown as Record<string, unknown>}
    width={1080}
    height={1920}
    fps={30}
    durationInFrames={150}
    calculateMetadata={({ props }) => {
      const s = props as unknown as AnimationSpec
      // Con `viewport` solo se renderiza esa zona (mismas coordenadas internas, sin reescalar).
      const v = s.viewport
      return { width: v ? v.w : s.width, height: v ? v.h : s.height, fps: s.fps, durationInFrames: s.durationInFrames }
    }}
  />
)
