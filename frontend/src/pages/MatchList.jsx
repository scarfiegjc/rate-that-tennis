/**
 * MatchList — Command centre. Matches grouped by date → tournament.
 * Each match is a compact horizontal row: time · players · probability · edge.
 */

import { useState, useEffect } from 'react'
import { useNavigate } from 'react-router-dom'
import { api } from '../api.js'
import FormDots from '../components/FormDots.jsx'
import EdgeBadge from '../components/EdgeBadge.jsx'
import ProbBar from '../components/ProbBar.jsx'

// ── Surface dot ───────────────────────────────────────────────────────────────

function SurfaceDot({ surface }) {
  const cls = (surface || '').toLowerCase().replace(' ', '-')
  return <span className={`surface-dot ${cls}`} title={surface} />
}

// ── Match row ─────────────────────────────────────────────────────────────────

function MatchRow({ match }) {
  const navigate = useNavigate()
  const p1   = match.first_player  || {}
  const p2   = match.second_player || {}
  const pred = match.prediction    || {}

  const isLive    = /in play|live/i.test(match.event_status || '')
  const isFinished = /finished/i.test(match.event_status || '')
  const edgeVal   = Math.max(pred.edge_first || 0, pred.edge_second || 0)
  const edgeName  = (pred.edge_first || 0) >= (pred.edge_second || 0)
    ? (p1.name || 'P1')
    : (p2.name || 'P2')
  const hasEdge   = edgeVal > 0.02

  const p1prob = pred.prob_first_player  != null ? Math.round(pred.prob_first_player  * 100) : null
  const p2prob = pred.prob_second_player != null ? Math.round(pred.prob_second_player * 100) : null

  const winner1 = isFinished && match.winner === 'First Player'
  const winner2 = isFinished && match.winner === 'Second Player'

  return (
    <button
      className={`match-row ${isLive ? 'match-row--live' : ''}`}
      onClick={() => navigate(`/match/${match.match_id}`)}
    >
      {/* Time / status */}
      <div className={`match-row-time ${isLive ? 'live' : ''}`}>
        {isLive
          ? <span className="live-dot" />
          : isFinished
            ? <span style={{ fontSize: 10, color: 'var(--text-3)' }}>FT</span>
            : match.event_time
              ? match.event_time.slice(0, 5)
              : '—'
        }
      </div>

      {/* Player 1 */}
      <div className="match-player-cell">
        <div className={`match-player-name ${winner1 ? 'winner' : ''}`}
             style={winner2 ? { color: 'var(--text-3)', fontWeight: 500 } : {}}>
          {p1.name || '—'}
        </div>
        <div className="match-player-sub">
          <span className="match-player-country">{p1.country_code || ''}</span>
          {p1.rtt_score != null && (
            <span className="match-player-rtt">RTT <span>{Math.round(p1.rtt_score)}</span></span>
          )}
          <FormDots dots={p1.form_dots || []} />
        </div>
      </div>

      {/* Centre — probability */}
      <div className="match-centre">
        {p1prob != null ? (
          <>
            <div className="match-probs">
              <span className="match-prob-p1">{p1prob}%</span>
              <span style={{ color: 'var(--border)', fontWeight: 400 }}>·</span>
              <span className="match-prob-p2">{p2prob}%</span>
            </div>
            <ProbBar
              p1={pred.prob_first_player}
              p2={pred.prob_second_player}
              name1={p1.name?.split(' ').pop() || 'P1'}
              name2={p2.name?.split(' ').pop() || 'P2'}
            />
          </>
        ) : (
          <span className="match-vs">vs</span>
        )}
      </div>

      {/* Player 2 */}
      <div className="match-player-cell right">
        <div className={`match-player-name ${winner2 ? 'winner' : ''}`}
             style={winner1 ? { color: 'var(--text-3)', fontWeight: 500 } : {}}>
          {p2.name || '—'}
        </div>
        <div className="match-player-sub">
          <FormDots dots={p2.form_dots || []} />
          {p2.rtt_score != null && (
            <span className="match-player-rtt">RTT <span>{Math.round(p2.rtt_score)}</span></span>
          )}
          <span className="match-player-country">{p2.country_code || ''}</span>
        </div>
      </div>

      {/* Edge / meta */}
      <div className="match-row-meta">
        {hasEdge
          ? <EdgeBadge edge={edgeVal} playerName={edgeName} />
          : isLive
            ? <span className="live-badge"><span className="live-dot" />Live</span>
            : isFinished
              ? null
              : p1prob != null
                ? <span className="edge-badge neutral">—</span>
                : null
        }
      </div>
    </button>
  )
}

// ── Tournament block ──────────────────────────────────────────────────────────

function TournamentBlock({ name, surface, matches }) {
  const [open, setOpen] = useState(true)

  const edgeCount = matches.filter(m => {
    const p = m.prediction || {}
    return Math.max(p.edge_first || 0, p.edge_second || 0) > 0.02
  }).length

  const liveCount = matches.filter(m =>
    /in play|live/i.test(m.event_status || '')
  ).length

  const surfaceCls = (surface || '').toLowerCase().replace(' ', '-')

  return (
    <div className="tournament-block">
      <button className="tournament-header" onClick={() => setOpen(o => !o)}>
        <span className={`chevron ${open ? 'open' : ''}`}>›</span>
        <SurfaceDot surface={surface} />
        <span className="tournament-name">{name}</span>
        <div className="tournament-info">
          {liveCount > 0 && (
            <span className="count-badge live">
              <span className="live-dot" />{liveCount} live
            </span>
          )}
          {edgeCount > 0 && (
            <span className="tournament-edge-count">
              {edgeCount} edge{edgeCount !== 1 ? 's' : ''}
            </span>
          )}
          <span className="tournament-match-count">
            {matches.length} match{matches.length !== 1 ? 'es' : ''}
          </span>
        </div>
      </button>

      {open && (
        <div>
          {matches.map(m => (
            <MatchRow key={m.match_id} match={m} />
          ))}
        </div>
      )}
    </div>
  )
}

