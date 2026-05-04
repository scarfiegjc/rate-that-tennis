/**
 * LivePage — Command Centre
 *
 * Time-ordered view of all matches. Auto-refreshes every 30 seconds.
 * Sections: Live Now · Up Next · Later Today · Tomorrow
 */

import { useState, useEffect, useCallback } from 'react'
import { useNavigate } from 'react-router-dom'
import { api } from '../api.js'
import SurfaceBadge from '../components/SurfaceBadge.jsx'
import EdgeBadge from '../components/EdgeBadge.jsx'
import FormDots from '../components/FormDots.jsx'
import ProbBar from '../components/ProbBar.jsx'

const REFRESH_MS = 30_000

// ── Classify each match into a time bucket ───────────────────────────────────

function classifyMatch(match) {
  const status = (match.event_status || '').toLowerCase()
  if (status === 'in play' || status === 'live' || status === 'playing') return 'live'
  if (status === 'finished' || status === 'complete' || status === 'completed') return 'finished'

  // upcoming — look at event_time
  const now = new Date()
  const today = now.toDateString()
  const matchDate = match.event_date ? new Date(match.event_date + 'T00:00:00') : null
  const isToday = matchDate ? matchDate.toDateString() === today : false
  const isTomorrow = matchDate
    ? matchDate.toDateString() === new Date(now.getTime() + 86400000).toDateString()
    : false

  if (!isToday && isTomorrow) return 'tomorrow'
  if (!isToday && !isTomorrow) return 'other'

  // parse event_time HH:MM
  if (match.event_time) {
    try {
      const [h, m] = match.event_time.split(':').map(Number)
      const matchTime = new Date(now)
      matchTime.setHours(h, m, 0, 0)
      const diffMin = (matchTime - now) / 60000
      if (diffMin <= 0) return 'now'      // overdue / just started
      if (diffMin <= 90) return 'next'    // next 90 min
      return 'later'
    } catch {
      return 'later'
    }
  }
  return 'later'
}

function bucketOrder(bucket) {
  const order = { live: 0, now: 1, next: 2, later: 3, finished: 4, tomorrow: 5, other: 6 }
  return order[bucket] ?? 7
}

function bucketLabel(bucket) {
  const labels = {
    live:     '🔴 Live Now',
    now:      'Starting Now',
    next:     'Up Next',
    later:    'Later Today',
    finished: 'Finished',
    tomorrow: 'Tomorrow',
    other:    'Upcoming',
  }
  return labels[bucket] || bucket
}

// ── Live match card (slightly richer than the home card) ─────────────────────

function LiveMatchCard({ match, isLive }) {
  const navigate = useNavigate()
  const p1 = match.first_player || {}
  const p2 = match.second_player || {}
  const pred = match.prediction || {}
  const market = match.market || {}

  const edgeP1 = pred.edge_first || 0
  const edgeP2 = pred.edge_second || 0
  const edgeVal = Math.max(edgeP1, edgeP2)
  const edgeName = edgeP1 >= edgeP2 ? (p1.name || 'P1') : (p2.name || 'P2')
  const hasEdge = edgeVal > 0.02

  const timeStr = match.event_time ? match.event_time.slice(0, 5) : '—'

  return (
    <button
      className={`match-card live-card ${isLive ? 'live-card--active' : ''}`}
      onClick={() => navigate(`/match/${match.match_id}`)}
    >
      {isLive && <div className="live-pulse-bar" />}

      <div className="match-card-meta">
        <span className="match-card-tournament">{match.tournament || 'Tournament TBD'}</span>
        <SurfaceBadge surface={match.surface} />
        <span className="match-card-round">{match.round}</span>
        {isLive ? (
          <span className="live-badge">LIVE</span>
        ) : (
          <span className="match-time-pill">{timeStr}</span>
        )}
      </div>

      <div className="match-card-body">
        <div className="match-card-players">
          {/* Player 1 */}
          <div className="match-player">
            <div className="match-player-name">{p1.name || '—'}</div>
            <div className="match-player-country">{p1.country_code || ''}</div>
            <FormDots dots={p1.form_dots || []} />
            {p1.rtt_score != null && (
              <div style={{ fontSize: 11, color: 'var(--text-muted)' }}>
                RTT {Math.round(p1.rtt_score)}
              </div>
            )}
          </div>

          {/* Centre — prediction bar */}
          <div className="match-prob-center">
            {pred.prob_first_player != null ? (
              <>
                <ProbBar
                  p1={pred.prob_first_player}
                  p2={pred.prob_second_player}
                  name1={p1.name?.split(' ').pop() || 'P1'}
                  name2={p2.name?.split(' ').pop() || 'P2'}
                />
                <div style={{ fontSize: 10, color: 'var(--text-muted)', marginTop: 2 }}>
                  {Math.round(pred.prob_first_player * 100)}%
                  <span style={{ color: 'var(--border)', margin: '0 4px' }}>·</span>
                  {Math.round((pred.prob_second_player || 0) * 100)}%
                </div>
              </>
            ) : (
              <div className="match-prob-vs">vs</div>
            )}
          </div>

          {/* Player 2 */}
          <div className="match-player right">
            <div className="match-player-name">{p2.name || '—'}</div>
            <div className="match-player-country">{p2.country_code || ''}</div>
            <div style={{ display: 'flex', justifyContent: 'flex-end' }}>
              <FormDots dots={p2.form_dots || []} />
            </div>
            {p2.rtt_score != null && (
              <div style={{ fontSize: 11, color: 'var(--text-muted)' }}>
                RTT {Math.round(p2.rtt_score)}
              </div>
            )}
          </div>
        </div>
      </div>

      <div className="match-card-footer">
        <span className="match-time">
          {isLive ? (
            <span className="live-status-text">In progress</span>
          ) : (
            timeStr
          )}
        </span>
        {hasEdge ? (
          <EdgeBadge edge={edgeVal} playerName={edgeName} />
        ) : pred.prob_first_player != null ? (
          <span className="edge-badge neutral">Market aligned</span>
        ) : (
          <span style={{ fontSize: 11, color: 'var(--text-muted)' }}>No prediction</span>
        )}
        {(market.odds_first_player || market.odds_second_player) && (
          <span style={{ fontSize: 11, color: 'var(--text-muted)' }}>
            {market.odds_first_player?.toFixed(2)} / {market.odds_second_player?.toFixed(2)}
          </span>
        )}
      </div>
    </button>
  )
}

