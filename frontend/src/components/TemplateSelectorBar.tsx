'use client'

import { TOKENS } from '@/lib/tokens'
import type { TemplateInfo } from '@/lib/apiTypes'

// ── Visual mini-thumbnails drawn via CSS (no images required) ─────────────────

function ClassicThumb({ selected }: { selected: boolean }) {
  const ink = selected ? '#fff' : '#1A1A1A'
  const line = selected ? 'rgba(255,255,255,0.35)' : '#ccc'
  return (
    <svg width={48} height={62} viewBox="0 0 48 62" style={{ borderRadius: 3 }}
      fill="none" xmlns="http://www.w3.org/2000/svg">
      <rect width={48} height={62} fill={selected ? '#2C2C2C' : '#fff'} />
      {/* name bar */}
      <rect x={8} y={6} width={32} height={4} rx={1} fill={ink} opacity={0.9} />
      <rect x={13} y={12} width={22} height={2} rx={1} fill={ink} opacity={0.5} />
      {/* rule */}
      <rect x={4} y={17} width={40} height={0.75} fill={line} />
      {/* section title */}
      <rect x={4} y={21} width={14} height={1.5} rx={0.5} fill={ink} opacity={0.7} />
      {/* body lines */}
      {[27,31,35,39,43,47,51].map((y, i) => (
        <rect key={i} x={4} y={y} width={i % 3 === 2 ? 28 : 40} height={1.2} rx={0.4} fill={ink} opacity={0.25} />
      ))}
    </svg>
  )
}

function ModernThumb({ selected }: { selected: boolean }) {
  const accent = '#0D9488'
  const bg = selected ? '#134E4A' : '#F0FDFA'
  return (
    <svg width={48} height={62} viewBox="0 0 48 62" style={{ borderRadius: 3 }}
      fill="none" xmlns="http://www.w3.org/2000/svg">
      <rect width={48} height={62} fill={bg} />
      {/* header strip */}
      <rect width={48} height={14} fill={selected ? '#0F3D39' : '#115E59'} />
      <rect x={5} y={4} width={20} height={3} rx={1} fill="white" opacity={0.9} />
      <rect x={5} y={9} width={13} height={1.5} rx={0.5} fill="white" opacity={0.5} />
      {/* accent line */}
      <rect x={4} y={19} width={12} height={1} rx={0.5} fill={accent} />
      {/* body lines */}
      {[23,27,31,35,40,44,48,52].map((y, i) => (
        <rect key={i} x={4} y={y} width={i % 3 === 1 ? 26 : 38} height={1} rx={0.4}
          fill={selected ? 'rgba(255,255,255,0.4)' : '#475569'} opacity={0.35} />
      ))}
      {/* skill pills */}
      <rect x={4} y={57} width={10} height={3} rx={1.5} fill={accent} opacity={0.25} />
      <rect x={16} y={57} width={10} height={3} rx={1.5} fill={accent} opacity={0.25} />
      <rect x={28} y={57} width={8} height={3} rx={1.5} fill={accent} opacity={0.25} />
    </svg>
  )
}

function ExecutiveThumb({ selected }: { selected: boolean }) {
  const ink = selected ? '#fff' : '#2C2C2C'
  const bg = selected ? '#2C2C2C' : '#FAFAF9'
  return (
    <svg width={48} height={62} viewBox="0 0 48 62" style={{ borderRadius: 3 }}
      fill="none" xmlns="http://www.w3.org/2000/svg">
      <rect width={48} height={62} fill={bg} />
      {/* bottom name border */}
      <rect x={4} y={4} width={22} height={3.5} rx={0.5} fill={ink} opacity={0.9} />
      <rect x={4} y={9.5} width={14} height={1.5} rx={0.5} fill={ink} opacity={0.4} />
      {/* thick rule */}
      <rect x={0} y={15} width={48} height={2.5} fill={ink} opacity={0.85} />
      {/* bold section strips */}
      <rect x={0} y={21} width={48} height={4} rx={0} fill={ink} opacity={0.12} />
      <rect x={3} y={22} width={12} height={1.8} rx={0.5} fill={ink} opacity={0.7} />
      {/* body lines */}
      {[29,33,37,42,46,50,54,58].map((y, i) => (
        <rect key={i} x={4} y={y} width={i % 3 === 2 ? 24 : 38} height={1.2} rx={0.4} fill={ink} opacity={0.22} />
      ))}
    </svg>
  )
}

