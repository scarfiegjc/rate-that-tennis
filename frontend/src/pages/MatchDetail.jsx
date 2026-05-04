import { useState, useEffect, useRef } from 'react'
import { useParams, Link } from 'react-router-dom'
import { api } from '../api.js'
import SurfaceBadge from '../components/SurfaceBadge.jsx'
import EdgeBadge from '../components/EdgeBadge.jsx'
import ProbBar from '../components/ProbBar.jsx'
import FormChart from '../components/FormChart.jsx'

// ─────────────────────────────────────────────────────────────────────────────
// Colour helpers
// ─────────────────────────────────────────────────────────────────────────────

function rttPastel(score) {
  if (score == null) return { bg: '#f0ede8', text: '#a8a29e' }
  if (score >= 80) return { bg: '#bbf0d0', text: '#166534' }
  if (score >= 65) return { bg: '#d9f0bb', text: '#3a5c14' }
  if (score >= 50) return { bg: '#fef3c7', text: '#92400e' }
  if (score >= 35) return { bg: '#fed7aa', text: '#9a3412' }
  return { bg: '#fecaca', text: '#991b1b' }
}

function perfPastel(index) {
  if (index == null) return { bg: '#f0ede8', text: '#a8a29e' }
  if (index >= 70) return { bg: '#bbf0d0', text: '#166534' }
  if (index >= 55) return { bg: '#d9f0bb', text: '#3a5c14' }
  if (index >= 45) return { bg: '#fef3c7', text: '#92400e' }
  if (index >= 30) return { bg: '#fed7aa', text: '#9a3412' }
  return { bg: '#fecaca', text: '#991b1b' }
}

// For dual rating bars: who has the advantage?
function advantageColor(v1, v2) {
  const n1 = v1 ?? 50, n2 = v2 ?? 50
  const diff = n1 - n2
  if (diff > 8)  return { c1: '#166534', c2: '#991b1b' }
  if (diff < -8) return { c1: '#991b1b', c2: '#166534' }
  return { c1: '#92400e', c2: '#92400e' }
}

function fmt(val, d = 0) {
  if (val == null) return '—'
  return Number(val).toFixed(d)
}

// ─────────────────────────────────────────────────────────────────────────────
// Small lozenges
// ─────────────────────────────────────────────────────────────────────────────

function RttLozenge({ score }) {
  if (score == null) return null
  const c = rttPastel(Math.round(score))
  return (
    <span style={{
      display: 'inline-flex', alignItems: 'center',
      background: c.bg, color: c.text,
      borderRadius: 20, padding: '2px 9px',
      fontSize: 13, fontWeight: 700,
      fontVariantNumeric: 'tabular-nums', letterSpacing: '-0.3px',
      flexShrink: 0,
    }}>
      {Math.round(score)}
    </span>
  )
}

function HandLozenge({ hand }) {
  if (!hand || hand === 'Unknown') return null
  const isLeft = hand === 'Left'
  return (
    <span style={{
      display: 'inline-flex', alignItems: 'center',
      background: isLeft ? '#e0f2fe' : '#f0ede8',
      color:      isLeft ? '#0369a1' : '#78716c',
      borderRadius: 20, padding: '2px 7px',
      fontSize: 11, fontWeight: 600,
      flexShrink: 0,
    }}>
      {isLeft ? 'L' : 'R'}
    </span>
  )
}

function MomentumSquares({ momentum, form_dots }) {
  // Show last 3 from form_dots (W/L), or derive from momentum
  const dots = (form_dots || []).slice(0, 3)
  if (!dots.length) {
    // Fallback: show momentum as 3 squares
    const color =
      momentum === 'rising'  ? '#bbf0d0' :
      momentum === 'falling' ? '#fecaca' : '#f0ede8'
    const border =
      momentum === 'rising'  ? '#166534' :
      momentum === 'falling' ? '#991b1b' : '#a8a29e'
    return (
      <div style={{ display: 'flex', gap: 4 }}>
        {[0,1,2].map(i => (
          <div key={i} style={{
            width: 10, height: 10, borderRadius: 2,
            background: color, border: `1px solid ${border}`,
          }} />
        ))}
      </div>
    )
  }
  return (
    <div style={{ display: 'flex', gap: 4 }}>
      {dots.map((d, i) => (
        <div key={i} style={{
          width: 10, height: 10, borderRadius: 2,
          background: d === 'W' ? '#bbf0d0' : d === 'L' ? '#fecaca' : '#f0ede8',
          border: `1px solid ${d === 'W' ? '#166534' : d === 'L' ? '#991b1b' : '#a8a29e'}`,
        }} />
      ))}
    </div>
  )
}

// ─────────────────────────────────────────────────────────────────────────────
// Non-sticky header (tournament info)
// ─────────────────────────────────────────────────────────────────────────────

