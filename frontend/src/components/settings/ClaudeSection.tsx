import { useState } from 'react'
import { useQueryClient } from '@tanstack/react-query'
import { CircleAlert, CircleCheck, LogIn, PlugZap, RefreshCw } from 'lucide-react'
import { toast } from 'sonner'
import { Button } from '@/components/ui/Button'
import { Badge, ProgressBar, Section } from '@/components/ui/feedback'
import { Field, Segmented, Slider } from '@/components/ui/fields'
import { ClaudeKeyForm, ClaudePricing } from './ClaudeKeyForm'
import { keys, useClaudeBudget, useClaudeSettings, useClaudeStatus, useClaudeUsage } from '@/hooks/queries'
import { ApiError, api } from '@/lib/api'
import { formatRelative } from '@/lib/format'
import type { ClaudeCheck, ClaudePreferences, RateLimitInfo } from '@/lib/types'

const errorText = (err: unknown) => (err instanceof ApiError ? err.message : String(err))

const WINDOW_LABEL: Record<string, string> = { five_hour: 'Ventana de 5 horas', seven_day: 'Ventana de 7 días' }

function Row({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div className="flex items-start justify-between gap-4 py-1.5 text-[13px]">
      <span className="shrink-0 text-fg-muted">{label}</span>
      <span className="min-w-0 text-right text-fg">{children}</span>
    </div>
  )
}

function Limits({ info }: { info: RateLimitInfo }) {
  const windows = Object.entries(info.unifiedWindows ?? {})
  return (
    <div className="mt-3 rounded-xl border border-line bg-surface-2 p-3.5">
      <div className="mb-2 flex items-center justify-between text-xs font-semibold uppercase tracking-wider text-fg-faint">
        <span>Límites de uso del plan</span>
        <span className="font-normal normal-case tracking-normal">informado por Claude Code en la última solicitud</span>
      </div>
      {windows.map(([key, w]) => (
        <div key={key} className="mb-2.5">
          <div className="mb-1 flex justify-between text-xs text-fg-muted">
            <span>{WINDOW_LABEL[key] ?? key}</span>
            <span className="tabular">
              {Math.round(w.utilization * 100)} % · se restablece {formatRelative(new Date(w.resetsAt * 1000).toISOString())}
            </span>
          </div>
          <ProgressBar value={w.utilization} label={WINDOW_LABEL[key] ?? key} />
        </div>
      ))}
      <p className="text-xs leading-relaxed text-fg-muted">
        {info.isUsingOverage
          ? 'Atención: la cuenta está usando uso extra (puede generar cargos).'
          : info.overageStatus === 'rejected'
            ? 'Uso extra desactivado: si se agotan los límites, las solicitudes se rechazan; no se generan cargos adicionales.'
            : `Uso extra de la cuenta: ${info.overageStatus ?? 'desconocido'} (si está permitido, superar los límites podría generar cargos).`}
      </p>
    </div>
  )
}

function LastCheck({ check }: { check: ClaudeCheck }) {
  return (
    <div className={`mt-3 rounded-xl border p-3.5 text-[13px] ${check.ok ? 'border-success/25 bg-success/5' : 'border-danger/25 bg-danger/5'}`}>
      <div className="flex items-center gap-2 font-medium">
        {check.ok ? <CircleCheck className="size-4 text-success" /> : <CircleAlert className="size-4 text-danger" />}
        {check.ok ? 'Última prueba real correcta' : 'La última prueba falló'}
        <span className="ml-auto text-xs font-normal text-fg-faint">{formatRelative(check.checked_at)}</span>
      </div>
      {check.ok ? (
        <p className="mt-1 text-xs text-fg-muted">
          Respondió <span className="font-mono text-fg">{check.model_reported}</span> con esfuerzo {check.effort} en{' '}
          {((check.duration_ms ?? 0) / 1000).toFixed(1)} s{check.cli_version ? ` · Claude Code ${check.cli_version}` : ''}
          {check.cost_estimate_usd != null && check.billing === 'api' ? ` · coste estimado ≈ ${check.cost_estimate_usd.toFixed(4)} USD` : ''}.
        </p>
      ) : (
        <p className="mt-1 text-xs text-danger">{check.error}</p>
      )}
    </div>
  )
}

