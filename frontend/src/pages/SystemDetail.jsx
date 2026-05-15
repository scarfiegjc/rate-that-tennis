import { useEffect, useState } from 'react'
import { Link, useParams } from 'react-router-dom'
import { api } from '../api'
import SurfaceBadge from '../components/SurfaceBadge.jsx'

function statusInfo(status) {
  if (!status) return { label: 'Upcoming', colour: 'var(--text-3)', bg: 'var(--bg-raised)' }
  const s = status.toLowerCase()
  if (s === 'finished' || s === 'ft' || s === 'awd' || s === 'retired')
    return { label: 'Finished', colour: 'var(--text-3)', bg: 'var(--bg-raised)' }
  if (s === 'not started' || s === 'ns' || s === 'scheduled')
    return { label: 'Upcoming', colour: 'var(--text-3)', bg: 'var(--bg-raised)' }
  // Anything else (Set 1, Set 2, Tiebreak, etc.) = live
  return { label: '● LIVE', colour: '#fff', bg: '#dc2626' }
}

function PickRow({ pick }) {
  const isSettled = pick.is_correct !== null && pick.is_correct !== undefined
  const pickedName = pick.pick === 'first_player' ? pick.p1?.name : pick.p2?.name
  const oppName    = pick.pick === 'first_player' ? pick.p2?.name : pick.p1?.name
  const resultColour = !isSettled ? 'var(--text-3)'
                     : pick.is_correct ? 'var(--green)' : 'var(--red)'
  const { label: statusLabel, colour: statusColour, bg: statusBg } = statusInfo(pick.event_status)
  const isLive = statusLabel === '● LIVE'

  return (
    <Link
      to={`/match/${pick.match_id}`}
      style={{
        display: 'grid',
        gridTemplateColumns: '1fr auto',
        padding: '12px 16px',
        borderBottom: '1px solid var(--border-faint)',
        alignItems: 'start',
        gap: 12,
        cursor: 'pointer',
      }}
    >
      {/* Left: pick info */}
      <div>
        {/* Status + tournament row */}
        <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 5 }}>
          <span style={{
            fontSize: 10, fontWeight: 700, letterSpacing: 0.5,
            padding: '2px 6px', borderRadius: 4,
            background: statusBg, color: statusColour,
            border: isLive ? 'none' : '1px solid var(--border)',
          }}>
            {statusLabel}
          </span>
          <span style={{ fontSize: 11, color: 'var(--text-3)' }}>
            {pick.tournament || ''}
            {pick.surface && <> · <SurfaceBadge surface={pick.surface} /></>}
          </span>
        </div>

        {/* Pick player — prominent */}
        <div style={{ display: 'flex', alignItems: 'baseline', gap: 6, marginBottom: 3 }}>
          <span style={{
            fontSize: 10, fontWeight: 700, textTransform: 'uppercase', letterSpacing: 0.5,
            color: 'var(--green-text)', background: 'var(--green-bg)',
            border: '1px solid var(--green-border)',
            padding: '1px 5px', borderRadius: 3,
          }}>Pick</span>
          <span style={{ fontSize: 14, fontWeight: 700, color: 'var(--text)' }}>
            {pickedName}
          </span>
        </div>

        {/* Opponent */}
        <div style={{ fontSize: 12, color: 'var(--text-3)', marginBottom: 4 }}>
          vs {oppName}
        </div>

        {/* Reason */}
        {pick.reason && (
          <div style={{ fontSize: 11, color: 'var(--text-2)', fontStyle: 'italic' }}>
            {pick.reason}
          </div>
        )}
      </div>

      {/* Right: result + prob + P/L */}
      <div style={{ display: 'flex', flexDirection: 'column', alignItems: 'flex-end', gap: 4, minWidth: 70 }}>
        <div style={{ fontSize: 18, fontWeight: 700, lineHeight: 1, color: resultColour }}>
          {!isSettled ? '·' : (pick.is_correct ? '✓' : '✗')}
        </div>
        {pick.pick_prob != null && (
          <div style={{ fontSize: 12, color: 'var(--text-2)', fontVariantNumeric: 'tabular-nums' }}>
            {Math.round(pick.pick_prob * 100)}%
            {pick.market_odds != null && (
              <span style={{ color: 'var(--text-3)', marginLeft: 4 }}>@ {pick.market_odds.toFixed(2)}</span>
            )}
          </div>
        )}
        <div style={{
          fontSize: 13, fontWeight: 700,
          color: pick.profit_loss == null ? 'var(--text-3)'
                : pick.profit_loss > 0 ? 'var(--green)'
                : 'var(--red)',
        }}>
          {pick.profit_loss == null ? '—'
            : pick.profit_loss > 0 ? `+${pick.profit_loss.toFixed(2)}u`
            : `${pick.profit_loss.toFixed(2)}u`}
        </div>
      </div>
    </Link>
  )
}

export default function SystemDetail() {
  const { code } = useParams()
  const [stats, setStats] = useState(null)
  const [picks, setPicks] = useState(null)
  const [filter, setFilter] = useState('open')     // open | all | settled
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
        {['open', 'settled', 'all'].map(f => (
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
          gridTemplateColumns: '1fr auto',
          padding: '8px 16px',
          borderBottom: '1px solid var(--border)',
          fontSize: 11,
          fontWeight: 600,
          color: 'var(--text-3)',
          textTransform: 'uppercase',
          letterSpacing: 0.4,
          background: 'var(--bg-raised)',
        }}>
          <div>Match / Pick</div>
          <div style={{ textAlign: 'right' }}>Result / Prob / P&L</div>
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
