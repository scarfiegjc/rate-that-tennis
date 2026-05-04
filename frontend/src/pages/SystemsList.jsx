import { useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import { api } from '../api'

function MetricChip({ label, value, colour }) {
  return (
    <div style={{ minWidth: 70, textAlign: 'center' }}>
      <div style={{
        fontSize: 18, fontWeight: 800, color: colour || 'var(--text)',
        fontVariantNumeric: 'tabular-nums', letterSpacing: '-0.5px', lineHeight: 1,
      }}>
        {value ?? '—'}
      </div>
      <div style={{ fontSize: 10, color: 'var(--text-3)', marginTop: 2,
                    textTransform: 'uppercase', letterSpacing: 0.4 }}>{label}</div>
    </div>
  )
}

export default function SystemsList() {
  const [data, setData] = useState(null)
  const [error, setError] = useState(null)

  useEffect(() => {
    let on = true
    api.systems().then(d => { if (on) setData(d) }).catch(e => { if (on) setError(e.message) })
    return () => { on = false }
  }, [])

  if (error) return <div className="page"><div className="error">{error}</div></div>
  if (!data) return <div className="page"><div className="loading">Loading…</div></div>

  return (
    <div className="page">
      <div className="cc-header">
        <div>
          <h1 className="cc-title">Systems</h1>
          <div className="cc-subtitle">
            Bettor-friendly heuristics that flag matches worth backing — each tracked across all picks.
          </div>
        </div>
        <div className="cc-meta-badges">
          <Link to="/predictions"        className="surface-pill">Today</Link>
          <Link to="/predictions/history" className="surface-pill">History</Link>
        </div>
      </div>

      <div style={{ display: 'grid', gap: 10 }}>
        {data.systems.map(s => {
          const accuracy = s.accuracy_pct
          const roi      = s.roi_pct
          const accColour = accuracy == null ? 'var(--text-3)'
                          : accuracy >= 65   ? 'var(--green)'
                          : accuracy >= 50   ? 'var(--amber)'
                          : 'var(--red)'
          const roiColour = roi == null ? 'var(--text-3)'
                          : roi >= 0    ? 'var(--green)'
                          : 'var(--red)'
          return (
            <Link
              key={s.code}
              to={`/systems/${s.code}`}
              className="card"
              style={{
                padding: '14px 18px',
                display: 'flex',
                alignItems: 'center',
                gap: 16,
                cursor: 'pointer',
                transition: 'border-color 0.15s, box-shadow 0.15s',
              }}
            >
              <div style={{
                fontSize: 24, lineHeight: 1, width: 40, textAlign: 'center',
              }}>{s.icon || '·'}</div>

              <div style={{ flex: 1 }}>
                <div style={{
                  fontSize: 15, fontWeight: 700, letterSpacing: '-0.2px',
                  color: s.accent_colour || 'var(--text)',
                }}>{s.name}</div>
                <div style={{ fontSize: 12, color: 'var(--text-3)', marginTop: 2, lineHeight: 1.4 }}>
                  {s.description}
                </div>
              </div>

              <div style={{ display: 'flex', gap: 12 }}>
                <MetricChip label="Picks"  value={s.picks_total} />
                <MetricChip label="Accuracy" value={accuracy != null ? `${accuracy}%` : '—'} colour={accColour} />
                <MetricChip label="ROI"      value={roi != null ? `${roi > 0 ? '+' : ''}${roi}%` : '—'} colour={roiColour} />
              </div>
            </Link>
          )
        })}
      </div>

      {data.systems.length === 0 && (
        <div className="card" style={{ padding: 32, textAlign: 'center', color: 'var(--text-3)' }}>
          No systems configured yet. Apply <code>predictions_schema.sql</code> to seed the canonical set.
        </div>
      )}
    </div>
  )
}