function MatchMeta({ match }) {
  const pred = match.prediction || {}
  return (
    <div style={{
      textAlign: 'center',
      padding: '18px 24px 0',
    }}>
      <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'center', gap: 8, marginBottom: 4 }}>
        <Link to="/" style={{ color: 'var(--text-3)', fontSize: 12 }}>← Today</Link>
        <span style={{ color: 'var(--text-3)' }}>·</span>
        <SurfaceBadge surface={match.surface} />
      </div>
      <div style={{
        fontSize: 17, fontWeight: 700, color: 'var(--text)',
        letterSpacing: '-0.3px', marginBottom: 2,
      }}>
        {match.tournament}
      </div>
      {match.round && (
        <div style={{ fontSize: 13, color: 'var(--text-3)', marginBottom: 4 }}>
          {match.round}
        </div>
      )}
      {pred.confidence && (
        <div style={{ fontSize: 11, color: 'var(--text-3)', marginBottom: 6 }}>
          <span style={{
            display: 'inline-block',
            width: 6, height: 6, borderRadius: '50%',
            background: pred.confidence === 'high' ? '#166534' : pred.confidence === 'medium' ? '#92400e' : '#a8a29e',
            marginRight: 4, verticalAlign: 'middle',
          }} />
          {pred.confidence} confidence
        </div>
      )}
    </div>
  )
}

// ─────────────────────────────────────────────────────────────────────────────
// Sticky player + tabs bar
// ─────────────────────────────────────────────────────────────────────────────

function PlayerBar({ match, activeTab, onTabClick, tabRefs }) {
  const p1 = match.first_player || {}
  const p2 = match.second_player || {}
  const pred = match.prediction || {}

  const TABS = [
    { id: 'intelligence', label: 'Intelligence' },
    { id: 'ratings',      label: 'Ratings' },
    { id: 'form',         label: 'Form' },
    { id: 'h2h',          label: 'Head to head' },
    { id: 'serve',        label: 'Serve' },
  ]

  return (
    <div style={{
      position: 'sticky',
      top: 52,
      zIndex: 90,
      background: 'var(--bg-card)',
      borderBottom: '1px solid var(--border)',
    }}>
      {/* Player names row */}
      <div style={{
        display: 'grid',
        gridTemplateColumns: '1fr auto 1fr',
        alignItems: 'center',
        gap: 16,
        padding: '12px 24px 8px',
      }}>
        {/* Player 1 */}
        <div style={{ display: 'flex', flexDirection: 'column', gap: 6 }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: 6, flexWrap: 'wrap' }}>
            <HandLozenge hand={p1.hand} />
            <Link to={`/player/${p1.player_id}`} style={{
              fontSize: 22, fontWeight: 700, letterSpacing: '-0.5px',
              color: 'var(--text)', textDecoration: 'none',
            }}>
              {p1.name || '—'}
            </Link>
            <RttLozenge score={p1.ratings?.rtt_score} />
          </div>
          <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
            {/* W/L dots */}
            {(p1.form_dots || []).length > 0 && (
              <div style={{ display: 'flex', gap: 3 }}>
                {(p1.form_dots || []).slice(0, 5).map((d, i) => (
                  <span key={i} title={d === 'W' ? 'Win' : 'Loss'} style={{
                    display: 'inline-block',
                    width: 7, height: 7, borderRadius: '50%',
                    background: d === 'W' ? '#166534' : '#e5e0d8',
                    opacity: d === 'W' ? 1 : 0.5,
                  }} />
                ))}
              </div>
            )}
            {p1.country_code && (
              <span style={{ fontSize: 11, color: 'var(--text-3)' }}>{p1.country_code}</span>
            )}
          </div>
        </div>

        {/* Centre probability */}
        <div style={{ display: 'flex', flexDirection: 'column', alignItems: 'center', gap: 6, minWidth: 100 }}>
          {pred.prob_first_player != null ? (
            <>
              <div style={{ display: 'flex', gap: 10, alignItems: 'baseline' }}>
                <span style={{ fontSize: 22, fontWeight: 800, color: 'var(--green)', fontVariantNumeric: 'tabular-nums' }}>
                  {Math.round(pred.prob_first_player * 100)}%
                </span>
                <span style={{ fontSize: 12, color: 'var(--text-3)' }}>vs</span>
                <span style={{ fontSize: 22, fontWeight: 800, color: 'var(--blue)', fontVariantNumeric: 'tabular-nums' }}>
                  {Math.round(pred.prob_second_player * 100)}%
                </span>
              </div>
              <ProbBar p1={pred.prob_first_player} p2={pred.prob_second_player} name1="" name2="" />
            </>
          ) : (
            <span style={{ fontSize: 18, fontWeight: 700, color: 'var(--text-3)' }}>vs</span>
          )}
        </div>

        {/* Player 2 */}
        <div style={{ display: 'flex', flexDirection: 'column', alignItems: 'flex-end', gap: 6 }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: 6, flexWrap: 'wrap', justifyContent: 'flex-end' }}>
            <RttLozenge score={p2.ratings?.rtt_score} />
            <Link to={`/player/${p2.player_id}`} style={{
              fontSize: 22, fontWeight: 700, letterSpacing: '-0.5px',
              color: 'var(--text)', textDecoration: 'none',
            }}>
              {p2.name || '—'}
            </Link>
            <HandLozenge hand={p2.hand} />
          </div>
          <div style={{ display: 'flex', alignItems: 'center', gap: 8, justifyContent: 'flex-end' }}>
            {p2.country_code && (
              <span style={{ fontSize: 11, color: 'var(--text-3)' }}>{p2.country_code}</span>
            )}
            {(p2.form_dots || []).length > 0 && (
              <div style={{ display: 'flex', gap: 3 }}>
                {(p2.form_dots || []).slice(0, 5).map((d, i) => (
                  <span key={i} title={d === 'W' ? 'Win' : 'Loss'} style={{
                    display: 'inline-block',
                    width: 7, height: 7, borderRadius: '50%',
                    background: d === 'W' ? '#166534' : '#e5e0d8',
                    opacity: d === 'W' ? 1 : 0.5,
                  }} />
                ))}
              </div>
            )}
          </div>
        </div>
      </div>

      {/* Tabs */}
      <div style={{
        display: 'flex',
        justifyContent: 'center',
        gap: 0,
        padding: '0 24px',
      }}>
        {TABS.map(t => (
          <button
            key={t.id}
            onClick={() => onTabClick(t.id)}
            style={{
              padding: '8px 14px',
              fontSize: 13,
              fontWeight: activeTab === t.id ? 600 : 500,
              color: activeTab === t.id ? 'var(--text)' : 'var(--text-3)',
              background: 'none',
              border: 'none',
              borderBottom: activeTab === t.id ? '2px solid var(--text)' : '2px solid transparent',
              cursor: 'pointer',
              whiteSpace: 'nowrap',
              transition: 'color 0.15s',
            }}
          >
            {t.label}
          </button>
        ))}
      </div>
    </div>
  )
}

