import { useEffect, useRef, useState, type ReactNode } from 'react'
import { FileVideoCamera, Upload } from 'lucide-react'
import { cn } from '@/lib/cn'

function hasFiles(event: DragEvent | React.DragEvent): boolean {
  return Array.from(event.dataTransfer?.types ?? []).includes('Files')
}

/**
 * Convierte toda el área en zona de soltado: muestra una capa al arrastrar archivos
 * y entrega los archivos soltados. Funciona con cualquier elemento hijo.
 */
export function DropArea({
  onFiles,
  disabled,
  children,
  label = 'Suelta para importar',
  hint = 'MP4 o MOV · los originales nunca se modifican',
  className,
}: {
  onFiles: (files: File[]) => void
  disabled?: boolean
  children: ReactNode
  label?: string
  hint?: string
  className?: string
}) {
  const [active, setActive] = useState(false)
  const depth = useRef(0)

  useEffect(() => {
    // Evita que el navegador abra el archivo si se suelta fuera de la zona.
    const prevent = (e: DragEvent) => {
      if (hasFiles(e)) e.preventDefault()
    }
    window.addEventListener('dragover', prevent)
    window.addEventListener('drop', prevent)
    return () => {
      window.removeEventListener('dragover', prevent)
      window.removeEventListener('drop', prevent)
    }
  }, [])

  return (
    <div
      className={cn('relative', className)}
      onDragEnter={(e) => {
        if (disabled || !hasFiles(e)) return
        depth.current += 1
        setActive(true)
      }}
      onDragOver={(e) => {
        if (disabled || !hasFiles(e)) return
        e.preventDefault()
        e.dataTransfer.dropEffect = 'copy'
      }}
      onDragLeave={() => {
        if (disabled) return
        depth.current = Math.max(0, depth.current - 1)
        if (depth.current === 0) setActive(false)
      }}
      onDrop={(e) => {
        if (disabled || !hasFiles(e)) return
        e.preventDefault()
        depth.current = 0
        setActive(false)
        const files = Array.from(e.dataTransfer.files)
        if (files.length) onFiles(files)
      }}
    >
      {children}
      {active && (
        <div className="pointer-events-none absolute inset-3 z-30 grid place-items-center rounded-3xl border-2 border-dashed border-accent bg-canvas/80 backdrop-blur-sm animate-fade-in">
          <div className="flex flex-col items-center text-center">
            <div className="mb-4 grid size-16 place-items-center rounded-2xl bg-accent-soft text-accent">
              <FileVideoCamera className="size-7" />
            </div>
            <p className="text-lg font-semibold text-fg">{label}</p>
            <p className="mt-1 text-sm text-fg-muted">{hint}</p>
          </div>
        </div>
      )}
    </div>
  )
}

/** Tarjeta grande de importación para estados vacíos. */
export function DropHero({
  onBrowse,
  title = 'Arrastra tu primer video aquí',
  subtitle = 'MP4 o MOV, vertical u horizontal. Video Studio guarda una copia en tu almacenamiento y nunca modifica el original.',
  actions,
}: {
  onBrowse: () => void
  title?: string
  subtitle?: string
  actions?: ReactNode
}) {
  return (
    <div className="relative overflow-hidden rounded-3xl border border-dashed border-line-strong bg-surface-1/70 px-8 py-16 text-center transition hover:border-accent/50">
      <div className="pointer-events-none absolute inset-0 bg-glow opacity-80" />
      <div className="relative mx-auto flex max-w-lg flex-col items-center">
        <button
          type="button"
          onClick={onBrowse}
          className="mb-6 grid size-[72px] place-items-center rounded-[22px] bg-gradient-to-br from-[#9d8cff] to-[#5b8cff] text-white shadow-[0_18px_50px_-15px_#7c6cff] transition hover:scale-105"
          aria-label="Elegir videos"
        >
          <Upload className="size-7" strokeWidth={2.2} />
        </button>
        <h2 className="text-xl font-semibold tracking-tight text-fg">{title}</h2>
        <p className="mt-2 text-sm leading-relaxed text-fg-muted">{subtitle}</p>
        {actions && <div className="mt-7 flex flex-wrap items-center justify-center gap-2.5">{actions}</div>}
      </div>
    </div>
  )
}
