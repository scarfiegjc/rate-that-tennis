import { useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import { api } from '../api'
import SurfaceBadge from '../components/SurfaceBadge.jsx'

function StatCard({ label, value, sub }) {
  return (
    <div className="metric-card" style={{ textAlign: 'left' }}>
      <div className="metric-label">{label}</div>
      <div className="metric-value">{value ?? '—'}</div>
      {sub && <div style={{ fontSize: 11, color: 'var(--text-3)', marginTop: 4 }}>{sub}</div>}
    </div>
  )
}

// ── Pick cell — thin column on the left showing the actual prediction ───────
function PickCell({ p }) {
  const predictedSide = p.predicted_winner === 'first_player' ? 'p1' : 'p2'
  const pickPlayer    = predictedSide === 'p1' ? p.p1 : p.p2
  const pickProb      = pickPlayer?.prob != null ? Math.round(pickPlayer.prob * 100) : null
  const isPending     = pickProb == null
  const isSettled     = p.is_correct !== null && p.is_correct !== undefined

  // Use the player's last name to keep the column thin
  const lastName = (pickPlayer?.name || '').trim().split(' ').slice(-1)[0] || pickPlayer?.name || '—'

  let outcomeColor = 'var(--text-3)'
  let outcomeIcon  = null
  if (isSettled) {
    outcomeColor = p.is_correct ? 'var(--green)' : 'var(--red)'
    outcomeIcon  = p.is_correct ? '✓' : '✗'
  }

  return (
    <div className="prediction-pick">
      <div className="prediction-pick-label">Pick</div>
      <div className="prediction-pick-name" title={pickPlayer?.name}>
        {isPending ? '—' : lastName}
      </div>
      <div className="prediction-pick-prob">
        {isPending ? <span style={{ fontStyle: 'italic', color: 'var(--text-3)' }}>pending</span> : `${pickProb}%`}
      </div>
      {outcomeIcon && (
        <div className="prediction-pick-outcome" style={{ color: outcomeColor }}>
          {outcomeIcon}
        </div>
      )}
      {p.confidence && !isPending && (
        <div className="prediction-pick-conf">
          <span className={`confidence-dot ${p.confidence}`} />
          <span style={{ fontSize: 10, color: 'var(--text-3)' }}>{p.confidence}</span>
        </div>
      )}
    </div>
  )
}

// ── Match bar — same look as the rest of the site ──────────────────────────
function MatchBar({ p }) {
  const p1Pct = p.p1?.prob != null ? Math.round(p.p1.prob * 100) : null
  const p2Pct = p.p2?.prob != null ? Math.round(p.p2.prob * 100) : null
  const isPending = p1Pct == null
  const isSettled = p.is_correct !== null && p.is_correct !== undefined
  const isLive    = /in play|live|set \d|game/i.test(p.event_status || '')
  const winnerSide = p.actual_winner === 'first_player' ? 'p1'
                   : p.actual_winner === 'second_player' ? 'p2' : null

  const liveSets = p.set_scores || p.final_result || ''
  const liveGame = p.game_result || ''

  return (
    <Link
      to={`/match/${p.match_id}`}
      className={`match-row ${isLive ? 'match-row--live' : ''}`}
      style={{
        gridTemplateColumns: '50px 1fr auto 1fr 96px',
        borderLeft: 'none',
      }}
    >
      <div className={`match-row-time ${isLive ? 'live' : ''}`}>
        {isLive ? <span className="live-dot" />
                : isSettled ? <span style={{ fontSize: 10, color: 'var(--text-3)' }}>FT</span>
                : (p.event_time ? p.event_time.slice(0, 5) : '—')}
      </div>

      {/* Player 1 */}
      <div className="match-player-cell">
        <div className="match-player-name" style={
          winnerSide === 'p1' ? { color: 'var(--green)' } :
          winnerSide === 'p2' ? { color: 'var(--text-3)', fontWeight: 500 } : {}
        }>
          {p.p1?.name}
        </div>
        <div className="match-player-sub">
          <span className="match-player-country">{p.p1?.country_code}</span>
          {p1Pct != null && <span className="match-player-rtt"><span>{p1Pct}%</span></span>}
        </div>
      </div>

      {/* Centre */}
      <div className={`match-centre ${isLive ? 'match-centre--inplay' : ''}`}>
        {isSettled && liveSets ? (
          <span className="match-final-score">{liveSets}</span>
        ) : isLive ? (
          <>
            <span className="match-live-score-big">{liveSets || '—'}</span>
            {liveGame && liveGame !== liveSets && (
              <span className="match-live-game">{liveGame}</span>
            )}
          </>
        ) : isPending ? (
          <span style={{ fontSize: 11, color: 'var(--text-3)', fontStyle: 'italic' }}>pending</span>
        ) : (
          <div className="match-probs">
            <span className={p1Pct >= 50 ? 'match-prob-p1' : 'match-prob-p2'}>{p1Pct}%</span>
            <span style={{ color: 'var(--text-3)' }}>·</span>
            <span className={p2Pct >= 50 ? 'match-prob-p1' : 'match-prob-p2'}>{p2Pct}%</span>
          </div>
        )}
      </div>

      {/* Player 2 */}
      <div className="match-player-cell right">
        <div className="match-player-name" style={
          winnerSide === 'p2' ? { color: 'var(--green)' } :
          winnerSide === 'p1' ? { color: 'var(--text-3)', fontWeight: 500 } : {}
        }>
          {p.p2?.name}
        </div>
        <div className="match-player-sub">
          {p2Pct != null && <span className="match-player-rtt"><span>{p2Pct}%</span></span>}
          <span className="match-player-country">{p.p2?.country_code}</span>
        </div>
      </div>

      {/* Right meta */}
      <div className="match-row-meta">
        {p.surface && <SurfaceBadge surface={p.surface} />}
        {isLive && (
          <span className="live-badge amber">
            <span className="live-dot" style={{ background: 'var(--amber)' }} />LIVE
          </span>
        )}
      </div>
    </Link>
  )
}

// ── Combined row: thin pick column + match bar ─────────────────────────────
function PredictionTrackerRow({ p }) {
  const isSettled = p.is_correct !== null && p.is_correct !== undefined
  const rowAccent = isSettled
    ? (p.is_correct ? 'prediction-tracker-row--correct' : 'prediction-tracker-row--wrong')
    : ''

  return (
    <div className={`prediction-tracker-row ${rowAccent}`}>
      <PickCell p={p} />
      <div className="prediction-tracker-match">
        <MatchBar p={p} />
      </div>
    </div>
  )
}

// ── Header row for the table ────────────────────────────────────────────────
function TableHeader() {
  return (
    <div className="prediction-tracker-row prediction-tracker-header">
      <div className="prediction-pick prediction-pick--header">
        <div style={{ fontSize: 10, fontWeight: 700, color: 'var(--text-3)',
                      textTransform: 'uppercase', letterSpacing: 0.6 }}>
          Prediction
        </div>
      </div>
      <div className="prediction-tracker-match prediction-tracker-match--header">
        <div style={{ fontSize: 10, fontWeight: 700, color: 'var(--text-3)',
                      textTransform: 'uppercase', letterSpacing: 0.6,
                      padding: '8px 16px' }}>
          Match
        </div>
      </div>
    </div>
  )
}

export default function PredictionsToday() {
  const [data, setData]   = useState(null)
  const [stats, setStats] = useState(null)
  const [error, setError] = useState(null)

  useEffect(() => {
    let on = true
    Promise.all([api.predictionsToday(2), api.predictionsStats()])
      .then(([t, s]) => { if (on) { setData(t); setStats(s) } })
      .catch(e => { if (on) setError(e.message) })
    return () => { on = false }
  }, [])

  if (error) return <div className="page"><div className="error">{error}</div></div>
  if (!data) return <div className="page"><div className="loading">Loading…</div></div>

  // Group by date
  const byDate = {}
  for (const p of data.predictions) {
    const d = p.event_date || 'unknown'
    if (!byDate[d]) byDate[d] = []
    byDate[d].push(p)
  }
  const dates = Object.keys(byDate).sort()

  return (
    <div className="page">
      <div className="cc-header">
        <div>
          <h1 className="cc-title">Predictions tracker</h1>
          <div className="cc-subtitle">
            Today + tomorrow's matches with live result tracking
          </div>
        </div>
        <div className="cc-meta-badges">
          <span className="count-badge edge">
            {data.summary.total} predictions
          </span>
          {data.summary.settled > 0 && (
            <span className="count-badge edge">
              {data.summary.correct}/{data.summary.settled} correct
              {data.summary.accuracy_pct != null && ` (${data.summary.accuracy_pct}%)`}
            </span>
          )}
        </div>
      </div>

      {/* Headline stats */}
      {stats && (
        <div className="metric-cards" style={{ gridTemplateColumns: 'repeat(4,1fr)' }}>
          <StatCard
            label="All-time accuracy"
            value={stats.overall.accuracy_pct != null ? `${stats.overall.accuracy_pct}%` : '—'}
            sub={`${stats.overall.correct} of ${stats.overall.settled} settled`}
          />
          {stats.by_confidence.find(c => c.confidence === 'high') && (
            <StatCard
              label="High-confidence accuracy"
              value={
                (() => {
                  const r = stats.by_confidence.find(c => c.confidence === 'high')
                  return r?.accuracy_pct != null ? `${r.accuracy_pct}%` : '—'
                })()
              }
              sub={(() => {
                const r = stats.by_confidence.find(c => c.confidence === 'high')
                return r ? `${r.correct} of ${r.settled}` : ''
              })()}
            />
          )}
          <StatCard
            label="Today"
            value={data.summary.total}
            sub={`${data.summary.settled} settled`}
          />
          <StatCard
            label="Today accuracy"
            value={data.summary.accuracy_pct != null ? `${data.summary.accuracy_pct}%` : '—'}
          />
        </div>
      )}

      {/* Daily groups — settled (results) first, then live, then upcoming */}
      {dates.map(d => {
        const sorted = [...byDate[d]].sort((a, b) => {
          // settled (has actual_winner) → 0, otherwise 1
          const aSettled = a.actual_winner ? 0 : 1
          const bSettled = b.actual_winner ? 0 : 1
          if (aSettled !== bSettled) return aSettled - bSettled
          // within unsettled: live first
          const aLive = /in play|live|set \d|game/i.test(a.event_status || '') ? 0 : 1
          const bLive = /in play|live|set \d|game/i.test(b.event_status || '') ? 0 : 1
          if (aLive !== bLive) return aLive - bLive
          const ta = a.event_time || '99:99'
          const tb = b.event_time || '99:99'
          if (ta !== tb) return ta < tb ? -1 : 1
          return (a.match_id || 0) - (b.match_id || 0)
        })
        return (
          <div key={d} style={{ marginTop: 24 }}>
            <div className="date-sep">{d}</div>
            <div className="card prediction-tracker-table" style={{ overflow: 'hidden' }}>
              <TableHeader />
              {sorted.map(p => <PredictionTrackerRow key={p.match_id} p={p} />)}
            </div>
          </div>
        )
      })}

      {data.predictions.length === 0 && (
        <div className="card" style={{ padding: 32, textAlign: 'center', color: 'var(--text-3)' }}>
          No predictions yet for the next 48 hours. Run <code>run_predictions.command</code> to populate them.
        </div>
      )}

      {/* Footer link to history */}
      <div style={{ marginTop: 24, textAlign: 'center' }}>
        <Link to="/predictions/history" className="surface-pill" style={{ display: 'inline-flex' }}>
          ← Historic results
        </Link>
        {' '}
        <Link to="/systems" className="surface-pill" style={{ display: 'inline-flex' }}>
          Systems →
        </Link>
      </div>
    </div>
  )
}