// ─────────────────────────────────────────────────────────────────────────────
// Section wrapper
// ─────────────────────────────────────────────────────────────────────────────

function Section({ id, sectionRef, title, children }) {
  return (
    <div ref={sectionRef} id={id} style={{ paddingTop: 28 }}>
      {title && (
        <div style={{
          fontSize: 11, fontWeight: 700, textTransform: 'uppercase',
          letterSpacing: '0.8px', color: 'var(--text-3)',
          marginBottom: 16, paddingLeft: 2,
        }}>
          {title}
        </div>
      )}
      {children}
    </div>
  )
}

// ─────────────────────────────────────────────────────────────────────────────
// Intelligence
// ─────────────────────────────────────────────────────────────────────────────

function SectionIntelligence({ match }) {
  const pred = match.prediction || {}
  const p1   = match.first_player  || {}
  const p2   = match.second_player || {}
  const bets  = pred.bet_recommendations || []

  return (
    <div>
      {!pred.prob_first_player ? (
        <div style={{
          background: 'var(--bg-card)', border: '1px solid var(--border)',
          borderRadius: 'var(--r-lg)', padding: 32, textAlign: 'center',
          color: 'var(--text-3)', fontSize: 14,
        }}>
          Prediction not yet available — check back closer to match time.
        </div>
      ) : (
        <>
          {/* Model narrative */}
          {pred.narrative && (
            <div style={{
              background: 'var(--bg-card)', border: '1px solid var(--border)',
              borderRadius: 'var(--r-lg)', padding: 20, marginBottom: 12,
            }}>
              <div style={{ fontSize: 11, fontWeight: 700, textTransform: 'uppercase', letterSpacing: '0.6px', color: 'var(--text-3)', marginBottom: 10 }}>
                Model reasoning
              </div>
              <p style={{ margin: 0, fontSize: 14, color: 'var(--text-2)', lineHeight: 1.75 }}>
                {pred.narrative}
              </p>
            </div>
          )}

          {/* Bet recommendations */}
          {bets.length > 0 && (
            <div style={{
              background: 'var(--bg-card)', border: '1px solid var(--border)',
              borderRadius: 'var(--r-lg)', padding: 20,
            }}>
              <div style={{ fontSize: 11, fontWeight: 700, textTransform: 'uppercase', letterSpacing: '0.6px', color: 'var(--text-3)', marginBottom: 10 }}>
                Value signals
              </div>
              {bets.map((b, i) => (
                <div key={i} style={{
                  display: 'flex', justifyContent: 'space-between', alignItems: 'center',
                  padding: '8px 0',
                  borderBottom: i < bets.length - 1 ? '1px solid var(--border-faint)' : 'none',
                }}>
                  <span style={{ fontSize: 13, fontWeight: 500 }}>{b.description || b.type}</span>
                  <EdgeBadge edge={b.edge} playerName={b.player} />
                </div>
              ))}
            </div>
          )}
        </>
      )}
    </div>
  )
}

// ─────────────────────────────────────────────────────────────────────────────
// Ratings — centred outward bars
// ─────────────────────────────────────────────────────────────────────────────

