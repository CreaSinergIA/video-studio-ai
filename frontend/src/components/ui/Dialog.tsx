import type { ReactNode } from 'react'
import { Dialog as D } from 'radix-ui'
import { X } from 'lucide-react'
import { cn } from '@/lib/cn'

interface DialogProps {
  open: boolean
  onOpenChange: (open: boolean) => void
  title: ReactNode
  description?: ReactNode
  children?: ReactNode
  footer?: ReactNode
  size?: 'sm' | 'md' | 'lg' | 'xl'
  icon?: ReactNode
  tone?: 'default' | 'danger'
}

const widths = { sm: 'max-w-md', md: 'max-w-lg', lg: 'max-w-2xl', xl: 'max-w-4xl' }

export function Dialog({
  open,
  onOpenChange,
  title,
  description,
  children,
  footer,
  size = 'md',
  icon,
  tone = 'default',
}: DialogProps) {
  return (
    <D.Root open={open} onOpenChange={onOpenChange}>
      <D.Portal>
        <D.Overlay className="fixed inset-0 z-50 bg-black/60 backdrop-blur-[3px] animate-fade-in" />
        <D.Content
          className={cn(
            'fixed left-1/2 top-1/2 z-50 flex max-h-[88vh] w-[calc(100vw-2rem)] -translate-x-1/2 -translate-y-1/2 flex-col overflow-hidden rounded-2xl border border-line-strong bg-surface-1 shadow-panel animate-pop-in focus:outline-none',
            widths[size],
          )}
        >
          <div className="flex items-start gap-3.5 px-6 pb-2 pt-6">
            {icon && (
              <div
                className={cn(
                  'mt-0.5 grid size-10 shrink-0 place-items-center rounded-xl',
                  tone === 'danger' ? 'bg-danger/12 text-danger' : 'bg-accent-soft text-accent',
                )}
              >
                {icon}
              </div>
            )}
            <div className="min-w-0 flex-1">
              <D.Title className="text-[17px] font-semibold tracking-tight text-fg">{title}</D.Title>
              {description ? (
                <D.Description className="mt-1 text-sm leading-relaxed text-fg-muted">
                  {description}
                </D.Description>
              ) : (
                <D.Description className="sr-only">{typeof title === 'string' ? title : ''}</D.Description>
              )}
            </div>
            <D.Close
              className="-mr-2 -mt-1 grid size-8 place-items-center rounded-lg text-fg-faint transition hover:bg-surface-3 hover:text-fg"
              aria-label="Cerrar"
            >
              <X className="size-4" />
            </D.Close>
          </div>
          {children && <div className="min-h-0 flex-1 overflow-y-auto px-6 py-3">{children}</div>}
          {footer && (
            <div className="flex items-center justify-end gap-2 border-t border-line bg-surface-2/60 px-6 py-4">
              {footer}
            </div>
          )}
        </D.Content>
      </D.Portal>
    </D.Root>
  )
}
