import type { ReactNode } from 'react'
import { Tooltip as T } from 'radix-ui'
import { LoaderCircle } from 'lucide-react'
import { cn } from '@/lib/cn'

export function Spinner({ className }: { className?: string }) {
  return <LoaderCircle className={cn('size-4 animate-spin', className)} aria-hidden />
}

export function ProgressBar({
  value,
  className,
  indeterminate,
  tone = 'accent',
  label,
}: {
  value: number
  className?: string
  indeterminate?: boolean
  tone?: 'accent' | 'success' | 'danger' | 'warning'
  label?: string
}) {
  const color = {
    accent: 'bg-accent',
    success: 'bg-success',
    danger: 'bg-danger',
    warning: 'bg-warning',
  }[tone]
  return (
    <div
      role="progressbar"
      aria-label={label}
      aria-valuemin={0}
      aria-valuemax={100}
      aria-valuenow={indeterminate ? undefined : Math.round(value * 100)}
      className={cn('h-1.5 w-full overflow-hidden rounded-full bg-surface-4', className)}
    >
      {indeterminate ? (
        <div className={cn('h-full w-1/3 animate-[indeterminate_1.3s_ease-in-out_infinite] rounded-full', color)} />
      ) : (
        <div
          className={cn('h-full rounded-full transition-[width] duration-300 ease-out', color)}
          style={{ width: `${Math.max(2, Math.min(100, value * 100))}%` }}
        />
      )}
    </div>
  )
}

type Tone = 'neutral' | 'accent' | 'success' | 'warning' | 'danger'
const tones: Record<Tone, string> = {
  neutral: 'bg-surface-3 text-fg-muted border-line',
  accent: 'bg-accent-soft text-accent border-accent/20',
  success: 'bg-success/10 text-success border-success/20',
  warning: 'bg-warning/10 text-warning border-warning/25',
  danger: 'bg-danger/10 text-danger border-danger/25',
}

export function Badge({
  children,
  tone = 'neutral',
  icon,
  className,
}: {
  children: ReactNode
  tone?: Tone
  icon?: ReactNode
  className?: string
}) {
  return (
    <span
      className={cn(
        'inline-flex h-6 items-center gap-1 whitespace-nowrap rounded-md border px-2 text-[11.5px] font-medium',
        tones[tone],
        className,
      )}
    >
      {icon}
      {children}
    </span>
  )
}

export function EmptyState({
  icon,
  title,
  description,
  action,
  className,
}: {
  icon: ReactNode
  title: ReactNode
  description?: ReactNode
  action?: ReactNode
  className?: string
}) {
  return (
    <div className={cn('flex flex-col items-center justify-center px-6 py-14 text-center', className)}>
      <div className="mb-4 grid size-12 place-items-center rounded-2xl border border-line bg-surface-2 text-fg-muted">
        {icon}
      </div>
      <h3 className="text-[15px] font-semibold text-fg">{title}</h3>
      {description && <p className="mt-1.5 max-w-sm text-sm leading-relaxed text-fg-muted">{description}</p>}
      {action && <div className="mt-5">{action}</div>}
    </div>
  )
}

export function Tooltip({
  content,
  children,
  side = 'top',
}: {
  content: ReactNode
  children: ReactNode
  side?: 'top' | 'right' | 'bottom' | 'left'
}) {
  return (
    <T.Root delayDuration={250}>
      <T.Trigger asChild>{children}</T.Trigger>
      <T.Portal>
        <T.Content
          side={side}
          sideOffset={8}
          className="z-[70] max-w-xs rounded-lg border border-line-strong bg-surface-3 px-2.5 py-1.5 text-xs leading-snug text-fg shadow-panel animate-fade-in"
        >
          {content}
        </T.Content>
      </T.Portal>
    </T.Root>
  )
}

export function Kbd({ children }: { children: ReactNode }) {
  return (
    <kbd className="inline-flex h-5 min-w-5 items-center justify-center rounded border border-line-strong bg-surface-3 px-1 font-mono text-[10.5px] text-fg-muted">
      {children}
    </kbd>
  )
}

export function Section({
  title,
  description,
  children,
  actions,
  className,
}: {
  title: ReactNode
  description?: ReactNode
  children: ReactNode
  actions?: ReactNode
  className?: string
}) {
  return (
    <section className={cn('rounded-2xl border border-line bg-surface-1 shadow-panel', className)}>
      <header className="flex items-start justify-between gap-4 border-b border-line px-5 py-4">
        <div>
          <h2 className="text-[15px] font-semibold tracking-tight text-fg">{title}</h2>
          {description && <p className="mt-0.5 text-[13px] text-fg-muted">{description}</p>}
        </div>
        {actions && <div className="flex shrink-0 items-center gap-2">{actions}</div>}
      </header>
      <div className="px-5 py-4">{children}</div>
    </section>
  )
}

/** Marca de función que llegará en una fase posterior (nunca se simula). */
export function FutureBadge({ phase }: { phase: number }) {
  return (
    <Badge tone="neutral" className="font-normal">
      No disponible · Fase {phase}
    </Badge>
  )
}