function RatingRow({ label, v1, v2 }) {
  const n1 = v1 != null ? Math.round(v1) : null
  const n2 = v2 != null ? Math.round(v2) : null
  const { c1, c2 } = advantageColor(n1, n2)
  const maxBar = 80 // px each side

  // Bar widths (proportional, max 80px)
  const w1 = n1 != null ? Math.round((n1 / 100) * maxBar) : 0
  const w2 = n2 != null ? Math.round((n2 / 100) * maxBar) : 0

  // Pastel backgrounds for the value chips
  const chip1 = n1 != null ? rttPastel(n1) : null
  const chip2 = n2 != null ? rttPastel(n2) : null

  return (
    <div style={{
      display: 'grid',
      gridTemplateColumns: `${maxBar}px 44px 120px 44px ${maxBar}px`,
      alignItems: 'center',
      gap: 6,
      margin: '5px 0',
    }}>
      {/* P1 bar (grows left) */}
      <div style={{ display: 'flex', justifyContent: 'flex-end', alignItems: 'center' }}>
        <div style={{
          width: w1, height: 6, borderRadius: 3,
          background: n1 != null ? c1.replace('text', '') : 'var(--bg-raised)',
          backgroundColor: n1 != null ? (n1 > (n2 ?? 50) ? '#bbf0d0' : n1 < (n2 ?? 50) - 8 ? '#fecaca' : '#fef3c7') : 'var(--bg-raised)',
          transition: 'width 0.5s ease',
        }} />
      </div>

      {/* P1 value chip */}
      {chip1 ? (
        <div style={{
          background: chip1.bg, color: chip1.text,
          borderRadius: 6, padding: '2px 6px',
          fontSize: 13, fontWeight: 700, textAlign: 'center',
          fontVariantNumeric: 'tabular-nums',
        }}>
          {n1}
        </div>
      ) : (
        <div style={{ fontSize: 12, color: 'var(--text-3)', textAlign: 'center' }}>—</div>
      )}

      {/* Label */}
      <div style={{
        textAlign: 'center', fontSize: 11,
        color: 'var(--text-3)', fontWeight: 500,
      }}>
        {label}
      </div>

      {/* P2 value chip */}
      {chip2 ? (
        <div style={{
          background: chip2.bg, color: chip2.text,
          borderRadius: 6, padding: '2px 6px',
          fontSize: 13, fontWeight: 700, textAlign: 'center',
          fontVariantNumeric: 'tabular-nums',
        }}>
          {n2}
        </div>
      ) : (
        <div style={{ fontSize: 12, color: 'var(--text-3)', textAlign: 'center' }}>—</div>
      )}

      {/* P2 bar (grows right) */}
      <div style={{ display: 'flex', justifyContent: 'flex-start', alignItems: 'center' }}>
        <div style={{
          width: w2, height: 6, borderRadius: 3,
          backgroundColor: n2 != null ? (n2 > (n1 ?? 50) ? '#bbf0d0' : n2 < (n1 ?? 50) - 8 ? '#fecaca' : '#fef3c7') : 'var(--bg-raised)',
          transition: 'width 0.5s ease',
        }} />
      </div>
    </div>
  )
}

function SectionRatings({ match }) {
  const p1 = match.first_player  || {}
  const p2 = match.second_player || {}
  const r1 = p1.ratings || {}
  const r2 = p2.ratings || {}

  const groups = [
    {
      label: 'Overall',
      rows: [
        { label: 'RTT Score',    k: 'rtt_score' },
        { label: 'Form',         k: 'form_score' },
      ]
    },
    {
      label: 'Surface',
      rows: [
        { label: 'Clay',    k: 'clay_rating' },
        { label: 'Hard',    k: 'hard_rating' },
        { label: 'Grass',   k: 'grass_rating' },
        { label: 'Indoor',  k: 'indoor_rating' },
      ]
    },
    {
      label: 'Skills',
      rows: [
        { label: 'Serve',        k: 'serve_rating' },
        { label: 'Return',       k: 'return_rating' },
        { label: 'Pressure',     k: 'pressure_rating' },
        { label: 'Consistency',  k: 'consistency_score' },
        { label: 'Big match',    k: 'big_match_rating' },
        { label: 'vs Top 10',    k: 'vs_top10_rating' },
      ]
    },
  ]

  const hasData = Object.keys(r1).length > 0 || Object.keys(r2).length > 0

  if (!hasData) {
    return (
      <div style={{
        background: 'var(--bg-card)', border: '1px solid var(--border)',
        borderRadius: 'var(--r-lg)', padding: 32,
        textAlign: 'center', color: 'var(--text-3)', fontSize: 14,
      }}>
        Ratings not yet computed for these players.
      </div>
    )
  }

  return (
    <div>
      {/* Player name header */}
      <div style={{
        display: 'flex',
        justifyContent: 'space-between',
        fontSize: 11, fontWeight: 600, color: 'var(--text-3)',
        marginBottom: 12, padding: '0 2px',
      }}>
        <span style={{ color: 'var(--green)' }}>{p1.name}</span>
        <span style={{ color: 'var(--blue)' }}>{p2.name}</span>
      </div>

      {groups.map(group => {
        const hasAny = group.rows.some(r => r1[r.k] != null || r2[r.k] != null)
        if (!hasAny) return null
        return (
          <div key={group.label} style={{
            background: 'var(--bg-card)', border: '1px solid var(--border)',
            borderRadius: 'var(--r-lg)', padding: '14px 18px',
            marginBottom: 10,
          }}>
            <div style={{
              fontSize: 10, fontWeight: 700, textTransform: 'uppercase',
              letterSpacing: '0.7px', color: 'var(--text-3)', marginBottom: 10,
            }}>
              {group.label}
            </div>
            <div style={{ display: 'flex', flexDirection: 'column', alignItems: 'center' }}>
              {group.rows.map(({ label, k }) => (
                <RatingRow key={k} label={label} v1={r1[k]} v2={r2[k]} />
              ))}
            </div>
          </div>
        )
      })}

      <div style={{ fontSize: 11, color: 'var(--text-3)', marginTop: 8, textAlign: 'center' }}>
        Ratings are 0–100, population-normalised across all active players
      </div>
    </div>
  )
}

