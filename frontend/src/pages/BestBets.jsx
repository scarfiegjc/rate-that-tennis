/**
 * BestBets — ratethat.tennis
 * ===========================
 * Lists upcoming matches where our ML model picks the winner AND Cloudbet's
 * price implies a lower probability than we do (positive edge).
 *
 * Edge is computed server-side against Cloudbet's specific price (not the
 * best price across all books), because Cloudbet is the affiliate — the
 * price quoted is the price the punter actually gets when they click
 * through. That keeps the bet-now CTA honest.
 */
import { useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import { api } from '../api'

const fmtDate = (iso) => {
  if (!iso) return ''
  try {
    return new Date(iso).toLocaleDateString('en-GB', {
      weekday: 'short', day: 'numeric', month: 'short',
    })
  } catch { return iso }
}

const pct = (p) => `${Math.round((p || 0) * 100)}%`

function BetCard({ bet }) {
  const matchHref = `/match/${bet.match_id}`
  const ctaHref   = bet.cloudbet_link || 'https://www.cloudbet.com/en/sports/tennis'

  return (
    <div style={{
      background: 'var(--bg-2)',
      border: '1px solid var(--border-1)',
      borderRadius: 14,
      overflow: 'hidden',
      display: 'flex',
      flexDirection: 'column',
      boxShadow: '0 2px 8px rgba(0,0,0,0.25)',
    }}>
      {/* Edge ribbon */}
      <div style={{
        background: 'var(--green)',
        color: '#fff',
        padding: '8px 14px',
        display: 'flex',
        justifyContent: 'space-between',
        alignItems: 'center',
      }}>
        <span style={{ fontWeight: 800, letterSpacing: '0.04em' }}>
          +{(bet.edge * 100).toFixed(1)}% EDGE
        </span>
        <span style={{ fontSize: 11, opacity: 0.85, textTransform: 'uppercase', letterSpacing: '0.08em' }}>
          {fmtDate(bet.event_date)}{bet.event_time ? ` · ${bet.event_time.slice(0,5)}` : ''}
        </span>
      </div>

      {/* Pick + opponent */}
      <div style={{ padding: '14px 16px 10px' }}>
        <div style={{ fontWeight: 800, fontSize: 18, color: 'var(--text-1)', lineHeight: 1.15 }}>
          {bet.pick_name}
          {bet.pick_country && (
            <span style={{ fontSize: 12, color: 'var(--text-3)', marginLeft: 6, fontWeight: 500 }}>
              {bet.pick_country}
            </span>
          )}
        </div>
        <div style={{ fontSize: 13, color: 'var(--text-2)', marginTop: 4 }}>
          to beat {bet.opp_name}
        </div>
        <div style={{
          fontSize: 11,
          color: 'var(--text-3)',
          marginTop: 6,
          letterSpacing: '0.03em',
        }}>
          {bet.tournament}{bet.surface ? ` · ${bet.surface}` : ''}{bet.round ? ` · ${bet.round}` : ''}
        </div>
      </div>

      {/* Stats row */}
      <div style={{
        margin: '0 16px 14px',
        padding: '10px 12px',
        background: 'var(--bg-1)',
        borderRadius: 10,
        display: 'grid',
        gridTemplateColumns: '1fr 1fr 1fr',
        gap: 8,
        textAlign: 'center',
      }}>
        <div>
          <div style={{ fontSize: 10, color: 'var(--text-3)', textTransform: 'uppercase', letterSpacing: '0.08em', fontWeight: 700 }}>Our Model</div>
          <div style={{ fontSize: 18, fontWeight: 800, color: 'var(--green)' }}>{pct(bet.model_prob)}</div>
        </div>
        <div>
          <div style={{ fontSize: 10, color: 'var(--text-3)', textTransform: 'uppercase', letterSpacing: '0.08em', fontWeight: 700 }}>Market</div>
          <div style={{ fontSize: 18, fontWeight: 800, color: 'var(--text-2)' }}>{pct(bet.implied_prob)}</div>
        </div>
        <div>
          <div style={{ fontSize: 10, color: 'var(--text-3)', textTransform: 'uppercase', letterSpacing: '0.08em', fontWeight: 700 }}>Cloudbet</div>
          <div style={{ fontSize: 18, fontWeight: 800, color: 'var(--text-1)' }}>{Number(bet.price).toFixed(2)}</div>
        </div>
      </div>

      {/* CTAs */}
      <div style={{
        marginTop: 'auto',
        display: 'grid',
        gridTemplateColumns: '1fr 1fr',
        borderTop: '1px solid var(--border-1)',
      }}>
        <Link to={matchHref} style={{
          padding: '13px 8px',
          textAlign: 'center',
          textDecoration: 'none',
          color: 'var(--text-1)',
          fontWeight: 700,
          fontSize: 13,
          letterSpacing: '0.06em',
          textTransform: 'uppercase',
          borderRight: '1px solid var(--border-1)',
          background: 'var(--bg-2)',
        }}>
          See Match
        </Link>
        <a
          href={ctaHref}
          target="_blank"
          rel="noopener noreferrer sponsored"
          style={{
            padding: '13px 8px',
            textAlign: 'center',
            textDecoration: 'none',
            color: '#fff',
            fontWeight: 700,
            fontSize: 13,
            letterSpacing: '0.06em',
            textTransform: 'uppercase',
            background: '#18181b',
          }}
        >
          Bet at Cloudbet →
        </a>
      </div>
    </div>
  )
}

export default function BestBets() {
  const [bets, setBets] = useState(null)
  const [error, setError] = useState(null)
  const [minEdge, setMinEdge] = useState(0.02)

  useEffect(() => {
    let on = true
    setBets(null)
    api.bestBets(5, minEdge, 40)
      .then(d => { if (on) setBets(d.bets || []) })
      .catch(e => { if (on) setError(e.message) })
    return () => { on = false }
  }, [minEdge])

  return (
    <div style={{ maxWidth: 1200, margin: '0 auto', padding: '24px 20px' }}>

      {/* Header */}
      <div style={{ marginBottom: 22 }}>
        <h1 style={{
          fontSize: '2.2rem',
          fontWeight: 900,
          color: 'var(--text-1)',
          margin: 0,
          letterSpacing: '-0.02em',
        }}>
          Best Bets
        </h1>
        <p style={{ color: 'var(--text-2)', maxWidth: 720, marginTop: 8, lineHeight: 1.5 }}>
          Matches where our model picks the winner and the market gives that
          pick a lower implied probability than we do.
        </p>

        {/* Edge threshold pills */}
        <div style={{ display: 'flex', gap: 8, marginTop: 14, flexWrap: 'wrap' }}>
          {[0.02, 0.05, 0.10].map(t => (
            <button
              key={t}
              onClick={() => setMinEdge(t)}
              style={{
                padding: '6px 14px',
                borderRadius: 999,
                border: '1px solid var(--border-1)',
                background: minEdge === t ? 'var(--green)' : 'var(--bg-2)',
                color: minEdge === t ? '#fff' : 'var(--text-2)',
                fontWeight: 700,
                fontSize: 13,
                cursor: 'pointer',
              }}
            >
              {(t * 100).toFixed(0)}%+ edge
            </button>
          ))}
        </div>
      </div>

      {/* Cards / loading / empty */}
      {error && (
        <div style={{ background: 'var(--bg-2)', border: '1px solid var(--border-1)', borderRadius: 10, padding: 16, color: 'var(--text-2)' }}>
          Couldn't load Best Bets: {error}
        </div>
      )}
      {!error && bets === null && (
        <div style={{ color: 'var(--text-2)', padding: 24, textAlign: 'center' }}>
          Loading…
        </div>
      )}
      {!error && bets !== null && bets.length === 0 && (
        <div style={{
          background: 'var(--bg-2)',
          border: '1px dashed var(--border-1)',
          borderRadius: 12,
          padding: '36px 20px',
          textAlign: 'center',
          color: 'var(--text-3)',
        }}>
          No predicted-winner value bets above the {(minEdge * 100).toFixed(0)}% edge
          threshold right now. Try a lower threshold or check back after the next
          Cloudbet odds refresh.
        </div>
      )}
      {!error && bets && bets.length > 0 && (
        <div style={{
          display: 'grid',
          gridTemplateColumns: 'repeat(auto-fill, minmax(320px, 1fr))',
          gap: 16,
          alignItems: 'stretch',
        }}>
          {bets.map(b => <BetCard key={`${b.match_id}-${b.side}`} bet={b} />)}
        </div>
      )}

      {/* Footer — responsible gambling line only */}
      <div style={{
        marginTop: 28,
        padding: '10px 16px',
        textAlign: 'center',
        fontSize: 11,
        color: 'var(--text-3)',
        letterSpacing: '0.06em',
        textTransform: 'uppercase',
        fontWeight: 600,
      }}>
        18+ · BeGambleAware.org
      </div>
    </div>
  )
}
