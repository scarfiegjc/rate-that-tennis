/**
 * MatchList — Command centre. 2/3 match list + 1/3 sidebar.
 * Singles only. Doubles excluded everywhere.
 *
 * Filters: surface · gender (Men/Women/All) · level (tickboxes) · tournament
 *          + visibility toggles: upcoming only · rated players · hide unidentified
 * Sort:    by time (grouped) · by win chance (flat ranked)
 * Sidebar: prediction win rate · RTT system selections · top 5 win chances
 */

import { useState, useEffect, useMemo } from 'react'
import { useNavigate } from 'react-router-dom'
import { api } from '../api.js'
import FormDots from '../components/FormDots.jsx'
import EdgeBadge from '../components/EdgeBadge.jsx'
import ProbBar from '../components/ProbBar.jsx'
import RttLozenge from '../components/RttLozenge.jsx'

// ── SEO URL helpers ───────────────────────────────────────────────────────────

function toSlug(str) {
  return (str || '')
    .toLowerCase()
    .normalize('NFD').replace(/[̀-ͯ]/g, '')   // strip diacritics
    .replace(/[^a-z0-9]+/g, '-')
    .replace(/^-+|-+$/g, '')
}

function matchUrl(match) {
  const date       = (match.event_date || '').slice(0, 10)
  const tournament = toSlug(match.tournament || '')
  const p1         = toSlug(match.first_player?.name  || 'player')
  const p2         = toSlug(match.second_player?.name || 'player')
  const slug       = [date, tournament, `${p1}-vs-${p2}`].filter(Boolean).join('-')
  return `/match/${match.match_id}/${slug}`
}

// ── Country flag emoji from ISO code (handles 2-letter alpha-2 and common 3-letter IOC codes) ─

const IOC_TO_ALPHA2 = {
  USA:'US', GBR:'GB', ESP:'ES', FRA:'FR', ITA:'IT', GER:'DE', RUS:'RU', SRB:'RS',
  AUT:'AT', ARG:'AR', CAN:'CA', AUS:'AU', JPN:'JP', CHN:'CN', KOR:'KR', BRA:'BR',
  NED:'NL', BEL:'BE', SUI:'CH', CRO:'HR', GRE:'GR', POL:'PL', NOR:'NO', SWE:'SE',
  DEN:'DK', FIN:'FI', CZE:'CZ', SVK:'SK', HUN:'HU', ROU:'RO', BUL:'BG', UKR:'UA',
  BLR:'BY', LAT:'LV', LTU:'LT', EST:'EE', POR:'PT', IRL:'IE', ISL:'IS', IND:'IN',
  KAZ:'KZ', MEX:'MX', COL:'CO', CHI:'CL', URU:'UY', PER:'PE', VEN:'VE', ECU:'EC',
  PAR:'PY', RSA:'ZA', EGY:'EG', MAR:'MA', TUN:'TN', ALG:'DZ', ISR:'IL', TUR:'TR',
  LIB:'LB', JOR:'JO', KSA:'SA', QAT:'QA', UAE:'AE', NZL:'NZ', TPE:'TW', HKG:'HK',
  SIN:'SG', THA:'TH', INA:'ID', MAS:'MY', PHI:'PH', VIE:'VN', PUR:'PR', DOM:'DO',
  BAH:'BS', BAR:'BB', JAM:'JM', SLO:'SI', MNE:'ME', MDA:'MD', GEO:'GE', ARM:'AM',
  AZE:'AZ', UZB:'UZ', LUX:'LU', MON:'MC', LIE:'LI', CYP:'CY', MLT:'MT', BIH:'BA',
  MKD:'MK', ALB:'AL', KOS:'XK',
}

function flagEmoji(code) {
  if (!code) return ''
  const up = code.toUpperCase()
  let cc = up.length === 2 ? up : (IOC_TO_ALPHA2[up] || '')
  if (cc.length !== 2) return ''
  return String.fromCodePoint(...[...cc].map(c => 0x1f1a5 + c.charCodeAt(0)))
}

// ── Surface dot ───────────────────────────────────────────────────────────────

function SurfaceDot({ surface }) {
  const cls = (surface || '').toLowerCase().replace(/\s+/g, '-')
  return <span className={`surface-dot ${cls}`} title={surface} />
}

