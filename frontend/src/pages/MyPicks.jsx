/**
 * MyPicks — two-tab page: Active picks + Results
 *
 * Active tab: pick cards with player toggle, form, ratings, H2H, edge, odds.
 *   - Amber + in-play lozenge when live (can't remove)
 *   - Confidence stars shown on card
 *   - Star to deselect (pending only)
 *   - Odds toggle: Our odds ↔ Best odds
 *
 * Results tab: summary squares + P&L chart + results table + breakdown tables
 */
import { useState, useEffect, useCallback } from 'react'
import { Link } from 'react-router-dom'
import { useAuth } from '../contexts/AuthContext.jsx'
import { api } from '../api.js'
import { seedPickedSet } from '../components/StarPick.jsx'
import AuthModal from '../components/AuthModal.jsx'
import FormDots from '../components/FormDots.jsx'
import { matchUrl } from '../utils/matchUrl.js'
import { playerUrl } from '../utils/playerUrl.js'
import courtClayImg  from '../assets/court-clay.jpg'
import courtGrassImg from '../assets/court-grass.jpg'
import courtHardImg  from '../assets/court-hard.jpg'

function courtBg(surface) {
  const s = (surface || '').toLowerCase()
  if (s.includes('clay'))  return courtClayImg
  if (s.includes('grass')) return courtGrassImg
  return courtHardImg
}

// Solid overlay colour per surface (matches tournament-header tint)
function courtOverlay(surface) {
  const s = (surface || '').toLowerCase()
  if (s.includes('clay'))  return 'rgba(184,72,54,0.72)'
  if (s.includes('grass')) return 'rgba(16,100,56,0.72)'
  if (s.includes('indoor') || s.includes('carpet')) return 'rgba(98,38,188,0.88)'
  return 'rgba(25,65,185,0.72)'
}

// ─────────────────────────────────────────────────────────────────────────────
// Helpers
// ─────────────────────────────────────────────────────────────────────────────

function fmt(n, d = 0) {
  if (n == null) return '—'
  return Number(n).toFixed(d)
}

function plColor(n) {
  if (n == null) return 'var(--text-3)'
  if (n > 0) return 'var(--green)'
  if (n < 0) return 'var(--red)'
  return 'var(--text-3)'
}

function surfaceColor(s) {
  const m = { Clay: 'var(--clay)', Hard: 'var(--hard)', Grass: 'var(--grass)', Indoor: 'var(--indoor)' }
  return m[s] || 'var(--text-3)'
}

function surfaceRatingKey(surface) {
  return {
    clay:       'clay_rating',
    hard:       'hard_rating',
    grass:      'grass_rating',
    'indoor hard': 'indoor_rating',
  }[(surface || '').toLowerCase()] || 'hard_rating'
}

// ─────────────────────────────────────────────────────────────────────────────
// In-play lozenge
// ─────────────────────────────────────────────────────────────────────────────

function InPlayLozenge() {
  return (
    <span style={{
      display: 'inline-flex', alignItems: 'center', gap: 4,
      background: '#FEF3C7', color: '#92400E',
      border: '1px solid #FDE68A',
      borderRadius: 20, padding: '2px 8px', fontSize: 11, fontWeight: 700,
    }}>
      <span style={{
        width: 6, height: 6, borderRadius: '50%',
        background: '#D97706', animation: 'pulse 1.5s infinite',
      }} />
      IN PLAY
    </span>
  )
}

// ─────────────────────────────────────────────────────────────────────────────
// Star row (confidence display)
// ─────────────────────────────────────────────────────────────────────────────

function ConfidenceStars({ n = 1, small = false }) {
  const sz = small ? 13 : 16
  return (
    <span style={{ display: 'inline-flex', gap: 1 }}>
      {[1,2,3,4,5].map(i => (
        <span key={i} style={{
          fontSize: sz, lineHeight: 1,
          color: i <= n ? '#F59E0B' : 'transparent',
          WebkitTextStroke: i <= n ? 'none' : '1.2px #D1CCC4',
        }}>★</span>
      ))}
    </span>
  )
}

// ─────────────────────────────────────────────────────────────────────────────
// EdgeBadge (inline copy to avoid import complexity)
// ─────────────────────────────────────────────────────────────────────────────

function EdgeBadge({ edge }) {
  if (edge == null) return <span style={{ fontSize: 11, color: 'var(--text-3)' }}>No edge data</span>
  if (Math.abs(edge) < 2) return <span style={{ fontSize: 11, color: 'var(--text-3)' }}>Market aligned</span>
  const color = edge >= 5 ? 'var(--green)' : 'var(--amber)'
  const bg    = edge >= 5 ? 'var(--green-bg)' : 'var(--amber-bg)'
  return (
    <span style={{
      display: 'inline-flex', alignItems: 'center',
      background: bg, color,
      borderRadius: 20, padding: '2px 8px',
      fontSize: 11, fontWeight: 700,
    }}>
      +{edge.toFixed(1)}% edge
    </span>
  )
}

