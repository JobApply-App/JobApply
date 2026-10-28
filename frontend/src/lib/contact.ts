// The one place JobApply's public contact details live. Used by the Footer's
// "Contact" dialog and the accessibility statement (IS 5568 asks for a way to
// reach a person — email AND phone). Published with the founder's consent
// (2026-10-28).

export const CONTACT_EMAIL = 'ronmorim98@gmail.com'
/** E.164, for tel: and wa.me links. */
export const CONTACT_PHONE_E164 = '+972542459908'
/** How it is shown to people (Israeli local format). */
export const CONTACT_PHONE_DISPLAY = '054-245-9908'
export const CONTACT_WHATSAPP_URL = `https://wa.me/${CONTACT_PHONE_E164.slice(1)}`