// ── Live lozenge (flashing) ────────────────────────────────────────────────────

function LiveLozenge({ small = false }) {
  return (
    <span className={small ? 'live-lozenge live-lozenge--sm' : 'live-lozenge'}>
      <span className="live-lozenge-dot" />
      LIVE
    </span>
  )
}

// ── Momentum lozenge ──────────────────────────────────────────────────────────

function MomentumLozenge({ momentum }) {
  if (!momentum) return null
  const config = {
    rising:  { label: '↑ Rising',  cls: 'rising' },
    stable:  { label: '→ Stable',  cls: 'stable' },
    falling: { label: '↓ Falling', cls: 'falling' },
  }
  const c = config[(momentum || '').toLowerCase()]
  if (!c) return null
  return <span className={`momentum-badge ${c.cls}`} style={{ fontSize: 10 }}>{c.label}</span>
}

// ── Tickbox component ─────────────────────────────────────────────────────────

function Tickbox({ label, checked, onChange, accent }) {
  const colour = accent || 'var(--green)'
  return (
    <label style={{
      display: 'inline-flex', alignItems: 'center', gap: 6,
      cursor: 'pointer', fontSize: 12, color: 'var(--text-2)',
      padding: '3px 8px', borderRadius: 6,
      border: `1px solid ${checked ? colour : 'var(--border)'}`,
      background: checked ? `color-mix(in srgb, ${colour} 12%, transparent)` : 'transparent',
      transition: 'all 0.12s',
      whiteSpace: 'nowrap', userSelect: 'none',
    }}>
      <input
        type="checkbox"
        checked={checked}
        onChange={onChange}
        style={{ accentColor: colour, cursor: 'pointer', width: 13, height: 13, margin: 0 }}
      />
      {label}
    </label>
  )
}

// ── Match row ─────────────────────────────────────────────────────────────────

function MatchRow({ match, showTournament }) {
  const navigate = useNavigate()
  const p1   = match.first_player  || {}
  const p2   = match.second_player || {}
  const pred = match.prediction    || {}

  const isLive     = /in play|live|set \d|game/i.test(match.event_status || '')
  const isFinished = /finished/i.test(match.event_status || '')
  const edgeVal    = Math.max(pred.edge_first || 0, pred.edge_second || 0)
  const edgeName   = (pred.edge_first || 0) >= (pred.edge_second || 0)
    ? (p1.name || 'P1')
    : (p2.name || 'P2')
  const hasEdge    = edgeVal > 0.02

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

  const liveScore = match.game_result || match.final_result || ''

  return (
    <button className={rowCls} onClick={() => navigate(matchUrl(match))}>

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
        <div
          className={`match-player-name ${winner1 ? 'winner' : ''}`}
          style={winner2 ? { color: 'var(--text-3)', fontWeight: 500 } : {}}
        >
          {p1.name || '—'}
        </div>
        <div className="match-player-sub">
          <span className="match-player-country" title={p1.country_code || ''}>
            {flagEmoji(p1.country_code) || p1.country_code || ''}
          </span>
          <RttLozenge score={p1.rtt_score} hideIfMissing />
          <MomentumLozenge momentum={p1.momentum} />
          <FormDots dots={p1.form_dots || []} max={10} />
        </div>
      </div>

      {/* Centre — live lozenge / score / probabilities / vs */}
      <div className="match-centre">
        {isLive ? (
          <div style={{ display: 'flex', flexDirection: 'column', alignItems: 'center', gap: 4 }}>
            <LiveLozenge />
            {liveScore && <span className="match-live-score">{liveScore}</span>}
          </div>
        ) : isFinished && (match.set_scores || match.final_result) ? (
          <span className="match-final-score">{match.set_scores || match.final_result}</span>
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
              hideLabels
            />
          </>
        ) : (
          <span className="match-vs">vs</span>
        )}
      </div>

      {/* Player 2 */}
      <div className="match-player-cell right">
        <div
          className={`match-player-name ${winner2 ? 'winner' : ''}`}
          style={winner1 ? { color: 'var(--text-3)', fontWeight: 500 } : {}}
        >
          {p2.name || '—'}
        </div>
        <div className="match-player-sub">
          <FormDots dots={p2.form_dots || []} max={10} />
          <MomentumLozenge momentum={p2.momentum} />
          <RttLozenge score={p2.rtt_score} hideIfMissing />
          <span className="match-player-country" title={p2.country_code || ''}>
            {flagEmoji(p2.country_code) || p2.country_code || ''}
          </span>
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
        {hasEdge
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

// ── Date group ────────────────────────────────────────────────────────────────

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
          <TournamentBlock key={name} name={name} surface={surface} matches={tMatches} />
        ))}
      </div>
    </div>
  )
}

