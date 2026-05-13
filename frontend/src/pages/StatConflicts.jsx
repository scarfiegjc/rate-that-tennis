/**
 * StatConflicts — "Stat Clash" page
 *
 * Shows upcoming matches where one player is great at a stat the other player
 * is poor at — creating a clear tactical advantage.
 *
 * Ordered by total conflict strength (strongest first).
 * Compounding conflicts (multiple stat clashes in one match) are grouped on
 * the same card with each conflict shown separately.
 */
import { useState, useEffect } from 'react'
import { Link, useNavigate } from 'react-router-dom'
import { api } from '../api.js'

// ─────────────────────────────────────────────────────────────────────────────
// Helpers
// ─────────────────────────────────────────────────────────────────────────────

function surfaceColor(s) {
  const m = {
    Clay: '#B45309', Hard: '#1D4ED8', Grass: '#15803D',
    Indoor: '#6D28D9', 'Indoor Hard': '#6D28D9',
  }
  return m[s] || 'var(--text-3)'
}

function surfaceBg(s) {
  const m = {
    Clay: '#FEF3C7', Hard: '#DBEAFE', Grass: '#DCFCE7',
    Indoor: '#EDE9FE', 'Indoor Hard': '#EDE9FE',
  }
  return m[s] || 'var(--bg-raised)'
}

function fmt(n, d = 0) {
  if (n == null) return '—'
  return Number(n).toFixed(d)
}

function ratingColor(v) {
  if (v == null) return 'var(--text-3)'
  if (v >= 65)  return '#166534'
  if (v >= 50)  return '#92400E'
  return '#991B1B'
}

function ratingBg(v) {
  if (v == null) return 'var(--bg-raised)'
  if (v >= 65)  return '#DCFCE7'
  if (v >= 50)  return '#FEF3C7'
  return '#FEE2E2'
}

// ─────────────────────────────────────────────────────────────────────────────
// Conflict badge (single stat clash)
// ─────────────────────────────────────────────────────────────────────────────

function ConflictBadge({ conflict, favPlayer, oppPlayer }) {
  const favName = favPlayer?.name?.split(' ').slice(-1)[0] || 'Player'
  const oppName = oppPlayer?.name?.split(' ').slice(-1)[0] || 'Opponent'

  return (
    <div style={{
      background: 'var(--bg-sunken)',
      borderRadius: 'var(--r)',
      padding: '10px 12px',
      display: 'flex',
      flexDirection: 'column',
      gap: 6,
    }}>
      {/* Label */}
      <div style={{
        fontSize: 10, fontWeight: 800, textTransform: 'uppercase',
        letterSpacing: '0.8px', color: 'var(--text-3)',
      }}>
        {conflict.label}
      </div>

      {/* The clash row */}
      <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
        {/* Favoured side */}
        <div style={{
          flex: 1, background: ratingBg(conflict.favoured_value),
          borderRadius: 6, padding: '6px 10px',
          display: 'flex', flexDirection: 'column', gap: 2,
        }}>
          <div style={{ fontSize: 11, fontWeight: 700, color: 'var(--text-2)' }}>
            {favName}
          </div>
          <div style={{ fontSize: 10, color: ratingColor(conflict.favoured_value) }}>
            {conflict.favoured_label}
          </div>
          <div style={{
            fontSize: 22, fontWeight: 900, lineHeight: 1,
            color: ratingColor(conflict.favoured_value),
            fontVariantNumeric: 'tabular-nums',
          }}>
            {fmt(conflict.favoured_value, 0)}
          </div>
        </div>

        {/* Gap arrow */}
        <div style={{ fontSize: 13, color: 'var(--text-3)', flexShrink: 0 }}>
          <span style={{ fontSize: 18, color: '#DC2626', fontWeight: 800 }}>→</span>
          <div style={{ fontSize: 9, textAlign: 'center', color: 'var(--text-3)', fontWeight: 600 }}>
            {fmt(conflict.gap, 0)} pts
          </div>
        </div>

        {/* Disadvantaged side */}
        <div style={{
          flex: 1, background: ratingBg(conflict.opponent_value),
          borderRadius: 6, padding: '6px 10px',
          display: 'flex', flexDirection: 'column', gap: 2,
        }}>
          <div style={{ fontSize: 11, fontWeight: 700, color: 'var(--text-2)' }}>
            {oppName}
          </div>
          <div style={{ fontSize: 10, color: ratingColor(conflict.opponent_value) }}>
            {conflict.opponent_label}
          </div>
          <div style={{
            fontSize: 22, fontWeight: 900, lineHeight: 1,
            color: ratingColor(conflict.opponent_value),
            fontVariantNumeric: 'tabular-nums',
          }}>
            {fmt(conflict.opponent_value, 0)}
          </div>
        </div>
      </div>
    </div>
  )
}

