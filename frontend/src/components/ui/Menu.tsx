import type { ReactNode } from 'react'
import { DropdownMenu as M } from 'radix-ui'
import { cn } from '@/lib/cn'

export interface MenuItem {
  label: string
  icon?: ReactNode
  onSelect: () => void
  danger?: boolean
  disabled?: boolean
  separatorBefore?: boolean
}

export function Menu({
  trigger,
  items,
  align = 'end',
}: {
  trigger: ReactNode
  items: MenuItem[]
  align?: 'start' | 'end'
}) {
  return (
    <M.Root modal={false}>
      <M.Trigger asChild>{trigger}</M.Trigger>
      <M.Portal>
        <M.Content
          align={align}
          sideOffset={6}
          className="z-[60] min-w-48 rounded-xl border border-line-strong bg-surface-2 p-1 shadow-panel animate-pop-in"
          onClick={(e) => e.stopPropagation()}
        >
          {items.map((item) => (
            <div key={item.label}>
              {item.separatorBefore && <M.Separator className="my-1 h-px bg-line" />}
              <M.Item
                disabled={item.disabled}
                onSelect={item.onSelect}
                className={cn(
                  'flex cursor-default select-none items-center gap-2.5 rounded-lg px-2.5 py-2 text-[13px] outline-none data-[disabled]:opacity-40 data-[highlighted]:bg-surface-4',
                  item.danger ? 'text-danger' : 'text-fg',
                )}
              >
                <span className="text-fg-muted [&>svg]:size-4">{item.icon}</span>
                {item.label}
              </M.Item>
            </div>
          ))}
        </M.Content>
      </M.Portal>
    </M.Root>
  )
}