// ── Win-chance flat list ──────────────────────────────────────────────────────

function WinChanceList({ matches }) {
  const sorted = [...matches].sort((a, b) => {
    const aLive = /in play|live/i.test(a.event_status || '') ? 1 : 0
    const bLive = /in play|live/i.test(b.event_status || '') ? 1 : 0
    if (aLive !== bLive) return bLive - aLive
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

// ── Sidebar ───────────────────────────────────────────────────────────────────

function StatMini({ label, value }) {
  return (
    <div className="sidebar-stat-mini">
      <div className="sidebar-stat-value">{value ?? '—'}</div>
      <div className="sidebar-stat-label">{label}</div>
    </div>
  )
}

function Sidebar({ allMatches }) {
  const navigate = useNavigate()
  const today = new Date().toISOString().slice(0, 10)

  const todaySingles = useMemo(() =>
    allMatches.filter(m => !m.is_doubles && (m.event_date || '').slice(0, 10) === today),
    [allMatches, today]
  )

  const liveNow   = todaySingles.filter(m => /in play|live|set \d|game/i.test(m.event_status || ''))
  const finished  = todaySingles.filter(m => /finished/i.test(m.event_status || ''))
  const withPred  = finished.filter(m => m.prediction?.prob_first_player != null && m.winner)
  const correct   = withPred.filter(m => {
    const p = m.prediction
    const pick = p.prob_first_player >= 0.5 ? 'First Player' : 'Second Player'
    return pick === m.winner
  })
  const winRate   = withPred.length > 0 ? Math.round(correct.length / withPred.length * 100) : null
  const rateColor = winRate == null
    ? 'var(--text-3)'
    : winRate >= 60 ? 'var(--green)'
    : winRate >= 45 ? 'var(--amber)'
    : 'var(--red)'

  const selections   = todaySingles.filter(m => Math.max(m.edge?.p1 || 0, m.edge?.p2 || 0) > 0.02)
  const selFinished  = selections.filter(m => /finished/i.test(m.event_status || '') && m.winner)
  const selWins      = selFinished.filter(m => {
    const backFirst = (m.edge?.p1 || 0) >= (m.edge?.p2 || 0)
    return (backFirst && m.winner === 'First Player') || (!backFirst && m.winner === 'Second Player')
  })
  const selWinRate   = selFinished.length > 0 ? Math.round(selWins.length / selFinished.length * 100) : null

  const topChances = [...todaySingles]
    .filter(m => m.prediction?.prob_first_player != null)
    .sort((a, b) =>
      Math.max(b.prediction.prob_first_player, b.prediction.prob_second_player) -
      Math.max(a.prediction.prob_first_player, a.prediction.prob_second_player)
    )
    .slice(0, 5)

  return (
    <aside className="match-sidebar">

      <div className="sidebar-box">
        <div className="sidebar-box-header">
          <span>📊</span>
          <span>Today's prediction rate</span>
        </div>
        <div style={{ textAlign: 'center', padding: '14px 0 10px' }}>
          {winRate != null ? (
            <>
              <div style={{ fontSize: 44, fontWeight: 700, color: rateColor, lineHeight: 1, letterSpacing: -2 }}>
                {winRate}%
              </div>
              <div style={{ fontSize: 12, color: 'var(--text-3)', marginTop: 6 }}>
                {correct.length} correct · {withPred.length} rated
              </div>
            </>
          ) : (
            <div style={{ fontSize: 13, color: 'var(--text-3)', padding: '6px 0' }}>
              {finished.length > 0 ? 'No predictions to score yet' : 'No completed matches yet'}
            </div>
          )}
        </div>
        <div className="sidebar-stats-row" style={{ borderTop: '1px solid var(--border-faint)', paddingTop: 10, marginTop: 4 }}>
          <StatMini label="Live" value={liveNow.length || '0'} />
          <StatMini label="Total" value={todaySingles.length} />
          <StatMini label="Done"  value={finished.length} />
        </div>
      </div>

      <div className="sidebar-box">
        <div className="sidebar-box-header">
          <span>🎯</span>
          <span>RTT System Selections</span>
        </div>
        <div className="sidebar-stats-row">
          <StatMini label="Selections" value={selections.length} />
          <StatMini label="Wins"       value={selFinished.length > 0 ? selWins.length : '—'} />
          <StatMini label="Win rate"   value={selWinRate != null ? `${selWinRate}%` : '—'} />
        </div>
        {selections.length === 0 ? (
          <div className="sidebar-empty">No value selections today</div>
        ) : (
          <div className="sidebar-selection-list">
            {selections.slice(0, 6).map(m => {
              const p1 = m.first_player || {}
              const p2 = m.second_player || {}
              const ep1 = m.edge?.p1 || 0
              const ep2 = m.edge?.p2 || 0
              const backFirst  = ep1 >= ep2
              const pickedName = backFirst ? p1.name : p2.name
              const prob = backFirst
                ? m.prediction?.prob_first_player
                : m.prediction?.prob_second_player
              const edge = Math.max(ep1, ep2)
              const isLive  = /in play|live|set \d|game/i.test(m.event_status || '')
              const isDone  = /finished/i.test(m.event_status || '')
              const won  = isDone && m.winner && (
                (backFirst && m.winner === 'First Player') || (!backFirst && m.winner === 'Second Player')
              )
              const lost = isDone && m.winner && !won
              return (
                <button
                  key={m.match_id}
                  className="sidebar-selection-row"
                  onClick={() => navigate(matchUrl(m))}
                >
                  <div style={{ flex: 1, minWidth: 0 }}>
                    <div style={{ fontWeight: 600, fontSize: 13, whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis' }}>
                      {pickedName || '—'}
                    </div>
                    <div style={{ fontSize: 11, color: 'var(--text-3)' }}>
                      {m.tournament || ''}{edge > 0 ? ` · +${Math.round(edge * 100)}% edge` : ''}
                    </div>
                  </div>
                  <div style={{ display: 'flex', flexDirection: 'column', alignItems: 'flex-end', gap: 2, flexShrink: 0 }}>
                    {prob != null && (
                      <span style={{ fontSize: 13, fontWeight: 700, color: 'var(--text-2)' }}>
                        {Math.round(prob * 100)}%
                      </span>
                    )}
                    {isLive && <LiveLozenge small />}
                    {won  && <span style={{ fontSize: 13, color: 'var(--green)', fontWeight: 700 }}>✓</span>}
                    {lost && <span style={{ fontSize: 13, color: 'var(--red)',   fontWeight: 700 }}>✗</span>}
                  </div>
                </button>
              )
            })}
          </div>
        )}
        <div style={{
          fontSize: 10, color: 'var(--text-3)', textAlign: 'center',
          padding: '6px 12px 2px', borderTop: '1px solid var(--border-faint)', marginTop: 4,
        }}>
          Matches where RTT model edge &gt; 2%
        </div>
      </div>

      <div className="sidebar-box">
        <div className="sidebar-box-header">
          <span>🏆</span>
          <span>Top win chances today</span>
        </div>
        {topChances.length === 0 ? (
          <div className="sidebar-empty">No predictions available</div>
        ) : (
          <div className="sidebar-selection-list">
            {topChances.map((m, i) => {
              const p1 = m.first_player || {}
              const p2 = m.second_player || {}
              const prob1 = m.prediction?.prob_first_player ?? 0
              const prob2 = m.prediction?.prob_second_player ?? 0
              const favourite = prob1 >= prob2 ? p1 : p2
              const underdog  = prob1 >= prob2 ? p2 : p1
              const favProb   = Math.max(prob1, prob2)
              const isLive    = /in play|live|set \d|game/i.test(m.event_status || '')
              return (
                <button
                  key={m.match_id}
                  className="sidebar-selection-row"
                  onClick={() => navigate(matchUrl(m))}
                >
                  <span style={{ fontSize: 11, fontWeight: 700, color: 'var(--text-3)', width: 20, flexShrink: 0, textAlign: 'left' }}>
                    #{i + 1}
                  </span>
                  <div style={{ flex: 1, minWidth: 0 }}>
                    <div style={{ fontSize: 13, fontWeight: 600, whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis' }}>
                      {favourite.name || '—'}
                    </div>
                    <div style={{ fontSize: 11, color: 'var(--text-3)', whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis' }}>
                      vs {underdog.name || '—'}
                    </div>
                  </div>
                  <div style={{ display: 'flex', flexDirection: 'column', alignItems: 'flex-end', gap: 2, flexShrink: 0 }}>
                    <span style={{ fontSize: 14, fontWeight: 700, color: 'var(--green)' }}>
                      {Math.round(favProb * 100)}%
                    </span>
                    {isLive && <LiveLozenge small />}
                  </div>
                </button>
              )
            })}
          </div>
        )}
      </div>

    </aside>
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
    weekday: 'long', day: 'numeric', month: 'long',
  })
}

// ── Tour-level classifier — drives the Slam/Masters / Challenger / ITF tickboxes

function detectLevel(match) {
  const t  = (match.tournament || '').trim()
  const lc = t.toLowerCase()
  if (/\b(m15|m25|w15|w25|w35|w50|w60|w75|w80|w100)\b/i.test(t)) return 'ITF'
  if (/\bchallenger\b/i.test(lc))                                  return 'Challenger'
  if (/^utr\s+ptt/i.test(t))                                       return 'Challenger'
  if (/\b(masters|1000|grand\s*slam|australian open|roland.?garros|wimbledon|us open)\b/i.test(lc))
    return 'Slam / Masters'
  return 'Tour'
}

// ── Constants ─────────────────────────────────────────────────────────────────

const SURFACES = ['All', 'Hard', 'Clay', 'Grass']
const GENDERS  = ['All', 'Men', 'Women']
const LEVELS   = ['Slam / Masters', 'Challenger', 'ITF']
const SORTS    = [
  { id: 'time',      label: 'By time' },
  { id: 'winchance', label: 'By win chance' },
]

// ── Main ──────────────────────────────────────────────────────────────────────

export default function MatchList() {
  const [matches,          setMatches]          = useState([])
  const [loading,          setLoading]          = useState(true)
  const [error,            setError]            = useState(null)
  const [surface,          setSurface]          = useState('All')
  const [gender,           setGender]           = useState('All')
  const [levels,           setLevels]           = useState(() => new Set(LEVELS))
  const [upcomingOnly,     setUpcomingOnly]     = useState(false)
  const [ratedOnly,        setRatedOnly]        = useState(false)
  const [hideUnidentified, setHideUnidentified] = useState(false)
  const [tournament,       setTournament]       = useState('')
  const [sortBy,           setSortBy]           = useState('time')
  const [lastFetch,        setLastFetch]        = useState(null)

  function toggleLevel(level) {
    setLevels(prev => {
      const next = new Set(prev)
      if (next.has(level)) next.delete(level)
      else next.add(level)
      return next
    })
  }

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

  // Tournament list from non-doubles matches only
  const tournamentOptions = useMemo(() => {
    const names = new Set()
    for (const m of matches) {
      if (!m.is_doubles && m.tournament) names.add(m.tournament)
    }
    return Array.from(names).sort()
  }, [matches])

  // Filter — doubles always excluded
  const filtered = useMemo(() => {
    return matches.filter(m => {
      if (m.is_doubles) return false
      if (surface !== 'All' && (m.surface || '').toLowerCase() !== surface.toLowerCase()) return false
      if (gender === 'Men'   && m.gender !== 'Men')   return false
      if (gender === 'Women' && m.gender !== 'Women') return false
      if (tournament && m.tournament !== tournament)   return false
      // Level tickboxes — Tour 250/500 always shows; only ITF/Challenger/Slams are gated
      const lvl = detectLevel(m)
      if (lvl !== 'Tour' && !levels.has(lvl)) return false
      if (upcomingOnly && /finished/i.test(m.event_status || '')) return false
      if (ratedOnly || hideUnidentified) {
        const r1 = m.first_player?.rtt_score
        const r2 = m.second_player?.rtt_score
        if (r1 == null || r2 == null) return false
      }
      return true
    })
  }, [matches, surface, gender, tournament, levels, upcomingOnly, ratedOnly, hideUnidentified])

  // Clear tournament if filtered away
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
          >↻</button>
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
        alignItems: 'center', marginBottom: 20,
        paddingBottom: 14, borderBottom: '1px solid var(--border-faint)',
      }}>

        {/* Surface */}
        <div style={{ display: 'flex', gap: 4, alignItems: 'center' }}>
          <span style={{ fontSize: 11, color: 'var(--text-3)', marginRight: 2, whiteSpace: 'nowrap' }}>Surface</span>
          {SURFACES.map(s => (
            <button key={s} className={`surface-pill ${surface === s ? 'active' : ''}`} onClick={() => setSurface(s)}>
              {s}
            </button>
          ))}
        </div>

        {/* Tour */}
        <div style={{ display: 'flex', gap: 4, alignItems: 'center' }}>
          <span style={{ fontSize: 11, color: 'var(--text-3)', marginRight: 2, whiteSpace: 'nowrap' }}>Tour</span>
          {GENDERS.map(g => (
            <button key={g} className={`surface-pill ${gender === g ? 'active' : ''}`} onClick={() => setGender(g)}>
              {g}
            </button>
          ))}
        </div>

        {/* Level tickboxes */}
        <div style={{ display: 'flex', gap: 6, alignItems: 'center', flexWrap: 'wrap' }}>
          <span style={{ fontSize: 11, color: 'var(--text-3)', marginRight: 2, whiteSpace: 'nowrap' }}>Level</span>
          {LEVELS.map(lvl => (
            <Tickbox
              key={lvl}
              label={lvl}
              checked={levels.has(lvl)}
              onChange={() => toggleLevel(lvl)}
            />
          ))}
        </div>

        {/* Visibility tickboxes */}
        <div style={{ display: 'flex', gap: 6, alignItems: 'center', flexWrap: 'wrap' }}>
          <Tickbox
            label="Upcoming only"
            checked={upcomingOnly}
            onChange={() => setUpcomingOnly(v => !v)}
            accent="var(--amber, #f59e0b)"
          />
          <Tickbox
            label="Rated players only"
            checked={ratedOnly}
            onChange={() => setRatedOnly(v => !v)}
            accent="var(--green, #4ade80)"
          />
          <Tickbox
            label="Hide unidentified players"
            checked={hideUnidentified}
            onChange={() => setHideUnidentified(v => !v)}
            accent="var(--accent, #3b82f6)"
          />
        </div>

        {/* Tournament */}
        <div style={{ display: 'flex', gap: 6, alignItems: 'center' }}>
          <span style={{ fontSize: 11, color: 'var(--text-3)', whiteSpace: 'nowrap' }}>Tournament</span>
          <select
            value={tournament}
            onChange={e => setTournament(e.target.value)}
            style={{
              padding: '4px 8px', borderRadius: 6,
              border: `1px solid ${tournament ? 'var(--accent, #3b82f6)' : 'var(--border)'}`,
              fontSize: 12, background: 'var(--bg-card)',
              color: tournament ? 'var(--accent, #3b82f6)' : 'var(--text-2)',
              fontFamily: 'inherit', cursor: 'pointer',
              fontWeight: tournament ? 600 : 400, maxWidth: 220,
            }}
          >
            <option value="">All tournaments</option>
            {tournamentOptions.map(t => <option key={t} value={t}>{t}</option>)}
          </select>
        </div>

        {/* Sort */}
        <div style={{ display: 'flex', gap: 4, alignItems: 'center', marginLeft: 'auto' }}>
          <span style={{ fontSize: 11, color: 'var(--text-3)', marginRight: 2, whiteSpace: 'nowrap' }}>Sort</span>
          {SORTS.map(s => (
            <button key={s.id} className={`surface-pill ${sortBy === s.id ? 'active' : ''}`} onClick={() => setSortBy(s.id)}>
              {s.label}
            </button>
          ))}
        </div>

      </div>

      {/* 2-column layout: match list + sidebar */}
      <div className="matchcenter-layout">

        <div className="matchcenter-main">
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

        {!loading && !error && (
          <Sidebar allMatches={matches} />
        )}

      </div>
    </div>
  )
}