// ─────────────────────────────────────────────────────────────────────────────
// Match conflict card
// ─────────────────────────────────────────────────────────────────────────────

function ConflictCard({ item }) {
  const navigate = useNavigate()
  const { first_player: p1, second_player: p2, conflicts } = item

  // The favoured player for the first (strongest) conflict
  const topConflict  = conflicts[0]
  const favIsFirst   = topConflict?.favoured_player === 'first'
  const favPlayer    = favIsFirst ? p1 : p2
  const oppPlayer    = favIsFirst ? p2 : p1

  return (
    <div
      style={{
        background: 'var(--bg-card)',
        border: '1px solid var(--border)',
        borderRadius: 'var(--r-lg)',
        boxShadow: 'var(--shadow-sm)',
        overflow: 'hidden',
        cursor: 'pointer',
        transition: 'box-shadow 0.15s',
      }}
      onClick={() => navigate(item.match_url)}
      onMouseEnter={e => e.currentTarget.style.boxShadow = 'var(--shadow)'}
      onMouseLeave={e => e.currentTarget.style.boxShadow = 'var(--shadow-sm)'}
    >
      {/* ── Header ── */}
      <div style={{
        padding: '10px 14px 8px',
        borderBottom: '1px solid var(--border-faint)',
        display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start',
      }}>
        <div style={{ minWidth: 0, flex: 1 }}>
          <div style={{
            fontSize: 12, fontWeight: 600, color: 'var(--text-2)',
            overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap',
          }}>
            {item.tournament || 'Unknown tournament'}
          </div>
          <div style={{ display: 'flex', alignItems: 'center', gap: 6, marginTop: 3, flexWrap: 'wrap' }}>
            {item.surface && (
              <span style={{
                fontSize: 10, fontWeight: 700,
                color: surfaceColor(item.surface),
                background: surfaceBg(item.surface),
                borderRadius: 20, padding: '1px 7px',
              }}>
                {item.surface}
              </span>
            )}
            {item.round && (
              <span style={{ fontSize: 10, color: 'var(--text-3)' }}>{item.round}</span>
            )}
            <span style={{ fontSize: 10, color: 'var(--text-3)' }}>
              {item.event_date}{item.event_time ? ` · ${item.event_time}` : ''}
            </span>
          </div>
        </div>

        {/* Conflict count badge */}
        {conflicts.length > 1 && (
          <div style={{
            display: 'flex', flexDirection: 'column', alignItems: 'center',
            background: '#FEF3C7', borderRadius: 'var(--r)', padding: '4px 8px',
            flexShrink: 0, marginLeft: 8,
          }}>
            <span style={{ fontSize: 16, fontWeight: 900, color: '#92400E', lineHeight: 1 }}>
              {conflicts.length}
            </span>
            <span style={{ fontSize: 9, color: '#92400E', fontWeight: 700, textTransform: 'uppercase' }}>
              clashes
            </span>
          </div>
        )}
      </div>

      {/* ── Players row ── */}
      <div style={{
        padding: '12px 14px',
        display: 'flex', alignItems: 'center', justifyContent: 'space-between', gap: 8,
        borderBottom: '1px solid var(--border-faint)',
      }}>
        {/* Favoured player */}
        <div style={{ flex: 1, minWidth: 0 }}>
          <div style={{
            fontSize: 20, fontWeight: 800, letterSpacing: '-0.4px', lineHeight: 1.1,
            overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap',
          }}>
            {favPlayer?.name || '—'}
          </div>
          {favPlayer?.win_prob != null && (
            <div style={{
              fontSize: 24, fontWeight: 900, color: '#166534',
              fontVariantNumeric: 'tabular-nums', lineHeight: 1.2,
            }}>
              {fmt(favPlayer.win_prob, 0)}%
              <span style={{ fontSize: 11, fontWeight: 500, color: 'var(--text-3)', marginLeft: 4 }}>
                win prob
              </span>
            </div>
          )}
          {favPlayer?.edge != null && Math.abs(favPlayer.edge) >= 2 && (
            <div style={{
              display: 'inline-flex', marginTop: 4,
              fontSize: 11, fontWeight: 700,
              color: favPlayer.edge >= 5 ? '#166534' : '#92400E',
              background: favPlayer.edge >= 5 ? '#DCFCE7' : '#FEF3C7',
              borderRadius: 20, padding: '2px 8px',
            }}>
              +{fmt(favPlayer.edge, 1)}% edge
            </div>
          )}
        </div>

        {/* vs divider */}
        <div style={{
          fontSize: 11, fontWeight: 700, color: 'var(--text-3)',
          flexShrink: 0, textAlign: 'center', padding: '0 4px',
        }}>
          vs
        </div>

        {/* Opponent */}
        <div style={{ flex: 1, minWidth: 0, textAlign: 'right' }}>
          <div style={{
            fontSize: 14, fontWeight: 600, letterSpacing: '-0.2px', lineHeight: 1.1,
            color: 'var(--text-2)',
            overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap',
          }}>
            {oppPlayer?.name || '—'}
          </div>
          {oppPlayer?.win_prob != null && (
            <div style={{
              fontSize: 18, fontWeight: 700, color: 'var(--text-3)',
              fontVariantNumeric: 'tabular-nums', lineHeight: 1.2,
            }}>
              {fmt(oppPlayer.win_prob, 0)}%
            </div>
          )}
        </div>
      </div>

      {/* ── Conflict badges ── */}
      <div style={{ padding: '12px 14px', display: 'flex', flexDirection: 'column', gap: 8 }}>
        {conflicts.map((c, i) => {
          const cFavIsFirst = c.favoured_player === 'first'
          const cFav = cFavIsFirst ? p1 : p2
          const cOpp = cFavIsFirst ? p2 : p1
          return (
            <ConflictBadge key={i} conflict={c} favPlayer={cFav} oppPlayer={cOpp} />
          )
        })}
      </div>

      {/* ── Footer: link to match ── */}
      <div style={{
        padding: '8px 14px 12px',
        display: 'flex', justifyContent: 'flex-end',
      }}>
        <Link
          to={item.match_url}
          onClick={e => e.stopPropagation()}
          style={{
            fontSize: 12, fontWeight: 600, color: 'var(--green)',
            display: 'flex', alignItems: 'center', gap: 4,
          }}
        >
          View match →
        </Link>
      </div>
    </div>
  )
}

