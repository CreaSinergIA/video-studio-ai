import type { ReactNode } from 'react'
import { Accordion } from 'radix-ui'
import { Captions, ChevronDown, Download, Palette, Smartphone, Sparkles, Volume2 } from 'lucide-react'
import { StylePreview } from '@/components/editor/StylePreview'
import { SubtitleOverlay } from '@/components/editor/SubtitleOverlay'
import { ColorInput, Field, Segmented, Select, Slider, Switch } from '@/components/ui/fields'
import { FutureBadge } from '@/components/ui/feedback'
import { cn } from '@/lib/cn'
import type { SubtitleSafeArea, Asset, Catalog, EditConfig, StyleId } from '@/lib/types'

type Updater = (mutate: (draft: EditConfig) => void) => void

const CLASSIC_ANIMS: string[] = ['none', 'fade', 'pop', 'slide_up']

const LEVELS = [
  { value: 'low' as const, label: 'Baja' },
  { value: 'medium' as const, label: 'Media' },
  { value: 'high' as const, label: 'Alta' },
]
const PACES = [
  { value: 'slow' as const, label: 'Pausado' },
  { value: 'medium' as const, label: 'Medio' },
  { value: 'fast' as const, label: 'Ágil' },
]

function SectionItem({
  value,
  icon,
  title,
  summary,
  phase,
  children,
}: {
  value: string
  icon: ReactNode
  title: string
  summary?: string
  phase?: number
  children: ReactNode
}) {
  return (
    <Accordion.Item value={value} className="border-b border-line last:border-b-0">
      <Accordion.Header>
        <Accordion.Trigger className="group flex w-full items-center gap-3 px-5 py-3.5 text-left transition hover:bg-surface-2/60">
          <span className="grid size-8 shrink-0 place-items-center rounded-lg bg-surface-3 text-fg-muted [&>svg]:size-4">{icon}</span>
          <span className="min-w-0 flex-1">
            <span className="block text-[13.5px] font-semibold text-fg">{title}</span>
            {summary && <span className="block truncate text-xs text-fg-faint">{summary}</span>}
          </span>
          <ChevronDown className="size-4 shrink-0 text-fg-faint transition-transform duration-200 group-data-[state=open]:rotate-180" />
        </Accordion.Trigger>
      </Accordion.Header>
      <Accordion.Content className="overflow-hidden px-5 pb-4 data-[state=closed]:animate-none">
        {phase && (
          <p className="mb-2 flex items-center gap-2 rounded-lg bg-surface-2 px-3 py-2 text-xs leading-snug text-fg-muted">
            <FutureBadge phase={phase} />
            <span>Se guarda ahora y se aplicará cuando el motor esté disponible.</span>
          </p>
        )}
        {children}
      </Accordion.Content>
    </Accordion.Item>
  )
}

function StylePicker({ config, update, catalog }: { config: EditConfig; update: Updater; catalog: Catalog }) {
  return (
    <div className="grid grid-cols-1 gap-2">
      {catalog.styles.map((style) => {
        const active = config.style.id === style.id
        return (
          <button
            key={style.id}
            type="button"
            onClick={() => update((d) => void (d.style.id = style.id))}
            aria-pressed={active}
            className={cn(
              'flex items-center gap-3 rounded-xl border p-2 text-left transition',
              active ? 'border-accent bg-accent-soft' : 'border-line bg-surface-2 hover:border-line-strong',
            )}
          >
            <StylePreview style={style.id} config={config.style} className="h-14 w-[88px] shrink-0 overflow-hidden rounded-lg" />
            <span className="min-w-0">
              <span className="block text-[13px] font-semibold text-fg">{style.name}</span>
              <span className="block text-xs text-fg-muted">{style.tagline}</span>
            </span>
          </button>
        )
      })}
    </div>
  )
}

