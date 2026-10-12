// Réplica exacta de `state_at` del backend (app/services/subtitles.py): la vista previa y la
// exportación calculan el mismo estado para cada instante.
import type { SubtitleTrack, TrackBlock } from './types'

const ANIM = { pop: 0.2, fade: 0.16, slide_up: 0.22 } as const
const FADE_OUT = 0.12

export interface WordState {
  visible: boolean
  highlight: boolean
  scale: number
  chars: number | null
}

export interface BlockState {
  alpha: number
  dy: number
  scale: number
  words: WordState[]
}

const round = (v: number, d: number) => Math.round(v * 10 ** d) / 10 ** d

const easeOutBack = (x: number) => 1 + 2.70158 * (x - 1) ** 3 + 1.70158 * (x - 1) ** 2

export function blockAt(track: SubtitleTrack, t: number): TrackBlock | null {
  // Búsqueda binaria: los bloques están ordenados y no se solapan.
  let lo = 0
  let hi = track.blocks.length - 1
  while (lo <= hi) {
    const mid = (lo + hi) >> 1
    const b = track.blocks[mid]
    if (t < b.start) hi = mid - 1
    else if (t >= b.end) lo = mid + 1
    else return b
  }
  return null
}

export function stateAt(track: SubtitleTrack, block: TrackBlock, t: number): BlockState {
  const { mode, animation: anim } = track
  const since = t - block.start
  let alpha = 1
  let dy = 0
  let blockScale = 1
  const entrance = mode === 'classic' || anim === 'fade' || anim === 'slide_up' ? anim : null
  if (entrance === 'fade' && since < ANIM.fade) {
    alpha = since / ANIM.fade
  } else if (entrance === 'slide_up' && since < ANIM.slide_up) {
    const p = since / ANIM.slide_up
    alpha = p
    dy = (1 - (1 - (1 - p) ** 3)) * track.font.line_height * 0.45
  } else if (entrance === 'pop' && mode === 'classic' && since < ANIM.pop) {
    blockScale = 0.85 + 0.15 * easeOutBack(since / ANIM.pop)
  }
  if (anim === 'fade' && block.end - t < FADE_OUT) {
    alpha = Math.min(alpha, Math.max(0, (block.end - t) / FADE_OUT))
  }
  const words = block.lines.flatMap((l) => l.words)
  let active: number | null = null
  if (mode === 'dynamic') {
    words.forEach((w, i) => {
      const next = i + 1 < words.length ? words[i + 1].start : block.end
      if (w.start <= t && t < Math.max(next, w.end)) active = i
    })
    if (active === null && t >= words[words.length - 1].start) active = words.length - 1
  }
  const states = words.map((w, i): WordState => {
    let visible = true
    let highlight = false
    let scale = 1
    let chars: number | null = null
    if (mode === 'dynamic') {
      if ((anim === 'word_by_word' || anim === 'typewriter') && w.start > t) visible = false
      if (anim === 'karaoke') highlight = w.start <= t
      else highlight = active === i
      if (anim === 'pop' && active === i && t - w.start < ANIM.pop) {
        const p = Math.max(0, (t - w.start) / ANIM.pop)
        scale = 1 + 0.12 * Math.sin(Math.PI * p)
      }
      if (anim === 'typewriter' && active === i) {
        // Conteo por puntos de código (como Python), para no partir emojis.
        const n = Array.from(w.text).length
        const dur = Math.max(0.05, w.end - w.start)
        chars = Math.max(1, Math.min(n, Math.ceil((n * (t - w.start)) / dur)))
      }
    }
    return { visible, highlight, scale: round(scale, 3), chars }
  })
  // Mismo redondeo que la exportación (state_at en Python).
  return { alpha: round(alpha, 3), dy: round(dy, 2), scale: round(blockScale, 3), words: states }
}

let fontsLoaded: Promise<void> | null = null

/** Registra en el navegador las mismas TTF que usa la exportación («VSA <familia>»). */
export function loadSubtitleFonts(faces: { family: string; file: string; weight: string }[]) {
  if (fontsLoaded) return fontsLoaded
  fontsLoaded = Promise.all(
    faces.map(async (f) => {
      const face = new FontFace(f.family, `url(/api/fonts/${encodeURIComponent(f.file)})`, {
        weight: f.weight,
        display: 'block',
      })
      document.fonts.add(face)
      try {
        await face.load()
      } catch {
        /* la vista previa usará una fuente de respaldo */
      }
    }),
  ).then(() => undefined)
  return fontsLoaded
}
