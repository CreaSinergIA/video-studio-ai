import { useState } from 'react'
import { useQueryClient } from '@tanstack/react-query'
import { DatabaseBackup, History, ShieldCheck, TriangleAlert } from 'lucide-react'
import { toast } from 'sonner'
import { Button } from '@/components/ui/Button'
import { Dialog } from '@/components/ui/Dialog'
import { Badge, Section } from '@/components/ui/feedback'
import { keys, useBackups } from '@/hooks/queries'
import { ApiError, api } from '@/lib/api'
import { formatBytes, formatRelative } from '@/lib/format'
import type { BackupItem } from '@/lib/types'

const KIND: Record<BackupItem['kind'], string> = {
  auto: 'Automática',
  manual: 'Manual',
  'pre-migracion': 'Antes de actualizar',
  'antes-de-restaurar': 'Antes de restaurar',
  'pre-fase': 'Punto de restauración',
  otra: 'Otra',
}

export function BackupsSection() {
  const qc = useQueryClient()
  const { data } = useBackups()
  const [busy, setBusy] = useState(false)
  const [restore, setRestore] = useState<BackupItem | null>(null)
  const run = async (fn: () => Promise<unknown>, ok: string) => {
    setBusy(true)
    try {
      await fn()
      toast.success(ok)
      await qc.invalidateQueries({ queryKey: keys.backups })
      return true
    } catch (err) {
      toast.error('No se pudo completar', { description: err instanceof ApiError ? err.message : String(err) })
      return false
    } finally {
      setBusy(false)
    }
  }
  return (
    <Section
      title="Datos y respaldos"
      description="Copias verificadas de la base de datos de proyectos, planes y versiones (los videos y exportaciones viven en tu almacenamiento y no se tocan)."
    >
      <div className="space-y-3">
        <div className="flex flex-wrap items-center gap-2 text-sm">
          {data?.integrity === 'ok' ? (
            <Badge tone="success" icon={<ShieldCheck className="size-3.5" />}>
              Base de datos íntegra
            </Badge>
          ) : (
            <Badge tone="danger" icon={<TriangleAlert className="size-3.5" />}>
              La base de datos no supera la comprobación de integridad: restaura una copia
            </Badge>
          )}
          <span className="text-xs text-fg-faint">Copias automáticas: al arrancar (cada ~20 h; se conservan 7) y antes de cada actualización.</span>
          <Button className="ml-auto" size="sm" variant="secondary" icon={<DatabaseBackup className="size-3.5" />} loading={busy} onClick={() => void run(api.createBackup, 'Copia creada y verificada')}>
            Crear copia ahora
          </Button>
        </div>
        <ul className="divide-y divide-line rounded-xl border border-line">
          {(data?.items ?? []).slice(0, 15).map((b) => (
            <li key={b.name} className="flex items-center gap-3 px-3 py-2 text-xs">
              <History className="size-3.5 shrink-0 text-fg-faint" />
              <span className="min-w-0 flex-1 truncate font-mono text-fg" title={b.name}>
                {b.name}
              </span>
              <Badge className="h-5 text-[10.5px]">{KIND[b.kind]}</Badge>
              <span className="w-20 text-right tabular text-fg-muted">{formatBytes(b.size)}</span>
              <span className="w-28 text-right text-fg-faint">{formatRelative(b.created_at)}</span>
              <Button size="sm" variant="ghost" className="h-6 px-2 text-[11px]" disabled={busy} onClick={() => setRestore(b)}>
                Restaurar…
              </Button>
            </li>
          ))}
          {data && data.items.length === 0 && <li className="px-3 py-2 text-xs text-fg-faint">Todavía no hay copias.</li>}
        </ul>
        {data && <p className="text-[11px] text-fg-faint">Carpeta: {data.directory}</p>}
      </div>
      <Dialog
        open={Boolean(restore)}
        onOpenChange={(o) => !o && setRestore(null)}
        size="sm"
        tone="danger"
        icon={<TriangleAlert className="size-5" />}
        title="¿Restaurar esta copia?"
        description={`La base de datos volverá al estado de «${restore?.name}». Antes se guarda una copia del estado actual («antes de restaurar»), así que puedes deshacerlo. Los videos y exportaciones no cambian.`}
        footer={
          <>
            <Button variant="secondary" onClick={() => setRestore(null)}>
              Cancelar
            </Button>
            <Button
              variant="danger"
              loading={busy}
              onClick={() =>
                restore &&
                void run(() => api.restoreBackup(restore.name), 'Copia restaurada').then((ok) => {
                  if (ok) {
                    setRestore(null)
                    void qc.invalidateQueries()
                  }
                })
              }
            >
              Restaurar
            </Button>
          </>
        }
      />
    </Section>
  )
}