// ─────────────────────────────────────────────────────────────────────────────
// Empty state
// ─────────────────────────────────────────────────────────────────────────────

function EmptyState() {
  return (
    <div style={{ padding: '60px 24px', textAlign: 'center' }}>
      <div style={{ fontSize: 40, marginBottom: 12 }}>📊</div>
      <p style={{ fontWeight: 600, marginBottom: 6 }}>No stat clashes found</p>
      <p style={{ color: 'var(--text-3)', fontSize: 13 }}>
        Stat conflicts appear when upcoming matches have a player who rates great
        at something their opponent rates poorly at. Check back when more matches
        are scheduled.
      </p>
    </div>
  )
}

// ─────────────────────────────────────────────────────────────────────────────
// Main page
// ─────────────────────────────────────────────────────────────────────────────

export default function StatConflicts() {
  const [data, setData]       = useState(null)
  const [loading, setLoading] = useState(true)
  const [error, setError]     = useState(null)
  const [daysAhead, setDaysAhead] = useState(2)

  async function load(days) {
    setLoading(true)
    setError(null)
    try {
      const d = await api.statConflicts(days)
      setData(d)
    } catch (e) {
      setError(e.message)
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => { load(daysAhead) }, [daysAhead])

  const items        = data?.conflicts || []
  const compounding  = items.filter(i => i.conflict_count >= 2)
  const single       = items.filter(i => i.conflict_count === 1)

  return (
    <main className="page">

      {/* ── Page header ── */}
      <div style={{ marginBottom: 24 }}>
        <h1 style={{ margin: '0 0 4px', fontSize: 24, fontWeight: 800, letterSpacing: '-0.5px' }}>
          Stat Clashes
        </h1>
        <p style={{ margin: 0, color: 'var(--text-3)', fontSize: 14 }}>
          Upcoming matches where one player's strength meets the opponent's weakness in the same stat.
          Compounding clashes (2+ conflicts) shown first.
        </p>
      </div>

      {/* ── Controls ── */}
      <div style={{
        display: 'flex', alignItems: 'center', gap: 8, marginBottom: 24, flexWrap: 'wrap',
      }}>
        <span style={{ fontSize: 12, color: 'var(--text-3)', fontWeight: 600 }}>Showing:</span>
        {[
          { label: 'Today', days: 1 },
          { label: 'Next 2 days', days: 2 },
          { label: 'Next 7 days', days: 7 },
        ].map(opt => (
          <button
            key={opt.days}
            onClick={() => setDaysAhead(opt.days)}
            style={{
              padding: '5px 12px', borderRadius: 20, fontSize: 12, fontWeight: 600,
              background: daysAhead === opt.days ? 'var(--text)' : 'var(--bg-raised)',
              color: daysAhead === opt.days ? 'var(--text-inv)' : 'var(--text-2)',
              border: '1px solid var(--border)',
            }}
          >
            {opt.label}
          </button>
        ))}
        <span style={{ marginLeft: 'auto', fontSize: 12, color: 'var(--text-3)' }}>
          {loading ? 'Loading…' : `${items.length} match${items.length !== 1 ? 'es' : ''} with clashes`}
        </span>
      </div>

      {/* ── Loading ── */}
      {loading && (
        <div style={{ padding: '60px 0', textAlign: 'center', color: 'var(--text-3)' }}>
          Finding stat clashes…
        </div>
      )}

      {/* ── Error ── */}
      {error && (
        <div style={{
          padding: '16px 20px', background: '#FEE2E2', borderRadius: 'var(--r)',
          color: '#991B1B', fontSize: 13, marginBottom: 24,
        }}>
          {error}
        </div>
      )}

      {/* ── Content ── */}
      {!loading && !error && (
        <>
          {items.length === 0 && <EmptyState />}

          {/* Compounding clashes (2+ stat conflicts) */}
          {compounding.length > 0 && (
            <section style={{ marginBottom: 32 }}>
              <div style={{
                display: 'flex', alignItems: 'center', gap: 8, marginBottom: 14,
              }}>
                <h2 style={{ margin: 0, fontSize: 14, fontWeight: 700 }}>
                  Compounding clashes
                </h2>
                <span style={{
                  background: '#FEF3C7', color: '#92400E',
                  borderRadius: 20, padding: '1px 8px', fontSize: 11, fontWeight: 700,
                }}>
                  {compounding.length}
                </span>
                <span style={{ fontSize: 12, color: 'var(--text-3)' }}>
                  2 or more stat advantages in the same match
                </span>
              </div>
              <div style={{
                display: 'grid',
                gridTemplateColumns: 'repeat(auto-fill, minmax(340px, 1fr))',
                gap: 16,
              }}>
                {compounding.map(item => (
                  <ConflictCard key={item.match_id} item={item} />
                ))}
              </div>
            </section>
          )}

          {/* Single clashes */}
          {single.length > 0 && (
            <section>
              <div style={{
                display: 'flex', alignItems: 'center', gap: 8, marginBottom: 14,
              }}>
                <h2 style={{ margin: 0, fontSize: 14, fontWeight: 700 }}>
                  Single clashes
                </h2>
                <span style={{
                  background: 'var(--bg-raised)', color: 'var(--text-3)',
                  borderRadius: 20, padding: '1px 8px', fontSize: 11, fontWeight: 700,
                }}>
                  {single.length}
                </span>
              </div>
              <div style={{
                display: 'grid',
                gridTemplateColumns: 'repeat(auto-fill, minmax(340px, 1fr))',
                gap: 16,
              }}>
                {single.map(item => (
                  <ConflictCard key={item.match_id} item={item} />
                ))}
              </div>
            </section>
          )}
        </>
      )}
    </main>
  )
}
