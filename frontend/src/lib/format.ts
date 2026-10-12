import type { Asset, StyleId } from './types'

export function formatBytes(bytes: number | null | undefined, digits = 1): string {
  if (bytes === null || bytes === undefined || !Number.isFinite(bytes)) return '—'
  const units = ['B', 'KB', 'MB', 'GB', 'TB']
  let value = bytes
  let unit = 0
  while (value >= 1024 && unit < units.length - 1) {
    value /= 1024
    unit++
  }
  return `${unit === 0 ? value : value.toFixed(digits)} ${units[unit]}`
}

/** 75.4 → "1:15" · 3725 → "1:02:05" */
export function formatDuration(seconds: number | null | undefined): string {
  if (seconds === null || seconds === undefined || !Number.isFinite(seconds)) return '—'
  const total = Math.max(0, Math.round(seconds))
  const h = Math.floor(total / 3600)
  const m = Math.floor((total % 3600) / 60)
  const s = total % 60
  return h > 0 ? `${h}:${String(m).padStart(2, '0')}:${String(s).padStart(2, '0')}` : `${m}:${String(s).padStart(2, '0')}`
}

/** Código de tiempo con centésimas: 01:15.40 */
export function formatTimecode(seconds: number): string {
  const safe = Math.max(0, seconds || 0)
  const h = Math.floor(safe / 3600)
  const m = Math.floor((safe % 3600) / 60)
  const s = Math.floor(safe % 60)
  const cs = Math.floor((safe % 1) * 100)
  const base = `${String(m).padStart(2, '0')}:${String(s).padStart(2, '0')}.${String(cs).padStart(2, '0')}`
  return h > 0 ? `${h}:${base}` : base
}

export function formatFps(fps: number): string {
  return Number.isInteger(fps) ? `${fps} fps` : `${fps.toFixed(2)} fps`
}

export function formatBitrate(bps: number | null | undefined): string {
  if (!bps) return '—'
  return bps >= 1_000_000 ? `${(bps / 1_000_000).toFixed(1)} Mb/s` : `${Math.round(bps / 1000)} kb/s`
}

export function formatResolution(asset: Pick<Asset, 'display_width' | 'display_height'>): string {
  return `${asset.display_width}×${asset.display_height}`
}

export function resolutionLabel(asset: Pick<Asset, 'display_width' | 'display_height'>): string {
  const short = Math.min(asset.display_width, asset.display_height)
  if (short >= 2160) return '4K'
  if (short >= 1440) return '1440p'
  if (short >= 1080) return '1080p'
  if (short >= 720) return '720p'
  return `${short}p`
}

const dateFormatter = new Intl.DateTimeFormat('es', {
  day: 'numeric',
  month: 'short',
  year: 'numeric',
})
const dateTimeFormatter = new Intl.DateTimeFormat('es', {
  day: 'numeric',
  month: 'short',
  year: 'numeric',
  hour: '2-digit',
  minute: '2-digit',
})
const relative = new Intl.RelativeTimeFormat('es', { numeric: 'auto' })

export function formatDate(iso: string | null | undefined): string {
  return iso ? dateFormatter.format(new Date(iso)) : '—'
}

export function formatDateTime(iso: string | null | undefined): string {
  return iso ? dateTimeFormatter.format(new Date(iso)) : '—'
}

export function formatRelative(iso: string | null | undefined): string {
  if (!iso) return '—'
  const diff = (new Date(iso).getTime() - Date.now()) / 1000
  const abs = Math.abs(diff)
  if (abs < 45) return 'justo ahora'
  if (abs < 3600) return relative.format(Math.round(diff / 60), 'minute')
  if (abs < 86400) return relative.format(Math.round(diff / 3600), 'hour')
  if (abs < 86400 * 7) return relative.format(Math.round(diff / 86400), 'day')
  return formatDate(iso)
}

const CODECS: Record<string, string> = {
  h264: 'H.264',
  hevc: 'HEVC (H.265)',
  prores: 'Apple ProRes',
  av1: 'AV1',
  vp9: 'VP9',
  aac: 'AAC',
  mp3: 'MP3',
  alac: 'ALAC',
  opus: 'Opus',
  pcm_s16le: 'PCM 16 bits',
  pcm_s24le: 'PCM 24 bits',
}

export function codecLabel(codec: string | null | undefined): string {
  if (!codec) return '—'
  return CODECS[codec] ?? codec.toUpperCase()
}

export const ORIENTATION_LABEL: Record<Asset['orientation'], string> = {
  vertical: 'Vertical',
  horizontal: 'Horizontal',
  square: 'Cuadrado',
}

export const STYLE_META: Record<StyleId, { name: string; color: string; textClass: string }> = {
  motion_tech: { name: 'Motion Tech', color: '#22d3ee', textClass: 'text-tech' },
  minimal_motion: { name: 'Minimal Motion', color: '#e8e1d6', textClass: 'text-minimal' },
  creative_explainer: { name: 'Creative Explainer', color: '#ff7a59', textClass: 'text-creative' },
}

/** Gestor de archivos del sistema del usuario, para los textos del panel. */
export const IS_WINDOWS = typeof navigator !== 'undefined' && /Windows/i.test(navigator.userAgent)
export const FILE_MANAGER = IS_WINDOWS ? 'el Explorador' : 'Finder'
