import { Check } from 'lucide-react'
import { cn } from '@/lib/cn'

export type FlowStepId = 'import' | 'analyze' | 'customize' | 'plan' | 'approve' | 'generate' | 'review' | 'export'

export interface FlowStep {
  id: FlowStepId
  label: string
  done: boolean
  hint: string
}

/** Pasos del flujo de edición (Importar → … → Exportar) con el estado real del proyecto.
 *  El primer paso sin completar se resalta como «siguiente»; cada paso lleva a su lugar. */
export function FlowSteps({ steps, onSelect }: { steps: FlowStep[]; onSelect: (id: FlowStepId) => void }) {
  const next = steps.find((s) => !s.done)?.id
  return (
    <nav aria-label="Progreso del proyecto" className="flex min-w-0 items-center gap-0.5 overflow-x-auto">
      {steps.map((s, i) => (
        <button
          key={s.id}
          type="button"
          onClick={() => onSelect(s.id)}
          title={s.hint}
          aria-current={s.id === next ? 'step' : undefined}
          className={cn(
            'flex shrink-0 items-center gap-1 rounded-md px-1.5 py-1 text-[11px] font-medium transition hover:bg-surface-3',
            s.done ? 'text-fg-muted' : s.id === next ? 'bg-accent-soft text-accent' : 'text-fg-faint',
          )}
        >
          {s.done ? (
            <Check className="size-3 text-success" aria-hidden />
          ) : (
            <span className="grid size-3.5 place-items-center rounded-full border border-current text-[8px]">{i + 1}</span>
          )}
          {s.label}
          <span className="sr-only">{s.done ? '(completado)' : s.id === next ? '(siguiente paso)' : '(pendiente)'}</span>
        </button>
      ))}
    </nav>
  )
}
