'use client'
/**
 * OddsComparison
 * --------------
 * Drops in under the Intelligence tab. For each player it shows:
 *   - "RTT" lozenge with our model's fair odds
 *   - "Best market: X.XX @ Bookmaker" lozenge with edge %
 *   - "Bet Now" CTA (only when the bookmaker has an active affiliate deal)
 * Plus an expandable row of every bookmaker that quoted the match.
 *
 * Player colours follow the existing convention used elsewhere on the page:
 *   p1 → green (var(--green))
 *   p2 → blue  (var(--blue))
 *
 * Live matches: hidden by default until LIVE_ODDS_VISIBLE is enabled in the
 * API. The structure renders an empty state in that case.
 */
import { useEffect, useState } from 'react'
import { api } from '../lib/api'

const fmtOdds = (n) =>
  n == null || isNaN(n) ? '—' : Number(n).toFixed(2)

const fmtEdge = (pct) => {
  if (pct == null) return null
  const sign = pct > 0 ? '+' : ''
  return `${sign}${pct.toFixed(1)}%`
}

const edgeColor = (pct) => {
  if (pct == null) return 'var(--text-3)'
  if (pct >= 5)    return 'var(--green-text)'
  if (pct >= 2)    return 'var(--green)'
  if (pct >= -2)   return 'var(--text-2)'
  return 'var(--text-3)'
}

// ─────────────────────────────────────────────────────────────────────────────
// Lozenge primitives
// ─────────────────────────────────────────────────────────────────────────────

function Lozenge({ children, bg, color, border, style = {} }) {
  return (
    <span
      style={{
        display: 'inline-flex',
        alignItems: 'center',
        gap: 6,
        padding: '6px 12px',
        borderRadius: 999,
        background: bg,
        color,
        border: border ? `1px solid ${border}` : 'none',
        fontSize: 13,
        fontWeight: 600,
        whiteSpace: 'nowrap',
        ...style,
      }}
    >
      {children}
    </span>
  )
}

function RttFairLozenge({ odds, accent }) {
  return (
    <Lozenge
      bg="var(--bg-raised)"
      color={accent}
      border="var(--border)"
    >
      <span style={{
        fontSize: 10, fontWeight: 700, letterSpacing: 0.6,
        textTransform: 'uppercase', opacity: 0.75,
      }}>
        RTT
      </span>
      <span style={{ fontSize: 14, fontWeight: 700 }}>{fmtOdds(odds)}</span>
    </Lozenge>
  )
}

function MarketLozenge({ best, accent }) {
  if (!best) {
    return (
      <Lozenge bg="var(--bg-raised)" color="var(--text-3)" border="var(--border-faint)">
        No market price yet
      </Lozenge>
    )
  }
  return (
    <Lozenge
      bg={accent}
      color="#fff"
      style={{ fontWeight: 700 }}
    >
      <span style={{ fontSize: 14 }}>{fmtOdds(best.decimal_odds)}</span>
      <span style={{ fontSize: 11, fontWeight: 500, opacity: 0.85 }}>
        · {best.display_name}
      </span>
    </Lozenge>
  )
}

function BetNowButton({ best, playerName, accent }) {
  if (!best || !best.click_url) return null
  const label = best.is_affiliate
    ? `Bet on ${playerName} at ${best.display_name}`
    : `View at ${best.display_name}`

  return (
    <a
      href={best.click_url}
      target="_blank"
      rel="noopener noreferrer sponsored"
      style={{
        display: 'inline-flex',
        alignItems: 'center',
        gap: 6,
        padding: '7px 14px',
        borderRadius: 999,
        background: accent,
        color: '#fff',
        fontSize: 13,
        fontWeight: 700,
        textDecoration: 'none',
        whiteSpace: 'nowrap',
        boxShadow: '0 1px 2px rgba(0,0,0,0.08)',
      }}
      title={label}
    >
      <span>Bet Now</span>
      <span aria-hidden="true">→</span>
    </a>
  )
}

// ─────────────────────────────────────────────────────────────────────────────
// Per-player row
// ─────────────────────────────────────────────────────────────────────────────

