import { useEffect, useState } from 'react'
import { LockKeyhole } from 'lucide-react'
import { SESSION_EVENT } from '@/lib/api'

/**
 * La API local exige el token de sesión que entrega el lanzador (cookie HttpOnly). Si el panel
 * se abre sin él (marcador antiguo, otro navegador, token renovado), se explica cómo entrar.
 */
export function SessionGate() {
  const [blocked, setBlocked] = useState(() => new URLSearchParams(window.location.search).get('session') === 'invalid')
  useEffect(() => {
    const onRequired = () => setBlocked(true)
    window.addEventListener(SESSION_EVENT, onRequired)
    return () => window.removeEventListener(SESSION_EVENT, onRequired)
  }, [])
  if (!blocked) return null
  return (
    <div role="alertdialog" aria-labelledby="session-title" className="fixed inset-0 z-[100] grid place-items-center bg-canvas/95 p-6 backdrop-blur">
      <div className="max-w-md rounded-2xl border border-line bg-surface-1 p-7 text-center shadow-panel">
        <div className="mx-auto mb-4 grid size-12 place-items-center rounded-xl bg-surface-3">
          <LockKeyhole className="size-5 text-fg-muted" />
        </div>
        <h1 id="session-title" className="text-lg font-semibold text-fg">
          Abre Video Studio AI desde su lanzador
        </h1>
        <p className="mt-2 text-sm leading-relaxed text-fg-muted">
          Por seguridad, el panel solo funciona en la ventana que abre el lanzador: así ningún otro programa ni otra cuenta de este equipo puede usar tus proyectos.
        </p>
        <ul className="mt-4 space-y-1.5 text-left text-[13px] text-fg-muted">
          <li>
            <span className="font-medium text-fg">macOS:</span> la app «Video Studio AI» de Aplicaciones, «Video Studio AI.command» o <code className="font-mono text-xs">./videostudio open</code>.
          </li>
          <li>
            <span className="font-medium text-fg">Windows:</span> el acceso directo «Video Studio AI» o «Video Studio AI.cmd».
          </li>
        </ul>
        <p className="mt-4 text-xs text-fg-faint">Si ya está en marcha, el lanzador solo abre esta ventana de nuevo: no se reinicia nada.</p>
      </div>
    </div>
  )
}
