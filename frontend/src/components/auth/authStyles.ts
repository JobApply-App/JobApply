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

export const authLabel = 'block text-[14px] font-medium text-slate-700 mb-2'
export const authSecondary = `w-full h-12 rounded-xl border border-slate-200 bg-white text-[15px] font-semibold text-slate-700 flex items-center justify-center gap-3 hover:bg-slate-50 hover:border-slate-300 disabled:opacity-50 disabled:pointer-events-none ${press}`

// The signup steps, on the glow of KycShell: larger type, and answers as tiles.
export const kycTitle = 'text-[34px] sm:text-[44px] leading-[1.06] font-bold tracking-[-0.035em] text-slate-900 [text-wrap:balance]'
export const kycSub = 'mt-3 text-[17px] leading-relaxed text-slate-600'
export const kycPrimary = `w-full h-14 rounded-2xl bg-ja-primaryHover text-white text-[16px] font-semibold tracking-tight flex items-center justify-center gap-2 shadow-elevation-2 hover:bg-ja-harbor disabled:opacity-40 disabled:pointer-events-none ${press}`
export function kycOption(on: boolean) {
  return `min-h-14 rounded-2xl px-3 py-2 text-[16px] font-semibold tracking-tight ${press} ${
    on ? 'bg-ja-harbor text-white shadow-elevation-2' : 'bg-white/70 text-slate-700 ring-1 ring-inset ring-slate-900/10 hover:bg-white'
  }`
}