// ─────────────────────────────────────────────────────────────────────────────
// Rating bar
// ─────────────────────────────────────────────────────────────────────────────

function RatingBar({ label, value }) {
  const v = Math.min(Math.max(value || 0, 0), 100)
  const color = v >= 70 ? '#166534' : v >= 50 ? '#92400E' : '#991B1B'
  return (
    <div style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
      <span style={{ fontSize: 10, color: 'var(--text-3)', width: 72, flexShrink: 0 }}>{label}</span>
      <div style={{ flex: 1, height: 4, background: 'var(--bg-sunken)', borderRadius: 99 }}>
        <div style={{ width: `${v}%`, height: '100%', background: color, borderRadius: 99 }} />
      </div>
      <span style={{ fontSize: 11, fontWeight: 700, color, width: 24, textAlign: 'right', fontVariantNumeric: 'tabular-nums' }}>
        {value != null ? Math.round(value) : '—'}
      </span>
    </div>
  )
}

// ─────────────────────────────────────────────────────────────────────────────
// Pick card (single)
// ─────────────────────────────────────────────────────────────────────────────

function PickCard({ pick, onRemove }) {
  const [side, setSide]       = useState('picked')
  const [useOurs, setUseOurs] = useState(true)
  const [intel, setIntel]     = useState(null)
  const matchId = pick.match?.id
  const p1name = pick.is_first_player ? pick.picked_player?.name : pick.opponent?.name
  const p2name = pick.is_first_player ? pick.opponent?.name : pick.picked_player?.name
  const matchLink = matchUrl({
    id: matchId,
    event_date: pick.match?.event_date,
    tournament: pick.match?.tournament_name,
    p1: { name: p1name },
    p2: { name: p2name },
  })
  useEffect(() => {
    if (!matchId) return
    let on = true
    api.matchIntelligence(matchId)
      .then(d => { if (on) setIntel(d) })
      .catch(() => {})
    return () => { on = false }
  }, [matchId])

  const isLive    = pick.status === 'live'
  const isPending = pick.status === 'pending'
  const surface   = pick.match?.surface || 'Hard'
  const srKey     = surfaceRatingKey(surface)

  const player   = side === 'picked' ? pick.picked_player : pick.opponent
  const ratings  = player?.ratings || {}
  const formDots = player?.form_dots || []

  const winProb       = player?.win_prob
  const edge          = side === 'picked' ? pick.picked_player?.edge : null
  const surfaceRating = ratings[srKey]
  const formRating    = ratings.form_score ?? ratings.form_rating
  const rttScore      = ratings.rtt_score

  // Pick intelligence: map player side to p1/p2 using is_first_player flag
  const i = intel?.intel || {}
  const intelText = (() => {
    if (!i.p1_intel && !i.p2_intel) return null
    if (side === 'picked') return pick.is_first_player ? i.p1_intel : i.p2_intel
    return pick.is_first_player ? i.p2_intel : i.p1_intel
  })()

  const oddsToShow = useOurs ? pick.our_odds : (pick.best_odds || pick.our_odds)
  const oddsLabel  = useOurs ? 'RTT odds' : `Best (${pick.best_odds_bookie || 'mkt'})`

  const isWinner = pick.status === 'won'
  const cardBg     = isLive ? '#FFFBEB' : isWinner ? '#f0fdf4' : 'var(--bg-card)'
  const cardBorder = isLive ? '2px solid #FDE68A' : isWinner ? '1px solid #86efac' : '1px solid var(--border)'

  return (
    <div style={{ background: cardBg, border: cardBorder, borderRadius: 'var(--r-lg)', boxShadow: 'var(--shadow-sm)', overflow: 'hidden' }}>

      {/* ── Header: court photo + tournament + meta ── */}
      <div style={{
        padding: '10px 14px 8px',
        borderBottom: '1px solid rgba(0,0,0,0.18)',
        display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', gap: 8,
        backgroundImage: `url(${courtBg(surface)})`,
        backgroundSize: 'cover', backgroundPosition: 'center',
        backgroundColor: courtOverlay(surface),
        backgroundBlendMode: 'multiply',
      }}>
        <div style={{ minWidth: 0, flex: 1 }}>
          <Link to={matchLink} style={{
            fontSize: 12, fontWeight: 700, color: '#fff',
            overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap', display: 'block',
          }}>
            {pick.match?.tournament_name || 'Unknown tournament'}
          </Link>
          <div style={{ display: 'flex', alignItems: 'center', gap: 6, marginTop: 2, flexWrap: 'wrap' }}>
            <span style={{ fontSize: 10, fontWeight: 600, color: 'rgba(255,255,255,0.9)' }}>{surface}</span>
            <span style={{ fontSize: 10, color: 'rgba(255,255,255,0.7)' }}>
              {pick.match?.event_date}{pick.match?.event_time ? ` · ${pick.match.event_time.slice(0,5)}` : ''}
            </span>
            {isLive && <InPlayLozenge />}
          </div>
        </div>
        <div style={{ display: 'flex', alignItems: 'center', gap: 6, flexShrink: 0 }}>
          {isPending && (
            <button onClick={() => onRemove(pick.id)} title="Remove pick"
              style={{ fontSize: 18, color: '#FDE68A', lineHeight: 1, padding: '2px 4px', textShadow: '0 0 4px rgba(0,0,0,0.4)' }}>★</button>
          )}
          {isLive && <span style={{ fontSize: 16, color: 'rgba(255,255,255,0.5)' }}>★</span>}
        </div>
      </div>

      {/* Live score */}
      {isLive && (pick.match?.set_scores || pick.match?.game_result) && (
        <div style={{ background: '#FEF9C3', padding: '8px 14px', borderBottom: '1px solid #FDE68A', display: 'flex', alignItems: 'center', justifyContent: 'center', gap: 12 }}>
          {pick.match?.set_scores && (
            <span style={{ fontSize: 16, fontWeight: 900, color: '#78350F', fontVariantNumeric: 'tabular-nums', letterSpacing: 1 }}>
              {pick.match.set_scores}
            </span>
          )}
          {pick.match?.game_result && (
            <span style={{ fontSize: 12, fontWeight: 600, color: '#92400E', fontVariantNumeric: 'tabular-nums' }}>
              ({pick.match.game_result})
            </span>
          )}
        </div>
      )}

      {/* ── Player tabs ── */}
      <div style={{ display: 'flex', borderBottom: '2px solid var(--border-faint)' }}>
        {['picked', 'opponent'].map(s => {
          const p = s === 'picked' ? pick.picked_player : pick.opponent
          const prob = p?.win_prob
          return (
            <button key={s} onClick={() => setSide(s)} style={{
              flex: 1, padding: '8px 14px',
              display: 'flex', justifyContent: 'space-between', alignItems: 'center',
              borderBottom: `2px solid ${side === s ? (s === 'picked' ? 'var(--green)' : 'var(--text-3)') : 'transparent'}`,
              marginBottom: -2,
              color: side === s ? 'var(--text)' : 'var(--text-3)',
              transition: 'all 0.15s',
            }}>
              <span style={{ fontSize: 12, fontWeight: 700 }}>
                {s === 'picked' ? '★ ' : ''}{p?.name?.split(' ').slice(-1)[0] || (s === 'picked' ? 'My pick' : 'Opponent')}
              </span>
              {prob != null && (
                <span style={{ fontSize: 13, fontWeight: 800, color: s === 'picked' ? 'var(--green)' : 'var(--text-3)', fontVariantNumeric: 'tabular-nums' }}>
                  {fmt(prob, 0)}%
                </span>
              )}
            </button>
          )
        })}
      </div>

      {/* ── Body ── */}
      <div style={{ padding: '14px', display: 'flex', flexDirection: 'column', gap: 14 }}>

        {/* Player name + win prob */}
        <div style={{ display: 'flex', alignItems: 'flex-start', justifyContent: 'space-between', gap: 8 }}>
          <span style={{ fontSize: 22, fontWeight: 800, letterSpacing: '-0.5px', lineHeight: 1.1 }}>
            {player?.name || '—'}
          </span>
          {winProb != null && (
            <div style={{ textAlign: 'right', flexShrink: 0 }}>
              <div style={{ fontSize: 34, fontWeight: 900, lineHeight: 1, color: side === 'picked' ? 'var(--green)' : 'var(--text-3)', fontVariantNumeric: 'tabular-nums' }}>
                {fmt(winProb, 0)}%
              </div>
              <div style={{ fontSize: 10, color: 'var(--text-3)', fontWeight: 600 }}>win probability</div>
            </div>
          )}
        </div>

        {/* Ratings squares */}
        <div style={{ display: 'flex', gap: 8 }}>
          {[
            { label: 'RTT', value: rttScore },
            { label: surface.split(' ')[0], value: surfaceRating },
            { label: 'Form', value: formRating },
          ].map(({ label, value }) => {
            const v = Math.round(value || 0)
            const color = value == null ? 'var(--text-3)' : v >= 70 ? 'var(--green)' : v >= 50 ? 'var(--amber)' : 'var(--red)'
            return (
              <div key={label} style={{ flex: 1, background: 'var(--bg-raised)', borderRadius: 'var(--r)', padding: '8px', textAlign: 'center' }}>
                <div style={{ fontSize: 9, color: 'var(--text-3)', fontWeight: 700, textTransform: 'uppercase', letterSpacing: '0.5px', marginBottom: 4 }}>{label}</div>
                <div style={{ fontSize: 20, fontWeight: 900, color, fontVariantNumeric: 'tabular-nums', lineHeight: 1 }}>
                  {value != null ? v : '—'}
                </div>
              </div>
            )
          })}
        </div>

        {/* Form dots */}
        {formDots.length > 0 && (
          <div>
            <div style={{ fontSize: 10, fontWeight: 700, color: 'var(--text-3)', textTransform: 'uppercase', letterSpacing: '0.5px', marginBottom: 6 }}>
              Recent form
            </div>
            <div style={{ display: 'flex', gap: 5, alignItems: 'center', flexWrap: 'wrap' }}>
              {formDots.slice(0, 10).map((d, idx) => (
                <div key={idx} style={{ display: 'flex', flexDirection: 'column', alignItems: 'center', gap: 2 }}>
                  <span style={{
                    display: 'inline-block', width: 11, height: 11, borderRadius: '50%',
                    background: d === 'W' ? '#166534' : '#DC2626',
                    opacity: d === 'W' ? 1 : 0.75,
                  }} />
                  <span style={{ fontSize: 9, fontWeight: 800, color: d === 'W' ? '#166534' : '#DC2626' }}>{d}</span>
                </div>
              ))}
            </div>
          </div>
        )}

        {/* H2H — always shown when viewing picked side */}
        {side === 'picked' && (
          <div style={{
            padding: '10px 12px', background: 'var(--bg-raised)', borderRadius: 'var(--r)',
            display: 'flex', alignItems: 'center', justifyContent: 'space-between',
          }}>
            <div>
              <div style={{ fontSize: 10, fontWeight: 700, color: 'var(--text-3)', textTransform: 'uppercase', letterSpacing: '0.5px', marginBottom: 2 }}>
                Head to head
              </div>
              {pick.h2h?.total > 0 ? (
                <div style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
                  <span style={{ fontSize: 20, fontWeight: 900, color: pick.h2h.wins > pick.h2h.losses ? 'var(--green)' : pick.h2h.wins < pick.h2h.losses ? 'var(--red)' : 'var(--text)' }}>
                    {pick.h2h.wins}–{pick.h2h.losses}
                  </span>
                  <span style={{ fontSize: 11, color: 'var(--text-3)' }}>
                    from {pick.h2h.total} meeting{pick.h2h.total !== 1 ? 's' : ''}
                  </span>
                </div>
              ) : (
                <span style={{ fontSize: 12, color: 'var(--text-3)', fontStyle: 'italic' }}>No previous meetings</span>
              )}
            </div>
            {pick.h2h?.total > 0 && (
              <div style={{ display: 'flex', gap: 3 }}>
                {Array.from({ length: Math.min(pick.h2h.total, 6) }, (_, i) => {
                  const isWin = i < pick.h2h.wins
                  return (
                    <span key={i} style={{
                      display: 'inline-block', width: 10, height: 10, borderRadius: '50%',
                      background: isWin ? '#166534' : '#DC2626', opacity: 0.8,
                    }} />
                  )
                }).reverse()}
              </div>
            )}
          </div>
        )}

        {/* Intelligence snippet */}
        {intelText && (
          <div style={{
            padding: '12px 14px',
            background: 'var(--bg-sunken)',
            borderLeft: '3px solid var(--green)',
            borderRadius: '0 var(--r) var(--r) 0',
          }}>
            <div style={{ fontSize: 10, fontWeight: 700, color: 'var(--green)', textTransform: 'uppercase', letterSpacing: '0.6px', marginBottom: 6 }}>
              Intelligence
            </div>
            <p style={{ fontSize: 12, lineHeight: 1.65, color: 'var(--text-2)', margin: 0 }}>
              {intelText.length > 320 ? intelText.slice(0, 320) + '…' : intelText}
            </p>
          </div>
        )}

        {/* ── Footer: edge + confidence + odds + match link ── */}
        <div style={{
          display: 'flex', alignItems: 'center', justifyContent: 'space-between', gap: 8,
          paddingTop: 10, borderTop: '1px solid var(--border-faint)',
        }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
            {side === 'picked' && <EdgeBadge edge={edge} />}
            <ConfidenceStars n={pick.confidence_stars} small />
          </div>
          <div style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
            <div style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
              <button onClick={() => setUseOurs(v => !v)} style={{
                fontSize: 10, fontWeight: 600, padding: '3px 7px',
                borderRadius: 20, border: '1px solid var(--border)',
                background: 'var(--bg-raised)', color: 'var(--text-3)',
              }}>
                {oddsLabel}
              </button>
              <span style={{ fontSize: 18, fontWeight: 800, color: 'var(--text)', fontVariantNumeric: 'tabular-nums' }}>
                {oddsToShow ? fmt(oddsToShow, 2) : '—'}
              </span>
            </div>
            {matchId && (
              <Link to={matchLink} style={{
                fontSize: 11, fontWeight: 600, color: 'var(--text-3)',
                padding: '3px 8px', borderRadius: 20,
                border: '1px solid var(--border)',
                background: 'var(--bg-raised)',
                whiteSpace: 'nowrap',
              }}>
                Match →
              </Link>
            )}
          </div>
        </div>
      </div>
    </div>
  )
}

// ─────────────────────────────────────────────────────────────────────────────
// Active tab
// ─────────────────────────────────────────────────────────────────────────────

function ActiveTab({ picks, loading, onRemove, onRefresh }) {
  if (loading) {
    return (
      <div style={{ padding: '60px 0', textAlign: 'center', color: 'var(--text-3)' }}>
        Loading picks…
      </div>
    )
  }

  if (!picks.length) {
    return (
      <div style={{ padding: '60px 24px', textAlign: 'center' }}>
        <div style={{ fontSize: 40, marginBottom: 12 }}>★</div>
        <p style={{ fontWeight: 600, marginBottom: 6 }}>No active picks yet</p>
        <p style={{ color: 'var(--text-3)', fontSize: 13 }}>
          Tap the ★ next to any player on the{' '}
          <Link to="/" style={{ color: 'var(--green)', fontWeight: 600 }}>match list</Link>{' '}
          to add your first pick.
        </p>
      </div>
    )
  }

  // Split: live first, then pending
  const live    = picks.filter(p => p.status === 'live')
  const pending = picks.filter(p => p.status === 'pending')

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 12 }}>
      {live.length > 0 && (
        <>
          <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
            <h3 style={{ margin: 0, fontSize: 13, fontWeight: 700, color: 'var(--amber)' }}>
              In play
            </h3>
            <span style={{
              background: 'var(--amber-bg)', color: 'var(--amber)',
              borderRadius: 20, padding: '1px 7px', fontSize: 11, fontWeight: 700,
            }}>{live.length}</span>
          </div>
          <div className="picks-grid">
            {live.map(p => <PickCard key={p.id} pick={p} onRemove={onRemove} />)}
          </div>
        </>
      )}
      {pending.length > 0 && (
        <>
          <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginTop: live.length ? 16 : 0 }}>
            <h3 style={{ margin: 0, fontSize: 13, fontWeight: 700, color: 'var(--text-2)' }}>
              Upcoming
            </h3>
            <span style={{
              background: 'var(--bg-raised)', color: 'var(--text-3)',
              borderRadius: 20, padding: '1px 7px', fontSize: 11, fontWeight: 700,
            }}>{pending.length}</span>
          </div>
          <div className="picks-grid">
            {pending.map(p => <PickCard key={p.id} pick={p} onRemove={onRemove} />)}
          </div>
        </>
      )}
    </div>
  )
}