function StyleParams({ style, config, update }: { style: StyleId; config: EditConfig; update: Updater }) {
  if (style === 'motion_tech') {
    const p = config.style.motion_tech
    return (
      <>
        <Field label="Color principal">
          <ColorInput label="Color principal" value={p.accent_color} onChange={(v) => update((d) => void (d.style.motion_tech.accent_color = v))} />
        </Field>
        <Field label="Color secundario">
          <ColorInput label="Color secundario" value={p.secondary_color} onChange={(v) => update((d) => void (d.style.motion_tech.secondary_color = v))} />
        </Field>
        <Field label="Retícula de fondo" hint="Rejilla técnica sutil detrás de los elementos">
          <Switch label="Retícula" checked={p.grid_overlay} onCheckedChange={(v) => update((d) => void (d.style.motion_tech.grid_overlay = v))} />
        </Field>
        <Field label="Datos y etiquetas" hint="Contadores, cifras y rótulos tipo HUD">
          <Switch label="Datos" checked={p.data_callouts} onCheckedChange={(v) => update((d) => void (d.style.motion_tech.data_callouts = v))} />
        </Field>
        <Field label="Densidad HUD" stacked>
          <Segmented label="Densidad HUD" value={p.hud_density} options={LEVELS} onValueChange={(v) => update((d) => void (d.style.motion_tech.hud_density = v))} className="w-full" />
        </Field>
        <Field label="Brillo (glow)" stacked>
          <Slider label="Brillo" value={p.glow} onValueChange={(v) => update((d) => void (d.style.motion_tech.glow = v))} format={(v) => `${v} %`} />
        </Field>
        <Field label="Transición" stacked>
          <Segmented
            label="Transición"
            value={p.transition}
            options={[
              { value: 'scan', label: 'Escaneo' },
              { value: 'glitch', label: 'Glitch' },
              { value: 'slide', label: 'Desliz' },
            ]}
            onValueChange={(v) => update((d) => void (d.style.motion_tech.transition = v))}
            className="w-full"
          />
        </Field>
      </>
    )
  }
  if (style === 'minimal_motion') {
    const p = config.style.minimal_motion
    return (
      <>
        <Field label="Color de acento">
          <ColorInput label="Color de acento" value={p.accent_color} onChange={(v) => update((d) => void (d.style.minimal_motion.accent_color = v))} />
        </Field>
        <Field label="Tono de fondo" stacked>
          <Segmented
            label="Tono de fondo"
            value={p.background_tone}
            options={[
              { value: 'dark', label: 'Oscuro' },
              { value: 'neutral', label: 'Neutro' },
              { value: 'light', label: 'Claro' },
            ]}
            onValueChange={(v) => update((d) => void (d.style.minimal_motion.background_tone = v))}
            className="w-full"
          />
        </Field>
        <Field label="Espacio negativo" stacked>
          <Segmented
            label="Espacio negativo"
            value={p.whitespace}
            options={[
              { value: 'airy', label: 'Amplio' },
              { value: 'balanced', label: 'Equilibrado' },
            ]}
            onValueChange={(v) => update((d) => void (d.style.minimal_motion.whitespace = v))}
            className="w-full"
          />
        </Field>
        <Field label="Escala tipográfica" stacked>
          <Segmented
            label="Escala tipográfica"
            value={p.type_scale}
            options={[
              { value: 'small', label: 'Pequeña' },
              { value: 'medium', label: 'Media' },
              { value: 'large', label: 'Grande' },
            ]}
            onValueChange={(v) => update((d) => void (d.style.minimal_motion.type_scale = v))}
            className="w-full"
          />
        </Field>
        <Field label="Curva de movimiento" stacked>
          <Segmented
            label="Curva"
            value={p.easing}
            options={[
              { value: 'smooth', label: 'Suave' },
              { value: 'spring', label: 'Muelle sutil' },
            ]}
            onValueChange={(v) => update((d) => void (d.style.minimal_motion.easing = v))}
            className="w-full"
          />
        </Field>
        <Field label="Transición" stacked>
          <Segmented
            label="Transición"
            value={p.transition}
            options={[
              { value: 'mask', label: 'Máscara' },
              { value: 'fade', label: 'Fundido' },
              { value: 'slide', label: 'Desliz' },
            ]}
            onValueChange={(v) => update((d) => void (d.style.minimal_motion.transition = v))}
            className="w-full"
          />
        </Field>
      </>
    )
  }
  const p = config.style.creative_explainer
  return (
    <>
      <Field label="Color de acento">
        <ColorInput label="Color de acento" value={p.accent_color} onChange={(v) => update((d) => void (d.style.creative_explainer.accent_color = v))} />
      </Field>
      <Field label="Paleta" stacked>
        <Segmented
          label="Paleta"
          value={p.palette}
          options={[
            { value: 'vibrant', label: 'Vibrante' },
            { value: 'pastel', label: 'Pastel' },
            { value: 'paper', label: 'Papel' },
          ]}
          onValueChange={(v) => update((d) => void (d.style.creative_explainer.palette = v))}
          className="w-full"
        />
      </Field>
      <Field label="Trazo" stacked>
        <Segmented
          label="Trazo"
          value={p.stroke}
          options={[
            { value: 'hand_drawn', label: 'A mano' },
            { value: 'clean', label: 'Limpio' },
          ]}
          onValueChange={(v) => update((d) => void (d.style.creative_explainer.stroke = v))}
          className="w-full"
        />
      </Field>
      <Field label="Iconografía" stacked>
        <Segmented
          label="Iconografía"
          value={p.icon_style}
          options={[
            { value: 'doodle', label: 'Garabato' },
            { value: 'flat', label: 'Plana' },
          ]}
          onValueChange={(v) => update((d) => void (d.style.creative_explainer.icon_style = v))}
          className="w-full"
        />
      </Field>
      <Field label="Textura de papel">
        <Switch label="Textura de papel" checked={p.paper_texture} onCheckedChange={(v) => update((d) => void (d.style.creative_explainer.paper_texture = v))} />
      </Field>
      <Field label="Velocidad de dibujo" stacked>
        <Segmented label="Velocidad de dibujo" value={p.draw_on_speed} options={PACES} onValueChange={(v) => update((d) => void (d.style.creative_explainer.draw_on_speed = v))} className="w-full" />
      </Field>
    </>
  )
}