export function ClaudeSection() {
  const qc = useQueryClient()
  const status = useClaudeStatus()
  const { data: prefs } = useClaudeSettings()
  const [testing, setTesting] = useState(false)
  const s = status.data

  const save = async (patch: Partial<ClaudePreferences>) => {
    if (!prefs) return
    const next = { ...prefs, ...patch }
    qc.setQueryData(keys.claudeSettings, next)
    try {
      await api.saveClaudeSettings(next)
    } catch (err) {
      toast.error('No se pudo guardar', { description: errorText(err) })
    }
    qc.invalidateQueries({ queryKey: keys.claudeSettings })
    qc.invalidateQueries({ queryKey: keys.claudeStatus })
  }
  const test = async () => {
    setTesting(true)
    try {
      const r = await api.testClaude()
      if (r.ok) toast.success('Claude Opus 5.5 conectado', { description: `Respondió ${r.model_reported} en ${((r.duration_ms ?? 0) / 1000).toFixed(1)} s.` })
      else toast.error('La prueba de conexión falló', { description: r.error })
    } catch (err) {
      toast.error('La prueba de conexión falló', { description: errorText(err) })
    } finally {
      setTesting(false)
      qc.invalidateQueries({ queryKey: keys.claudeStatus })
    }
  }

  const state = !s
    ? null
    : s.verified
      ? { tone: 'success' as const, label: 'Conectado y verificado' }
      : s.ready
        ? { tone: 'warning' as const, label: 'Listo · sin verificar' }
        : { tone: 'danger' as const, label: 'No conectado' }

  return (
    <Section
      title="Director creativo (Claude)"
      description="Claude Opus 5.5 interpreta tu video y propone el plan de edición. Recibe la transcripción con sus tiempos, los datos de escenas y rostros, tus preferencias y unos pocos fotogramas reducidos; nunca el archivo de video. Se conecta con TU PROPIA clave de API de Anthropic: Video Studio AI es gratuito, pero el uso de Claude se factura en tu cuenta de Anthropic según su tarifa y sus límites."
    >
      <div className="rounded-xl border border-line bg-surface-2 p-4">
        <div className="mb-2 flex items-center gap-2">
          <PlugZap className="size-4 text-fg-muted" />
          <span className="text-[13.5px] font-semibold text-fg">Estado de la conexión</span>
          {state && (
            <Badge tone={state.tone} className="ml-auto">
              {state.label}
            </Badge>
          )}
        </div>
        {status.isLoading && <p className="text-sm text-fg-muted">Comprobando…</p>}
        {s && (
          <div className="divide-y divide-line">
            <Row label="Mecanismo">
              {s.transport === 'claude_code' ? 'Claude Code (modo headless oficial)' : 'Messages API (clave en el llavero)'}
            </Row>
            {s.transport === 'claude_code' && s.cli && (
              <>
                <Row label="Instalación">
                  {s.cli.installed ? (
                    <span>
                      v{s.cli.version} · <span className="font-mono text-xs text-fg-muted">{s.cli.cli_path}</span>
                    </span>
                  ) : (
                    <span className="text-danger">No encontrada</span>
                  )}
                </Row>
                <Row label="Autenticación">
                  {s.cli.logged_in ? (
                    <span>
                      Sesión de {s.cli.auth_method === 'claude.ai' ? 'claude.ai' : s.cli.auth_method}
                      {s.cli.subscription ? ` · plan ${s.cli.subscription.charAt(0).toUpperCase()}${s.cli.subscription.slice(1)}` : ''}
                    </span>
                  ) : (
                    <span className="text-danger">{s.cli.message ?? 'Sin sesión'}</span>
                  )}
                </Row>
              </>
            )}
            {s.transport === 'api' && <Row label="Clave de API">{s.api_key_saved ? `Guardada en ${s.key_store ?? 'el llavero del sistema'}` : <span className="text-danger">No configurada</span>}</Row>}
            <Row label="Modelo">
              <span className="font-mono text-xs">{s.model}</span>
              {s.last_check?.ok && s.last_check.model_reported === s.model && <span className="ml-1.5 text-xs text-success">verificado</span>}
            </Row>
            <Row label="Facturación">
              {s.billing === 'subscription'
                ? 'Incluido en tu plan (sin cargos por solicitud)'
                : 'Por tokens en tu cuenta de la Consola de Claude'}
            </Row>
          </div>
        )}
        {s?.last_check && <LastCheck check={s.last_check} />}
        {s?.last_check?.rate_limit && <Limits info={s.last_check.rate_limit} />}
        <div className="mt-4 flex flex-wrap gap-2">
          <Button size="sm" variant="primary" loading={testing} disabled={!s?.ready} icon={<PlugZap className="size-3.5" />} onClick={() => void test()}>
            Probar conexión
          </Button>
          <Button size="sm" variant="secondary" icon={<RefreshCw className="size-3.5" />} onClick={() => qc.invalidateQueries({ queryKey: keys.claudeStatus })}>
            Reconectar
          </Button>
          {s?.transport === 'claude_code' && s.cli?.installed && !s.cli.logged_in && (
            <Button
              size="sm"
              variant="secondary"
              icon={<LogIn className="size-3.5" />}
              onClick={async () => {
                try {
                  const r = await api.claudeLogin()
                  toast.info(r.opened ? 'Se abrió Terminal con el inicio de sesión oficial' : `Ejecuta: ${r.command}`, {
                    description: 'Completa el inicio de sesión en el navegador y pulsa «Reconectar».',
                  })
                } catch (err) {
                  toast.error('No se pudo abrir el inicio de sesión', { description: errorText(err) })
                }
              }}
            >
              Iniciar sesión en Claude Code
            </Button>
          )}
        </div>
        <div className="mt-3">
          <ClaudePricing />
        </div>
        <p className="mt-2 text-xs leading-relaxed text-fg-faint">
          «Probar conexión» envía una solicitud real mínima (sin datos tuyos y con muy pocos tokens: un coste mínimo, del orden de céntimos de dólar o menos) para comprobar autenticación, modelo y esfuerzo. Para comprobar solo la clave, sin coste, usa «Comprobar» junto a la clave.
          {s?.transport === 'claude_code' &&
            ' Con Claude Code las solicitudes consumen los límites de tu plan, compartidos con tu uso habitual de Claude Code. El coste que muestra el consumo es una estimación de Claude Code a precio de lista, no un cargo.'}
        </p>
      </div>

      {prefs && (
        <div className="mt-5 divide-y divide-line">
          {(s?.transports ?? ['api']).includes('claude_code') && (
          <Field label="Mecanismo de conexión" hint="Solo para pruebas automáticas con un CLI simulado.">
            <Segmented
              label="Mecanismo"
              value={prefs.transport}
              onValueChange={(v) => void save({ transport: v })}
              options={[
                { value: 'claude_code', label: 'Claude Code' },
                { value: 'api', label: 'Clave de API' },
              ]}
            />
          </Field>
          )}
          {prefs.transport === 'api' && (
            <Field label="Tu clave de API de Anthropic" stacked>
              <ClaudeKeyForm />
            </Field>
          )}
          <Field label="Modelo" hint="Video Studio AI usa Claude Opus 5.5 para la dirección creativa (independiente del modelo con el que se desarrolla la aplicación).">
            <span className="font-mono text-xs text-fg">{prefs.model}</span>
          </Field>
          <Field label="Esfuerzo" hint="Medio es el equilibrio recomendado entre calidad del plan, tiempo y consumo.">
            <Segmented
              label="Esfuerzo"
              value={prefs.effort}
              onValueChange={(v) => void save({ effort: v })}
              options={[
                { value: 'low', label: 'Bajo' },
                { value: 'medium', label: 'Medio' },
                { value: 'high', label: 'Alto' },
              ]}
            />
          </Field>
          <Field label="Fotogramas por solicitud" hint="Se eligen los más informativos (al menos uno por escena). Más fotogramas = más contexto y más consumo.">
            <Slider label="Fotogramas por solicitud" className="w-56" min={2} max={24} value={prefs.max_frames} onValueChange={(v) => void save({ max_frames: v })} />
          </Field>
          <Field label="Tiempo máximo por solicitud">
            <Slider label="Tiempo máximo por solicitud" className="w-56" min={60} max={1800} step={30} value={prefs.timeout_seconds} onValueChange={(v) => void save({ timeout_seconds: v })} format={(v) => `${Math.round(v / 60)} min`} />
          </Field>
          {prefs.transport === 'claude_code' && (
            <Field label="Tope de coste estimado por solicitud" hint="Protección ante solicitudes desbordadas (sobre la estimación de Claude Code).">
              <Slider label="Tope de coste estimado" className="w-56" min={1} max={40} value={Math.round(prefs.max_budget_usd_per_call * 2)} onValueChange={(v) => void save({ max_budget_usd_per_call: v / 2 })} format={(v) => `${(v / 2).toFixed(1)} USD`} />
            </Field>
          )}
          <h3 className="pt-2 text-[13px] font-semibold text-fg">Control de solicitudes</h3>
          <Field label="Solicitudes autorizadas en 24 h" hint="Si una operación puede superar este límite, Video Studio AI pide tu confirmación antes de enviarla (solo para esa operación).">
            <Slider label="Solicitudes autorizadas en 24 h" className="w-56" min={1} max={200} value={prefs.daily_request_limit} onValueChange={(v) => void save({ daily_request_limit: v })} />
          </Field>
          <Field label="Reintentos ante errores temporales" hint="Sobrecarga o red. Cada reintento es una solicitud real y cuenta en el límite.">
            <Slider label="Reintentos" className="w-56" min={0} max={4} value={prefs.max_retries} onValueChange={(v) => void save({ max_retries: v })} />
          </Field>
          <Field label="Tope por operación" hint="Máximo absoluto de solicitudes de una misma operación (con reintentos), aunque Claude falle varias veces.">
            <Slider label="Tope por operación" className="w-56" min={1} max={40} value={prefs.max_requests_per_operation} onValueChange={(v) => void save({ max_requests_per_operation: v })} />
          </Field>
          <UsageSummary />
        </div>
      )}
    </Section>
  )
}

