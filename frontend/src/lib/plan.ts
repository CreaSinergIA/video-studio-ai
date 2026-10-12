import type { InterventionStatus, InterventionType, PlanIntervention, PlanStatus } from './types'

export const TYPE_META: Record<InterventionType, { label: string; short: string; color: string }> = {
  keep_original: { label: 'Conservar original', short: 'Original', color: '#64748b' },
  overlay_motion: { label: 'Motion graphics superpuestos', short: 'Superpuesto', color: '#22d3ee' },
  fullscreen_animation: { label: 'Animación a pantalla completa', short: 'Pantalla completa', color: '#f472b6' },
  diagram: { label: 'Diagrama explicativo', short: 'Diagrama', color: '#a78bfa' },
  kinetic_typography: { label: 'Tipografía cinética', short: 'Tipografía', color: '#facc15' },
  screen_highlight: { label: 'Resaltado de pantalla', short: 'Resaltado', color: '#34d399' },
  transition: { label: 'Transición visual', short: 'Transición', color: '#fb923c' },
  no_intervention: { label: 'Sin intervención', short: 'Sin intervención', color: '#475569' },
}

export const TYPE_ORDER: InterventionType[] = [
  'overlay_motion',
  'diagram',
  'kinetic_typography',
  'fullscreen_animation',
  'screen_highlight',
  'transition',
  'keep_original',
  'no_intervention',
]

export const STATUS_META: Record<InterventionStatus, { label: string; tone: 'neutral' | 'success' | 'danger' | 'warning' }> = {
  proposed: { label: 'Pendiente', tone: 'neutral' },
  accepted: { label: 'Aceptada', tone: 'success' },
  rejected: { label: 'Rechazada', tone: 'danger' },
  needs_changes: { label: 'Requiere corrección', tone: 'warning' },
}

export const PLAN_STATUS_TONE: Record<PlanStatus, 'neutral' | 'accent' | 'success' | 'danger' | 'warning'> = {
  draft: 'neutral',
  in_review: 'accent',
  approved: 'success',
  rejected: 'danger',
  needs_changes: 'warning',
}

export const SCENE_KIND: Record<string, string> = {
  talking_head: 'Persona a cámara',
  screen_recording: 'Grabación de pantalla',
  app_demo: 'Demostración de app',
  no_face: 'Sin rostro visible',
  b_roll: 'Recurso / b-roll',
  transition_pause: 'Transición o pausa',
  other: 'Otro',
}

export const POLICY: Record<string, string> = {
  open: 'se puede animar',
  light: 'intervenir poco',
  preserve: 'preservar (no tapar)',
}

export const LAYOUT: Record<string, string> = {
  fullscreen: 'Pantalla completa',
  overlay_top: 'Superpuesto arriba',
  overlay_bottom: 'Superpuesto abajo',
  overlay_left: 'Superpuesto a la izquierda',
  overlay_right: 'Superpuesto a la derecha',
  overlay_corner: 'En una esquina',
  around_subject: 'Alrededor del sujeto',
  split_screen: 'Pantalla dividida',
  picture_in_picture: 'Picture-in-picture',
  center: 'Centrado',
}

export const SUBTITLES: Record<string, string> = {
  keep: 'Se mantienen',
  hide: 'Se ocultan durante la animación',
  move_top: 'Se suben',
  move_bottom: 'Se bajan',
  integrate: 'Se integran en la animación',
}

export const TIMING: Record<string, string> = {
  word_anchored: 'anclado a palabras medidas',
  model_seconds: 'segundos propuestos por Claude',
  repaired: 'corregido por la validación',
}

export function fmtT(t: number) {
  const m = Math.floor(t / 60)
  const s = t - m * 60
  return `${m}:${s.toFixed(1).padStart(4, '0')}`
}

export const isPassive = (i: PlanIntervention) => i.type === 'keep_original' || i.type === 'no_intervention'
