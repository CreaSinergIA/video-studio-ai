import { useQueryClient } from '@tanstack/react-query'
import { CircleAlert, CircleCheck, Download, Play } from 'lucide-react'
import { toast } from 'sonner'
import { Button } from '@/components/ui/Button'
import { Badge, ProgressBar, Section } from '@/components/ui/feedback'
import { keys, useEngine, useSfx } from '@/hooks/queries'
import { ApiError, api } from '@/lib/api'
import { formatBytes, formatRelative } from '@/lib/format'

function Row({ label, ok, children }: { label: string; ok: boolean; children: React.ReactNode }) {
  return (
    <div className="flex items-start gap-3 py-2 text-[13px]">
      {ok ? <CircleCheck className="mt-0.5 size-4 shrink-0 text-success" /> : <CircleAlert className="mt-0.5 size-4 shrink-0 text-warning" />}
      <span className="w-40 shrink-0 text-fg-muted">{label}</span>
      <span className="min-w-0 flex-1 text-fg">{children}</span>
    </div>
  )
}

export function EngineSection() {
  const qc = useQueryClient()
  const { data: st } = useEngine()
  const { data: sfx } = useSfx()
  const play = (kind: string) => {
    const a = new Audio(`/api/animations/sfx/${kind}`)
    void a.play().catch(() => undefined)
  }
  return (
    <Section
      title="Motor de animaciones"
      description="Las animaciones se generan por código en este equipo con Remotion (React + SVG), a partir del plan aprobado. No se usa ningún servicio externo de video. Remotion tiene licencia propia: es gratuito para personas y empresas de hasta 3 personas; las organizaciones mayores necesitan su licencia de empresa (remotion.pro/license). El navegador de render se descarga de su fuente oficial."
    >
      <div className="rounded-xl border border-line bg-surface-2 p-4">
        <div className="mb-1 flex items-center gap-2">
          <span className="text-[13.5px] font-semibold text-fg">Estado</span>
          {st && <Badge tone={st.ready ? 'success' : 'warning'} className="ml-auto">{st.ready ? 'Listo' : 'Falta configurar'}</Badge>}
        </div>
        {st && (
          <div className="divide-y divide-line">
            <Row label="Node.js" ok={Boolean(st.node.path)}>
              {st.node.version ?? 'No encontrado'} <span className="font-mono text-xs text-fg-muted">{st.node.path}</span>
            </Row>
            <Row label="Remotion" ok={st.remotion.installed === st.remotion.expected}>
              {st.remotion.installed ? `v${st.remotion.installed}` : 'No instalado'}
              {st.remotion.installed !== st.remotion.expected && ` (se espera v${st.remotion.expected})`}
            </Row>
            <Row label="Navegador de render" ok={st.browser.installed}>
              {st.browser.installed ? (
                <span>
                  {st.browser.name} {st.browser.version}
                  {st.browser.codesign ? ` · firma ${st.browser.codesign}` : ' · verificado por SHA-256'}
                  <span className="mt-0.5 block font-mono text-[11px] text-fg-muted">SHA-256 {st.browser.sha256?.slice(0, 24)}… · instalado {formatRelative(st.browser.installed_at)}</span>
                </span>
              ) : (
                <span>
                  No instalado. Descarga oficial de Google («Chrome for Testing», {formatBytes(st.browser.download_bytes)}), verificada con las huellas publicadas (y, en macOS, la firma de código).
                </span>
              )}
            </Row>
          </div>
        )}
        {st?.job && (
          <div className="mt-3">
            <div className="mb-1 flex justify-between text-xs text-fg-muted">
              <span>{st.job.stage ?? 'Descargando'}</span>
              <span className="tabular">{Math.round(st.job.progress * 100)} %</span>
            </div>
            <ProgressBar value={st.job.progress} label="Instalación del navegador de render" />
          </div>
        )}
        {st && !st.browser.installed && !st.job && (
          <Button
            className="mt-3"
            size="sm"
            variant="primary"
            icon={<Download className="size-3.5" />}
            onClick={async () => {
              try {
                await api.installEngine()
                qc.invalidateQueries({ queryKey: keys.engine })
              } catch (err) {
                toast.error('No se pudo iniciar la descarga', { description: err instanceof ApiError ? err.message : String(err) })
              }
            }}
          >
            Descargar navegador de render ({st ? formatBytes(st.browser.download_bytes) : ''})
          </Button>
        )}
        {st && <p className="mt-3 text-xs leading-relaxed text-fg-faint">{st.license}</p>}
      </div>

      <h3 className="mb-2 mt-5 text-xs font-semibold uppercase tracking-wider text-fg-faint">Efectos de sonido (generados por programa, sin licencias de terceros)</h3>
      <div className="grid grid-cols-2 gap-2 md:grid-cols-3">
        {sfx?.map((s) => (
          <button
            key={s.kind}
            type="button"
            onClick={() => play(s.kind)}
            className="flex items-center gap-2 rounded-lg border border-line bg-surface-2 px-3 py-2 text-left text-[13px] text-fg transition hover:bg-surface-3"
            aria-label={`Escuchar ${s.label}`}
          >
            <Play className="size-3.5 text-accent" />
            <span className="min-w-0 flex-1 truncate">{s.label}</span>
            <span className="text-[11px] tabular text-fg-faint">{s.duration.toFixed(2)} s</span>
          </button>
        ))}
      </div>
    </Section>
  )
}
