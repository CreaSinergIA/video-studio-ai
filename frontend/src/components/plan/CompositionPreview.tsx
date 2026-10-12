import type { AnalysisFrame, PlanIntervention } from '@/lib/types'
import { TYPE_META } from '@/lib/plan'
import { cn } from '@/lib/cn'

/**
 * Fotograma real del video con la composición propuesta encima: zona que ocuparía la
 * animación (color del tipo) y rostros protegidos medidos (rojo discontinuo). Es un esquema
 * de planificación, no un render.
 */
export function CompositionPreview({
  item,
  frame,
  aspect,
  className,
}: {
  item: PlanIntervention
  frame: AnalysisFrame | undefined
  aspect: number
  className?: string
}) {
  const color = TYPE_META[item.type].color
  const full = item.composition.layout === 'fullscreen' || item.type === 'fullscreen_animation'
  const region = full ? { x: 0, y: 0, w: 1, h: 1 } : item.composition.region
  const passive = item.type === 'keep_original' || item.type === 'no_intervention'
  return (
    <div
      className={cn('relative overflow-hidden rounded-lg bg-black ring-1 ring-white/10', className)}
      style={{ aspectRatio: String(aspect) }}
      role="img"
      aria-label={`Esquema de composición: ${TYPE_META[item.type].label}`}
    >
      {frame ? (
        <img src={frame.url} alt="" className="absolute inset-0 size-full object-cover" loading="lazy" />
      ) : (
        <div className="absolute inset-0 grid place-items-center text-[10px] text-white/40">sin fotograma</div>
      )}
      {full && !passive && item.composition.background !== 'original_video' && (
        <div className="absolute inset-0" style={{ background: `${color}33`, backdropFilter: item.composition.background === 'blurred_video' ? 'blur(3px)' : undefined }} />
      )}
      {item.protected_regions.map((r, i) => (
        <div
          key={i}
          className="absolute rounded-sm border border-dashed border-red-400/90"
          style={{ left: `${r.x * 100}%`, top: `${r.y * 100}%`, width: `${r.w * 100}%`, height: `${r.h * 100}%` }}
          title="Rostro detectado (zona protegida)"
        />
      ))}
      {region && !passive && (
        <div
          className="absolute rounded-[3px] border-2"
          style={{
            left: `${region.x * 100}%`,
            top: `${region.y * 100}%`,
            width: `${region.w * 100}%`,
            height: `${region.h * 100}%`,
            borderColor: color,
            background: `${color}26`,
          }}
          title="Zona que ocuparía la animación"
        />
      )}
    </div>
  )
}
