import { useEffect, useState } from 'react'
import { Link, useParams } from 'react-router-dom'
import { api } from '../api'
import SurfaceBadge from '../components/SurfaceBadge.jsx'

function PickRow({ pick }) {
  const isSettled = pick.is_correct !== null && pick.is_correct !== undefined
  const sideName = pick.pick === 'first_player' ? pick.p1?.name : pick.p2?.name
  const oppName  = pick.pick === 'first_player' ? pick.p2?.name : pick.p1?.name
  const colour = !isSettled ? 'var(--text-3)'
               : pick.is_correct ? 'var(--green)' : 'var(--red)'

  return (
    <Link
      to={`/match/${pick.match_id}`}
      style={{
        display: 'grid',
        gridTemplateColumns: '40px 1fr 90px 70px',
        padding: '11px 16px',
        borderBottom: '1px solid var(--border-faint)',
        alignItems: 'center',
        cursor: 'pointer',
      }}
    >
      <div style={{ color: colour, fontSize: 16, fontWeight: 700 }}>
        {!isSettled ? '·' : (pick.is_correct ? '✓' : '✗')}
      </div>
      <div>
        <div style={{ fontSize: 13, fontWeight: 600 }}>
          {sideName} <span style={{ color: 'var(--text-3)', fontWeight: 400 }}>vs</span> {oppName}
        </div>
        <div style={{ fontSize: 11, color: 'var(--text-3)', marginTop: 2 }}>
          {pick.event_date} · {pick.tournament || ''}
          {pick.surface && <> · <SurfaceBadge surface={pick.surface} /></>}
          {pick.confidence && <> · <span className="confidence">
            <span className={`confidence-dot ${pick.confidence}`} /> {pick.confidence}
          </span></>}
        </div>
        <div style={{ fontSize: 11, color: 'var(--text-2)', marginTop: 4, fontStyle: 'italic' }}>
          {pick.reason}
        </div>
      </div>
      <div style={{ fontSize: 13, color: 'var(--text-2)', fontVariantNumeric: 'tabular-nums' }}>
        {pick.pick_prob != null && `${Math.round(pick.pick_prob * 100)}%`}
        {pick.market_odds != null && (
          <div style={{ fontSize: 11, color: 'var(--text-3)' }}>
            @ {pick.market_odds.toFixed(2)}
          </div>
        )}
      </div>
      <div style={{
        fontSize: 13, fontWeight: 700, textAlign: 'right',
        color: pick.profit_loss == null ? 'var(--text-3)'
              : pick.profit_loss > 0 ? 'var(--green)'
              : 'var(--red)',
      }}>
        {pick.profit_loss == null ? '—'
          : pick.profit_loss > 0 ? `+${pick.profit_loss.toFixed(2)}u`
          : `${pick.profit_loss.toFixed(2)}u`}
      </div>
    </Link>
  )
}

export default function SystemDetail() {
  const { code } = useParams()
  const [stats, setStats] = useState(null)
  const [picks, setPicks] = useState(null)
  const [filter, setFilter] = useState('all')      // all | open | settled
  const [error, setError] = useState(null)

  useEffect(() => {
    let on = true
    api.systemStats(code).then(d => { if (on) setStats(d) }).catch(e => { if (on) setError(e.message) })
    return () => { on = false }
  }, [code])

  useEffect(() => {
    let on = true
    api.systemPicks(code, { status: filter, limit: 200 })
       .then(d => { if (on) setPicks(d) })
       .catch(e => { if (on) setError(e.message) })
    return () => { on = false }
  }, [code, filter])

  if (error) return <div className="page"><div className="error">{error}</div></div>
  if (!stats) return <div className="page"><div className="loading">Loading…</div></div>

  const s = stats.system

  return (
    <div className="page">
      <div className="cc-header">
        <div style={{ display: 'flex', alignItems: 'center', gap: 14 }}>
          <div style={{ fontSize: 36, lineHeight: 1 }}>{s.icon}</div>
          <div>
            <h1 className="cc-title" style={{ color: s.accent_colour }}>{s.name}</h1>
            <div className="cc-subtitle" style={{ maxWidth: 720 }}>{s.description}</div>
          </div>
        </div>
        <div className="cc-meta-badges">
          <Link to="/systems" className="surface-pill">← All systems</Link>
        </div>
      </div>

      <div className="metric-cards" style={{ gridTemplateColumns: 'repeat(4,1fr)', marginBottom: 20 }}>
        <div className="metric-card">
          <div className="metric-value">{s.picks_total ?? 0}</div>
          <div className="metric-label">Total picks</div>
        </div>
        <div className="metric-card">
          <div className="metric-value">{s.picks_settled ?? 0}</div>
          <div className="metric-label">Settled</div>
        </div>
        <div className="metric-card">
          <div className="metric-value" style={{
            color: s.accuracy_pct == null ? 'var(--text-3)'
                  : s.accuracy_pct >= 60  ? 'var(--green)'
                  : s.accuracy_pct >= 50  ? 'var(--amber)'
                  : 'var(--red)',
          }}>
            {s.accuracy_pct != null ? `${s.accuracy_pct}%` : '—'}
          </div>
          <div className="metric-label">Accuracy</div>
        </div>
        <div className="metric-card">
          <div className="metric-value" style={{
            color: s.roi_pct == null ? 'var(--text-3)'
                  : s.roi_pct >= 0    ? 'var(--green)'
                  : 'var(--red)',
          }}>
            {s.roi_pct != null ? `${s.roi_pct > 0 ? '+' : ''}${s.roi_pct}%` : '—'}
          </div>
          <div className="metric-label">ROI</div>
        </div>
      </div>

      {/* Picks list */}
      <div style={{ display: 'flex', gap: 6, marginBottom: 12 }}>
        {['all', 'open', 'settled'].map(f => (
          <button
            key={f}
            onClick={() => setFilter(f)}
            className={`surface-pill ${filter === f ? 'active' : ''}`}
          >
            {f.charAt(0).toUpperCase() + f.slice(1)}
          </button>
        ))}
      </div>

      <div className="card" style={{ overflow: 'hidden' }}>
        <div style={{
          display: 'grid',
          gridTemplateColumns: '40px 1fr 90px 70px',
          padding: '8px 16px',
          borderBottom: '1px solid var(--border)',
          fontSize: 11,
          fontWeight: 600,
          color: 'var(--text-3)',
          textTransform: 'uppercase',
          letterSpacing: 0.4,
          background: 'var(--bg-raised)',
        }}>
          <div></div>
          <div>Pick</div>
          <div>Prob / Odds</div>
          <div style={{ textAlign: 'right' }}>P/L</div>
        </div>
        {picks?.picks?.length ? picks.picks.map(p => <PickRow key={p.pick_id} pick={p} />) : (
          <div style={{ padding: 24, textAlign: 'center', color: 'var(--text-3)' }}>
            {picks ? 'No picks yet.' : 'Loading…'}
          </div>
        )}
      </div>
    </div>
  )
}