export function ConfigForm({
  config,
  onChange,
  catalog,
  asset,
  defaultOpen = ['style'],
  subtitleSafeArea,
}: {
  config: EditConfig
  onChange: (next: EditConfig) => void
  catalog: Catalog
  asset?: Asset | null
  defaultOpen?: string[]
  /** Resultado real de la zona segura con la configuración actual (pista calculada). */
  subtitleSafeArea?: SubtitleSafeArea | null
}) {
  const update: Updater = (mutate) => {
    const draft = structuredClone(config)
    mutate(draft)
    onChange(draft)
  }
  const s = config.subtitles
  const style = catalog.styles.find((x) => x.id === config.style.id)
  const fourKAllowed = !asset || Math.min(asset.display_width, asset.display_height) >= 2160
  const thumb = asset?.thumbnail_url
  const ratio = asset ? `${asset.display_width} / ${asset.display_height}` : '9 / 16'

  return (
    <Accordion.Root type="multiple" defaultValue={defaultOpen}>
      <SectionItem value="style" icon={<Palette />} title="Estilo visual" summary={style ? `${style.name} · ${style.tagline}` : undefined}>
        <StylePicker config={config} update={update} catalog={catalog} />
        {style && (
          <div className="mt-3 space-y-1.5 rounded-xl border border-line bg-surface-2 p-3 text-xs leading-relaxed text-fg-muted">
            <p>
              <span className="font-medium text-fg">Movimiento:</span> {style.motion_language}
            </p>
            <p>
              <span className="font-medium text-fg">Composición:</span> {style.composition}
            </p>
            <p>
              <span className="font-medium text-fg">Ritmo:</span> {style.pacing}
            </p>
          </div>
        )}
        <div className="mt-2 divide-y divide-line/60">
          <StyleParams style={config.style.id} config={config} update={update} />
        </div>
      </SectionItem>

      <SectionItem value="subtitles" icon={<Captions />} title="Subtítulos" summary={s.enabled ? `${s.mode === 'dynamic' ? 'Dinámico' : 'Clásico'} · ${s.font_family} · ${s.font_size} px · ${catalog.subtitle_animations.find((a) => a.id === s.animation)?.label ?? ''}` : 'Desactivados'}>
        <div className="relative mx-auto mb-3 max-h-64 overflow-hidden rounded-xl border border-line bg-stage" style={{ aspectRatio: ratio, width: asset?.orientation === 'horizontal' ? '100%' : undefined, height: asset?.orientation === 'horizontal' ? undefined : 256 }}>
          {thumb ? <img src={thumb} alt="" className="absolute inset-0 size-full object-cover" /> : <div className="absolute inset-0 checker" />}
          <SubtitleOverlay settings={s} orientation={asset?.orientation ?? 'vertical'} label={false} />
        </div>
        <Field label="Activar subtítulos">
          <Switch label="Activar subtítulos" checked={s.enabled} onCheckedChange={(v) => update((d) => void (d.subtitles.enabled = v))} />
        </Field>
        <fieldset disabled={!s.enabled} className="divide-y divide-line/60 disabled:opacity-50">
          <Field label="Tipografía">
            <Select
              label="Tipografía"
              value={s.font_family}
              options={catalog.subtitle_fonts.map((f) => ({ value: f, label: f }))}
              onValueChange={(v) => update((d) => void (d.subtitles.font_family = v))}
            />
          </Field>
          <Field label="Peso" stacked>
            <Segmented
              label="Peso"
              size="sm"
              value={String(s.font_weight) as `${typeof s.font_weight}`}
              options={(['400', '500', '600', '700', '800', '900'] as const).map((w) => ({ value: w, label: w }))}
              onValueChange={(v) => update((d) => void (d.subtitles.font_weight = Number(v) as typeof s.font_weight))}
              className="w-full"
            />
          </Field>
          <Field label="Tamaño" hint="Referencia: lado corto de 1080 px" stacked>
            <Slider label="Tamaño" min={24} max={160} value={s.font_size} onValueChange={(v) => update((d) => void (d.subtitles.font_size = v))} format={(v) => `${v} px`} />
          </Field>
          <Field label="Mayúsculas">
            <Switch label="Mayúsculas" checked={s.uppercase} onCheckedChange={(v) => update((d) => void (d.subtitles.uppercase = v))} />
          </Field>
          <Field label="Color del texto">
            <ColorInput label="Color del texto" value={s.text_color} onChange={(v) => update((d) => void (d.subtitles.text_color = v))} />
          </Field>
          <Field label="Palabra destacada">
            <ColorInput label="Color de palabra destacada" value={s.highlight_color} onChange={(v) => update((d) => void (d.subtitles.highlight_color = v))} />
          </Field>
          <Field label="Contorno">
            <div className="flex items-center gap-2">
              {s.outline_enabled && <ColorInput label="Color del contorno" value={s.outline_color} onChange={(v) => update((d) => void (d.subtitles.outline_color = v))} />}
              <Switch label="Contorno" checked={s.outline_enabled} onCheckedChange={(v) => update((d) => void (d.subtitles.outline_enabled = v))} />
            </div>
          </Field>
          {s.outline_enabled && (
            <Field label="Grosor del contorno" stacked>
              <Slider label="Grosor del contorno" min={0} max={16} value={s.outline_width} onValueChange={(v) => update((d) => void (d.subtitles.outline_width = v))} format={(v) => `${v} px`} />
            </Field>
          )}
          <Field label="Sombra">
            <div className="flex items-center gap-2">
              {s.shadow_enabled && <ColorInput label="Color de la sombra" value={s.shadow_color} onChange={(v) => update((d) => void (d.subtitles.shadow_color = v))} />}
              <Switch label="Sombra" checked={s.shadow_enabled} onCheckedChange={(v) => update((d) => void (d.subtitles.shadow_enabled = v))} />
            </div>
          </Field>
          {s.shadow_enabled && (
            <Field label="Difuminado de sombra" stacked>
              <Slider label="Difuminado de sombra" min={0} max={40} value={s.shadow_blur} onValueChange={(v) => update((d) => void (d.subtitles.shadow_blur = v))} format={(v) => `${v} px`} />
            </Field>
          )}
          <Field label="Posición automática" hint="Vertical: tercio inferior elevado (evita la interfaz de redes). Horizontal: abajo.">
            <Switch label="Posición automática" checked={s.auto_position} onCheckedChange={(v) => update((d) => void (d.subtitles.auto_position = v))} />
          </Field>
          {s.auto_position && (
            <Field
              label="Dentro de la zona segura"
              hint="Mantiene los subtítulos fuera de la interfaz de la red de destino (Destino), sin tapar ojos ni boca."
            >
              <Switch
                label="Dentro de la zona segura"
                checked={s.safe_area === 'platform'}
                onCheckedChange={(v) => update((d) => void (d.subtitles.safe_area = v ? 'platform' : 'none'))}
              />
            </Field>
          )}
          {s.auto_position && <SafeAreaNote area={subtitleSafeArea ?? null} enabled={s.safe_area === 'platform'} platform={config.delivery.platform} onEnable={() => update((d) => void (d.subtitles.safe_area = 'platform'))} onOneLine={() => update((d) => void (d.subtitles.max_words_per_line = Math.min(d.subtitles.max_words_per_line, 3)))} />}
          {!s.auto_position && (
            <Field label="Posición" stacked>
              <Segmented
                label="Posición"
                value={s.position}
                options={[
                  { value: 'top', label: 'Arriba' },
                  { value: 'middle', label: 'Centro' },
                  { value: 'bottom', label: 'Abajo' },
                ]}
                onValueChange={(v) => update((d) => void (d.subtitles.position = v))}
                className="w-full"
              />
            </Field>
          )}
          <Field label="Margen" stacked>
            <Slider label="Margen" min={0} max={40} value={s.margin_percent} onValueChange={(v) => update((d) => void (d.subtitles.margin_percent = v))} format={(v) => `${v} %`} />
          </Field>
          <Field label="Modo" hint={s.mode === 'dynamic' ? 'Sincronizado por palabra, con la palabra activa resaltada.' : 'Bloques por frase con transición discreta.'} stacked>
            <Segmented
              label="Modo de subtítulos"
              value={s.mode}
              options={[
                { value: 'dynamic', label: 'Dinámico' },
                { value: 'classic', label: 'Clásico' },
              ]}
              onValueChange={(v) =>
                update((d) => {
                  d.subtitles.mode = v
                  if (v === 'classic' && !CLASSIC_ANIMS.includes(d.subtitles.animation)) d.subtitles.animation = 'fade'
                })
              }
              className="w-full"
            />
          </Field>
          <Field label="Palabras por línea" stacked>
            <Slider label="Palabras por línea" min={1} max={10} value={s.max_words_per_line} onValueChange={(v) => update((d) => void (d.subtitles.max_words_per_line = v))} />
          </Field>
          <Field label="Líneas por bloque" stacked>
            <Segmented
              label="Líneas por bloque"
              value={String(s.max_lines) as '1' | '2' | '3'}
              options={(['1', '2', '3'] as const).map((n) => ({ value: n, label: n }))}
              onValueChange={(v) => update((d) => void (d.subtitles.max_lines = Number(v)))}
              className="w-full"
            />
          </Field>
          <Field label="Animación">
            <Select
              label="Animación de subtítulos"
              value={s.animation}
              options={catalog.subtitle_animations
                .filter((a) => s.mode === 'dynamic' || CLASSIC_ANIMS.includes(a.id))
                .map((a) => ({ value: a.id, label: a.label }))}
              onValueChange={(v) => update((d) => void (d.subtitles.animation = v))}
            />
          </Field>
        </fieldset>
      </SectionItem>

      <SectionItem value="animations" icon={<Sparkles />} title="Animaciones" summary={config.animations.enabled ? `Intensidad ${LEVELS.find((l) => l.value === config.animations.intensity)?.label.toLowerCase()}` : 'Desactivadas'} phase={4}>
        <Field label="Activar animaciones">
          <Switch label="Activar animaciones" checked={config.animations.enabled} onCheckedChange={(v) => update((d) => void (d.animations.enabled = v))} />
        </Field>
        <fieldset disabled={!config.animations.enabled} className="divide-y divide-line/60 disabled:opacity-50">
          <Field label="Intensidad" stacked>
            <Segmented label="Intensidad" value={config.animations.intensity} options={LEVELS} onValueChange={(v) => update((d) => void (d.animations.intensity = v))} className="w-full" />
          </Field>
          <Field label="Preferencia de formato" hint="Elementos discretos sobre el video o animaciones a pantalla completa" stacked>
            <Segmented
              label="Formato de animaciones"
              value={config.animations.placement}
              options={[
                { value: 'discrete', label: 'Discretas' },
                { value: 'balanced', label: 'Mixto' },
                { value: 'fullscreen', label: 'Pantalla completa' },
              ]}
              onValueChange={(v) => update((d) => void (d.animations.placement = v))}
              className="w-full"
            />
          </Field>
          <Field label="Ritmo" stacked>
            <Segmented label="Ritmo" value={config.animations.pace} options={PACES} onValueChange={(v) => update((d) => void (d.animations.pace = v))} className="w-full" />
          </Field>
        </fieldset>
      </SectionItem>

      <SectionItem value="delivery" icon={<Smartphone />} title="Destino" summary={{ universal: 'Universal (Reels + TikTok)', instagram_reels: 'Instagram Reels', tiktok: 'TikTok', none: 'Sin interfaz social' }[config.delivery.platform]}>
        <Field label="Red social" hint="Las animaciones informativas se colocan fuera de la interfaz de la plataforma (solo en videos verticales). Puedes ver las zonas con el botón de guías del reproductor." stacked>
          <Select
            label="Red social de destino"
            value={config.delivery.platform}
            options={[
              { value: 'universal', label: 'Universal: Instagram Reels y TikTok' },
              { value: 'instagram_reels', label: 'Instagram Reels' },
              { value: 'tiktok', label: 'TikTok' },
              { value: 'none', label: 'Sin interfaz social' },
            ]}
            onValueChange={(v) => update((d) => void (d.delivery.platform = v))}
          />
        </Field>
      </SectionItem>

      <SectionItem value="audio" icon={<Volume2 />} title="Audio" summary={config.audio.sfx_enabled ? `Efectos ${{ soft: 'suaves', balanced: 'equilibrados', strong: 'intensos' }[config.audio.sfx_intensity]} · ${config.audio.sfx_volume} %` : 'Sin efectos'} phase={4}>
        <Field label="Efectos de sonido">
          <Switch label="Efectos de sonido" checked={config.audio.sfx_enabled} onCheckedChange={(v) => update((d) => void (d.audio.sfx_enabled = v))} />
        </Field>
        <Field label="Presencia" hint="Respecto a la voz medida del video. La voz siempre queda por encima." stacked>
          <Segmented
            label="Presencia de los efectos"
            value={config.audio.sfx_intensity}
            options={[
              { value: 'soft', label: 'Suave' },
              { value: 'balanced', label: 'Equilibrada' },
              { value: 'strong', label: 'Intensa' },
            ]}
            onValueChange={(v) => update((d) => void (d.audio.sfx_intensity = v))}
            className="w-full"
          />
        </Field>
        <Field label="Volumen de efectos" hint="Ajuste fino: 70 % es el nivel de la presencia elegida." stacked>
          <Slider label="Volumen de efectos" disabled={!config.audio.sfx_enabled} value={config.audio.sfx_volume} onValueChange={(v) => update((d) => void (d.audio.sfx_volume = v))} format={(v) => `${v} %`} />
        </Field>
        <Field label="Música de fondo" hint="Video Studio AI no añade música de fondo.">
          <span className="text-xs font-medium text-fg-faint">Desactivada</span>
        </Field>
      </SectionItem>

      <SectionItem value="export" icon={<Download />} title="Exportación" summary={`${config.export.resolution === 'original' ? 'Resolución original' : config.export.resolution} · ${config.export.fps === 'original' ? 'FPS original' : `${config.export.fps} fps`}`} >
        <Field label="Resolución" hint={!fourKAllowed ? '4K solo está disponible si el video original es 4K.' : undefined} stacked>
          <Segmented
            label="Resolución"
            value={config.export.resolution}
            options={[
              { value: 'original', label: 'Original' },
              { value: '1080p', label: '1080p' },
              { value: '4k', label: '4K', disabled: !fourKAllowed },
            ]}
            onValueChange={(v) => update((d) => void (d.export.resolution = v))}
            className="w-full"
          />
        </Field>
        <Field label="Fotogramas por segundo">
          <Select
            label="FPS"
            value={String(config.export.fps)}
            options={[
              { value: 'original', label: asset ? `Original (${Math.round(asset.fps * 100) / 100})` : 'Original' },
              ...[24, 25, 30, 50, 60].map((f) => ({ value: String(f), label: `${f} fps` })),
            ]}
            onValueChange={(v) => update((d) => void (d.export.fps = v === 'original' ? 'original' : (Number(v) as 24 | 25 | 30 | 50 | 60)))}
          />
        </Field>
        <Field label="Formato">
          <Select
            label="Formato de salida"
            value={config.export.format}
            options={[
              { value: 'mp4_h264', label: 'MP4 · H.264' },
              { value: 'mp4_hevc', label: 'MP4 · HEVC' },
              { value: 'mov_prores', label: 'MOV · ProRes 422' },
            ]}
            onValueChange={(v) => update((d) => void (d.export.format = v))}
          />
        </Field>
        <Field label="Codificador" hint="Hardware (VideoToolbox): misma calidad por tamaño y mucho más rápido en Apple Silicon." stacked>
          <Segmented
            label="Codificador"
            value={config.export.encoder}
            options={[
              { value: 'hardware', label: 'Hardware' },
              { value: 'software', label: 'Software' },
            ]}
            onValueChange={(v) => update((d) => void (d.export.encoder = v))}
            className="w-full"
          />
        </Field>
        <Field label="Calidad" stacked>
          <Segmented
            label="Calidad"
            value={config.export.quality}
            options={[
              { value: 'high', label: 'Alta' },
              { value: 'max', label: 'Máxima' },
            ]}
            onValueChange={(v) => update((d) => void (d.export.quality = v))}
            className="w-full"
          />
        </Field>
      </SectionItem>
    </Accordion.Root>
  )
}

