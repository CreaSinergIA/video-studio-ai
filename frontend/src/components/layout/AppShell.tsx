import { useEffect, useRef } from 'react'
import { NavLink, Outlet, useLocation, useNavigate } from 'react-router'
import { useQueryClient } from '@tanstack/react-query'
import { Clapperboard, HardDrive, LayoutGrid, Settings2 } from 'lucide-react'
import { toast } from 'sonner'
import { Tooltip } from '@/components/ui/feedback'
import { keys, useJobs, useSettings, useSetupStatus, useStorageStatus } from '@/hooks/queries'
import { api } from '@/lib/api'
import { cn } from '@/lib/cn'
import { loadSubtitleFonts } from '@/lib/subtitleState'
import { formatBytes, FILE_MANAGER } from '@/lib/format'
import { ImportTray } from './ImportTray'
import { HealthBanner } from './HealthBanner'
import { SessionGate } from './SessionGate'
import { StorageBanner } from './StorageBanner'

function Logo() {
  return (
    <div className="relative grid size-10 place-items-center rounded-xl bg-gradient-to-br from-[#9d8cff] to-[#5b8cff] shadow-[0_10px_30px_-10px_#7c6cff]">
      <Clapperboard className="size-[19px] text-white" strokeWidth={2.2} />
    </div>
  )
}

function NavItem({ to, label, icon }: { to: string; label: string; icon: React.ReactNode }) {
  return (
    <NavLink
      to={to}
      end={to === '/'}
      className={({ isActive }) =>
        cn(
          'group flex w-14 flex-col items-center gap-1 rounded-xl py-2 text-[10.5px] font-medium transition',
          isActive ? 'bg-surface-3 text-fg' : 'text-fg-faint hover:bg-surface-2 hover:text-fg-muted',
        )
      }
    >
      <span className="[&>svg]:size-[19px]">{icon}</span>
      {label}
    </NavLink>
  )
}

function StorageIndicator() {
  const { data } = useStorageStatus()
  const state = !data ? 'loading' : !data.configured ? 'none' : data.available ? 'ok' : 'error'
  const color = {
    loading: 'bg-fg-faint',
    none: 'bg-warning',
    ok: 'bg-success',
    error: 'bg-danger',
  }[state]
  const content =
    state === 'ok' && data
      ? `${data.volume_name ? `Disco «${data.volume_name}»` : 'Almacenamiento'} conectado · ${formatBytes(data.free_bytes)} libres`
      : (data?.message ?? 'Comprobando almacenamiento…')
  return (
    <Tooltip content={content} side="right">
      <NavLink
        to="/settings#storage"
        className="relative grid size-10 place-items-center rounded-xl text-fg-faint transition hover:bg-surface-2 hover:text-fg"
        aria-label={content}
      >
        <HardDrive className="size-[18px]" />
        <span className={cn('absolute right-2 top-2 size-2 rounded-full ring-2 ring-canvas', color)} />
      </NavLink>
    </Tooltip>
  )
}

/** Registra las tipografías TTF de subtítulos (las mismas que usa la exportación). */
function SubtitleFontLoader() {
  useEffect(() => {
    void api
      .fonts()
      .then(loadSubtitleFonts)
      .catch(() => undefined)
  }, [])
  return null
}

/** Aplica tema y movimiento reducido según las preferencias guardadas. */
function PreferenceApplier() {
  const { data } = useSettings()
  const theme = data?.general.theme ?? 'dark'
  const motion = data?.general.reduce_motion ?? 'system'
  useEffect(() => {
    const root = document.documentElement
    const media = window.matchMedia('(prefers-color-scheme: light)')
    const apply = () => {
      root.dataset.theme = theme === 'system' ? (media.matches ? 'light' : 'dark') : theme
    }
    apply()
    media.addEventListener('change', apply)
    root.dataset.motion = motion === 'on' ? 'reduce' : motion === 'off' ? 'full' : 'system'
    return () => media.removeEventListener('change', apply)
  }, [theme, motion])
  return null
}

