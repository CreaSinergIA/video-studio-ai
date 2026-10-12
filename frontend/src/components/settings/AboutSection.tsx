import { Info } from 'lucide-react'
import { Badge, Section } from '@/components/ui/feedback'
import { useSystemInfo } from '@/hooks/queries'

/** Acerca de: edición, versión, atribución, licencias de terceros y diagnóstico de plataforma. */
export function AboutSection() {
  const { data } = useSystemInfo()
  const p = data?.platform
  return (
    <Section title="Acerca de" description="Información del producto, licencias y compatibilidad de este equipo.">
      <div className="space-y-4 text-sm">
        <div className="flex items-start gap-3 rounded-xl border border-line bg-surface-2 p-4">
          <Info className="mt-0.5 size-4 shrink-0 text-fg-muted" />
          <div className="min-w-0 space-y-1">
            <p className="font-semibold text-fg">
              {data?.app.name ?? 'Video Studio AI'} — {data?.app.edition ?? 'Community Edition'}
            </p>
            <p className="text-fg-muted">Versión {data?.app.version ?? '—'}</p>
            <p className="text-fg-muted">{data?.app.creator ?? 'Created by Gabo'}</p>
            <p className="text-xs leading-relaxed text-fg-faint">
              Gratuito y sin marcas de agua: nada de esta información se añade a tus videos, vistas previas ni archivos exportados.
            </p>
          </div>
        </div>
        <div className="space-y-2 text-xs leading-relaxed text-fg-muted">
          <p>
            <span className="font-medium text-fg">Remotion.</span> Las animaciones se generan con Remotion, software de código disponible con licencia propia (no es open source). Es gratuito
            para personas, organizaciones sin ánimo de lucro y empresas de hasta 3 personas; las organizaciones mayores necesitan su propia licencia de empresa de Remotion:{' '}
            <a className="text-accent underline" href="https://www.remotion.pro/license" target="_blank" rel="noreferrer">
              remotion.pro/license
            </a>
            .
          </p>
          <p>
            <span className="font-medium text-fg">Claude.</span> Usa Claude de Anthropic con tu propia clave de API (facturación y límites de tu cuenta de Anthropic). Video Studio AI no
            está afiliado a Anthropic.
          </p>
          <p>
            <span className="font-medium text-fg">Otros componentes.</span> Fuentes (SIL OFL 1.1), modelo de rostros YuNet (MIT), Whisper (MIT) y bibliotecas de código abierto: ver
            THIRD_PARTY_NOTICES.md en el repositorio.
          </p>
        </div>
        {p && (
          <div className="rounded-xl border border-line bg-surface-2 p-4 text-xs">
            <p className="mb-2 font-semibold text-fg">Compatibilidad de este equipo</p>
            <p className="text-fg-muted">
              {p.os} · {p.arch}
              {p.apple_silicon ? ' · Apple Silicon' : ''}
              {p.nvidia_gpu ? ` · ${p.nvidia_gpu}` : ''}
            </p>
            <ul className="mt-2 space-y-1">
              {p.transcription_engines.map((e) => (
                <li key={e.id} className="flex items-center gap-2">
                  <Badge tone={e.available ? 'success' : e.implemented ? 'warning' : 'neutral'} className="h-5 text-[10.5px]">
                    {e.available ? 'Disponible' : e.implemented ? 'No disponible aquí' : 'Pendiente'}
                  </Badge>
                  <span className="text-fg">{e.name}</span>
                  <span className="text-fg-faint">· {e.reason}</span>
                </li>
              ))}
            </ul>
            {p.notes.map((n) => (
              <p key={n} className="mt-2 text-fg-faint">
                {n}
              </p>
            ))}
          </div>
        )}
      </div>
    </Section>
  )
}
