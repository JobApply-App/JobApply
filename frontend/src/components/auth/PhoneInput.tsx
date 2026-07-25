'use client'

import { useState, useRef, useEffect } from 'react'
import { isValidPhoneNumber }          from 'react-phone-number-input'

// ── Country data ──────────────────────────────────────────────────────────────

interface Country {
  code:  string
  dial:  string
  flag:  string
  name:  string
}

// Comprehensive list ordered: IL first, then alphabetically
const COUNTRIES: Country[] = [
  { code: 'IL', dial: '+972', flag: '🇮🇱', name: 'Israel'           },
  { code: 'AE', dial: '+971', flag: '🇦🇪', name: 'UAE'              },
  { code: 'AR', dial: '+54',  flag: '🇦🇷', name: 'Argentina'        },
  { code: 'AT', dial: '+43',  flag: '🇦🇹', name: 'Austria'          },
  { code: 'AU', dial: '+61',  flag: '🇦🇺', name: 'Australia'        },
  { code: 'BE', dial: '+32',  flag: '🇧🇪', name: 'Belgium'          },
  { code: 'BR', dial: '+55',  flag: '🇧🇷', name: 'Brazil'           },
  { code: 'CA', dial: '+1',   flag: '🇨🇦', name: 'Canada'           },
  { code: 'CH', dial: '+41',  flag: '🇨🇭', name: 'Switzerland'      },
  { code: 'CN', dial: '+86',  flag: '🇨🇳', name: 'China'            },
  { code: 'CZ', dial: '+420', flag: '🇨🇿', name: 'Czech Republic'   },
  { code: 'DE', dial: '+49',  flag: '🇩🇪', name: 'Germany'          },
  { code: 'DK', dial: '+45',  flag: '🇩🇰', name: 'Denmark'          },
  { code: 'EG', dial: '+20',  flag: '🇪🇬', name: 'Egypt'            },
  { code: 'ES', dial: '+34',  flag: '🇪🇸', name: 'Spain'            },
  { code: 'FI', dial: '+358', flag: '🇫🇮', name: 'Finland'          },
  { code: 'FR', dial: '+33',  flag: '🇫🇷', name: 'France'           },
  { code: 'GB', dial: '+44',  flag: '🇬🇧', name: 'United Kingdom'   },
  { code: 'GR', dial: '+30',  flag: '🇬🇷', name: 'Greece'           },
  { code: 'HK', dial: '+852', flag: '🇭🇰', name: 'Hong Kong'        },
  { code: 'HU', dial: '+36',  flag: '🇭🇺', name: 'Hungary'          },
  { code: 'ID', dial: '+62',  flag: '🇮🇩', name: 'Indonesia'        },
  { code: 'IE', dial: '+353', flag: '🇮🇪', name: 'Ireland'          },
  { code: 'IN', dial: '+91',  flag: '🇮🇳', name: 'India'            },
  { code: 'IT', dial: '+39',  flag: '🇮🇹', name: 'Italy'            },
  { code: 'JP', dial: '+81',  flag: '🇯🇵', name: 'Japan'            },
  { code: 'KR', dial: '+82',  flag: '🇰🇷', name: 'South Korea'      },
  { code: 'MX', dial: '+52',  flag: '🇲🇽', name: 'Mexico'           },
  { code: 'MY', dial: '+60',  flag: '🇲🇾', name: 'Malaysia'         },
  { code: 'NG', dial: '+234', flag: '🇳🇬', name: 'Nigeria'          },
  { code: 'NL', dial: '+31',  flag: '🇳🇱', name: 'Netherlands'      },
  { code: 'NO', dial: '+47',  flag: '🇳🇴', name: 'Norway'           },
  { code: 'NZ', dial: '+64',  flag: '🇳🇿', name: 'New Zealand'      },
  { code: 'PH', dial: '+63',  flag: '🇵🇭', name: 'Philippines'      },
  { code: 'PK', dial: '+92',  flag: '🇵🇰', name: 'Pakistan'         },
  { code: 'PL', dial: '+48',  flag: '🇵🇱', name: 'Poland'           },
  { code: 'PT', dial: '+351', flag: '🇵🇹', name: 'Portugal'         },
  { code: 'RO', dial: '+40',  flag: '🇷🇴', name: 'Romania'          },
  { code: 'RU', dial: '+7',   flag: '🇷🇺', name: 'Russia'           },
  { code: 'SA', dial: '+966', flag: '🇸🇦', name: 'Saudi Arabia'     },
  { code: 'SE', dial: '+46',  flag: '🇸🇪', name: 'Sweden'           },
  { code: 'SG', dial: '+65',  flag: '🇸🇬', name: 'Singapore'        },
  { code: 'TH', dial: '+66',  flag: '🇹🇭', name: 'Thailand'         },
  { code: 'TR', dial: '+90',  flag: '🇹🇷', name: 'Turkey'           },
  { code: 'TW', dial: '+886', flag: '🇹🇼', name: 'Taiwan'           },
  { code: 'UA', dial: '+380', flag: '🇺🇦', name: 'Ukraine'          },
  { code: 'US', dial: '+1',   flag: '🇺🇸', name: 'United States'    },
  { code: 'VN', dial: '+84',  flag: '🇻🇳', name: 'Vietnam'          },
  { code: 'ZA', dial: '+27',  flag: '🇿🇦', name: 'South Africa'     },
]

