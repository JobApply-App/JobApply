// The controls shared by login and signup, in the landing page's language:
// tall, rounded-xl, 16px text so a phone never zooms the page on focus, and
// #0F766E for the primary action (white on it passes AA; #0D9488 does not).

const press = 'transition-[background-color,border-color,transform,opacity] duration-ja-ui active:scale-[0.97] active:duration-ja-press focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-teal-600'

export function authInput(hasError = false) {
  return `w-full h-12 rounded-xl border bg-white px-4 text-[16px] text-slate-900 outline-none transition-[border-color,box-shadow] duration-ja-ui placeholder:text-slate-400 disabled:opacity-50 focus:ring-4 ${
    hasError
      ? 'border-rose-400 focus:border-rose-500 focus:ring-rose-500/10'
      : 'border-slate-200 hover:border-slate-300 focus:border-teal-600 focus:ring-teal-600/10'
  }`
}

export const authTitle = 'text-[30px] sm:text-[36px] leading-[1.1] font-bold tracking-[-0.03em] text-slate-900'
export const authSub = 'mt-2 text-[16px] leading-relaxed text-slate-500'
export const authLabel = 'block text-[14px] font-medium text-slate-700 mb-2'
export const authPrimary = `w-full h-12 rounded-xl bg-ja-primaryHover text-white text-[15px] font-semibold tracking-tight flex items-center justify-center gap-2 hover:bg-ja-harbor disabled:opacity-40 disabled:pointer-events-none ${press}`
export const authSecondary = `w-full h-12 rounded-xl border border-slate-200 bg-white text-[15px] font-semibold text-slate-700 flex items-center justify-center gap-3 hover:bg-slate-50 hover:border-slate-300 disabled:opacity-50 disabled:pointer-events-none ${press}`
export function authChip(on: boolean) {
  return `min-h-11 rounded-xl border px-4 text-[15px] font-medium ${press} ${
    on ? 'border-teal-700 bg-teal-50 text-teal-900' : 'border-slate-200 bg-white text-slate-700 hover:border-slate-300 hover:bg-slate-50'
  }`
}