// ─────────────────────────────────────────────────────────────────────────────
// Form — chart + racecard rows
// ─────────────────────────────────────────────────────────────────────────────

// FormRacecard: chip centred, opponent/WL/score on the outside — mirrors RatingRow style.
// align='left'  → [opponent + score | text-right] [W/L] [chip] (P1 column)
// align='right' → [chip] [W/L] [opponent + score | text-left] (P2 column)
function FormRacecard({ matches, playerName, align = 'left' }) {
  if (!matches || !matches.length) {
    return (
      <div style={{ fontSize: 12, color: 'var(--text-3)', padding: '12px 0' }}>
        No recent form data
      </div>
    )
  }

  const isRight = align === 'right'

  return (
    <div>
      {matches.slice(0, 10).map((m, i) => {
        const c = perfPastel(m.performance_index)

        const chip = (
          <div style={{
            background: c.bg, color: c.text,
            borderRadius: 6, padding: '3px 8px',
            fontSize: 13, fontWeight: 700,
            fontVariantNumeric: 'tabular-nums',
            minWidth: 36, textAlign: 'center',
            flexShrink: 0,
          }}>
            {m.performance_index != null ? Math.round(m.performance_index) : '—'}
          </div>
        )

        const wlBadge = (
          <div style={{
            width: 20, height: 20, borderRadius: 4,
            background: m.won ? '#bbf0d0' : '#fecaca',
            color: m.won ? '#166534' : '#991b1b',
            fontSize: 10, fontWeight: 800,
            display: 'flex', alignItems: 'center', justifyContent: 'center',
            flexShrink: 0,
          }}>
            {m.won ? 'W' : 'L'}
          </div>
        )

        const opponentText = (
          <div style={{ flex: 1, minWidth: 0, textAlign: isRight ? 'left' : 'right' }}>
            <div style={{
              fontSize: 12, fontWeight: 500, color: 'var(--text-2)',
              whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis',
            }}>
              {m.opponent_name || 'Unknown'}
            </div>
            {m.score && (
              <div style={{
                fontSize: 10, color: 'var(--text-3)',
                fontFamily: 'var(--font-mono)', marginTop: 1,
              }}>
                {m.score}
              </div>
            )}
          </div>
        )

        return (
          <div key={i} style={{
            display: 'flex',
            flexDirection: isRight ? 'row' : 'row-reverse',
            alignItems: 'center',
            gap: 7,
            padding: '5px 0',
            borderBottom: i < Math.min(matches.length, 10) - 1 ? '1px solid var(--border-faint)' : 'none',
          }}>
            {/* Right player: chip | WL | opponent */}
            {/* Left player (row-reverse): opponent | WL | chip */}
            {chip}
            {wlBadge}
            {opponentText}
          </div>
        )
      })}
    </div>
  )
}

