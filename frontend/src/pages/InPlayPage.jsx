/**
 * InPlayPage — only matches that are currently in play.
 *
 * Auto-refreshes every 20 seconds. The live score is the headline of every row.
 */

import { useState, useEffect, useCallback } from 'react'
import { useNavigate } from 'react-router-dom'
import { api } from '../api.js'
import FormDots from '../components/FormDots.jsx'
import RttLozenge from '../components/RttLozenge.jsx'

const REFRESH_MS = 20_000

function isLiveStatus(status) {
  return /in play|live|set \d|game/i.test(status || '')
}

function LiveScoreDisplay({ match }) {
  // Prefer aggregated set scores; fall back to game_result / final_result.
  const sets = match.set_scores || match.final_result || ''
  const game = match.game_result || ''
  const status = match.event_status || ''

  return (
    <div className="match-centre match-centre--inplay">
      {sets ? (
        <div className="match-live-score-big">{sets}</div>
      ) : (
        <div className="match-live-score-big" style={{ opacity: 0.6 }}>—</div>
      )}
      {game && game !== sets && (
        <div className="match-live-game">{game}</div>
      )}
      <div className="match-live-status">{status}</div>
    </div>
  )
}

function InPlayRow({ match }) {
  const navigate = useNavigate()
  const p1   = match.first_player  || {}
  const p2   = match.second_player || {}
  const pred = match.prediction    || {}
  const p1prob = pred.prob_first_player  != null ? Math.round(pred.prob_first_player  * 100) : null
  const p2prob = pred.prob_second_player != null ? Math.round(pred.prob_second_player * 100) : null

  return (
    <button
      className="match-row match-row--live"
      onClick={() => navigate(`/match/${match.match_id}`)}
    >
      {/* Live indicator */}
      <div className="match-row-time live">
        <span className="live-dot" />
      </div>

      {/* Player 1 */}
      <div className="match-player-cell">
        <div className="match-player-name">{p1.name || '—'}</div>
        <div className="match-player-sub">
          <span className="match-player-country">{p1.country_code || ''}</span>
          <RttLozenge score={p1.rtt_score} hideIfMissing />
          <FormDots dots={p1.form_dots || []} max={10} />
        </div>
      </div>

      {/* Centre — live score is the headline */}
      <LiveScoreDisplay match={match} />

      {/* Player 2 */}
      <div className="match-player-cell right">
        <div className="match-player-name">{p2.name || '—'}</div>
        <div className="match-player-sub">
          <FormDots dots={p2.form_dots || []} max={10} />
          <RttLozenge score={p2.rtt_score} hideIfMissing />
          <span className="match-player-country">{p2.country_code || ''}</span>
        </div>
      </div>

      {/* Right meta — model probabilities + tournament */}
      <div className="match-row-meta">
        {p1prob != null && (
          <span className="match-prob-pair" title="Model prediction">
            <span className={p1prob >= 50 ? 'match-prob-p1' : 'match-prob-p2'}>{p1prob}%</span>
            <span style={{ color: 'var(--border)', margin: '0 3px' }}>·</span>
            <span className={p2prob >= 50 ? 'match-prob-p1' : 'match-prob-p2'}>{p2prob}%</span>
          </span>
        )}
        <span className="live-badge amber">
          <span className="live-dot" style={{ background: 'var(--amber)' }} />LIVE
        </span>
      </div>
    </button>
  )
}

function TournamentGroup({ name, matches }) {
  return (
    <div className="tournament-block" style={{ marginBottom: 12 }}>
      <div className="tournament-header" style={{ cursor: 'default' }}>
        <span className="tournament-name">{name || 'Tournament'}</span>
        <div className="tournament-info">
          <span className="count-badge live">
            <span className="live-dot" />{matches.length} live
          </span>
        </div>
      </div>
      <div>
        {matches.map(m => <InPlayRow key={m.match_id} match={m} />)}
      </div>
    </div>
  )
}

export default function InPlayPage() {
  const [matches,    setMatches]    = useState([])
  const [loading,    setLoading]    = useState(true)
  const [error,      setError]      = useState(null)
  const [lastFetch,  setLastFetch]  = useState(null)

  const load = useCallback(() => {
    api.matchesToday()
      .then(data => {
        const all = Array.isArray(data) ? data : data.matches || []
        const live = all.filter(m => isLiveStatus(m.event_status))
        setMatches(live)
        setLastFetch(new Date())
        setLoading(false)
      })
      .catch(e => { setError(e.message); setLoading(false) })
  }, [])

  useEffect(() => {
    load()
    const t = setInterval(load, REFRESH_MS)
    return () => clearInterval(t)
  }, [load])

  if (loading) return <div className="page"><div className="loading">Loading live matches…</div></div>
  if (error)   return <div className="page"><div className="error">{error}</div></div>

  // Group by tournament
  const byTournament = {}
  for (const m of matches) {
    const key = m.tournament || 'Other'
    if (!byTournament[key]) byTournament[key] = []
    byTournament[key].push(m)
  }
  const tournamentList = Object.entries(byTournament).sort(([a], [b]) => a.localeCompare(b))

  return (
    <div className="page">
      <div className="cc-header">
        <div>
          <h1 className="cc-title">In play</h1>
          <div className="cc-subtitle">
            Matches happening right now · refreshes every 20s
          </div>
        </div>
        <div className="cc-meta-badges">
          <span className="count-badge live">
            <span className="live-dot" />{matches.length} live
          </span>
          {lastFetch && (
            <span style={{ fontSize: 11, color: 'var(--text-3)' }}>
              {lastFetch.toLocaleTimeString('en-GB', { hour: '2-digit', minute: '2-digit', second: '2-digit' })}
            </span>
          )}
        </div>
      </div>

      {matches.length === 0 ? (
        <div className="card" style={{ padding: 40, textAlign: 'center' }}>
          <div style={{ fontSize: 16, fontWeight: 600, marginBottom: 4 }}>Nothing in play right now</div>
          <div style={{ fontSize: 13, color: 'var(--text-3)' }}>
            Come back when matches are underway. Page refreshes automatically.
          </div>
        </div>
      ) : (
        tournamentList.map(([name, ms]) => (
          <TournamentGroup key={name} name={name} matches={ms} />
        ))
      )}
    </div>
  )
}
