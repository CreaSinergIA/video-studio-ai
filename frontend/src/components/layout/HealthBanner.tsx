import { useNavigate } from 'react-router'
import { useQuery } from '@tanstack/react-query'
import { FlaskConical, TriangleAlert } from 'lucide-react'
import { Button } from '@/components/ui/Button'
import { api } from '@/lib/api'

/** Avisos del arranque: base de datos dañada (con acceso a las copias) o entorno de pruebas. */
export function HealthBanner() {
  const navigate = useNavigate()
  const { data } = useQuery({ queryKey: ['health'], queryFn: api.health, staleTime: 60_000 })
  if (!data) return null
  if (data.db_integrity !== 'ok') {
    return (
      <div role="alert" className="flex items-center gap-3 border-b border-danger/25 bg-danger/[0.08] px-5 py-2.5 text-sm">
        <TriangleAlert className="size-4 shrink-0 text-danger" />
        <p className="min-w-0 flex-1 text-fg">
          <span className="font-semibold">La base de datos no supera la comprobación de integridad.</span>{' '}
          <span className="text-fg-muted">Restaura una copia de seguridad verificada para evitar perder cambios.</span>
        </p>
        <Button size="sm" variant="secondary" onClick={() => navigate('/settings#backups')}>
          Ver copias
        </Button>
      </div>
    )
  }
  if (data.environment === 'test') {
    return (
      <div className="flex items-center gap-2 border-b border-line bg-surface-2 px-5 py-1 text-[11px] text-fg-muted">
        <FlaskConical className="size-3.5" /> Entorno de pruebas: estos datos no son los de tu instancia habitual.
      </div>
    )
  }
  return null
}
