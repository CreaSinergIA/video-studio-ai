import { useCallback, useRef, useState, type ReactNode } from 'react'
import { Gauge } from 'lucide-react'
import { Button } from '@/components/ui/Button'
import { Dialog } from '@/components/ui/Dialog'
import { BudgetCtx, type Ask, type BudgetDetails } from './budget-context'

export function BudgetProvider({ children }: { children: ReactNode }) {
  const [state, setState] = useState<{ message: string; details: BudgetDetails } | null>(null)
  const resolver = useRef<((ok: boolean) => void) | null>(null)
  const ask = useCallback<Ask>(
    (message, details) =>
      new Promise<boolean>((resolve) => {
        // Una sola confirmación a la vez: la anterior (si quedaba abierta) se da por cancelada.
        resolver.current?.(false)
        resolver.current = resolve
        setState({ message, details })
      }),
    [],
  )
  const close = (ok: boolean) => {
    resolver.current?.(ok)
    resolver.current = null
    setState(null)
  }
  const d = state?.details
  return (
    <BudgetCtx.Provider value={ask}>
      {children}
      <Dialog
        open={Boolean(state)}
        onOpenChange={(o) => !o && close(false)}
        size="sm"
        icon={<Gauge className="size-5" />}
        title="Confirmar solicitudes a Claude"
        description={state?.message}
        footer={
          <>
            <Button variant="secondary" onClick={() => close(false)}>
              Cancelar
            </Button>
            <Button variant="primary" onClick={() => close(true)}>
              Continuar solo esta vez
            </Button>
          </>
        }
      >
        {d && (
          <dl className="grid grid-cols-2 gap-x-4 gap-y-1.5 text-sm">
            <dt className="text-fg-muted">Usadas en 24 h</dt>
            <dd className="tabular text-fg">
              {d.used_24h} de {d.limit_24h}
            </dd>
            <dt className="text-fg-muted">Esta operación</dt>
            <dd className="tabular text-fg">
              {d.estimate.expected} (hasta {d.estimate.maximum} con reintentos)
            </dd>
            <dt className="col-span-2 mt-1 text-xs leading-relaxed text-fg-faint">
              {d.billing === 'subscription'
                ? 'Con Claude Code y tu plan no hay cargos por solicitud: se consumen los límites de uso del plan. El límite de 24 h es tu autorización en Video Studio AI (Ajustes → Claude).'
                : 'Con la API se factura por tokens según la tarifa de Anthropic.'}
            </dt>
          </dl>
        )}
      </Dialog>
    </BudgetCtx.Provider>
  )
}