function MinimalistThumb({ selected }: { selected: boolean }) {
  const ink = selected ? '#fff' : '#18181B'
  const bg = selected ? '#18181B' : '#fff'
  const faint = selected ? 'rgba(255,255,255,0.4)' : '#A1A1AA'
  return (
    <svg width={48} height={62} viewBox="0 0 48 62" style={{ borderRadius: 3 }}
      fill="none" xmlns="http://www.w3.org/2000/svg">
      <rect width={48} height={62} fill={bg} />
      {/* thin name + underline, no color block */}
      <rect x={6} y={7} width={26} height={3} rx={0.5} fill={ink} opacity={0.9} />
      <rect x={6} y={12.5} width={16} height={1.2} rx={0.4} fill={faint} />
      <rect x={6} y={17} width={36} height={0.6} fill={ink} opacity={0.8} />
      {/* wide-tracked section label */}
      <rect x={6} y={22} width={10} height={1.2} rx={0.4} fill={ink} opacity={0.7} />
      {/* body lines, airy spacing */}
      {[27,31.5,36,42,46.5,51].map((y, i) => (
        <rect key={i} x={6} y={y} width={i % 3 === 2 ? 22 : 36} height={1} rx={0.4} fill={faint} />
      ))}
    </svg>
  )
}

function TechModernThumb({ selected }: { selected: boolean }) {
  const accent = '#14B8A6'
  const sideBg = '#0F172A'
  return (
    <svg width={48} height={62} viewBox="0 0 48 62" style={{ borderRadius: 3 }}
      fill="none" xmlns="http://www.w3.org/2000/svg">
      <rect width={48} height={62} fill="#fff" />
      {/* dark sidebar */}
      <rect x={0} y={0} width={17} height={62} fill={sideBg} />
      <rect x={3} y={6} width={11} height={2.5} rx={0.5} fill="#fff" opacity={0.95} />
      <rect x={3} y={11} width={8} height={1.2} rx={0.4} fill={accent} />
      <rect x={3} y={18} width={6} height={1} rx={0.4} fill="#fff" opacity={0.35} />
      <rect x={3} y={21} width={9} height={1} rx={0.4} fill="#fff" opacity={0.35} />
      <rect x={3} y={30} width={7} height={1.2} rx={0.4} fill={accent} opacity={0.8} />
      {[34,37,40].map((y, i) => (
        <rect key={i} x={3} y={y} width={9} height={0.9} rx={0.3} fill="#fff" opacity={0.3} />
      ))}
      {/* main column */}
      <rect x={21} y={7} width={11} height={1.4} rx={0.4} fill={accent} />
      <rect x={21} y={10.5} width={24} height={0.8} fill={accent} opacity={0.6} />
      {[15,19,23,29,33,37,43,47,51].map((y, i) => (
        <rect key={i} x={21} y={y} width={i % 3 === 2 ? 16 : 24} height={1} rx={0.4}
          fill={selected ? accent : '#475569'} opacity={0.3} />
      ))}
    </svg>
  )
}

const THUMBS: Record<string, (p: { selected: boolean }) => JSX.Element> = {
  t1_classic:    ClassicThumb,
  t2_modern:     ModernThumb,
  t3_executive:  ExecutiveThumb,
  t4_minimalist: MinimalistThumb,
  t5_techmodern: TechModernThumb,
}

// ── Component ─────────────────────────────────────────────────────────────────

export interface TemplateSelectorBarProps {
  templates:        TemplateInfo[]
  selectedId:       string
  onSelect:         (id: string) => void
  isLoading?:       boolean
}

export function TemplateSelectorBar({
  templates, selectedId, onSelect, isLoading,
}: TemplateSelectorBarProps) {
  return (
    <div style={{ marginBottom: 14 }}>
      <p style={{
        fontSize: 10.5, fontWeight: 600, color: TOKENS.color.ink2,
        textTransform: 'uppercase', letterSpacing: '0.7px', marginBottom: 8,
      }}>
        Template
      </p>
      <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap' }}>
        {templates.map(t => {
          const Thumb = THUMBS[t.id]
          const active = t.id === selectedId
          return (
            <button
              key={t.id}
              onClick={() => !isLoading && onSelect(t.id)}
              disabled={isLoading}
              title={t.description}
              style={{
                flex: '1 1 60px',
                display: 'flex', flexDirection: 'column', alignItems: 'center',
                gap: 5, padding: '7px 4px 6px',
                borderRadius: 10,
                border: active
                  ? `2px solid ${TOKENS.color.primary}`
                  : `1.5px solid ${TOKENS.color.line}`,
                background: active ? TOKENS.color.primarySoft : '#fff',
                cursor: isLoading ? 'default' : 'pointer',
                opacity: isLoading ? 0.55 : 1,
                transition: 'border-color 0.15s, background 0.15s',
                position: 'relative',
              }}
            >
              {Thumb && <Thumb selected={active} />}
              <span style={{
                fontSize: 10, fontWeight: active ? 700 : 500,
                color: active ? TOKENS.color.primary : TOKENS.color.muted,
                lineHeight: 1,
              }}>
                {t.name}
              </span>
              {active && (
                <span style={{
                  position: 'absolute', top: 4, right: 4,
                  width: 8, height: 8, borderRadius: '50%',
                  background: TOKENS.color.primary,
                }} />
              )}
            </button>
          )
        })}
      </div>
    </div>
  )
}
