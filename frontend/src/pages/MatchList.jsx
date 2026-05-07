/**
 * MatchList — Command centre. Matches grouped by date → tournament.
 * Each match is a compact horizontal row: time · players · probability · edge.
 *
 * Filters: surface · gender (Men/Women) · tournament
 * Sort:    by time (default, grouped view) · by win chance (flat ranked list)
 */

import { useState, useEffect, useMemo } from 'react'
import { useNavigate } from 'react-router-dom'
import { api } from '../api.js'
import FormDots from '../components/FormDots.jsx'
import EdgeBadge from '../components/EdgeBadge.jsx'
import ProbBar from '../components/ProbBar.jsx'
import RttLozenge from '../components/RttLozenge.jsx'

// ── Surface dot ───────────────────────────────────────────────────────────────

function SurfaceDot({ surface }) {
  const cls = (surface || '').toLowerCase().replace(' ', '-')
  return <span className={`surface-dot ${cls}`} title={surface} />
}

// ── Match row ─────────────────────────────────────────────────────────────────

function MatchRow({ match, showTournament }) {
  const navigate = useNavigate()
  const p1   = match.first_player  || {}
  const p2   = match.second_player || {}
  const pred = match.prediction    || {}

  const isLive    = /in play|live|set \d|game/i.test(match.event_status || '')
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

  let predictionCorrect = null
  if (isFinished && p1prob != null) {
    const predictedSide = p1prob >= 50 ? 1 : 2
    const actualWinner  = winner1 ? 1 : winner2 ? 2 : null
    if (actualWinner != null) predictionCorrect = predictedSide === actualWinner
  }

  const rowCls = isLive
    ? 'match-row match-row--live'
    : predictionCorrect === true
      ? 'match-row match-row--correct'
      : predictionCorrect === false
        ? 'match-row match-row--wrong'
        : 'match-row'

  const liveScore = match.final_result || match.game_result || ''

  return (
    <button
      className={rowCls}
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
          <RttLozenge score={p1.rtt_score} hideIfMissing />
          <FormDots dots={p1.form_dots || []} max={10} />
        </div>
      </div>

      {/* Centre */}
      <div className="match-centre">
        {isFinished && (match.set_scores || match.final_result) ? (
          <span className="match-final-score">
            {match.set_scores || match.final_result}
          </span>
        ) : isLive && liveScore ? (
          <span className="match-live-score">{liveScore}</span>
        ) : p1prob != null ? (
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
          <FormDots dots={p2.form_dots || []} max={10} />
          <RttLozenge score={p2.rtt_score} hideIfMissing />
          <span className="match-player-country">{p2.country_code || ''}</span>
        </div>
      </div>

      {/* Edge / meta */}
      <div className="match-row-meta">
        {showTournament && match.tournament && (
          <span style={{
            fontSize: 10, color: 'var(--text-3)', maxWidth: 120,
            overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap',
            marginRight: 6,
          }}>
            {match.tournament}
          </span>
        )}
        {isLive
          ? <span className="live-badge amber"><span className="live-dot" style={{ background: 'var(--amber)' }} />LIVE</span>
          : hasEdge
            ? <EdgeBadge edge={edgeVal} playerName={edgeName} />
            : isFinished
              ? predictionCorrect === true
                ? <span style={{ fontSize: 14, color: 'var(--green)', fontWeight: 700 }}>✓</span>
                : predictionCorrect === false
                  ? <span style={{ fontSize: 14, color: 'var(--red)', fontWeight: 700 }}>✗</span>
                  : null
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
          {[...matches].sort((a, b) => {
            const aLive = /in play|live|set \d|game/i.test(a.event_status || '') ? 1 : 0
            const bLive = /in play|live|set \d|game/i.test(b.event_status || '') ? 1 : 0
            if (aLive !== bLive) return bLive - aLive
            const aFin = /finished/i.test(a.event_status || '') ? 1 : 0
            const bFin = /finished/i.test(b.event_status || '') ? 1 : 0
            if (aFin !== bFin) return aFin - bFin
            const ta = a.event_time || '99:99'
            const tb = b.event_time || '99:99'
            if (ta !== tb) return ta < tb ? -1 : 1
            return (a.match_id || 0) - (b.match_id || 0)
          }).map(m => (
            <MatchRow key={m.match_id} match={m} showTournament={false} />
          ))}
        </div>
      )}
    </div>
  )
}

// ── Date group (grouped / by-time view) ──────────────────────────────────────

function DateGroup({ date, matches }) {
  const byTournament = {}
  for (const m of matches) {
    const key = m.tournament || 'Unknown Tournament'
    if (!byTournament[key]) byTournament[key] = { surface: m.surface, matches: [] }
    byTournament[key].matches.push(m)
  }

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

// ── Win-chance flat list ──────────────────────────────────────────────────────

function WinChanceList({ matches }) {
  const sorted = [...matches].sort((a, b) => {
    // Live matches always at top
    const aLive = /in play|live/i.test(a.event_status || '') ? 1 : 0
    const bLive = /in play|live/i.test(b.event_status || '') ? 1 : 0
    if (aLive !== bLive) return bLive - aLive
    // Sort by most decisive prediction (furthest from 50/50)
    const aProb = Math.max(
      a.prediction?.prob_first_player  ?? 0.5,
      a.prediction?.prob_second_player ?? 0.5,
    )
    const bProb = Math.max(
      b.prediction?.prob_first_player  ?? 0.5,
      b.prediction?.prob_second_player ?? 0.5,
    )
    return bProb - aProb
  })

  return (
    <div className="tournament-block" style={{ marginBottom: 24 }}>
      <div style={{
        fontSize: 11, fontWeight: 700, textTransform: 'uppercase',
        letterSpacing: 0.6, color: 'var(--text-3)',
        padding: '8px 14px 6px',
      }}>
        Ranked by model confidence · {sorted.length} match{sorted.length !== 1 ? 'es' : ''}
      </div>
      {sorted.map(m => (
        <MatchRow key={m.match_id} match={m} showTournament />
      ))}
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
const GENDERS  = ['All', 'Men', 'Women']
const SORTS    = [
  { id: 'time',      label: 'By time' },
  { id: 'winchance', label: 'By win chance' },
]

export default function MatchList() {
  const [matches,    setMatches]    = useState([])
  const [loading,    setLoading]    = useState(true)
  const [error,      setError]      = useState(null)
  const [surface,    setSurface]    = useState('All')
  const [gender,     setGender]     = useState('All')
  const [tournament, setTournament] = useState('')
  const [sortBy,     setSortBy]     = useState('time')
  const [lastFetch,  setLastFetch]  = useState(null)

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

  // Build tournament list from all matches (before filtering)
  const tournamentOptions = useMemo(() => {
    const names = new Set()
    for (const m of matches) {
      if (m.tournament) names.add(m.tournament)
    }
    return Array.from(names).sort()
  }, [matches])

  // Apply all active filters
  const filtered = useMemo(() => {
    return matches.filter(m => {
      if (surface !== 'All' && (m.surface || '').toLowerCase() !== surface.toLowerCase()) return false
      if (gender === 'Men'   && m.gender !== 'Men')   return false
      if (gender === 'Women' && m.gender !== 'Women') return false
      if (tournament && m.tournament !== tournament)   return false
      return true
    })
  }, [matches, surface, gender, tournament])

  // Clear tournament selection if it disappears from the filtered set
  useEffect(() => {
    if (tournament && filtered.length > 0 && !filtered.some(m => m.tournament === tournament)) {
      setTournament('')
    }
  }, [surface, gender]) // eslint-disable-line

  const liveCount = filtered.filter(m => /in play|live/i.test(m.event_status || '')).length
  const edgeCount = filtered.filter(m =>
    Math.max(m.prediction?.edge_first || 0, m.prediction?.edge_second || 0) > 0.02
  ).length

  const groups = groupByDate(filtered)

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
          <button
            onClick={load}
            style={{ fontSize: 13, color: 'var(--text-3)', padding: '4px 6px',
                     borderRadius: 'var(--r-sm)', transition: 'color 0.12s' }}
            title="Refresh"
          >
            ↻
          </button>
          {lastFetch && (
            <div style={{ fontSize: 11, color: 'var(--text-3)' }}>
              Updated {lastFetch.toLocaleTimeString('en-GB', { hour: '2-digit', minute: '2-digit' })}
            </div>
          )}
        </div>
      </div>

      {/* Filter + sort bar */}
      <div style={{
        display: 'flex', flexWrap: 'wrap', gap: 12,
        alignItems: 'center', marginBottom: 16,
        paddingBottom: 12,
        borderBottom: '1px solid var(--border-faint)',
      }}>

        {/* Surface */}
        <div style={{ display: 'flex', gap: 4, alignItems: 'center' }}>
          <span style={{ fontSize: 11, color: 'var(--text-3)', marginRight: 2, whiteSpace: 'nowrap' }}>Surface</span>
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

        {/* Gender / Tour */}
        <div style={{ display: 'flex', gap: 4, alignItems: 'center' }}>
          <span style={{ fontSize: 11, color: 'var(--text-3)', marginRight: 2, whiteSpace: 'nowrap' }}>Tour</span>
          {GENDERS.map(g => (
            <button
              key={g}
              className={`surface-pill ${gender === g ? 'active' : ''}`}
              onClick={() => setGender(g)}
            >
              {g}
            </button>
          ))}
        </div>

        {/* Tournament dropdown */}
        <div style={{ display: 'flex', gap: 6, alignItems: 'center' }}>
          <span style={{ fontSize: 11, color: 'var(--text-3)', whiteSpace: 'nowrap' }}>Tournament</span>
          <select
            value={tournament}
            onChange={e => setTournament(e.target.value)}
            style={{
              padding: '4px 8px', borderRadius: 6,
              border: `1px solid ${tournament ? 'var(--accent, #3b82f6)' : 'var(--border)'}`,
              fontSize: 12,
              background: 'var(--bg-card)',
              color: tournament ? 'var(--accent, #3b82f6)' : 'var(--text-2)',
              fontFamily: 'inherit', cursor: 'pointer',
              fontWeight: tournament ? 600 : 400,
              maxWidth: 220,
            }}
          >
            <option value="">All tournaments</option>
            {tournamentOptions.map(t => (
              <option key={t} value={t}>{t}</option>
            ))}
          </select>
        </div>

        {/* Sort — pushed to the right */}
        <div style={{ display: 'flex', gap: 4, alignItems: 'center', marginLeft: 'auto' }}>
          <span style={{ fontSize: 11, color: 'var(--text-3)', marginRight: 2, whiteSpace: 'nowrap' }}>Sort</span>
          {SORTS.map(s => (
            <button
              key={s.id}
              className={`surface-pill ${sortBy === s.id ? 'active' : ''}`}
              onClick={() => setSortBy(s.id)}
            >
              {s.label}
            </button>
          ))}
        </div>

      </div>

      {/* Content */}
      {loading ? (
        <div className="loading">Loading matches…</div>
      ) : error ? (
        <div className="error">{error}</div>
      ) : filtered.length === 0 ? (
        <div className="loading">No matches found for these filters.</div>
      ) : sortBy === 'winchance' ? (
        <WinChanceList matches={filtered} />
      ) : (
        Object.entries(groups).map(([date, dayMatches]) => (
          <DateGroup key={date} date={date} matches={dayMatches} />
        ))
      )}
    </div>
  )
}