// ─────────────────────────────────────────────────────────────────────────────
// Results tab
// ─────────────────────────────────────────────────────────────────────────────

function SummarySquare({ label, value, sub, color }) {
  return (
    <div style={{
      background: 'var(--bg-card)', border: '1px solid var(--border)',
      borderRadius: 'var(--r-lg)', padding: '16px 20px',
      display: 'flex', flexDirection: 'column', gap: 4,
      flex: '1 1 140px', minWidth: 0,
    }}>
      <span style={{ fontSize: 11, color: 'var(--text-3)', fontWeight: 600, textTransform: 'uppercase', letterSpacing: '0.5px' }}>{label}</span>
      <span style={{ fontSize: 28, fontWeight: 800, color: color || 'var(--text)', fontVariantNumeric: 'tabular-nums', lineHeight: 1.1 }}>
        {value}
      </span>
      {sub && <span style={{ fontSize: 11, color: 'var(--text-3)' }}>{sub}</span>}
    </div>
  )
}

function PLChart({ series }) {
  if (!series || series.length < 2) {
    return <div style={{ padding: '24px', textAlign: 'center', color: 'var(--text-3)', fontSize: 13 }}>
      Not enough data for a chart yet
    </div>
  }

  const values = series.map(s => s.pl)
  const min = Math.min(0, ...values)
  const max = Math.max(0, ...values)
  const range = max - min || 1
  const W = 600, H = 140, PAD = 20

  const pts = series.map((s, i) => {
    const x = PAD + (i / (series.length - 1)) * (W - PAD * 2)
    const y = PAD + ((max - s.pl) / range) * (H - PAD * 2)
    return [x, y]
  })

  const pathD = pts.map((p, i) => `${i === 0 ? 'M' : 'L'}${p[0].toFixed(1)},${p[1].toFixed(1)}`).join(' ')
  const fillD = `${pathD} L${pts[pts.length-1][0]},${H} L${pts[0][0]},${H} Z`

  const zeroY = PAD + ((max - 0) / range) * (H - PAD * 2)
  const lastPL = values[values.length - 1]
  const lineColor = lastPL >= 0 ? '#059669' : '#DC2626'

  return (
    <svg viewBox={`0 0 ${W} ${H}`} style={{ width: '100%', height: 'auto', display: 'block' }}>
      {/* Zero line */}
      {min < 0 && max > 0 && (
        <line x1={PAD} y1={zeroY} x2={W - PAD} y2={zeroY}
          stroke="var(--border)" strokeWidth={1} strokeDasharray="4 4" />
      )}
      {/* Fill */}
      <path d={fillD} fill={lineColor} opacity={0.08} />
      {/* Line */}
      <path d={pathD} fill="none" stroke={lineColor} strokeWidth={2} strokeLinejoin="round" strokeLinecap="round" />
      {/* End dot */}
      <circle cx={pts[pts.length-1][0]} cy={pts[pts.length-1][1]} r={4}
        fill={lineColor} stroke="white" strokeWidth={2} />
    </svg>
  )
}