function SectionForm({ match }) {
  const [surface, setSurface]   = useState('all')
  const [p1Form,  setP1Form]    = useState(null)
  const [p2Form,  setP2Form]    = useState(null)
  const [loading, setLoading]   = useState(true)

  const p1 = match.first_player  || {}
  const p2 = match.second_player || {}

  useEffect(() => {
    setLoading(true)
    Promise.all([
      api.playerForm(p1.player_id, surface),
      api.playerForm(p2.player_id, surface),
    ]).then(([f1, f2]) => {
      setP1Form(f1); setP2Form(f2); setLoading(false)
    }).catch(() => setLoading(false))
  }, [surface, p1.player_id, p2.player_id])

  const surfaces = ['all', 'Clay', 'Hard', 'Grass']

  const p1Matches = p1Form?.matches || []
  const p2Matches = p2Form?.matches || []

  // Form summaries
  function summary(ms) {
    if (!ms.length) return null
    const avg  = ms.reduce((s, m) => s + (m.performance_index || 0), 0) / ms.length
    const wins = ms.filter(m => m.won).length
    const last5 = ms.slice(0, 5)
    const prior5 = ms.slice(5, 10)
    const trend = last5.length && prior5.length
      ? last5.reduce((s, m) => s + (m.performance_index || 0), 0) / last5.length
        - prior5.reduce((s, m) => s + (m.performance_index || 0), 0) / prior5.length
      : 0
    return { avg: avg.toFixed(1), wins, total: ms.length, trend: trend.toFixed(1) }
  }

  const s1 = summary(p1Matches)
  const s2 = summary(p2Matches)

  return (
    <div>
      {/* Surface filter */}
      <div style={{ display: 'flex', gap: 6, marginBottom: 16 }}>
        {surfaces.map(s => (
          <button
            key={s}
            onClick={() => setSurface(s)}
            className={`tab-btn ${surface === s ? 'active' : ''}`}
            style={{ padding: '4px 10px', fontSize: 12 }}
          >
            {s}
          </button>
        ))}
      </div>

      {loading ? (
        <div className="loading">Loading form data…</div>
      ) : (
        <>
          {/* Chart */}
          <div style={{ marginBottom: 20 }}>
            <FormChart
              p1Form={p1Form}
              p2Form={p2Form}
              p1Name={p1.name}
              p2Name={p2.name}
            />
          </div>

          {/* Summary stats + momentum side by side */}
          <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 10, marginBottom: 20 }}>
            {[
              { name: p1.name, s: s1, r: p1.ratings, fd: p1.form_dots },
              { name: p2.name, s: s2, r: p2.ratings, fd: p2.form_dots },
            ].map(({ name, s, r, fd }) => (
              <div key={name} style={{
                background: 'var(--bg-card)', border: '1px solid var(--border)',
                borderRadius: 'var(--r-lg)', padding: 14,
              }}>
                <div style={{ fontSize: 11, fontWeight: 600, color: 'var(--text-3)', marginBottom: 8 }}>
                  {name}
                </div>
                {s ? (
                  <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr 1fr', gap: 6, marginBottom: 10 }}>
                    <div style={{
                      background: 'var(--bg-raised)', border: '1px solid var(--border-faint)',
                      borderRadius: 8, padding: '8px 6px', textAlign: 'center',
                    }}>
                      <div style={{ fontSize: 18, fontWeight: 800, letterSpacing: '-0.5px', lineHeight: 1 }}>{s.avg}</div>
                      <div style={{ fontSize: 9, textTransform: 'uppercase', letterSpacing: '0.5px', color: 'var(--text-3)', marginTop: 3 }}>Avg idx</div>
                    </div>
                    <div style={{
                      background: 'var(--bg-raised)', border: '1px solid var(--border-faint)',
                      borderRadius: 8, padding: '8px 6px', textAlign: 'center',
                    }}>
                      <div style={{ fontSize: 18, fontWeight: 800, letterSpacing: '-0.5px', lineHeight: 1 }}>
                        {s.wins}/{s.total}
                      </div>
                      <div style={{ fontSize: 9, textTransform: 'uppercase', letterSpacing: '0.5px', color: 'var(--text-3)', marginTop: 3 }}>W/L</div>
                    </div>
                    <div style={{
                      background: 'var(--bg-raised)', border: '1px solid var(--border-faint)',
                      borderRadius: 8, padding: '8px 6px', textAlign: 'center',
                    }}>
                      <div style={{
                        fontSize: 18, fontWeight: 800, letterSpacing: '-0.5px', lineHeight: 1,
                        color: Number(s.trend) > 0 ? '#166534' : Number(s.trend) < 0 ? '#991b1b' : 'var(--text)',
                      }}>
                        {Number(s.trend) > 0 ? '+' : ''}{s.trend}
                      </div>
                      <div style={{ fontSize: 9, textTransform: 'uppercase', letterSpacing: '0.5px', color: 'var(--text-3)', marginTop: 3 }}>Trend</div>
                    </div>
                  </div>
                ) : (
                  <div style={{ fontSize: 12, color: 'var(--text-3)', marginBottom: 10 }}>No data</div>
                )}
                {/* Momentum */}
                <div style={{ display: 'flex', alignItems: 'center', gap: 8, paddingTop: 8, borderTop: '1px solid var(--border-faint)' }}>
                  <MomentumSquares momentum={r?.momentum} form_dots={fd} />
                  <span style={{
                    fontSize: 11, fontWeight: 600,
                    color: r?.momentum === 'rising' ? '#166534' : r?.momentum === 'falling' ? '#991b1b' : 'var(--text-3)',
                  }}>
                    Momentum: {r?.momentum
                      ? r.momentum.charAt(0).toUpperCase() + r.momentum.slice(1)
                      : 'Stable'}
                  </span>
                </div>
              </div>
            ))}
          </div>

          {/* Racecard form log - side by side */}
          <div style={{
            background: 'var(--bg-card)', border: '1px solid var(--border)',
            borderRadius: 'var(--r-lg)', padding: 16,
          }}>
            <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 24 }}>
              <div>
                <div style={{ fontSize: 11, fontWeight: 600, color: 'var(--green)', marginBottom: 10 }}>
                  {p1.name}
                </div>
                <FormRacecard matches={p1Matches} playerName={p1.name} align="left" />
              </div>
              <div>
                <div style={{ fontSize: 11, fontWeight: 600, color: 'var(--blue)', marginBottom: 10, textAlign: 'right' }}>
                  {p2.name}
                </div>
                <FormRacecard matches={p2Matches} playerName={p2.name} align="right" />
              </div>
            </div>
          </div>
        </>
      )}
    </div>
  )
}

// ─────────────────────────────────────────────────────────────────────────────
// H2H (unchanged)
// ─────────────────────────────────────────────────────────────────────────────

