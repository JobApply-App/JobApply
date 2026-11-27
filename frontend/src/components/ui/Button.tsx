import { ButtonHTMLAttributes, ReactNode, forwardRef } from 'react'

// The button system (note 10, Ron's choice 2026-11-26: "1+6"): Apple's
// capsule and sizes, with Mercury's tint ladder in place of outlines.
// One shape for every action; the variants differ only in how strong the
// colour is. Ariel and remove follow the same ladder in their own hue.
// Rules and the reasons behind them: DESIGN_SYSTEM.md, "Buttons".
//
// Use <Button> for buttons and buttonClasses() for a <Link> that looks like
// one, never hand-written button classes.

export type ButtonVariant =
  | 'primary'      // the one main action on a surface: deep harbor fill
  | 'secondary'    // teal at 10%
  | 'quiet'        // hairline ring, no fill: dismiss, cancel, "not relevant"
  | 'ariel'        // Ariel's cyan-teal at 11%: anything that opens or asks Ariel
  | 'danger'       // red at 8%: remove, delete
  | 'onDark'       // white fill on a dark band
  | 'onDarkGlass'  // translucent beside onDark

// compact: 44 on phones (the touch target), 34 from the sm breakpoint up,
// for rows of actions in a card that are dense on a desktop.
export type ButtonSize = 'sm' | 'md' | 'lg' | 'compact'

const base =
  'relative inline-flex items-center justify-center gap-[7px] whitespace-nowrap rounded-full font-medium tracking-[-0.005em] ' +
  'transition-[background-color,color,box-shadow,transform] duration-200 active:scale-[0.95] active:duration-ja-press ' +
  'focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-[3px] focus-visible:outline-teal-700 ' +
  'disabled:cursor-not-allowed disabled:active:scale-100 disabled:bg-slate-900/[.05] disabled:text-slate-400 disabled:shadow-none disabled:ring-0 ' +
  'motion-reduce:active:scale-100'

// Hover only where there is a real pointer, so a tap on a phone doesn't
// leave the hover colour stuck on.
const variants: Record<ButtonVariant, string> = {
  primary:
    'bg-ja-harbor text-white shadow-[inset_0_1px_0_rgba(255,255,255,0.14),0_8px_18px_-10px_rgba(19,78,74,0.7)] ' +
    '[@media(hover:hover)]:hover:bg-[#0F3F3C]',
  secondary:
    'bg-teal-600/10 text-ja-inkDeep [@media(hover:hover)]:hover:bg-teal-600/[.16]',
  quiet:
    'text-slate-700 ring-1 ring-inset ring-slate-900/[.12] [@media(hover:hover)]:hover:bg-slate-900/[.04]',
  ariel:
    'bg-ja-ai/[.11] text-ja-aiInk [@media(hover:hover)]:hover:bg-ja-ai/[.18]',
  danger:
    'bg-red-600/[.08] text-red-700 [@media(hover:hover)]:hover:bg-red-600/[.12]',
  onDark:
    'bg-white text-ja-harbor focus-visible:outline-white [@media(hover:hover)]:hover:bg-teal-50',
  onDarkGlass:
    'bg-teal-100/[.16] text-white ring-1 ring-inset ring-teal-100/[.36] backdrop-blur-md focus-visible:outline-white ' +
    '[@media(hover:hover)]:hover:bg-teal-100/[.24]',
}

// 44 is the touch-target height; sm is for dense rows (cards, toolbars),
// lg for the one action a page or band is built around.
const sizes: Record<ButtonSize, string> = {
  sm: 'h-[34px] px-4 text-[15px]',
  md: 'h-11 px-[22px] text-[16px]',
  lg: 'h-[54px] px-[30px] text-[18px]',
  compact: 'h-11 px-[22px] text-[16px] sm:h-[34px] sm:px-4 sm:text-[15px]',
}
const iconSizes: Record<ButtonSize, string> = {
  sm: 'h-[34px] w-[34px]',
  md: 'h-11 w-11',
  lg: 'h-[54px] w-[54px]',
  compact: 'h-11 w-11 sm:h-[34px] sm:w-[34px]',
}

export function buttonClasses({
  variant = 'primary', size = 'md', iconOnly = false,
}: { variant?: ButtonVariant; size?: ButtonSize; iconOnly?: boolean } = {}): string {
  return `${base} ${variants[variant]} ${iconOnly ? iconSizes[size] : sizes[size]}`
}

interface ButtonProps extends ButtonHTMLAttributes<HTMLButtonElement> {
  variant?:   ButtonVariant
  size?:      ButtonSize
  /** Square/round button with only an icon: give it an aria-label. */
  iconOnly?:  boolean
  /**
   * For an action that saves: 'busy' blurs the label into a spinner,
   * 'done' into doneLabel, in place, so the button never jumps in width.
   */
  state?:     'idle' | 'busy' | 'done'
  doneLabel?: ReactNode
  children:   ReactNode
}

const layer = 'transition-[opacity,filter] duration-200 motion-reduce:transition-opacity'
const hidden = 'opacity-0 blur-[4px]'

export const Button = forwardRef<HTMLButtonElement, ButtonProps>(function Button(
  { variant = 'primary', size = 'md', iconOnly = false, state, doneLabel, className = '', type = 'button', children, ...rest },
  ref,
) {
  const cls = `${buttonClasses({ variant, size, iconOnly })} ${className}`
  if (state === undefined) {
    return <button ref={ref} type={type} className={cls} {...rest}>{children}</button>
  }
  return (
    <button ref={ref} type={type} className={cls} aria-busy={state === 'busy'} {...rest}>
      <span className={`inline-flex items-center gap-[7px] ${layer} ${state === 'idle' ? '' : hidden}`}>{children}</span>
      <span aria-hidden className={`absolute inset-0 flex items-center justify-center ${layer} ${state === 'busy' ? '' : hidden}`}>
        <span className="h-4 w-4 rounded-full border-2 border-current border-t-transparent animate-spin" />
      </span>
      <span aria-live="polite" className={`absolute inset-0 flex items-center justify-center gap-[7px] ${layer} ${state === 'done' ? '' : hidden}`}>
        {state === 'done' ? doneLabel : null}
      </span>
    </button>
  )
})
