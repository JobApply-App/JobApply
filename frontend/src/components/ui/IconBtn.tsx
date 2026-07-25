import { ButtonHTMLAttributes, ReactNode } from 'react'

interface IconBtnProps extends ButtonHTMLAttributes<HTMLButtonElement> {
  children: ReactNode
}

export function IconBtn({ children, className = '', ...rest }: IconBtnProps) {
  return (
    <button
      className={`inline-flex h-9 w-9 items-center justify-center rounded-lg text-slate-400 hover:text-slate-700 hover:bg-slate-100 transition ${className}`}
      {...rest}
    >
      {children}
    </button>
  )
}