function SectionH2H({ match }) {
  const [h2h, setH2h]       = useState(null)
  const [loading, setLoading] = useState(true)
  const p1 = match.first_player  || {}
  const p2 = match.second_player || {}

  useEffect(() => {
    if (!p1.player_id || !p2.player_id) { setLoading(false); return }
    api.h2h(p1.player_id, p2.player_id)
      .then(data => { setH2h(data); setLoading(false) })
      .catch(() => setLoading(false))
  }, [p1.player_id, p2.player_id])

  if (loading) return <div className="loading">Loading H2H…</div>

  const summary  = h2h?.summary  || {}
  const meetings = h2h?.matches  || []

  return (
    <div>
      <div className="h2h-summary">
        <div>
          <div className="h2h-wins p1">{summary.p1_wins ?? 0}</div>
          <div className="h2h-label">{p1.name}</div>
        </div>
        <div style={{ fontSize: 13, color: 'var(--text-muted)', textAlign: 'center' }}>
          {summary.total ?? 0} meetings
        </div>
        <div>
          <div className="h2h-wins p2">{summary.p2_wins ?? 0}</div>
          <div className="h2h-label">{p2.name}</div>
        </div>
      </div>

      {summary.by_surface && Object.keys(summary.by_surface).length > 0 && (
        <div className="card" style={{ marginBottom: 16 }}>
          <div className="card-header">By surface</div>
          {Object.entries(summary.by_surface).map(([surf, counts]) => (
            <div key={surf} className="stat-bar-row">
              <div style={{ textAlign: 'right', fontSize: 13, fontWeight: 600 }}>{counts.p1}</div>
              <div className="stat-bar-label"><SurfaceBadge surface={surf} /></div>
              <div style={{ fontSize: 13, fontWeight: 600 }}>{counts.p2}</div>
            </div>
          ))}
        </div>
      )}

      {meetings.length === 0 ? (
        <div className="loading" style={{ minHeight: 80 }}>No H2H meetings on record</div>
      ) : (
        <div className="card">
          <div className="card-header">Recent meetings</div>
          {meetings.slice(0, 10).map((m, i) => (
            <div key={i} className="h2h-match">
              <div className="h2h-winner-dot"
                style={{ background: m.winner === 'first_player' ? 'var(--accent-green)' : 'var(--accent-blue)' }}
              />
              <div className="h2h-match-info">
                <div className="h2h-match-score">{m.score || '—'}</div>
                <div className="h2h-match-detail">
                  {m.tournament} · {m.round} · {m.date?.slice(0, 10)}
                </div>
              </div>
              <SurfaceBadge surface={m.surface} />
            </div>
          ))}
        </div>
      )}
    </div>
  )
}

// ─────────────────────────────────────────────────────────────────────────────
// Serve (unchanged)
// ─────────────────────────────────────────────────────────────────────────────

const ZONE_LABELS = { wide: 'Wide', body: 'Body', t: 'T' }

function zoneOpacity(pct) {
  if (pct >= 0.45) return 0.9
  if (pct >= 0.35) return 0.65
  if (pct >= 0.25) return 0.45
  return 0.15
}

function SectionServe({ match }) {
  const [player,   setPlayer]   = useState('p1')
  const [serveNum, setServeNum] = useState(1)
  const [side,     setSide]     = useState('deuce')

  const p1 = match.first_player  || {}
  const p2 = match.second_player || {}
  const current  = player === 'p1' ? p1 : p2
  const colorRgb = player === 'p1' ? '0,204,122' : '56,139,253'
  const serveZones = current.serve_zones?.[`s${serveNum}`]?.[side] || null
  const stats = current.stats?.overall || {}

  return (
    <div>
      <div style={{ display: 'flex', gap: 16, marginBottom: 16, flexWrap: 'wrap' }}>
        <div style={{ display: 'flex', gap: 4 }}>
          {[['p1', p1.name || 'P1'], ['p2', p2.name || 'P2']].map(([key, label]) => (
            <button key={key} onClick={() => setPlayer(key)}
              className={`tab-btn ${player === key ? 'active' : ''}`}
              style={{ padding: '4px 10px', fontSize: 12 }}>
              {label?.split(' ').pop()}
            </button>
          ))}
        </div>
        <div style={{ display: 'flex', gap: 4 }}>
          {[1, 2].map(n => (
            <button key={n} onClick={() => setServeNum(n)}
              className={`tab-btn ${serveNum === n ? 'active' : ''}`}
              style={{ padding: '4px 10px', fontSize: 12 }}>
              {n}{n === 1 ? 'st' : 'nd'} serve
            </button>
          ))}
        </div>
        <div style={{ display: 'flex', gap: 4 }}>
          {['deuce', 'ad'].map(s => (
            <button key={s} onClick={() => setSide(s)}
              className={`tab-btn ${side === s ? 'active' : ''}`}
              style={{ padding: '4px 10px', fontSize: 12, textTransform: 'capitalize' }}>
              {s}
            </button>
          ))}
        </div>
      </div>

      <div className="two-col">
        <div>
          <div className="section-title">Placement zones</div>
          {current.serve_zones_estimated && (
            <div style={{ fontSize: 11, color: 'var(--text-muted)', marginBottom: 8 }}>
              Estimated from serve stats — charting data pending
            </div>
          )}
          <div className="serve-zone-grid">
            {['wide', 'body', 't'].map(z => {
              const pct = serveZones?.[z] ?? 0.33
              return (
                <div key={z} className="serve-zone-cell"
                  style={{
                    background: `rgba(${colorRgb}, ${zoneOpacity(pct)})`,
                    border: `1px solid rgba(${colorRgb}, 0.3)`,
                  }}>
                  <div>
                    <div style={{ fontSize: 10, color: '#8b949e' }}>{ZONE_LABELS[z]}</div>
                    <div style={{ fontSize: 13, fontWeight: 700 }}>{Math.round(pct * 100)}%</div>
                  </div>
                </div>
              )
            })}
          </div>
        </div>

        <div>
          <div className="section-title">Serve stats</div>
          <div className="metric-cards" style={{ gridTemplateColumns: '1fr 1fr' }}>
            <div className="metric-card">
              <div className="metric-value">
                {stats.first_serve_pct != null ? `${(stats.first_serve_pct * 100).toFixed(0)}%` : '—'}
              </div>
              <div className="metric-label">1st serve in</div>
            </div>
            <div className="metric-card">
              <div className="metric-value">
                {stats.aces_per_match != null ? Number(stats.aces_per_match).toFixed(1) : '—'}
              </div>
              <div className="metric-label">Aces/match</div>
            </div>
            <div className="metric-card">
              <div className="metric-value">
                {current.ratings?.serve_rating != null ? Math.round(current.ratings.serve_rating) : '—'}
              </div>
              <div className="metric-label">Serve rating</div>
            </div>
            <div className="metric-card">
              <div className="metric-value">
                {stats.bp_saved_pct != null ? `${(stats.bp_saved_pct * 100).toFixed(0)}%` : '—'}
              </div>
              <div className="metric-label">BP saved</div>
            </div>
          </div>
        </div>
      </div>
    </div>
  )
}