// ── Helpers ───────────────────────────────────────────────────────────────────

function buildE164(dial: string, local: string) {
  return dial + local.replace(/\D/g, '')
}

// ── Props ─────────────────────────────────────────────────────────────────────

interface PhoneInputProps {
  value:     string
  onChange:  (full: string) => void
  disabled?: boolean
  hasError?: boolean
  id?:       string
}

// ── Component ─────────────────────────────────────────────────────────────────

export function PhoneInput({
  value,
  onChange,
  disabled  = false,
  hasError  = false,
  id        = 'phone',
}: PhoneInputProps) {
  const [country,  setCountry]  = useState<Country>(() =>
    COUNTRIES.find(c => value.startsWith(c.dial)) ?? COUNTRIES[0]
  )
  const [local,    setLocal]    = useState(() => {
    const match = COUNTRIES.find(c => value.startsWith(c.dial))
    return match ? value.slice(match.dial.length) : ''
  })
  const [open,     setOpen]     = useState(false)
  const [query,    setQuery]    = useState('')
  const [touched,  setTouched]  = useState(false)

  const wrapperRef  = useRef<HTMLDivElement>(null)
  const searchRef   = useRef<HTMLInputElement>(null)

  // Close on outside click
  useEffect(() => {
    if (!open) return
    function handler(e: MouseEvent) {
      if (wrapperRef.current && !wrapperRef.current.contains(e.target as Node)) {
        setOpen(false)
        setQuery('')
      }
    }
    document.addEventListener('mousedown', handler)
    return () => document.removeEventListener('mousedown', handler)
  }, [open])

  // Focus search when dropdown opens
  useEffect(() => {
    if (open) setTimeout(() => searchRef.current?.focus(), 50)
  }, [open])

  const filtered = query
    ? COUNTRIES.filter(c =>
        c.name.toLowerCase().includes(query.toLowerCase()) ||
        c.dial.includes(query)
      )
    : COUNTRIES

  function selectCountry(c: Country) {
    setCountry(c)
    setOpen(false)
    setQuery('')
    onChange(buildE164(c.dial, local))
  }

  function handleLocalChange(e: React.ChangeEvent<HTMLInputElement>) {
    const raw = e.target.value.replace(/[^\d\s\-().]/g, '')
    setLocal(raw)
    setTouched(true)
    onChange(buildE164(country.dial, raw))
  }

  const full    = buildE164(country.dial, local)
  const isValid = full.length > 4 && isValidPhoneNumber(full)
  const invalid = touched && local.replace(/\D/g, '').length > 0 && !isValid

  const borderColor = (hasError || invalid) ? '#F43F5E' : isValid ? '#14b8a6' : '#E2E8F0'
  const focusCls    = (hasError || invalid)
    ? 'focus-within:border-rose-400 focus-within:ring-2 focus-within:ring-rose-500/20'
    : 'focus-within:border-teal-400 focus-within:ring-2 focus-within:ring-teal-500/20'

  return (
    <div className="relative" ref={wrapperRef}>
      {/* Input row */}
      <div
        className={`flex items-stretch rounded-lg border bg-slate-50 overflow-hidden transition-all ${focusCls} ${disabled ? 'opacity-50' : ''}`}
        style={{ borderColor }}
      >
        {/* Country trigger */}
        <button
          type="button"
          onClick={() => { if (!disabled) { setOpen(v => !v); setQuery('') } }}
          disabled={disabled}
          className="flex items-center gap-1.5 px-3 py-2.5 border-r bg-slate-50 hover:bg-slate-100 transition-colors flex-shrink-0"
          style={{ borderColor: '#E2E8F0' }}
          aria-label="Select country code"
          aria-haspopup="listbox"
          aria-expanded={open}
        >
          <span className="text-lg leading-none">{country.flag}</span>
          <span className="text-[13px] font-medium text-slate-600">{country.dial}</span>
          <svg
            width="10" height="10" viewBox="0 0 24 24" fill="none"
            stroke="currentColor" strokeWidth="2.5" strokeLinecap="round"
            className={`text-slate-400 transition-transform duration-150 ${open ? 'rotate-180' : ''}`}
            aria-hidden="true"
          >
            <polyline points="6 9 12 15 18 9" />
          </svg>
        </button>

        {/* Number input */}
        <input
          id={id}
          type="tel"
          inputMode="tel"
          autoComplete="tel-national"
          disabled={disabled}
          placeholder="50 000 0000"
          value={local}
          onChange={handleLocalChange}
          onBlur={() => setTouched(true)}
          className="flex-1 min-w-0 bg-transparent px-3 py-2.5 text-sm text-slate-900 placeholder:text-slate-400 outline-none"
          aria-label="Phone number"
        />

        {/* Valid checkmark */}
        {isValid && !invalid && (
          <span className="flex items-center pr-3" aria-hidden="true">
            <span className="w-4 h-4 rounded-full flex items-center justify-center"
              style={{ background: '#14b8a6' }}>
              <svg width="8" height="8" viewBox="0 0 24 24" fill="none"
                stroke="white" strokeWidth="3.5" strokeLinecap="round" strokeLinejoin="round">
                <polyline points="20 6 9 17 4 12" />
              </svg>
            </span>
          </span>
        )}
      </div>

      {/* Validation message */}
      {invalid && (
        <p className="mt-1.5 text-xs text-rose-600" role="alert">
          Please enter a valid phone number for the selected country.
        </p>
      )}

      {/* Dropdown */}
      {open && (
        <div
          className="absolute z-50 left-0 mt-1.5 w-72 rounded-xl bg-white/85 backdrop-blur-xl border border-white/60 shadow-floating overflow-hidden"
          role="listbox"
          aria-label="Select country"
        >
          {/* Search */}
          <div className="p-2 border-b border-slate-100">
            <div className="flex items-center gap-2 rounded-lg bg-slate-50 border border-slate-200 px-3 py-1.5">
              <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="#94a3b8"
                strokeWidth="2.2" strokeLinecap="round" aria-hidden="true">
                <circle cx="11" cy="11" r="8" /><line x1="21" y1="21" x2="16.65" y2="16.65" />
              </svg>
              <input
                ref={searchRef}
                type="text"
                placeholder="Search country…"
                value={query}
                onChange={e => setQuery(e.target.value)}
                className="flex-1 bg-transparent text-sm text-slate-800 placeholder:text-slate-400 outline-none"
              />
            </div>
          </div>

          {/* List */}
          <ul className="max-h-52 overflow-y-auto py-1">
            {filtered.length === 0 ? (
              <li className="px-4 py-3 text-sm text-slate-400 text-center">No results</li>
            ) : (
              filtered.map(c => (
                <li key={c.code}>
                  <button
                    type="button"
                    role="option"
                    aria-selected={c.code === country.code}
                    onClick={() => selectCountry(c)}
                    className={`w-full flex items-center gap-3 px-3 py-2 text-sm text-left transition-colors ${
                      c.code === country.code
                        ? 'bg-teal-50 text-teal-700'
                        : 'text-slate-700 hover:bg-slate-50'
                    }`}
                  >
                    <span className="text-base leading-none w-5 flex-shrink-0">{c.flag}</span>
                    <span className="flex-1 truncate font-medium">{c.name}</span>
                    <span className={`text-[12px] flex-shrink-0 tabular-nums ${c.code === country.code ? 'text-teal-500' : 'text-slate-400'}`}>
                      {c.dial}
                    </span>
                    {c.code === country.code && (
                      <svg width="10" height="10" viewBox="0 0 24 24" fill="none"
                        stroke="currentColor" strokeWidth="3" strokeLinecap="round"
                        className="text-teal-500 flex-shrink-0">
                        <polyline points="20 6 9 17 4 12" />
                      </svg>
                    )}
                  </button>
                </li>
              ))
            )}
          </ul>
        </div>
      )}
    </div>
  )
}