// ── Date group ────────────────────────────────────────────────────────────────

function DateGroup({ date, matches }) {
  // Group by tournament
  const byTournament = {}
  for (const m of matches) {
    const key = m.tournament || 'Unknown Tournament'
    if (!byTournament[key]) byTournament[key] = { surface: m.surface, matches: [] }
    byTournament[key].matches.push(m)
  }

  // Tournaments with edges first
  const sorted = Object.entries(byTournament).sort(([, a], [, b]) => {
    const eA = a.matches.filter(m =>
      Math.max(m.prediction?.edge_first || 0, m.prediction?.edge_second || 0) > 0.02
    ).length
    const eB = b.matches.filter(m =>
      Math.max(m.prediction?.edge_first || 0, m.prediction?.edge_second || 0) > 0.02
    ).length
    return eB - eA
  })

  return (
    <div style={{ marginBottom: 24 }}>
      <div className="date-sep">{formatDate(date)}</div>
      <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
        {sorted.map(([name, { surface, matches: tMatches }]) => (
          <TournamentBlock
            key={name}
            name={name}
            surface={surface}
            matches={tMatches}
          />
        ))}
      </div>
    </div>
  )
}

// ── Helpers ───────────────────────────────────────────────────────────────────

function formatDate(dateStr) {
  if (!dateStr || dateStr === 'Unknown') return 'Unknown Date'
  try {
    const d = new Date(dateStr + 'T00:00:00')
    const today    = new Date()
    const tomorrow = new Date(today)
    tomorrow.setDate(today.getDate() + 1)
    if (d.toDateString() === today.toDateString())    return 'Today'
    if (d.toDateString() === tomorrow.toDateString()) return 'Tomorrow'
    return d.toLocaleDateString('en-GB', { weekday: 'long', day: 'numeric', month: 'short' })
  } catch {
    return dateStr
  }
}

function groupByDate(matches) {
  const groups = {}
  for (const m of matches) {
    const d = (m.event_date || 'Unknown').slice(0, 10)
    if (!groups[d]) groups[d] = []
    groups[d].push(m)
  }
  return groups
}

function todayLabel() {
  return new Date().toLocaleDateString('en-GB', {
    weekday: 'long', day: 'numeric', month: 'long'
  })
}

// ── Main ──────────────────────────────────────────────────────────────────────

const SURFACES = ['All', 'Hard', 'Clay', 'Grass']

export default function MatchList() {
  const [matches,  setMatches]  = useState([])
  const [loading,  setLoading]  = useState(true)
  const [error,    setError]    = useState(null)
  const [surface,  setSurface]  = useState('All')
  const [lastFetch, setLastFetch] = useState(null)

  function load() {
    setLoading(true)
    api.matchesToday()
      .then(data => {
        setMatches(Array.isArray(data) ? data : data.matches || [])
        setLastFetch(new Date())
        setLoading(false)
      })
      .catch(e => { setError(e.message); setLoading(false) })
  }

  useEffect(() => { load() }, [])

  const filtered = surface === 'All'
    ? matches
    : matches.filter(m => (m.surface || '').toLowerCase() === surface.toLowerCase())

  const groups = groupByDate(filtered)

  const liveCount = filtered.filter(m =>
    /in play|live/i.test(m.event_status || '')
  ).length
  const edgeCount = filtered.filter(m =>
    Math.max(m.prediction?.edge_first || 0, m.prediction?.edge_second || 0) > 0.02
  ).length

  return (
    <div className="page">
      {/* Header */}
      <div className="cc-header">
        <div>
          <h1 className="cc-title">Match Centre</h1>
          <div className="cc-subtitle">{todayLabel()}</div>
        </div>
        <div style={{ display: 'flex', flexDirection: 'column', alignItems: 'flex-end', gap: 8 }}>
          <div className="cc-meta-badges">
            {liveCount > 0 && (
              <span className="count-badge live">
                <span className="live-dot" />{liveCount} live
              </span>
            )}
            {edgeCount > 0 && (
              <span className="count-badge edge">
                {edgeCount} edge{edgeCount !== 1 ? 's' : ''} identified
              </span>
            )}
          </div>
          <div style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
            <div className="surface-filters">
              {SURFACES.map(s => (
                <button
                  key={s}
                  className={`surface-pill ${surface === s ? 'active' : ''}`}
                  onClick={() => setSurface(s)}
                >
                  {s}
                </button>
              ))}
            </div>
            <button
              onClick={load}
              style={{ fontSize: 13, color: 'var(--text-3)', padding: '4px 6px',
                       borderRadius: 'var(--r-sm)', transition: 'color 0.12s' }}
              title="Refresh"
            >
              ↻
            </button>
          </div>
          {lastFetch && (
            <div style={{ fontSize: 11, color: 'var(--text-3)' }}>
              Updated {lastFetch.toLocaleTimeString('en-GB', { hour: '2-digit', minute: '2-digit' })}
            </div>
          )}
        </div>
      </div>

      {/* Content */}
      {loading ? (
        <div className="loading">Loading matches…</div>
      ) : error ? (
        <div className="error">{error}</div>
      ) : Object.keys(groups).length === 0 ? (
        <div className="loading">No matches found.</div>
      ) : (
        Object.entries(groups).map(([date, dayMatches]) => (
          <DateGroup key={date} date={date} matches={dayMatches} />
        ))
      )}
    </div>
  )
}