function PlayerRow({ playerName, fairOdds, best, accent, isHeadline }) {
  const edge = best?.edge_pct ?? null
  const showCta = isHeadline && best?.click_url

  return (
    <div style={{
      background: 'var(--bg-card)',
      border: `1px solid ${isHeadline ? accent : 'var(--border)'}`,
      borderRadius: 'var(--r-lg)',
      padding: '14px 16px',
      display: 'flex',
      flexDirection: 'column',
      gap: 10,
      position: 'relative',
      overflow: 'hidden',
    }}>
      {/* Coloured top bar — matches IntelColumn convention */}
      <div style={{
        position: 'absolute', left: 0, right: 0, top: 0, height: 3, background: accent,
      }} />

      {/* Headline text */}
      <div style={{ fontSize: 13, color: 'var(--text-2)', lineHeight: 1.45 }}>
        {best ? (
          <>
            Best odds available for{' '}
            <strong style={{ color: 'var(--text)' }}>{playerName}</strong> are with{' '}
            <strong style={{ color: accent }}>{best.display_name}</strong>
          </>
        ) : (
          <>No market price yet for <strong>{playerName}</strong></>
        )}
      </div>

      {/* Lozenges row */}
      <div style={{
        display: 'flex',
        flexWrap: 'wrap',
        alignItems: 'center',
        gap: 10,
      }}>
        <RttFairLozenge odds={fairOdds} accent={accent} />
        <MarketLozenge  best={best}     accent={accent} />
        {edge != null && (
          <span style={{
            fontSize: 12,
            fontWeight: 700,
            color: edgeColor(edge),
            padding: '4px 8px',
            background: edge >= 2 ? 'var(--green-bg)' : 'var(--bg-raised)',
            borderRadius: 6,
          }}>
            {fmtEdge(edge)} {edge >= 2 ? 'value' : edge <= -2 ? 'short' : 'aligned'}
          </span>
        )}
        {showCta && (
          <BetNowButton best={best} playerName={playerName} accent={accent} />
        )}
      </div>
    </div>
  )
}

// ─────────────────────────────────────────────────────────────────────────────
// Compare-all-bookmakers expandable
// ─────────────────────────────────────────────────────────────────────────────

function CompareAll({ bookmakers, fair, p1Name, p2Name }) {
  const [open, setOpen] = useState(false)
  if (!bookmakers || bookmakers.length === 0) return null

  return (
    <div style={{ marginTop: 12 }}>
      <button
        onClick={() => setOpen(o => !o)}
        style={{
          background: 'none',
          border: 'none',
          color: 'var(--text-2)',
          fontSize: 12,
          fontWeight: 600,
          cursor: 'pointer',
          padding: '6px 0',
          display: 'inline-flex',
          alignItems: 'center',
          gap: 4,
        }}
      >
        <span>{open ? '▾' : '▸'}</span>
        {open ? 'Hide' : 'Compare all'} {bookmakers.length} bookmaker{bookmakers.length === 1 ? '' : 's'}
      </button>

      {open && (
        <div style={{
          marginTop: 8,
          background: 'var(--bg-card)',
          border: '1px solid var(--border)',
          borderRadius: 'var(--r-lg)',
          overflow: 'hidden',
        }}>
          <table style={{
            width: '100%',
            borderCollapse: 'collapse',
            fontSize: 13,
          }}>
            <thead>
              <tr style={{
                background: 'var(--bg-raised)',
                color: 'var(--text-3)',
                fontSize: 11,
                textTransform: 'uppercase',
                letterSpacing: 0.6,
              }}>
                <th style={{ textAlign: 'left',  padding: '8px 12px', fontWeight: 700 }}>Bookmaker</th>
                <th style={{ textAlign: 'right', padding: '8px 12px', fontWeight: 700, color: 'var(--green)' }}>{p1Name}</th>
                <th style={{ textAlign: 'right', padding: '8px 12px', fontWeight: 700, color: 'var(--blue)'  }}>{p2Name}</th>
                <th style={{ textAlign: 'right', padding: '8px 12px', fontWeight: 700 }}>Action</th>
              </tr>
            </thead>
            <tbody>
              {bookmakers.map((b) => {
                const e1 = b.p1 ? ((b.p1.decimal_odds / fair.p1) - 1) * 100 : null
                const e2 = b.p2 ? ((b.p2.decimal_odds / fair.p2) - 1) * 100 : null
                return (
                  <tr key={b.key} style={{ borderTop: '1px solid var(--border-faint)' }}>
                    <td style={{ padding: '10px 12px', fontWeight: 600 }}>
                      {b.display_name}
                      {b.is_affiliate && (
                        <span style={{
                          marginLeft: 6, fontSize: 10, fontWeight: 700, letterSpacing: 0.5,
                          color: 'var(--green-text)', background: 'var(--green-bg)',
                          padding: '2px 6px', borderRadius: 4,
                        }}>
                          PARTNER
                        </span>
                      )}
                    </td>
                    <td style={{ padding: '10px 12px', textAlign: 'right' }}>
                      {b.p1 ? (
                        <>
                          <span style={{ fontWeight: 600 }}>{fmtOdds(b.p1.decimal_odds)}</span>
                          {e1 != null && (
                            <span style={{
                              marginLeft: 6, fontSize: 11, fontWeight: 600,
                              color: edgeColor(e1),
                            }}>
                              {fmtEdge(e1)}
                            </span>
                          )}
                        </>
                      ) : '—'}
                    </td>
                    <td style={{ padding: '10px 12px', textAlign: 'right' }}>
                      {b.p2 ? (
                        <>
                          <span style={{ fontWeight: 600 }}>{fmtOdds(b.p2.decimal_odds)}</span>
                          {e2 != null && (
                            <span style={{
                              marginLeft: 6, fontSize: 11, fontWeight: 600,
                              color: edgeColor(e2),
                            }}>
                              {fmtEdge(e2)}
                            </span>
                          )}
                        </>
                      ) : '—'}
                    </td>
                    <td style={{ padding: '10px 12px', textAlign: 'right' }}>
                      {b.click_url ? (
                        <a
                          href={b.click_url}
                          target="_blank"
                          rel="noopener noreferrer sponsored"
                          style={{
                            fontSize: 12, fontWeight: 600,
                            color: b.is_affiliate ? 'var(--green)' : 'var(--text-2)',
                            textDecoration: 'none',
                          }}
                        >
                          {b.is_affiliate ? 'Bet Now →' : 'View →'}
                        </a>
                      ) : (
                        <span style={{ color: 'var(--text-3)', fontSize: 12 }}>—</span>
                      )}
                    </td>
                  </tr>
                )
              })}
            </tbody>
          </table>
        </div>
      )}
    </div>
  )
}