function UsageSummary() {
  const budget = useClaudeBudget()
  const usage = useClaudeUsage()
  const b = budget.data
  const u = usage.data
  if (!b || !u) return null
  const last = u.by_day.slice(-7)
  return (
    <div className="rounded-xl border border-line bg-surface-2 p-3 text-xs">
      <div className="flex flex-wrap items-baseline gap-x-4 gap-y-1">
        <span className="text-fg">
          Últimas 24 h: <strong className="tabular">{b.used_24h}</strong> de {b.limit_24h} solicitudes autorizadas
        </span>
        <span className="text-fg-muted">
          30 días: {u.requests} solicitudes · {(u.input_tokens + u.output_tokens).toLocaleString('es')} tokens
        </span>
      </div>
      <ProgressBar className="mt-2" value={Math.min(1, b.used_24h / Math.max(1, b.limit_24h))} label="Solicitudes usadas en 24 h" />
      {last.length > 0 && (
        <table className="mt-2 w-full text-left">
          <thead className="text-fg-faint">
            <tr>
              <th className="py-0.5 font-medium">Día</th>
              <th className="py-0.5 font-medium">Solicitudes</th>
              <th className="py-0.5 font-medium">Errores</th>
              <th className="py-0.5 font-medium">Reintentos</th>
            </tr>
          </thead>
          <tbody className="tabular text-fg-muted">
            {last.map((d) => (
              <tr key={d.day}>
                <td className="py-0.5">{d.day}</td>
                <td>{d.requests}</td>
                <td>{d.errors}</td>
                <td>{d.retries}</td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
      <p className="mt-2 leading-relaxed text-fg-faint">
        {b.billing === 'subscription'
          ? `Con Claude Code y tu plan no hay cargos por solicitud: se consumen los límites de uso del plan. ${u.cost_estimate_usd !== null ? `La cifra de Claude Code (≈ ${u.cost_estimate_usd.toFixed(2)} USD en 30 días) es una estimación a precio de lista, no un cargo.` : ''}`
          : `Con la API se factura por tokens.${u.cost_estimate_usd !== null ? ` Estimación de 30 días: ≈ ${u.cost_estimate_usd.toFixed(2)} USD.` : ''}`}
      </p>
    </div>
  )
}