// ── Section block ─────────────────────────────────────────────────────────────

function BucketSection({ bucket, matches }) {
  const isLive = bucket === 'live' || bucket === 'now'
  return (
    <div className={`bucket-section ${isLive ? 'bucket-section--live' : ''}`}>
      <div className={`bucket-header ${isLive ? 'bucket-header--live' : ''}`}>
        <span className="bucket-label">{bucketLabel(bucket)}</span>
        <span className="bucket-count">{matches.length} match{matches.length !== 1 ? 'es' : ''}</span>
      </div>
      <div className="match-list">
        {matches.map(m => (
          <LiveMatchCard key={m.match_id} match={m} isLive={isLive} />
        ))}
      </div>
    </div>
  )
}

// ── Surface filter ────────────────────────────────────────────────────────────

const SURFACES = ['all', 'Hard', 'Clay', 'Grass']

// ── Main LivePage ─────────────────────────────────────────────────────────────

export default function LivePage() {
  const [matches, setMatches] = useState([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState(null)
  const [surface, setSurface] = useState('all')
  const [lastRefresh, setLastRefresh] = useState(null)

  const load = useCallback(() => {
    api.matchesToday()
      .then(data => {
        setMatches(Array.isArray(data) ? data : data.matches || [])
        setLastRefresh(new Date())
        setLoading(false)
      })
      .catch(e => {
        setError(e.message)
        setLoading(false)
      })
  }, [])

  useEffect(() => {
    load()
    const interval = setInterval(load, REFRESH_MS)
    return () => clearInterval(interval)
  }, [load])

  const filtered = surface === 'all'
    ? matches
    : matches.filter(m => (m.surface || '').toLowerCase() === surface.toLowerCase())

  // Group into buckets, sorted by time within each bucket
  const buckets = {}
  for (const m of filtered) {
    const b = classifyMatch(m)
    if (!buckets[b]) buckets[b] = []
    buckets[b].push(m)
  }

  // Sort matches within each bucket by time
  for (const b of Object.keys(buckets)) {
    buckets[b].sort((a, b) => {
      const ta = a.event_time || '99:99'
      const tb = b.event_time || '99:99'
      return ta.localeCompare(tb)
    })
  }

  // Render buckets in order, omitting empty ones
  const orderedBuckets = Object.keys(buckets).sort((a, b) => bucketOrder(a) - bucketOrder(b))
  const liveCount = (buckets.live?.length || 0) + (buckets.now?.length || 0)

  if (loading) return <div className="page"><div className="loading">Loading matches…</div></div>
  if (error)   return <div className="page"><div className="error">Error: {error}</div></div>

  return (
    <div className="page">
      {/* Header */}
      <div className="command-centre-header">
        <div style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
          <h1 style={{ margin: 0, fontSize: 20, fontWeight: 700 }}>Command Centre</h1>
          {liveCount > 0 && (
            <span className="live-count-badge">
              <span className="pulse-ring" />
              {liveCount} live
            </span>
          )}
        </div>
        <div style={{ display: 'flex', alignItems: 'center', gap: 12 }}>
          {/* Surface filter */}
          <div style={{ display: 'flex', gap: 4 }}>
            {SURFACES.map(s => (
              <button
                key={s}
                onClick={() => setSurface(s)}
                className={`tab-btn ${surface === s ? 'active' : ''}`}
                style={{ padding: '4px 10px', fontSize: 12 }}
              >
                {s === 'all' ? 'All' : s}
              </button>
            ))}
          </div>
          {/* Refresh indicator */}
          <button className="refresh-btn" onClick={load} title="Refresh">
            ↺
          </button>
          {lastRefresh && (
            <span className="refresh-time">
              Updated {lastRefresh.toLocaleTimeString('en-GB', { hour: '2-digit', minute: '2-digit' })}
            </span>
          )}
        </div>
      </div>

      {orderedBuckets.length === 0 ? (
        <div className="loading" style={{ marginTop: 40 }}>
          No matches found. Is the API running?
        </div>
      ) : (
        orderedBuckets.map(b => (
          <BucketSection key={b} bucket={b} matches={buckets[b]} />
        ))
      )}
    </div>
  )
}