/** Refresca proyectos cuando termina una tarea y avisa de los fallos. */
function JobWatcher() {
  const qc = useQueryClient()
  const { data: jobs } = useJobs()
  const seen = useRef(new Map<string, string>())
  useEffect(() => {
    if (!jobs) return
    let changed = false
    for (const job of jobs) {
      const previous = seen.current.get(job.id)
      if (previous && previous !== job.status) {
        changed = true
        if (job.status === 'failed') {
          toast.error(job.label, { description: job.error ?? 'La tarea falló.' })
        } else if (job.status === 'succeeded' && job.kind === 'export') {
          const exportId = typeof job.result?.export_id === 'string' ? job.result.export_id : null
          toast.success('Exportación terminada y verificada', {
            description: 'También disponible en «Exportar» del proyecto.',
            action: exportId ? { label: `Mostrar en ${FILE_MANAGER}`, onClick: () => void api.revealExport(exportId) } : undefined,
            duration: 10_000,
          })
        } else if (job.status === 'succeeded' && job.kind === 'scene_revise') {
          toast.success('Nueva versión de la escena lista', { description: 'Compárala con la versión en uso antes de aplicarla.' })
        } else if (job.status === 'succeeded' && job.kind === 'download_model') {
          toast.success('Modelo de transcripción instalado y verificado')
        } else if (job.status === 'succeeded' && job.kind === 'verify') {
          toast.success('Original verificado', {
            description: 'El archivo coincide byte a byte con el importado.',
          })
        }
      }
      if (!previous && job.status !== 'queued' && job.status !== 'running') changed = true
      seen.current.set(job.id, job.status)
    }
    if (changed) {
      qc.invalidateQueries({ queryKey: keys.projects })
      // Fase 2: resultados que dependen de tareas (análisis, pista, exportaciones, modelos).
      qc.invalidateQueries({ queryKey: ['analysis'] })
      qc.invalidateQueries({ queryKey: ['track'] })
      qc.invalidateQueries({ queryKey: ['exports'] })
      // Fase 5: escenas, animaciones y plan (una escena aplicada crea una versión del plan).
      qc.invalidateQueries({ queryKey: ['scene'] })
      qc.invalidateQueries({ queryKey: ['animations'] })
      qc.invalidateQueries({ queryKey: ['plan'] })
      qc.invalidateQueries({ queryKey: keys.asrModels })
      qc.invalidateQueries({ queryKey: keys.engine })
      qc.invalidateQueries({ queryKey: keys.setup })
    }
  }, [jobs, qc])
  return null
}

/** Primera ejecución: lleva una sola vez al asistente si aún no se completó. */
function SetupRedirect() {
  const { data } = useSetupStatus()
  const location = useLocation()
  const navigate = useNavigate()
  const done = useRef(false)
  useEffect(() => {
    if (!data || done.current) return
    done.current = true
    if (!data.completed_at && location.pathname !== '/setup') navigate('/setup', { replace: true })
  }, [data, location.pathname, navigate])
  return null
}

export function AppShell() {
  return (
    <div className="flex h-full bg-canvas">
      <PreferenceApplier />
      <SubtitleFontLoader />
      <JobWatcher />
      <SetupRedirect />
      <SessionGate />
      <aside className="flex w-[76px] shrink-0 flex-col items-center gap-2 border-r border-line bg-surface-1/60 py-4">
        <NavLink to="/" aria-label="Video Studio AI — Biblioteca" className="mb-4">
          <Logo />
        </NavLink>
        <nav className="flex flex-col items-center gap-1.5" aria-label="Navegación principal">
          <NavItem to="/" label="Biblioteca" icon={<LayoutGrid />} />
          <NavItem to="/settings" label="Ajustes" icon={<Settings2 />} />
        </nav>
        <div className="mt-auto flex flex-col items-center gap-2">
          <StorageIndicator />
          {/* Atribución discreta: solo en el panel, nunca en los videos ni en las vistas previas. */}
          <NavLink to="/settings#about" className="px-1 text-center text-[8.5px] leading-tight text-fg-faint/70 transition hover:text-fg-muted" title="Acerca de Video Studio AI">
            Created by Gabo
          </NavLink>
        </div>
      </aside>
      <div className="flex min-w-0 flex-1 flex-col">
        <HealthBanner />
        <StorageBanner />
        <main className="relative min-h-0 flex-1 overflow-hidden">
          <Outlet />
        </main>
      </div>
      <ImportTray />
    </div>
  )
}
