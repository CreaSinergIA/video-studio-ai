import { useState } from 'react'
import { useNavigate } from 'react-router'
import { useQueryClient } from '@tanstack/react-query'
import { RefreshCw, Unplug } from 'lucide-react'
import { Button } from '@/components/ui/Button'
import { keys, useStorageStatus } from '@/hooks/queries'

/** Aviso persistente cuando el almacenamiento configurado no está disponible. */
export function StorageBanner() {
  const { data, refetch, isFetching } = useStorageStatus()
  const qc = useQueryClient()
  const navigate = useNavigate()
  const [checking, setChecking] = useState(false)
  if (!data || !data.configured || data.available) return null

  const retry = async () => {
    setChecking(true)
    await refetch()
    qc.invalidateQueries({ queryKey: keys.projects })
    setChecking(false)
  }

  return (
    <div
      role="alert"
      className="flex items-center gap-3 border-b border-warning/25 bg-warning/[0.08] px-5 py-2.5 text-sm animate-fade-in"
    >
      <Unplug className="size-4 shrink-0 text-warning" />
      <p className="min-w-0 flex-1 text-fg">
        <span className="font-semibold">Almacenamiento no disponible.</span>{' '}
        <span className="text-fg-muted">{data.message}</span>
      </p>
      <Button size="sm" variant="ghost" onClick={() => navigate('/settings#storage')}>
        Ajustes
      </Button>
      <Button
        size="sm"
        variant="secondary"
        loading={checking || isFetching}
        icon={<RefreshCw className="size-3.5" />}
        onClick={retry}
      >
        Reintentar
      </Button>
    </div>
  )
}
