'use client'
import Link from 'next/link'
import { usePathname } from 'next/navigation'

const TABS = [
  { to: '/predictions',         label: 'Results',     match: (p) => p === '/predictions' },
  { to: '/predictions/today',   label: 'Today',       match: (p) => p.startsWith('/predictions/today') },
  { to: '/predictions/history', label: 'Daily',       match: (p) => p.startsWith('/predictions/history') },
]

export default function PredictionsTabs() {
  const pathname = usePathname()
  return (
    <div style={{
      display: 'flex', gap: 4, marginTop: 4, marginBottom: 4,
      borderBottom: '1px solid var(--border-faint)',
    }}>
      {TABS.map(t => {
        const active = t.match(pathname)
        return (
          <Link
            key={t.to}
            href={t.to}
            style={{
              padding: '8px 14px', fontSize: 12, fontWeight: 600,
              color: active ? 'var(--text)' : 'var(--text-3)',
              borderBottom: active ? '2px solid var(--text)' : '2px solid transparent',
              marginBottom: -1,
              textDecoration: 'none',
              letterSpacing: 0.2,
            }}
          >
            {t.label}
          </Link>
        )
      })}
    </div>
  )
}
