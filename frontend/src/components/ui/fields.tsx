import { forwardRef, useId, type InputHTMLAttributes, type ReactNode } from 'react'
import { Select as S, Slider as RSlider, Switch as RSwitch, ToggleGroup } from 'radix-ui'
import { Check, ChevronDown } from 'lucide-react'
import { cn } from '@/lib/cn'

export const Input = forwardRef<HTMLInputElement, InputHTMLAttributes<HTMLInputElement>>(
  function Input({ className, ...rest }, ref) {
    return (
      <input
        ref={ref}
        className={cn(
          'h-9 w-full rounded-[10px] border border-line-strong bg-surface-2 px-3 text-sm text-fg placeholder:text-fg-faint transition focus:border-accent focus:outline-none focus:ring-2 focus:ring-accent/25 disabled:opacity-50',
          className,
        )}
        {...rest}
      />
    )
  },
)

/** Fila de ajuste: etiqueta + ayuda a la izquierda, control a la derecha (o debajo). */
export function Field({
  label,
  hint,
  children,
  stacked,
  htmlFor,
  className,
}: {
  label: ReactNode
  hint?: ReactNode
  children: ReactNode
  stacked?: boolean
  htmlFor?: string
  className?: string
}) {
  return (
    <div
      className={cn(
        stacked ? 'flex flex-col gap-2' : 'flex items-center justify-between gap-4',
        'py-2',
        className,
      )}
    >
      <div className="min-w-0">
        <label htmlFor={htmlFor} className="block text-[13px] font-medium text-fg">
          {label}
        </label>
        {hint && <p className="mt-0.5 text-xs leading-snug text-fg-faint">{hint}</p>}
      </div>
      <div className={cn(stacked ? 'w-full' : 'shrink-0')}>{children}</div>
    </div>
  )
}

export function Switch({
  checked,
  onCheckedChange,
  label,
  disabled,
  id,
}: {
  checked: boolean
  onCheckedChange: (v: boolean) => void
  label: string
  disabled?: boolean
  id?: string
}) {
  return (
    <RSwitch.Root
      id={id}
      checked={checked}
      onCheckedChange={onCheckedChange}
      disabled={disabled}
      aria-label={label}
      className="relative h-[22px] w-[38px] shrink-0 rounded-full border border-line-strong bg-surface-4 transition-colors data-[state=checked]:border-transparent data-[state=checked]:bg-accent disabled:opacity-40"
    >
      <RSwitch.Thumb className="block size-[16px] translate-x-[2px] rounded-full bg-white shadow transition-transform duration-200 ease-out data-[state=checked]:translate-x-[18px]" />
    </RSwitch.Root>
  )
}

export function Slider({
  value,
  onValueChange,
  min = 0,
  max = 100,
  step = 1,
  label,
  format,
  className,
  disabled,
}: {
  value: number
  onValueChange: (v: number) => void
  min?: number
  max?: number
  step?: number
  label: string
  format?: (v: number) => string
  className?: string
  disabled?: boolean
}) {
  return (
    <div className={cn('flex items-center gap-3', className)}>
      <RSlider.Root
        value={[value]}
        min={min}
        max={max}
        step={step}
        disabled={disabled}
        onValueChange={([v]) => onValueChange(v)}
        aria-label={label}
        className="relative flex h-5 w-full touch-none select-none items-center"
      >
        <RSlider.Track className="relative h-1 grow overflow-hidden rounded-full bg-surface-4">
          <RSlider.Range className="absolute h-full rounded-full bg-accent" />
        </RSlider.Track>
        <RSlider.Thumb className="block size-3.5 rounded-full border-2 border-accent bg-white shadow transition hover:scale-110 focus:outline-none focus-visible:ring-4 focus-visible:ring-accent/30" />
      </RSlider.Root>
      <span className="w-12 shrink-0 text-right text-xs tabular text-fg-muted">
        {format ? format(value) : value}
      </span>
    </div>
  )
}

export interface Option<T extends string | number> {
  value: T
  label: string
  disabled?: boolean
  hint?: string
}

