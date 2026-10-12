import { useState } from 'react'
import { useQueryClient } from '@tanstack/react-query'
import { CircleAlert, CircleCheck, ExternalLink, KeyRound, ShieldCheck, Trash } from 'lucide-react'
import { toast } from 'sonner'
import { Button } from '@/components/ui/Button'
import { Input } from '@/components/ui/fields'
import { keys, useClaudeStatus } from '@/hooks/queries'
import { ApiError, api } from '@/lib/api'
import type { ClaudeKeyCheck } from '@/lib/types'

const errorText = (err: unknown) => (err instanceof ApiError ? err.message : String(err))

/** Precios de lista (USD por millón de tokens) para que el usuario conozca el coste. */
export function ClaudePricing() {
  const { data: s } = useClaudeStatus()
  const price = s?.pricing?.usd_per_mtok
  if (!price) return null
  const n = (v: number) => v.toLocaleString('es', { maximumFractionDigits: 2 })
  return (
    <p className="text-xs leading-relaxed text-fg-muted">
      <span className="font-medium text-fg">Coste de Claude Opus 5.5 (precio de lista, {s?.pricing?.as_of}):</span> {n(price.input)} USD por millón de tokens de entrada y{' '}
      {n(price.output)} USD por millón de salida (caché: {n(price.cache_read)} USD lectura · {n(price.cache_write)} USD escritura). Cada solicitud muestra su estimación en el consumo;
      la factura real y los límites de tu cuenta están en la{' '}
      <a className="text-accent underline" href="https://platform.claude.com/settings/billing" target="_blank" rel="noreferrer">
        Consola de Claude
      </a>
      .
    </p>
  )
}

/**
 * Clave de API propia del usuario: guardar (en el llavero del sistema), comprobar sin coste
 * (API de modelos) y eliminar. Nunca se muestra ni se guarda en el navegador.
 */
export function ClaudeKeyForm({ compact = false }: { compact?: boolean }) {
  const qc = useQueryClient()
  const { data: s } = useClaudeStatus()
  const [key, setKey] = useState('')
  const [busy, setBusy] = useState<'save' | 'verify' | 'delete' | null>(null)
  const [check, setCheck] = useState<ClaudeKeyCheck | null>(null)
  const store = s?.key_store ?? 'el llavero del sistema'

  const refresh = () => {
    qc.invalidateQueries({ queryKey: keys.claudeStatus })
    qc.invalidateQueries({ queryKey: ['setup-status'] })
  }
  const verify = async () => {
    setBusy('verify')
    try {
      const r = await api.verifyClaudeKey()
      setCheck(r)
      if (r.ok) toast.success('Clave válida', { description: `Tu cuenta tiene acceso a ${r.display_name ?? r.model}. Esta comprobación no tiene coste.` })
    } catch (err) {
      setCheck({ ok: false, error: errorText(err) })
    } finally {
      setBusy(null)
    }
  }
  const save = async () => {
    setBusy('save')
    setCheck(null)
    try {
      await api.saveApiKey(key.trim())
      setKey('')
      toast.success(`Clave guardada en ${store}`)
      refresh()
      setBusy(null)
      await verify()
    } catch (err) {
      toast.error('No se pudo guardar la clave', { description: errorText(err) })
      setBusy(null)
    }
  }
  const remove = async () => {
    if (!window.confirm('¿Eliminar la clave de API de este equipo? Podrás guardar otra cuando quieras.')) return
    setBusy('delete')
    try {
      await api.deleteApiKey()
      setCheck(null)
      toast.success('Clave eliminada de este equipo')
    } catch (err) {
      toast.error('No se pudo eliminar la clave', { description: errorText(err) })
    } finally {
      setBusy(null)
      refresh()
    }
  }

  return (
    <div className="space-y-3">
      <div className="flex flex-wrap gap-2">
        <Input
          type="password"
          autoComplete="off"
          spellCheck={false}
          aria-label="Clave de API de Anthropic"
          className="min-w-[240px] flex-1"
          placeholder={s?.api_key_saved ? '•••••••• (guardada; escribe otra para cambiarla)' : 'sk-ant-…'}
          value={key}
          onChange={(e) => setKey(e.target.value)}
        />
        <Button variant="primary" icon={<KeyRound className="size-4" />} disabled={key.trim().length < 20} loading={busy === 'save'} onClick={() => void save()}>
          {s?.api_key_saved ? 'Cambiar clave' : 'Guardar clave'}
        </Button>
        {s?.api_key_saved && (
          <>
            <Button variant="secondary" icon={<ShieldCheck className="size-4" />} loading={busy === 'verify'} onClick={() => void verify()}>
              Comprobar (sin coste)
            </Button>
            <Button variant="ghost" aria-label="Eliminar la clave de API" icon={<Trash className="size-4" />} loading={busy === 'delete'} onClick={() => void remove()}>
              Eliminar
            </Button>
          </>
        )}
      </div>
      {check && (
        <div role="status" className={`flex items-start gap-2 rounded-lg border px-3 py-2 text-[13px] ${check.ok ? 'border-success/25 bg-success/5 text-fg' : 'border-danger/25 bg-danger/5 text-danger'}`}>
          {check.ok ? <CircleCheck className="mt-0.5 size-4 shrink-0 text-success" /> : <CircleAlert className="mt-0.5 size-4 shrink-0" />}
          <span>{check.ok ? `Clave válida: acceso a ${check.display_name ?? check.model} confirmado (${((check.duration_ms ?? 0) / 1000).toFixed(1)} s, sin coste).` : check.error}</span>
        </div>
      )}
      <p className="text-xs leading-relaxed text-fg-faint">
        Crea la clave en{' '}
        <a className="inline-flex items-center gap-0.5 text-accent underline" href="https://platform.claude.com/settings/keys" target="_blank" rel="noreferrer">
          platform.claude.com → API Keys <ExternalLink className="size-3" />
        </a>
        . Se guarda en {store}: nunca en el navegador, la base de datos, los registros ni los proyectos.
        {!compact && ' «Comprobar» consulta la API de modelos de Anthropic: verifica la clave y el acceso a Opus 5.5 sin enviar ninguna solicitud al modelo.'}
      </p>
      <p className="text-xs leading-relaxed text-fg-faint">
        <span className="font-medium text-fg-muted">Importante:</span> una suscripción Claude Pro o Max no incluye el uso de la API. La API se factura aparte, por tokens, en tu cuenta de la Consola de Claude.
      </p>
    </div>
  )
}