const pct = (v: number) => `${Math.round(v * 100)} %`

/** Explica dónde quedan los subtítulos respecto a la interfaz de la plataforma y ofrece
 *  alternativas (nunca cambia la configuración sin un clic del usuario). */
function SafeAreaNote({
  area,
  enabled,
  platform,
  onEnable,
  onOneLine,
}: {
  area: SubtitleSafeArea | null
  enabled: boolean
  platform: string
  onEnable: () => void
  onOneLine: () => void
}) {
  if (platform === 'none' || !area) return null
  if (!enabled) {
    return (
      <p className="rounded-lg bg-surface-2 px-3 py-2 text-[11.5px] leading-relaxed text-fg-muted">
        Posición actual: {area.range ? `${pct(area.range[0])}–${pct(area.range[1])} del alto` : '—'}. Si se publica con interfaz social, puede quedar bajo los botones o la descripción.{' '}
        <button type="button" className="font-medium text-accent hover:underline" onClick={onEnable}>
          Probar dentro de la zona segura
        </button>
      </p>
    )
  }
  if (area.status === 'no_space') {
    return (
      <div className="rounded-lg bg-warning/10 px-3 py-2 text-[11.5px] leading-relaxed text-warning">
        En {area.blocks_without_space} de {area.blocks} bloques no hay sitio seguro sin tapar ojos o boca: esos bloques conservan la posición automática habitual.{' '}
        <button type="button" className="font-medium underline" onClick={onOneLine}>
          Probar con líneas más cortas
        </button>
      </div>
    )
  }
  const high = area.range && area.band && area.range[1] < (area.band[0] + area.band[1]) / 2
  return (
    <p className={`rounded-lg px-3 py-2 text-[11.5px] leading-relaxed ${high ? 'bg-warning/10 text-warning' : 'bg-success/10 text-success'}`}>
      Dentro de la zona segura ({area.band ? `${pct(area.band[0])}–${pct(area.band[1])}` : ''}): los subtítulos ocupan {area.range ? `${pct(area.range[0])}–${pct(area.range[1])}` : '—'} del alto.
      {high
        ? ' Para no tapar el rostro ni la interfaz suben por encima de la cara, donde suelen ir las animaciones: estas pueden quedarse sin espacio legible (aviso en naranja en las guías y en Plan IA). Valora otro destino (TikTok deja más sitio) o desactiva esta opción.'
        : ''}
    </p>
  )
}
