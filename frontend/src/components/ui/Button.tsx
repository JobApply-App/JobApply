import { TOKENS } from '@/lib/tokens'
import { ButtonHTMLAttributes, ReactNode } from 'react'

type Variant = 'primary' | 'secondary' | 'ghost'
type Size    = 'sm' | 'md' | 'lg'

interface ButtonProps extends ButtonHTMLAttributes<HTMLButtonElement> {
  variant?: Variant
  size?: Size
  children: ReactNode
}

const sizes: Record<Size, string> = {
  sm: 'h-8 px-3 text-[13px]',
  md: 'h-10 px-4 text-[14px]',
  lg: 'h-11 px-5 text-[14.5px]',
}

const variantClasses: Record<Variant, string> = {
  primary:   'text-white shadow-sm hover:opacity-90',
  secondary: 'bg-white text-slate-700 border border-slate-200 hover:border-slate-300 hover:bg-slate-50 shadow-sm',
  ghost:     'text-slate-500 hover:text-slate-800 hover:bg-slate-100',
}

const base = 'inline-flex items-center justify-center gap-1.5 rounded-lg font-medium transition active:scale-[0.98] focus:outline-none focus-visible:ring-2 focus-visible:ring-teal-500 focus-visible:ring-offset-2'

export function Button({ variant = 'primary', size = 'md', className = '', children, ...rest }: ButtonProps) {
  const style = variant === 'primary' ? { background: TOKENS.color.primary } : {}
  return (
    <button
      className={`${base} ${sizes[size]} ${variantClasses[variant]} ${className}`}
      style={style}
      {...rest}
    >
      {children}
    </button>
  )
}