// ─────────────────────────────────────────────────────────────────────────────
// Main component
// ─────────────────────────────────────────────────────────────────────────────

export default function OddsComparison({ matchId }) {
  const [data, setData] = useState(null)
  const [error, setError] = useState(null)

  useEffect(() => {
    if (!matchId) return
    let on = true
    api.matchOdds(matchId)
      .then(d => { if (on) setData(d) })
      .catch(e => { if (on) setError(e.message) })
    return () => { on = false }
  }, [matchId])

  if (error) {
    // Fail silently — odds are a non-critical enhancement
    return null
  }

  if (!data) {
    return (
      <div style={{
        background: 'var(--bg-card)', border: '1px solid var(--border)',
        borderRadius: 'var(--r-lg)', padding: 16, marginTop: 16,
      }}>
        <div style={{ height: 14, width: 180, background: 'var(--bg-raised)', borderRadius: 4, marginBottom: 10 }} />
        <div style={{ height: 36, background: 'var(--bg-raised)', borderRadius: 8 }} />
      </div>
    )
  }

  // Hide the whole block if we have no bookmakers and odds aren't shown anyway
  if (data.live_hidden) {
    return (
      <div style={{
        background: 'var(--bg-card)', border: '1px solid var(--border-faint)',
        borderRadius: 'var(--r-lg)', padding: '14px 18px', marginTop: 16,
        display: 'flex', alignItems: 'center', gap: 12,
        color: 'var(--text-3)', fontSize: 13,
      }}>
        <span style={{
          width: 8, height: 8, borderRadius: '50%', background: 'var(--green)',
          flexShrink: 0, animation: 'pulse 1.5s ease-in-out infinite',
        }} />
        <span>Match in progress — live odds hidden until in-play subscription is enabled.</span>
      </div>
    )
  }

  if (!data.all_bookmakers || data.all_bookmakers.length === 0) {
    return null   // No odds yet — just don't render the section
  }

  const p1Name = data.players?.p1?.name || 'Player 1'
  const p2Name = data.players?.p2?.name || 'Player 2'
  const fair   = data.rtt_fair_odds || { p1: null, p2: null }
  const best   = data.best_value    || { p1: null, p2: null }

  return (
    <div style={{ marginTop: 20 }}>
      {/* Section header */}
      <div style={{
        display: 'flex', alignItems: 'baseline', justifyContent: 'space-between',
        marginBottom: 10, gap: 12, flexWrap: 'wrap',
      }}>
        <h3 style={{
          margin: 0,
          fontSize: 13,
          fontWeight: 700,
          textTransform: 'uppercase',
          letterSpacing: 0.7,
          color: 'var(--text-3)',
        }}>
          Market vs RTT model
        </h3>
        <span style={{ fontSize: 11, color: 'var(--text-3)' }}>
          {data.fetched_at && (
            <>Updated {new Date(data.fetched_at).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })} · </>
          )}
          {data.bookmaker_count} bookmaker{data.bookmaker_count === 1 ? '' : 's'}
        </span>
      </div>

      {/* Side-by-side player rows */}
      <div style={{
        display: 'grid',
        gridTemplateColumns: '1fr 1fr',
        gap: 12,
      }}>
        <PlayerRow
          playerName={p1Name}
          fairOdds={fair.p1}
          best={best.p1}
          accent="var(--green)"
          isHeadline={data.headline_side === 'p1'}
        />
        <PlayerRow
          playerName={p2Name}
          fairOdds={fair.p2}
          best={best.p2}
          accent="var(--blue)"
          isHeadline={data.headline_side === 'p2'}
        />
      </div>

      {/* Expandable comparison */}
      <CompareAll
        bookmakers={data.all_bookmakers}
        fair={fair}
        p1Name={p1Name}
        p2Name={p2Name}
      />

      {/* Affiliate disclosure (UKGC compliance) */}
      <div style={{
        marginTop: 10,
        fontSize: 10,
        color: 'var(--text-3)',
        lineHeight: 1.5,
      }}>
        Odds shown are for comparison and are subject to change at the bookmaker. Where a "PARTNER"
        link is shown, ratethat.tennis may earn a commission if you sign up — this never affects our
        ratings or recommendations. 18+ · gamble responsibly · BeGambleAware.org
      </div>
    </div>
  )
}
