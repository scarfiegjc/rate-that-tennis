// Sub-nav for the three Predictions sub-pages. Used by:
//   /predictions          → PredictionsResults  (Results)
//   /predictions/today    → PredictionsToday    (Today)
//   /predictions/history  → PredictionsHistory  (Daily history)

import { Link, useLocation } from 'react-router-dom'

const TABS = [
  { to: '/predictions',         label: 'Results',     match: (p) => p === '/predictions' },
  { to: '/predictions/today',   label: 'Today',       match: (p) => p.startsWith('/predictions/today') },
  { to: '/predictions/history', label: 'Daily',       match: (p) => p.startsWith('/predictions/history') },
]

export default function PredictionsTabs() {
  const loc = useLocation()
  return (
    <div style={{
      display: 'flex', gap: 4, marginTop: 4, marginBottom: 4,
      borderBottom: '1px solid var(--border-faint)',
    }}>
      {TABS.map(t => {
        const active = t.match(loc.pathname)
        return (
          <Link
            key={t.to}
            to={t.to}
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