// ─────────────────────────────────────────────────────────────────────────────
// Main
// ─────────────────────────────────────────────────────────────────────────────

const SECTIONS = [
  { id: 'intelligence', label: 'Intelligence' },
  { id: 'ratings',      label: 'Ratings'      },
  { id: 'form',         label: 'Form'          },
  { id: 'h2h',          label: 'Head to head'  },
  { id: 'serve',        label: 'Serve'         },
]

export default function MatchDetail() {
  const { id } = useParams()
  const [match,   setMatch]   = useState(null)
  const [loading, setLoading] = useState(true)
  const [error,   setError]   = useState(null)
  const [activeTab, setActiveTab] = useState('intelligence')

  // One ref per section for scroll-to
  const refs = {
    intelligence: useRef(null),
    ratings:      useRef(null),
    form:         useRef(null),
    h2h:          useRef(null),
    serve:        useRef(null),
  }

  useEffect(() => {
    api.match(id)
      .then(data => {
        const p1   = data.players?.first  || {}
        const p2   = data.players?.second || {}
        const pred = data.prediction || {}
        const mkt  = data.market    || {}
        const edge = data.edge      || {}
        setMatch({
          ...data.match,
          first_player:  { ...p1, player_id: p1.id },
          second_player: { ...p2, player_id: p2.id },
          prediction: {
            ...pred,
            edge_first:  edge.p1,
            edge_second: edge.p2,
          },
          market: {
            odds_first_player:  mkt.p1?.decimal_odds,
            odds_second_player: mkt.p2?.decimal_odds,
            bookmaker:          mkt.p1?.bookmaker || mkt.p2?.bookmaker,
          },
          edge,
        })
        setLoading(false)
      })
      .catch(e => { setError(e.message); setLoading(false) })
  }, [id])

  function handleTabClick(tabId) {
    setActiveTab(tabId)
    const ref = refs[tabId]
    if (ref?.current) {
      // 52px nav + ~110px sticky player bar
      const offset = 52 + 120
      const top = ref.current.getBoundingClientRect().top + window.scrollY - offset
      window.scrollTo({ top, behavior: 'smooth' })
    }
  }

  if (loading) return <div className="page"><div className="loading">Loading match…</div></div>
  if (error)   return <div className="page"><div className="error">{error}</div></div>
  if (!match)  return null

  // Odds row
  const mkt = match.market || {}

  return (
    <div className="page" style={{ paddingTop: 0 }}>
      {/* Non-sticky meta */}
      <div style={{
        background: 'var(--bg-card)',
        borderBottom: '1px solid var(--border)',
        paddingBottom: 0,
      }}>
        <MatchMeta match={match} />

        {/* Odds */}
        {(mkt.odds_first_player || mkt.odds_second_player) && (
          <div style={{
            display: 'flex', justifyContent: 'center', gap: 24,
            padding: '6px 24px', fontSize: 12, color: 'var(--text-3)',
          }}>
            <span>{match.first_player?.name}: <strong style={{ color: 'var(--text-2)' }}>{mkt.odds_first_player?.toFixed(2) || '—'}</strong></span>
            <span>{match.second_player?.name}: <strong style={{ color: 'var(--text-2)' }}>{mkt.odds_second_player?.toFixed(2) || '—'}</strong></span>
            {mkt.bookmaker && <span style={{ color: 'var(--text-3)' }}>{mkt.bookmaker}</span>}
          </div>
        )}
      </div>

      {/* Sticky player + tabs bar */}
      <PlayerBar
        match={match}
        activeTab={activeTab}
        onTabClick={handleTabClick}
        tabRefs={refs}
      />

      {/* All content sections */}
      <div style={{ padding: '0 0 60px' }}>
        <Section id="intelligence" sectionRef={refs.intelligence} title="Intelligence">
          <SectionIntelligence match={match} />
        </Section>

        <Section id="ratings" sectionRef={refs.ratings} title="Ratings">
          <SectionRatings match={match} />
        </Section>

        <Section id="form" sectionRef={refs.form} title="Form">
          <SectionForm match={match} />
        </Section>

        <Section id="h2h" sectionRef={refs.h2h} title="Head to head">
          <SectionH2H match={match} />
        </Section>

        <Section id="serve" sectionRef={refs.serve} title="Serve">
          <SectionServe match={match} />
        </Section>
      </div>
    </div>
  )
}
