'use client'
import { useEffect, useState } from 'react'
import Link from 'next/link'
import { api } from '../../lib/api'
import SurfaceBadge from '../SurfaceBadge'

function StatCard({ label, value, sub }) {
  return (
    <div className="metric-card" style={{ textAlign: 'left' }}>
      <div className="metric-label">{label}</div>
      <div className="metric-value">{value ?? '—'}</div>
      {sub && <div style={{ fontSize: 11, color: 'var(--text-3)', marginTop: 4 }}>{sub}</div>}
    </div>
  )
}

function PredictionRow({ p }) {
  const p1Pct = p.p1?.prob != null ? Math.round(p.p1.prob * 100) : null
  const p2Pct = p.p2?.prob != null ? Math.round(p.p2.prob * 100) : null
  const isPending = p1Pct == null
  // A 50/50 prediction is not a real pick — exclude from outcome display to
  // keep visible ✓/✗ markers consistent with the header count.
  const isFiftyFifty = p1Pct != null && Math.abs(p1Pct - 50) <= 1
  const isSettled = p.is_correct !== null && p.is_correct !== undefined && !isFiftyFifty
  const winnerSide = p.actual_winner === 'first_player' ? 'p1'
                   : p.actual_winner === 'second_player' ? 'p2' : null
  // Derive the predicted side from probability directly — same logic as
  // MatchDetail — so the pick indicator is always consistent with the bar.
  const predictedSide = p1Pct != null && !isFiftyFifty
    ? (p1Pct > 50 ? 'p1' : 'p2')
    : null

  // colour coding for the row outcome
  let outcomeStyle = {}
  if (isSettled) {
    outcomeStyle = p.is_correct
      ? { background: 'var(--green-bg)', borderLeft: '3px solid var(--green)' }
      : { background: 'var(--red-bg)',   borderLeft: '3px solid var(--red)' }
  } else {
    outcomeStyle = { borderLeft: '3px solid var(--border)' }
  }

  return (
    <Link
      to={`/match/${p.match_id}`}
      className="match-row"
      style={{ ...outcomeStyle, gridTemplateColumns: '60px 1fr auto 1fr 110px' }}
    >
      <div className="match-row-time">
        {p.event_time ? p.event_time.slice(0, 5) : '—'}
        <div style={{ fontSize: 10, color: 'var(--text-3)' }}>
          {(p.event_status || '').slice(0, 12)}
        </div>
      </div>

      <div className={`match-player-cell ${winnerSide === 'p1' ? 'winner' : ''}`}>
        <div className="match-player-name" style={
          winnerSide === 'p1' ? { color: 'var(--green)' } :
          winnerSide === 'p2' ? { color: 'var(--text-3)' } : {}
        }>
          {p.p1?.name}
        </div>
        <div className="match-player-sub">
          <span className="match-player-country">{p.p1?.country_code}</span>
          {predictedSide === 'p1' && !isFiftyFifty && (
            <span style={{ fontSize: 10, color: 'var(--text-3)' }}>· pick</span>
          )}
        </div>
      </div>

      <div className="match-centre">
        {isPending ? (
          <span style={{ fontSize: 11, color: 'var(--text-3)', fontStyle: 'italic' }}>
            pending
          </span>
        ) : (
          <>
            <div className="match-probs">
              <span className={p1Pct >= 50 ? 'match-prob-p1' : 'match-prob-p2'}>{p1Pct}%</span>
              <span style={{ color: 'var(--text-3)' }}>·</span>
              <span className={p2Pct >= 50 ? 'match-prob-p1' : 'match-prob-p2'}>{p2Pct}%</span>
            </div>
            {p.confidence && (
              <span className="confidence">
                <span className={`confidence-dot ${p.confidence}`} />
                {p.confidence}
              </span>
            )}
          </>
        )}
      </div>

      <div className="match-player-cell right">
        <div className="match-player-name" style={
          winnerSide === 'p2' ? { color: 'var(--green)' } :
          winnerSide === 'p1' ? { color: 'var(--text-3)' } : {}
        }>
          {p.p2?.name}
        </div>
        <div className="match-player-sub">
          {predictedSide === 'p2' && !isFiftyFifty && (
            <span style={{ fontSize: 10, color: 'var(--text-3)' }}>pick ·</span>
          )}
          <span className="match-player-country">{p.p2?.country_code}</span>
        </div>
      </div>

      <div className="match-row-meta">
        {p.surface && <SurfaceBadge surface={p.surface} />}
        {isSettled && (
          <span style={{
            fontSize: 11,
            fontWeight: 700,
            color: p.is_correct ? 'var(--green-text)' : 'var(--red)',
            marginLeft: 4,
          }}>
            {p.is_correct ? '✓' : '✗'}
          </span>
        )}
      </div>
    </Link>
  )
}

export default function PredictionsTodayClient() {

  const [data, setData] = useState(null)
  const [stats, setStats] = useState(null)
  const [error, setError] = useState(null)

  useEffect(() => {
    let on = true
    api.predictionsToday(2)
      .then(t => { if (on) setData(t) })
      .catch(e => { if (on) setError(e.message) })
    api.predictionsStats()
      .then(s => { if (on) setStats(s) })
      .catch(() => {/* stats panel optional — don't block the page */})
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
            <div className="card" style={{ overflow: 'hidden' }}>
              {sorted.map(p => <PredictionRow key={p.match_id} p={p} />)}
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
        <Link href="/predictions/history" className="surface-pill" style={{ display: 'inline-flex' }}>
          ← Historic results
        </Link>
        {' '}
        <Link href="/systems" className="surface-pill" style={{ display: 'inline-flex' }}>
          Systems →
        </Link>
      </div>
    </div>
  )
}