function ResultsTab({ data, loading }) {
  if (loading) {
    return <div style={{ padding: '60px 0', textAlign: 'center', color: 'var(--text-3)' }}>Loading…</div>
  }
  if (!data) return null

  const { picks, stats, pl_series, surface_breakdown, stars_breakdown } = data

  if (!picks || picks.length === 0) {
    return (
      <div style={{ padding: '60px 24px', textAlign: 'center' }}>
        <p style={{ fontWeight: 600 }}>No settled picks yet</p>
        <p style={{ color: 'var(--text-3)', fontSize: 13 }}>
          Results appear here once your picks' matches have finished.
        </p>
      </div>
    )
  }

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 24 }}>

      {/* Summary squares */}
      <div style={{ display: 'flex', flexWrap: 'wrap', gap: 10 }}>
        <SummarySquare label="Picks" value={stats.total} />
        <SummarySquare label="Wins" value={stats.wins} color="var(--green)" />
        <SummarySquare label="Losses" value={stats.losses} color="var(--red)" />
        <SummarySquare label="Win rate" value={`${stats.win_rate}%`}
          color={stats.win_rate >= 55 ? 'var(--green)' : stats.win_rate >= 45 ? 'var(--amber)' : 'var(--red)'} />
        <SummarySquare
          label="P&L (£1/★)"
          value={stats.total_pl >= 0 ? `+£${fmt(stats.total_pl,2)}` : `-£${fmt(Math.abs(stats.total_pl),2)}`}
          color={plColor(stats.total_pl)}
          sub="based on confidence stake"
        />
      </div>

      {/* P&L chart */}
      <div style={{
        background: 'var(--bg-card)', border: '1px solid var(--border)',
        borderRadius: 'var(--r-lg)', padding: '16px',
      }}>
        <h3 style={{ margin: '0 0 12px', fontSize: 13, fontWeight: 700 }}>P&amp;L over time</h3>
        <PLChart series={pl_series} />
      </div>

      {/* Results table */}
      <div style={{
        background: 'var(--bg-card)', border: '1px solid var(--border)',
        borderRadius: 'var(--r-lg)', overflow: 'hidden',
      }}>
        <div style={{ padding: '12px 16px', borderBottom: '1px solid var(--border-faint)' }}>
          <h3 style={{ margin: 0, fontSize: 13, fontWeight: 700 }}>All results</h3>
        </div>
        <div style={{ overflowX: 'auto' }}>
          <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: 12 }}>
            <thead>
              <tr style={{ background: 'var(--bg-raised)' }}>
                {['Date','Player','Tournament','Surface','Conf.','Odds','Result','P&L'].map(h => (
                  <th key={h} style={{ padding: '8px 12px', textAlign: 'left', fontWeight: 600, fontSize: 11,
                    color: 'var(--text-3)', whiteSpace: 'nowrap' }}>{h}</th>
                ))}
              </tr>
            </thead>
            <tbody>
              {picks.map((p, i) => {
                const won  = p.status === 'won'
                const lost = p.status === 'lost'
                return (
                  <tr key={p.id} style={{ borderTop: i > 0 ? '1px solid var(--border-faint)' : 'none' }}>
                    <td style={{ padding: '8px 12px', color: 'var(--text-3)' }}>{p.match?.event_date}</td>
                    <td style={{ padding: '8px 12px', fontWeight: 600 }}>
                      <Link to={playerUrl({ id: p.player_id, name: p.picked_player?.name })} style={{ color: 'var(--text)' }}>
                        {p.picked_player?.name || '—'}
                      </Link>
                    </td>
                    <td style={{ padding: '8px 12px', color: 'var(--text-3)', maxWidth: 140,
                      overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
                      {p.match?.tournament_name || '—'}
                    </td>
                    <td style={{ padding: '8px 12px', color: surfaceColor(p.match?.surface) }}>
                      {p.match?.surface || '—'}
                    </td>
                    <td style={{ padding: '8px 12px' }}>
                      <ConfidenceStars n={p.confidence_stars} small />
                    </td>
                    <td style={{ padding: '8px 12px', fontVariantNumeric: 'tabular-nums' }}>
                      {fmt(p.our_odds, 2)}
                    </td>
                    <td style={{ padding: '8px 12px' }}>
                      <span style={{
                        fontWeight: 700,
                        color: won ? 'var(--green)' : lost ? 'var(--red)' : 'var(--text-3)',
                      }}>
                        {p.status.toUpperCase()}
                      </span>
                      {p.live_score && (
                        <span style={{ marginLeft: 6, color: 'var(--text-3)', fontSize: 11 }}>
                          {p.live_score}
                        </span>
                      )}
                    </td>
                    <td style={{ padding: '8px 12px', fontWeight: 700, fontVariantNumeric: 'tabular-nums',
                      color: plColor(p.profit_loss) }}>
                      {p.profit_loss != null
                        ? (p.profit_loss >= 0 ? `+£${fmt(p.profit_loss,2)}` : `-£${fmt(Math.abs(p.profit_loss),2)}`)
                        : '—'}
                    </td>
                  </tr>
                )
              })}
            </tbody>
          </table>
        </div>
      </div>

      {/* Breakdown tables */}
      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(240px, 1fr))', gap: 16 }}>

        {/* By surface */}
        <div style={{ background: 'var(--bg-card)', border: '1px solid var(--border)',
          borderRadius: 'var(--r-lg)', overflow: 'hidden' }}>
          <div style={{ padding: '10px 14px', borderBottom: '1px solid var(--border-faint)' }}>
            <h3 style={{ margin: 0, fontSize: 13, fontWeight: 700 }}>By surface</h3>
          </div>
          <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: 12 }}>
            <thead>
              <tr style={{ background: 'var(--bg-raised)' }}>
                {['Surface','W','L','P&L'].map(h => (
                  <th key={h} style={{ padding: '6px 10px', textAlign: 'left', fontWeight: 600,
                    fontSize: 11, color: 'var(--text-3)' }}>{h}</th>
                ))}
              </tr>
            </thead>
            <tbody>
              {Object.entries(surface_breakdown || {}).map(([surf, d], i) => (
                <tr key={surf} style={{ borderTop: i > 0 ? '1px solid var(--border-faint)' : 'none' }}>
                  <td style={{ padding: '6px 10px', color: surfaceColor(surf), fontWeight: 600 }}>{surf}</td>
                  <td style={{ padding: '6px 10px', color: 'var(--green)', fontWeight: 600 }}>{d.wins}</td>
                  <td style={{ padding: '6px 10px', color: 'var(--red)', fontWeight: 600 }}>{d.losses}</td>
                  <td style={{ padding: '6px 10px', fontWeight: 700, color: plColor(d.pl),
                    fontVariantNumeric: 'tabular-nums' }}>
                    {d.pl >= 0 ? `+£${fmt(d.pl,2)}` : `-£${fmt(Math.abs(d.pl),2)}`}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>

        {/* By confidence */}
        <div style={{ background: 'var(--bg-card)', border: '1px solid var(--border)',
          borderRadius: 'var(--r-lg)', overflow: 'hidden' }}>
          <div style={{ padding: '10px 14px', borderBottom: '1px solid var(--border-faint)' }}>
            <h3 style={{ margin: 0, fontSize: 13, fontWeight: 700 }}>By confidence</h3>
          </div>
          <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: 12 }}>
            <thead>
              <tr style={{ background: 'var(--bg-raised)' }}>
                {['Stars','W','L','P&L'].map(h => (
                  <th key={h} style={{ padding: '6px 10px', textAlign: 'left', fontWeight: 600,
                    fontSize: 11, color: 'var(--text-3)' }}>{h}</th>
                ))}
              </tr>
            </thead>
            <tbody>
              {Object.entries(stars_breakdown || {})
                .sort(([a],[b]) => Number(b) - Number(a))
                .map(([stars, d], i) => (
                <tr key={stars} style={{ borderTop: i > 0 ? '1px solid var(--border-faint)' : 'none' }}>
                  <td style={{ padding: '6px 10px' }}>
                    <ConfidenceStars n={Number(stars)} small />
                  </td>
                  <td style={{ padding: '6px 10px', color: 'var(--green)', fontWeight: 600 }}>{d.wins}</td>
                  <td style={{ padding: '6px 10px', color: 'var(--red)', fontWeight: 600 }}>{d.losses}</td>
                  <td style={{ padding: '6px 10px', fontWeight: 700, color: plColor(d.pl),
                    fontVariantNumeric: 'tabular-nums' }}>
                    {d.pl >= 0 ? `+£${fmt(d.pl,2)}` : `-£${fmt(Math.abs(d.pl),2)}`}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>
    </div>
  )
}

// ─────────────────────────────────────────────────────────────────────────────
// Main page
// ─────────────────────────────────────────────────────────────────────────────

export default function MyPicks() {
  const { isLoggedIn, loading: authLoading } = useAuth()
  const [showAuth, setShowAuth]   = useState(false)
  const [tab, setTab]             = useState('active')

  const [activePicks, setActivePicks] = useState([])
  const [activeLoading, setActiveLoading] = useState(false)

  const [resultsData, setResultsData] = useState(null)
  const [resultsLoading, setResultsLoading] = useState(false)

  const loadActive = useCallback(async () => {
    if (!isLoggedIn) return
    setActiveLoading(true)
    try {
      const data = await api.picksActive()
      setActivePicks(data.picks || [])
      // Seed the star cache
      seedPickedSet(data.picks || [])
      // Store in window for StarPick's delete lookup
      window._rttActivePicks = data.picks || []
    } catch (e) {
      console.warn('picks/active failed', e)
    } finally {
      setActiveLoading(false)
    }
  }, [isLoggedIn])

  const loadResults = useCallback(async () => {
    if (!isLoggedIn) return
    setResultsLoading(true)
    try {
      const data = await api.picksResults()
      setResultsData(data)
    } catch (e) {
      console.warn('picks/results failed', e)
    } finally {
      setResultsLoading(false)
    }
  }, [isLoggedIn])

  useEffect(() => {
    if (isLoggedIn) {
      loadActive()
      loadResults()
    }
  }, [isLoggedIn, loadActive, loadResults])

  async function handleRemove(pickId) {
    try {
      await api.deletePick(pickId)
      setActivePicks(ps => ps.filter(p => p.id !== pickId))
      window._rttActivePicks = (window._rttActivePicks || []).filter(p => p.id !== pickId)
      // Refresh star set
      seedPickedSet((window._rttActivePicks || []))
    } catch (e) {
      console.warn('delete pick failed', e)
    }
  }

  // Not logged in
  if (!authLoading && !isLoggedIn) {
    return (
      <main style={{ maxWidth: 560, margin: '80px auto', padding: '0 24px', textAlign: 'center' }}>
        <div style={{ fontSize: 40, marginBottom: 16 }}>★</div>
        <h1 style={{ fontSize: 22, fontWeight: 800, marginBottom: 8 }}>My Picks</h1>
        <p style={{ color: 'var(--text-3)', marginBottom: 24 }}>
          Log in to save your picks, track your results, and measure your P&amp;L over time.
        </p>
        <button
          onClick={() => setShowAuth(true)}
          style={{
            padding: '11px 28px', borderRadius: 'var(--r)',
            background: 'var(--text)', color: 'var(--text-inv)',
            fontWeight: 700, fontSize: 15,
          }}
        >
          Log in / Sign up
        </button>
        {showAuth && <AuthModal onClose={() => setShowAuth(false)} />}
      </main>
    )
  }

  return (
    <main style={{ maxWidth: 900, margin: '0 auto', padding: '24px 16px 48px' }}>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 20 }}>
        <h1 style={{ margin: 0, fontSize: 22, fontWeight: 800 }}>My Picks</h1>
        <button onClick={loadActive} style={{ fontSize: 12, color: 'var(--text-3)', padding: '4px 8px' }}>
          ↻ Refresh
        </button>
      </div>

      {/* Tabs */}
      <div style={{
        display: 'flex', borderBottom: '2px solid var(--border)',
        marginBottom: 24, gap: 0,
      }}>
        {[
          { id: 'active',  label: `Active (${activePicks.length})` },
          { id: 'results', label: 'Results' },
        ].map(t => (
          <button
            key={t.id}
            onClick={() => setTab(t.id)}
            style={{
              padding: '10px 18px', fontSize: 14, fontWeight: 600,
              borderBottom: `2px solid ${tab === t.id ? 'var(--text)' : 'transparent'}`,
              marginBottom: -2, color: tab === t.id ? 'var(--text)' : 'var(--text-3)',
              transition: 'color 0.15s',
            }}
          >
            {t.label}
          </button>
        ))}
      </div>

      {tab === 'active' && (
        <ActiveTab
          picks={activePicks}
          loading={activeLoading}
          onRemove={handleRemove}
          onRefresh={loadActive}
        />
      )}
      {tab === 'results' && (
        <ResultsTab data={resultsData} loading={resultsLoading} />
      )}
    </main>
  )
}
