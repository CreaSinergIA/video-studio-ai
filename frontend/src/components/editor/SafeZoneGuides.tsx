import { Bookmark, Heart, MessageCircle, Music2, Send, UserRound } from 'lucide-react'
import type { AnimationLayout, SafeZoneProfile } from '@/lib/types'

/**
 * Guías de composición sobre el reproductor (solo en el panel; nunca se exportan).
 * Dibuja la interfaz de la red social de destino de forma esquemática, la franja de
 * subtítulos, los rostros y la región de las animaciones activas en `time`.
 */
export function SafeZoneGuides({
  profile,
  layout,
  time,
  vertical,
}: {
  profile: SafeZoneProfile | null
  layout: AnimationLayout | null
  time: number
  vertical: boolean
}) {
  const pct = (v: number) => `${(v * 100).toFixed(2)}%`
  const box = (r: { x: number; y: number; w: number; h: number }) => ({ left: pct(r.x), top: pct(r.y), width: pct(r.w), height: pct(r.h) })
  const zones = vertical ? (profile?.zones ?? []) : []
  const active = (layout?.items ?? []).filter((i) => time >= i.start && time <= i.end)
  const isTikTok = (id: string) => id.startsWith('tt_')
  return (
    <div className="pointer-events-none absolute inset-0 overflow-hidden" aria-hidden data-testid="safe-zone-guides">
      {zones.map((z) => (
        <div key={z.id} className="absolute border border-dashed border-rose-300/70 bg-rose-500/15" style={box(z)} title={z.label}>
          {z.id.endsWith('_top') && (
            <div className="flex h-full items-center justify-center gap-3 text-[10px] font-semibold text-white/80">
              {isTikTok(z.id) ? (
                <>
                  <span className="opacity-60">Siguiendo</span>
                  <span>Para ti</span>
                </>
              ) : (
                <span>Reels</span>
              )}
            </div>
          )}
          {z.id.endsWith('_right') && (
            <div className="flex h-full flex-col items-center justify-center gap-[6%] text-white/85">
              <UserRound className="size-4" />
              <Heart className="size-4" />
              <MessageCircle className="size-4" />
              {isTikTok(z.id) ? <Bookmark className="size-4" /> : <Send className="size-4" />}
              <Send className="size-4 -rotate-12 opacity-70" />
            </div>
          )}
          {z.id.endsWith('_bottom') && (
            <div className="flex h-full flex-col justify-end gap-1 p-[4%] text-[9px] text-white/80">
              <div className="h-1.5 w-1/3 rounded bg-white/60" />
              <div className="h-1.5 w-2/3 rounded bg-white/40" />
              <div className="flex items-center gap-1">
                <Music2 className="size-2.5" />
                <div className="h-1.5 w-1/2 rounded bg-white/40" />
              </div>
            </div>
          )}
        </div>
      ))}
      {layout?.subtitle_band && (
        <div
          className="absolute inset-x-0 border-y border-dashed border-sky-300/70 bg-sky-400/10"
          style={{ top: pct(layout.subtitle_band[0]), height: pct(layout.subtitle_band[1] - layout.subtitle_band[0]) }}
        >
          <span className="absolute left-1 top-0.5 rounded bg-sky-500/70 px-1 text-[9px] font-semibold text-white">Subtítulos</span>
        </div>
      )}
      {active.flatMap((i) =>
        i.faces.map((f, k) => (
          <div key={`${i.intervention_id}-f${k}`} className="absolute rounded-md border-2 border-amber-300/90" style={box(f)}>
            <span className="absolute -top-4 left-0 rounded bg-amber-400/80 px-1 text-[9px] font-semibold text-black">Rostro</span>
          </div>
        )),
      )}
      {active.map((i) => {
        const warn = i.warnings.length > 0
        return (
          <div
            key={i.intervention_id}
            className={`absolute rounded-md border-2 ${warn ? 'border-orange-400 bg-orange-400/15' : 'border-emerald-400/90 bg-emerald-400/10'}`}
            style={box(i.region)}
            title={warn ? i.warnings.map((w) => w.message).join('\n') : undefined}
          >
            <span className={`absolute -top-4 right-0 rounded px-1 text-[9px] font-semibold ${warn ? 'bg-orange-400 text-black' : 'bg-emerald-500/90 text-white'}`}>
              {warn ? '⚠ ' : ''}
              {i.template}
            </span>
          </div>
        )
      })}
    </div>
  )
}