export function Select<T extends string | number>({
  value,
  onValueChange,
  options,
  label,
  className,
  disabled,
}: {
  value: T
  onValueChange: (v: T) => void
  options: Option<T>[]
  label: string
  className?: string
  disabled?: boolean
}) {
  const current = options.find((o) => o.value === value)
  return (
    <S.Root
      value={String(value)}
      disabled={disabled}
      onValueChange={(v) => {
        const match = options.find((o) => String(o.value) === v)
        if (match) onValueChange(match.value)
      }}
    >
      <S.Trigger
        aria-label={label}
        className={cn(
          'inline-flex h-9 min-w-36 items-center justify-between gap-2 rounded-[10px] border border-line-strong bg-surface-2 px-3 text-sm text-fg transition hover:bg-surface-3 focus:outline-none focus-visible:ring-2 focus-visible:ring-accent/40 disabled:opacity-50',
          className,
        )}
      >
        <S.Value>{current?.label}</S.Value>
        <S.Icon>
          <ChevronDown className="size-4 text-fg-faint" />
        </S.Icon>
      </S.Trigger>
      <S.Portal>
        <S.Content
          position="popper"
          sideOffset={6}
          className="z-[60] max-h-80 min-w-[var(--radix-select-trigger-width)] overflow-hidden rounded-xl border border-line-strong bg-surface-2 p-1 shadow-panel animate-pop-in"
        >
          <S.Viewport>
            {options.map((o) => (
              <S.Item
                key={String(o.value)}
                value={String(o.value)}
                disabled={o.disabled}
                className="relative flex cursor-default select-none items-center rounded-lg py-2 pl-8 pr-3 text-sm text-fg outline-none data-[disabled]:opacity-40 data-[highlighted]:bg-surface-4"
              >
                <S.ItemIndicator className="absolute left-2.5">
                  <Check className="size-3.5 text-accent" />
                </S.ItemIndicator>
                <div>
                  <S.ItemText>{o.label}</S.ItemText>
                  {o.hint && <div className="text-xs text-fg-faint">{o.hint}</div>}
                </div>
              </S.Item>
            ))}
          </S.Viewport>
        </S.Content>
      </S.Portal>
    </S.Root>
  )
}

/** Control segmentado (radio accesible) para pocas opciones. */
export function Segmented<T extends string>({
  value,
  onValueChange,
  options,
  label,
  className,
  size = 'md',
}: {
  value: T
  onValueChange: (v: T) => void
  options: (Option<T> & { icon?: ReactNode })[]
  label: string
  className?: string
  size?: 'sm' | 'md'
}) {
  return (
    <ToggleGroup.Root
      type="single"
      value={value}
      onValueChange={(v) => v && onValueChange(v as T)}
      aria-label={label}
      className={cn('inline-flex rounded-[10px] border border-line bg-surface-2 p-0.5', className)}
    >
      {options.map((o) => (
        <ToggleGroup.Item
          key={o.value}
          value={o.value}
          disabled={o.disabled}
          title={o.hint}
          className={cn(
            'inline-flex flex-1 items-center justify-center gap-1.5 whitespace-nowrap rounded-lg font-medium text-fg-muted transition hover:text-fg disabled:opacity-40 data-[state=on]:bg-surface-4 data-[state=on]:text-fg data-[state=on]:shadow-sm',
            size === 'sm' ? 'h-7 px-2.5 text-xs' : 'h-8 px-3 text-[13px]',
          )}
        >
          {o.icon}
          {o.label}
        </ToggleGroup.Item>
      ))}
    </ToggleGroup.Root>
  )
}

export function ColorInput({
  value,
  onChange,
  label,
}: {
  value: string
  onChange: (v: string) => void
  label: string
}) {
  const id = useId()
  return (
    <label
      htmlFor={id}
      className="inline-flex h-9 cursor-pointer items-center gap-2 rounded-[10px] border border-line-strong bg-surface-2 pl-1.5 pr-3 text-xs font-medium uppercase tabular text-fg-muted transition hover:bg-surface-3"
    >
      <span
        className="relative size-6 overflow-hidden rounded-md border border-line-strong"
        style={{ background: value }}
      >
        <input
          id={id}
          type="color"
          value={value.toLowerCase()}
          onChange={(e) => onChange(e.target.value.toUpperCase())}
          aria-label={label}
          className="absolute inset-0 cursor-pointer opacity-0"
        />
      </span>
      {value}
    </label>
  )
}
