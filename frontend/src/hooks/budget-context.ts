import { createContext, useCallback, useContext } from 'react'
import { ApiError } from '@/lib/api'

/** Detalle que envía el backend con el error «budget_confirm». */
export interface BudgetDetails {
  used_24h: number
  limit_24h: number
  estimate: { operation: string; expected: number; maximum: number }
  billing: 'subscription' | 'api'
}

/** La operación se canceló al no confirmar el presupuesto (no es un error que mostrar). */
export class BudgetDeclined extends Error {
  constructor() {
    super('Operación cancelada: no se confirmó el uso adicional de Claude.')
  }
}

export type Ask = (message: string, details: BudgetDetails) => Promise<boolean>
export const BudgetCtx = createContext<Ask | null>(null)

/** Ejecuta una operación con Claude; si supera el límite autorizado, pide confirmación
 *  explícita y la repite con `confirm_budget`. Si el usuario cancela, lanza BudgetDeclined. */
export function useBudget() {
  const ask = useContext(BudgetCtx)
  return useCallback(
    async <T>(call: (confirm: boolean) => Promise<T>): Promise<T> => {
      try {
        return await call(false)
      } catch (err) {
        if (!(err instanceof ApiError) || err.code !== 'budget_confirm' || !ask) throw err
        const ok = await ask(err.message, err.details as unknown as BudgetDetails)
        if (!ok) throw new BudgetDeclined()
        return call(true)
      }
    },
    [ask],
  )
}
