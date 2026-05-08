import { useState, useEffect } from 'react'
import { useParams, Link } from 'react-router-dom'
import { api } from '../api.js'
import SurfaceBadge from '../components/SurfaceBadge.jsx'
import FormChart from '../components/FormChart.jsx'

// ─────────────────────────────────────────────────────────────────────────────
// Colour helpers tied to the site's light theme palette (defined in index.css):
//   --green / --amber / --red / --clay / --hard / --grass / --indoor
// ─────────────────────────────────────────────────────────────────────────────

function rttPastel(score) {
  if (score == null) return { bg: '#f0ede8', text: '#a8a29e' }
  if (score >= 80) return { bg: '#bbf0d0', text: '#166534' }
  if (score >= 65) return { bg: '#d9f0bb', text: '#3a5c14' }
  if (score >= 50) return { bg: '#fef3c7', text: '#92400e' }
  if (score >= 35) return { bg: '#fed7aa', text: '#9a3412' }
  return { bg: '#fecaca', text: '#991b1b' }
}

function rttTier(score) {
  if (score == null) return null
  if (score >= 90) return { label: 'Elite · Top 1%',     color: 'var(--green)' }
  if (score >= 80) return { label: 'Top tier · Top 5%',  color: 'var(--green)' }
  if (score >= 70) return { label: 'Strong · Top 15%',   color: 'var(--green)' }
  if (score >= 60) return { label: 'Solid · Top 30%',    color: 'var(--amber)' }
  if (score >= 50) return { label: 'Average',            color: 'var(--amber)' }
  if (score >= 40) return { label: 'Below average',      color: 'var(--text-3)' }
  return { label: 'Developing',                          color: 'var(--text-3)' }
}

// Rough percentile estimate from RTT scale (0–100). Useful for skill bars.
function pctFromScore(v) {
  if (v == null) return null
  if (v >= 95) return 'Top 1%'
  if (v >= 90) return 'Top 3%'
  if (v >= 85) return 'Top 7%'
  if (v >= 80) return 'Top 12%'
  if (v >= 75) return 'Top 20%'
  if (v >= 70) return 'Top 30%'
  if (v >= 60) return 'Top 50%'
  return null
}

function ageFromBirthday(birthday) {
  if (!birthday) return null
  const bd = new Date(birthday)
  if (Number.isNaN(bd.getTime())) return null
  const ms = Date.now() - bd.getTime()
  return Math.floor(ms / (365.25 * 24 * 3600 * 1000))
}

function handLabel(hand) {
  if (!hand) return null
  const h = String(hand).toLowerCase()
  if (h.startsWith('l')) return 'Left-handed'
  if (h.startsWith('r')) return 'Right-handed'
  return null
}

// Small flag emoji from ISO country code (2 letters)
function flagEmoji(countryCode) {
  if (!countryCode || countryCode.length !== 2) return ''
  const cc = countryCode.toUpperCase()
  return String.fromCodePoint(...[...cc].map(c => 0x1f1a5 + c.charCodeAt(0)))
}

// ─────────────────────────────────────────────────────────────────────────────
// Hero — name, meta chips, big RTT score, 90-day sparkline
// ─────────────────────────────────────────────────────────────────────────────

function HeroSparkline({ history }) {
  if (!history || history.length < 3) {
    return (
      <div style={{ height: 30, fontSize: 10, color: 'var(--text-3)', textAlign: 'center', marginTop: 6 }}>
        Not enough rating history
      </div>
    )
  }
  // history is most-recent first; reverse for left-to-right time order
  const points = [...history].reverse()
  const w = 130, h = 32
  const values = points.map(p => Number(p.rtt_score) || 0)
  const min = Math.min(...values)
  const max = Math.max(...values)
  const range = Math.max(1, max - min)
  const xs = points.map((_, i) => (i / (points.length - 1)) * w)
  const ys = values.map(v => h - 2 - ((v - min) / range) * (h - 4))
  const linePoints = xs.map((x, i) => `${x.toFixed(1)},${ys[i].toFixed(1)}`).join(' ')
  const areaPoints = `${linePoints} ${w},${h} 0,${h}`
  const trajectory = values[values.length - 1] - values[0]
  const trajColor = trajectory > 0 ? 'var(--green)' : trajectory < 0 ? 'var(--red)' : 'var(--text-3)'
  return (
    <>
      <svg width={w} height={h} style={{ display: 'block', margin: '4px 0 0' }}>
        <polyline points={areaPoints} fill="rgba(5, 150, 105, 0.12)" stroke="none" />
        <polyline points={linePoints} fill="none" stroke="#059669" strokeWidth="1.5" strokeLinejoin="round" />
      </svg>
      <div style={{ fontSize: 10, color: 'var(--text-3)', textAlign: 'center', marginTop: 2 }}>
        Trajectory ·{' '}
        <span style={{ color: trajColor, fontWeight: 600 }}>
          {trajectory > 0 ? '+' : ''}{trajectory.toFixed(1)}
        </span>
      </div>
    </>
  )
}

function Hero({ player, ratings, history }) {
  const flag = flagEmoji(player.country_code)
  const age = ageFromBirthday(player.birthday)
  const hand = handLabel(player.hand)
  const rtt = ratings.rtt_score != null ? Math.round(ratings.rtt_score) : null
  const tier = rttTier(rtt)

  // Best surface from the four surface ratings
  const surfaces = [
    { name: 'Hard',   v: ratings.hard_rating },
    { name: 'Clay',   v: ratings.clay_rating },
    { name: 'Grass',  v: ratings.grass_rating },
    { name: 'Indoor', v: ratings.indoor_rating },
  ].filter(s => s.v != null)
  surfaces.sort((a, b) => b.v - a.v)
  const bestSurface = surfaces[0]

  return (
    <div style={{
      background: 'var(--bg-card)',
      border: '1px solid var(--border)',
      borderRadius: 'var(--r-lg)',
      padding: '22px 26px',
      marginBottom: 18,
    }}>
      <div style={{ display: 'flex', gap: 24, alignItems: 'flex-start', flexWrap: 'wrap' }}>
        {/* Identity column */}
        <div style={{ flex: 1, minWidth: 280 }}>
          <div style={{
            fontSize: 28, fontWeight: 800, letterSpacing: '-0.5px', lineHeight: 1.1,
            color: 'var(--text)',
          }}>
            {player.full_name || player.name}
          </div>
          <div style={{
            fontSize: 12, color: 'var(--text-3)', marginTop: 6,
            display: 'flex', gap: 6, flexWrap: 'wrap', alignItems: 'center',
          }}>
            {flag && <span style={{ fontSize: 14 }}>{flag}</span>}
            {player.country && <span>{player.country}</span>}
            {age && <><span>·</span><span>{age} yrs</span></>}
            {hand && <><span>·</span><span>{hand}</span></>}
            {player.height_cm && <><span>·</span><span>{player.height_cm} cm</span></>}
            {player.turned_pro && <><span>·</span><span>Pro since {player.turned_pro}</span></>}
          </div>
          <div style={{
            display: 'flex', gap: 6, flexWrap: 'wrap', marginTop: 10,
          }}>
            {bestSurface && (
              <span style={{
                background: 'var(--bg-raised)', color: 'var(--text-2)',
                padding: '3px 10px', borderRadius: 99,
                fontSize: 11, fontWeight: 600,
              }}>
                Best surface · {bestSurface.name}
              </span>
            )}
            {ratings.momentum && ratings.momentum !== 'stable' && (
              <span style={{
                background: ratings.momentum === 'rising' ? 'var(--green-bg)' : '#fecaca',
                color: ratings.momentum === 'rising' ? 'var(--green-text)' : '#991b1b',
                padding: '3px 10px', borderRadius: 99,
                fontSize: 11, fontWeight: 700,
              }}>
                {ratings.momentum === 'rising' ? '↑ Rising' : '↓ Falling'}
              </span>
            )}
            {player.is_active === false && (
              <span style={{
                background: 'var(--bg-raised)', color: 'var(--text-3)',
                padding: '3px 10px', borderRadius: 99,
                fontSize: 11, fontWeight: 600,
              }}>
                Inactive
              </span>
            )}
          </div>
        </div>

        {/* RTT score column */}
        <div style={{ textAlign: 'center', flexShrink: 0, minWidth: 130 }}>
          <div style={{
            fontSize: 56, fontWeight: 900, lineHeight: 1,
            color: 'var(--green)',
            fontVariantNumeric: 'tabular-nums',
            letterSpacing: '-1px',
          }}>
            {rtt ?? '—'}
          </div>
          <div style={{
            fontSize: 10, textTransform: 'uppercase', letterSpacing: '0.8px',
            color: 'var(--text-3)', marginTop: 4, fontWeight: 700,
          }}>
            RTT Score
          </div>
          {tier && (
            <div style={{
              display: 'inline-block', marginTop: 6,
              fontSize: 10, textTransform: 'uppercase', letterSpacing: '0.5px',
              padding: '3px 10px', borderRadius: 99, fontWeight: 700,
              background: 'var(--green-bg)', color: 'var(--green-text)',
            }}>
              {tier.label}
            </div>
          )}
          <HeroSparkline history={history} />
        </div>
      </div>
    </div>
  )
}

// ─────────────────────────────────────────────────────────────────────────────
// Tabs
// ─────────────────────────────────────────────────────────────────────────────

function TabBar({ tabs, active, onChange }) {
  return (
    <div style={{
      display: 'flex',
      borderBottom: '1px solid var(--border)',
      marginBottom: 18,
      gap: 0,
    }}>
      {tabs.map(t => (
        <button
          key={t}
          onClick={() => onChange(t)}
          style={{
            background: 'none',
            border: 'none',
            borderBottom: active === t ? '2px solid var(--green)' : '2px solid transparent',
            color: active === t ? 'var(--text)' : 'var(--text-3)',
            fontSize: 13,
            fontWeight: active === t ? 700 : 500,
            padding: '10px 16px',
            cursor: 'pointer',
            transition: 'color 0.15s, border-color 0.15s',
            fontFamily: 'inherit',
          }}
        >
          {t}
        </button>
      ))}
    </div>
  )
}

// ─────────────────────────────────────────────────────────────────────────────
// Overview tab pieces
// ─────────────────────────────────────────────────────────────────────────────

function buildNarrative(player, ratings, surfaceStats, recent) {
  const bits = []
  const name = (player.full_name || player.name || 'This player').split(' ').slice(-1)[0]
  const rtt = ratings.rtt_score
  const surfaces = [
    { k: 'hard', name: 'hard', v: ratings.hard_rating },
    { k: 'clay', name: 'clay', v: ratings.clay_rating },
    { k: 'grass', name: 'grass', v: ratings.grass_rating },
    { k: 'indoor', name: 'indoor', v: ratings.indoor_rating },
  ].filter(s => s.v != null)
  surfaces.sort((a, b) => b.v - a.v)

  if (rtt != null) {
    if (rtt >= 90)      bits.push(`${name} sits in the top tier of the RTT model with a score of ${Math.round(rtt)}.`)
    else if (rtt >= 80) bits.push(`${name} grades out as a top-tier player at RTT ${Math.round(rtt)}.`)
    else if (rtt >= 70) bits.push(`${name} is a strong tour-level player with an RTT of ${Math.round(rtt)}.`)
    else if (rtt >= 60) bits.push(`${name} sits in the solid mid-tier with an RTT of ${Math.round(rtt)}.`)
    else if (rtt >= 50) bits.push(`${name} grades out around the tour average at RTT ${Math.round(rtt)}.`)
    else                bits.push(`${name} grades below tour average at RTT ${Math.round(rtt)}.`)
  }

  if (surfaces.length >= 2 && (surfaces[0].v - surfaces[surfaces.length - 1].v) >= 8) {
    bits.push(`Best on ${surfaces[0].name} (${Math.round(surfaces[0].v)}), weakest on ${surfaces[surfaces.length - 1].name} (${Math.round(surfaces[surfaces.length - 1].v)}).`)
  } else if (surfaces.length >= 2) {
    bits.push(`Surface profile is balanced — within a few points across all four.`)
  }

  if (ratings.momentum === 'rising')        bits.push(`Momentum is rising over the last few weeks.`)
  else if (ratings.momentum === 'falling')  bits.push(`Momentum is falling — recent results have dragged the rating down.`)

  if (recent && recent.wins != null && recent.losses != null) {
    const total = recent.wins + recent.losses
    if (total > 0) {
      const pct = Math.round((recent.wins / total) * 100)
      bits.push(`Last 10: ${recent.wins}–${recent.losses} (${pct}%).`)
    }
  }

  return bits.join(' ')
}

function GlanceCard({ title, children }) {
  return (
    <div style={{
      background: 'var(--bg-card)',
      border: '1px solid var(--border)',
      borderRadius: 'var(--r)',
      padding: '14px 16px',
    }}>
      <div style={{
        fontSize: 10, fontWeight: 700, textTransform: 'uppercase',
        letterSpacing: '0.6px', color: 'var(--text-3)', marginBottom: 12,
      }}>
        {title}
      </div>
      {children}
    </div>
  )
}

function FormDotsBig({ str }) {
  if (!str) return <div style={{ color: 'var(--text-3)', fontSize: 12 }}>No recent matches</div>
  const dots = String(str).replace(/\s+/g, '').split('').slice(0, 10)
  return (
    <div style={{ display: 'flex', gap: 4, flexWrap: 'wrap' }}>
      {dots.map((d, i) => (
        <span key={i} style={{
          width: 18, height: 18, borderRadius: '50%',
          display: 'inline-flex', alignItems: 'center', justifyContent: 'center',
          fontSize: 10, fontWeight: 800,
          background: d === 'W' ? 'var(--green-bg)' : '#fecaca',
          color: d === 'W' ? 'var(--green-text)' : '#991b1b',
        }}>{d}</span>
      ))}
    </div>
  )
}

function SurfaceBars({ surfaceStats }) {
  // surfaceStats can come from /stats endpoint as live_surface_stats array
  if (!surfaceStats || surfaceStats.length === 0) {
    return <div style={{ color: 'var(--text-3)', fontSize: 12 }}>No surface data yet</div>
  }
  const colors = {
    'Hard':   'var(--hard)',
    'Clay':   'var(--clay)',
    'Grass':  'var(--grass)',
    'Indoor Hard': 'var(--indoor)',
    'Indoor': 'var(--indoor)',
    'Carpet': 'var(--indoor)',
  }
  const items = surfaceStats
    .map(s => {
      const w = Number(s.wins) || 0
      const l = Number(s.losses) || 0
      const total = w + l
      return { name: s.surface, w, l, total, pct: total ? (w / total) * 100 : 0 }
    })
    .filter(s => s.total > 0)
    .sort((a, b) => b.total - a.total)
  if (items.length === 0) {
    return <div style={{ color: 'var(--text-3)', fontSize: 12 }}>No surface data yet</div>
  }
  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
      {items.map(s => (
        <div key={s.name} style={{
          display: 'grid',
          gridTemplateColumns: '46px 1fr 76px',
          gap: 8, alignItems: 'center', fontSize: 12,
        }}>
          <span style={{ color: 'var(--text-2)', fontWeight: 600 }}>{s.name}</span>
          <span style={{
            height: 8, background: 'var(--bg-raised)', borderRadius: 4, overflow: 'hidden',
          }}>
            <span style={{
              display: 'block', height: '100%', width: `${Math.round(s.pct)}%`,
              background: colors[s.name] || 'var(--text-3)', borderRadius: 4,
            }} />
          </span>
          <span style={{
            textAlign: 'right', fontFamily: 'var(--font-mono)',
            color: 'var(--text-3)', fontVariantNumeric: 'tabular-nums',
          }}>
            <b style={{ color: 'var(--text-2)', fontWeight: 700 }}>{s.w}-{s.l}</b>
            {' · '}{Math.round(s.pct)}%
          </span>
        </div>
      ))}
    </div>
  )
}

function PressureGrid({ ratings }) {
  const items = [
    { v: ratings.pressure_rating, l: 'Pressure' },
    { v: ratings.big_match_rating, l: 'Big match' },
    { v: ratings.vs_top10_rating, l: 'vs Top 10' },
  ]
  return (
    <div style={{
      display: 'grid', gridTemplateColumns: '1fr 1fr 1fr', gap: 8,
    }}>
      {items.map(({ v, l }) => (
        <div key={l} style={{ textAlign: 'center' }}>
          <div style={{
            fontSize: 22, fontWeight: 800,
            color: v != null ? 'var(--text)' : 'var(--text-3)',
            fontVariantNumeric: 'tabular-nums', lineHeight: 1,
          }}>
            {v != null ? Math.round(v) : '—'}
          </div>
          <div style={{
            fontSize: 10, color: 'var(--text-3)', marginTop: 4,
            textTransform: 'uppercase', letterSpacing: '0.4px',
          }}>
            {l}
          </div>
        </div>
      ))}
    </div>
  )
}

function SkillBar({ name, value }) {
  const v = value != null ? Math.round(value) : null
  const w = v != null ? Math.max(0, Math.min(100, v)) : 0
  const pct = pctFromScore(v)
  const tone = v == null ? '#a8a29e'
             : v >= 80 ? '#166534'
             : v >= 65 ? '#3a5c14'
             : v >= 50 ? '#92400e'
             : '#991b1b'
  return (
    <div style={{
      display: 'grid',
      gridTemplateColumns: '110px 1fr 60px 70px',
      gap: 14, alignItems: 'center',
      padding: '8px 0',
      borderBottom: '1px solid var(--border-faint)',
      fontSize: 13,
    }}>
      <div style={{ color: 'var(--text-2)', fontWeight: 600 }}>{name}</div>
      <div style={{
        height: 8, background: 'var(--bg-raised)', borderRadius: 4, overflow: 'hidden',
      }}>
        <div style={{
          height: '100%', width: `${w}%`, borderRadius: 4,
          background: 'linear-gradient(90deg, var(--green) 0%, #047857 100%)',
        }} />
      </div>
      <div style={{
        fontFamily: 'var(--font-mono)', fontWeight: 700,
        textAlign: 'right', color: tone, fontVariantNumeric: 'tabular-nums',
      }}>
        {v ?? '—'}
      </div>
      <div style={{
        fontSize: 11, fontWeight: 700, textAlign: 'right',
        color: pct ? 'var(--green-text)' : 'var(--text-3)',
      }}>
        {pct || '—'}
      </div>
    </div>
  )
}

function OverviewTab({ player, ratings, recent, history, surfaceStats }) {
  const narrative = buildNarrative(player, ratings, surfaceStats, recent)
  const surfaceFromStats = surfaceStats?.live_surface_stats || []
  return (
    <>
      {narrative && (
        <div style={{
          background: 'var(--bg-card)',
          borderLeft: '3px solid var(--green)',
          padding: '14px 18px',
          borderRadius: 'var(--r-sm)',
          fontSize: 13, lineHeight: 1.6, color: 'var(--text-2)',
          marginBottom: 16,
          border: '1px solid var(--border)',
          borderLeftWidth: 3,
        }}>
          {narrative}
        </div>
      )}

      <div style={{
        display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(220px, 1fr))',
        gap: 12, marginBottom: 18,
      }}>
        <GlanceCard title="Form · Last 10">
          <FormDotsBig str={recent?.last_10} />
          <div style={{ fontSize: 12, color: 'var(--text-3)', marginTop: 10 }}>
            <b style={{ color: 'var(--text-2)' }}>{recent?.wins ?? 0}W — {recent?.losses ?? 0}L</b>
            {ratings.form_score != null && (
              <> · perf <b style={{ color: 'var(--text-2)' }}>{Math.round(ratings.form_score)}</b></>
            )}
          </div>
        </GlanceCard>

        <GlanceCard title="Surface record · 24m">
          <SurfaceBars surfaceStats={surfaceFromStats} />
        </GlanceCard>

        <GlanceCard title="Pressure metrics">
          <PressureGrid ratings={ratings} />
        </GlanceCard>
      </div>

      <div style={{
        background: 'var(--bg-card)',
        border: '1px solid var(--border)',
        borderRadius: 'var(--r)',
        padding: '14px 18px',
        marginBottom: 14,
      }}>
        <div style={{
          fontSize: 11, fontWeight: 700, textTransform: 'uppercase',
          letterSpacing: '0.6px', color: 'var(--text-3)', marginBottom: 4,
        }}>
          Skill ratings
        </div>
        <SkillBar name="Serve"        value={ratings.serve_rating} />
        <SkillBar name="Return"       value={ratings.return_rating} />
        <SkillBar name="Pressure"     value={ratings.pressure_rating} />
        <SkillBar name="Consistency"  value={ratings.consistency_rating} />
        <SkillBar name="Big match"    value={ratings.big_match_rating} />
        <SkillBar name="vs Top 10"    value={ratings.vs_top10_rating} />
      </div>
    </>
  )
}

// ─────────────────────────────────────────────────────────────────────────────
// Form tab — performance index chart + recent matches list
// ─────────────────────────────────────────────────────────────────────────────

function FormTab({ player, formData }) {
  const matches = formData?.matches || []

  return (
    <>
      <div style={{
        background: 'var(--bg-card)',
        border: '1px solid var(--border)',
        borderRadius: 'var(--r)',
        padding: '16px 18px',
        marginBottom: 14,
      }}>
        <div style={{
          fontSize: 11, fontWeight: 700, textTransform: 'uppercase',
          letterSpacing: '0.6px', color: 'var(--text-3)', marginBottom: 10,
        }}>
          Performance index — last {matches.length} matches
        </div>
        <FormChart
          p1Form={formData}
          p1Name={player.name}
        />
        <div style={{ fontSize: 11, color: 'var(--text-3)', marginTop: 8 }}>
          Each point reflects opponent quality and score gap, not just W/L.
          Wins over top players score higher; close losses to elites score better than
          heavy losses to lower-ranked players.
        </div>
      </div>

      <div style={{
        background: 'var(--bg-card)',
        border: '1px solid var(--border)',
        borderRadius: 'var(--r)',
        padding: '6px 0',
      }}>
        <div style={{
          fontSize: 11, fontWeight: 700, textTransform: 'uppercase',
          letterSpacing: '0.6px', color: 'var(--text-3)',
          padding: '10px 16px',
        }}>
          Recent matches
        </div>
        {matches.length === 0 && (
          <div style={{ padding: '0 16px 16px', color: 'var(--text-3)', fontSize: 13 }}>
            No recent match data.
          </div>
        )}
        {matches.map((m, i) => {
          const won = m.won === true || m.won === 't' || m.won === 'true'
          return (
            <div key={i} style={{
              display: 'grid',
              gridTemplateColumns: '24px 1fr auto auto',
              gap: 12, alignItems: 'center',
              padding: '8px 16px',
              borderTop: i ? '1px solid var(--border-faint)' : 'none',
              fontSize: 13,
            }}>
              <span style={{
                width: 20, height: 20, borderRadius: '50%',
                display: 'inline-flex', alignItems: 'center', justifyContent: 'center',
                fontSize: 10, fontWeight: 800,
                background: won ? 'var(--green-bg)' : '#fecaca',
                color: won ? 'var(--green-text)' : '#991b1b',
              }}>
                {won ? 'W' : 'L'}
              </span>
              <div style={{ minWidth: 0, overflow: 'hidden' }}>
                <div style={{ fontWeight: 600, color: 'var(--text)', whiteSpace: 'nowrap', textOverflow: 'ellipsis', overflow: 'hidden' }}>
                  vs {m.opponent_name || '—'}
                  {m.opponent_rank && (
                    <span style={{ color: 'var(--text-3)', fontSize: 11, marginLeft: 4 }}>
                      #{m.opponent_rank}
                    </span>
                  )}
                </div>
                <div style={{ color: 'var(--text-3)', fontSize: 11, marginTop: 1 }}>
                  {m.tournament || '—'}
                  {m.date && <> · {String(m.date).slice(0, 10)}</>}
                </div>
              </div>
              {m.surface && <SurfaceBadge surface={m.surface} />}
              {m.performance_index != null && (
                <div style={{
                  fontFamily: 'var(--font-mono)',
                  fontWeight: 700, fontSize: 12,
                  color: m.performance_index >= 60 ? 'var(--green-text)'
                       : m.performance_index >= 40 ? 'var(--text-2)'
                       : 'var(--text-3)',
                  fontVariantNumeric: 'tabular-nums', minWidth: 28, textAlign: 'right',
                }}>
                  {Math.round(m.performance_index)}
                </div>
              )}
            </div>
          )
        })}
      </div>
    </>
  )
}

// ─────────────────────────────────────────────────────────────────────────────
// Match History tab
// ─────────────────────────────────────────────────────────────────────────────

const HIST_LIMIT = 25

function MatchHistoryTab({ playerId }) {
  const [surface, setSurface] = useState('all')
  const [offset, setOffset] = useState(0)
  const [data, setData] = useState(null)
  const [loading, setLoading] = useState(false)

  useEffect(() => {
    let on = true
    setLoading(true)
    api.playerMatches(playerId, { surface, limit: HIST_LIMIT, offset })
       .then(d => { if (on) setData(d) })
       .finally(() => { if (on) setLoading(false) })
    return () => { on = false }
  }, [playerId, surface, offset])

  const matches = data?.matches || []
  const total = data?.total || 0
  const filters = ['all', 'clay', 'hard', 'grass', 'indoor']

  return (
    <>
      <div style={{ display: 'flex', gap: 6, flexWrap: 'wrap', marginBottom: 14 }}>
        {filters.map(f => (
          <button
            key={f}
            onClick={() => { setSurface(f); setOffset(0) }}
            style={{
              padding: '4px 12px',
              fontSize: 12,
              borderRadius: 99,
              border: '1px solid var(--border)',
              background: surface === f ? 'var(--green-bg)' : 'var(--bg-card)',
              color: surface === f ? 'var(--green-text)' : 'var(--text-2)',
              fontWeight: surface === f ? 700 : 500,
              cursor: 'pointer',
              fontFamily: 'inherit',
            }}
          >
            {f === 'all' ? 'All' : f.charAt(0).toUpperCase() + f.slice(1)}
          </button>
        ))}
      </div>

      <div style={{
        background: 'var(--bg-card)',
        border: '1px solid var(--border)',
        borderRadius: 'var(--r)',
        overflow: 'hidden',
      }}>
        {loading && matches.length === 0 && (
          <div style={{ padding: 20, color: 'var(--text-3)', fontSize: 13, textAlign: 'center' }}>
            Loading…
          </div>
        )}
        {matches.length === 0 && !loading && (
          <div style={{ padding: 20, color: 'var(--text-3)', fontSize: 13, textAlign: 'center' }}>
            No matches found for this filter.
          </div>
        )}
        {matches.map((m, i) => {
          const won = m.won === true || m.won === 't' || m.won === 'true'
          return (
            <div key={i} style={{
              display: 'grid',
              gridTemplateColumns: '24px 1fr auto auto auto',
              gap: 12, alignItems: 'center',
              padding: '10px 16px',
              borderTop: i ? '1px solid var(--border-faint)' : 'none',
              fontSize: 13,
            }}>
              <span style={{
                width: 20, height: 20, borderRadius: '50%',
                display: 'inline-flex', alignItems: 'center', justifyContent: 'center',
                fontSize: 10, fontWeight: 800,
                background: won ? 'var(--green-bg)' : '#fecaca',
                color: won ? 'var(--green-text)' : '#991b1b',
              }}>
                {won ? 'W' : 'L'}
              </span>
              <div style={{ minWidth: 0, overflow: 'hidden' }}>
                <div style={{
                  fontWeight: 600, color: 'var(--text)',
                  whiteSpace: 'nowrap', textOverflow: 'ellipsis', overflow: 'hidden',
                }}>
                  vs {m.opponent_name || '—'}
                  {m.opponent_rank && (
                    <span style={{ color: 'var(--text-3)', fontSize: 11, marginLeft: 4 }}>
                      #{m.opponent_rank}
                    </span>
                  )}
                </div>
                <div style={{ color: 'var(--text-3)', fontSize: 11, marginTop: 1 }}>
                  {m.tournament || '—'}
                </div>
              </div>
              {m.surface && <SurfaceBadge surface={m.surface} />}
              {m.score && (
                <div style={{
                  fontFamily: 'var(--font-mono)', fontSize: 11,
                  color: 'var(--text-3)', whiteSpace: 'nowrap',
                  fontVariantNumeric: 'tabular-nums',
                }}>
                  {m.score}
                </div>
              )}
              <div style={{ fontSize: 11, color: 'var(--text-3)', whiteSpace: 'nowrap' }}>
                {m.date && String(m.date).slice(0, 10)}
              </div>
            </div>
          )
        })}
      </div>

      {total > HIST_LIMIT && (
        <div style={{ display: 'flex', gap: 8, justifyContent: 'center', marginTop: 14 }}>
          <button
            disabled={offset === 0}
            onClick={() => setOffset(Math.max(0, offset - HIST_LIMIT))}
            style={{
              padding: '6px 12px', borderRadius: 6, fontSize: 12,
              border: '1px solid var(--border)', background: 'var(--bg-card)',
              color: offset === 0 ? 'var(--text-3)' : 'var(--text-2)',
              cursor: offset === 0 ? 'default' : 'pointer',
              fontFamily: 'inherit',
            }}
          >
            ← Newer
          </button>
          <span style={{ alignSelf: 'center', fontSize: 12, color: 'var(--text-3)' }}>
            {offset + 1}–{Math.min(total, offset + HIST_LIMIT)} of {total}
          </span>
          <button
            disabled={offset + HIST_LIMIT >= total}
            onClick={() => setOffset(offset + HIST_LIMIT)}
            style={{
              padding: '6px 12px', borderRadius: 6, fontSize: 12,
              border: '1px solid var(--border)', background: 'var(--bg-card)',
              color: offset + HIST_LIMIT >= total ? 'var(--text-3)' : 'var(--text-2)',
              cursor: offset + HIST_LIMIT >= total ? 'default' : 'pointer',
              fontFamily: 'inherit',
            }}
          >
            Older →
          </button>
        </div>
      )}
    </>
  )
}

// ─────────────────────────────────────────────────────────────────────────────
// Stats tab — career averages + surface stats + rankings history
// ─────────────────────────────────────────────────────────────────────────────

function StatRow({ label, value, suffix = '' }) {
  return (
    <div style={{
      display: 'grid', gridTemplateColumns: '1fr auto',
      padding: '7px 0', borderBottom: '1px dashed var(--border-faint)',
      fontSize: 13,
    }}>
      <span style={{ color: 'var(--text-2)' }}>{label}</span>
      <span style={{
        fontFamily: 'var(--font-mono)', fontWeight: 700, color: 'var(--text)',
        fontVariantNumeric: 'tabular-nums',
      }}>
        {value != null ? `${value}${suffix}` : '—'}
      </span>
    </div>
  )
}

function StatsTab({ stats }) {
  if (!stats) {
    return <div style={{ padding: 20, color: 'var(--text-3)', fontSize: 13, textAlign: 'center' }}>Loading career stats…</div>
  }
  const serve = stats.career_serve_averages || {}
  const sample = serve.sample_size
  const surfaces = stats.surface_stats || []
  const rankings = stats.rankings_history || []

  return (
    <div style={{
      display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(280px, 1fr))', gap: 14,
    }}>
      <div style={{
        background: 'var(--bg-card)', border: '1px solid var(--border)',
        borderRadius: 'var(--r)', padding: '14px 18px',
      }}>
        <div style={{
          fontSize: 11, fontWeight: 700, textTransform: 'uppercase',
          letterSpacing: '0.6px', color: 'var(--text-3)', marginBottom: 4,
        }}>
          Career serve averages
          {sample > 0 && (
            <span style={{
              fontWeight: 500, textTransform: 'none', letterSpacing: 0,
              color: 'var(--text-3)', marginLeft: 6,
            }}>
              · over {sample} matches
            </span>
          )}
        </div>
        <StatRow label="Ace rate"            value={serve.avg_ace_pct} suffix="%" />
        <StatRow label="Double fault rate"   value={serve.avg_df_pct} suffix="%" />
        <StatRow label="1st serve in"        value={serve.avg_1st_serve_pct} suffix="%" />
        <StatRow label="1st serve points won" value={serve.avg_1st_won_pct} suffix="%" />
        <StatRow label="2nd serve points won" value={serve.avg_2nd_won_pct} suffix="%" />
        <StatRow label="Break points saved"  value={serve.avg_bp_save_pct} suffix="%" />
      </div>

      <div style={{
        background: 'var(--bg-card)', border: '1px solid var(--border)',
        borderRadius: 'var(--r)', padding: '14px 18px',
      }}>
        <div style={{
          fontSize: 11, fontWeight: 700, textTransform: 'uppercase',
          letterSpacing: '0.6px', color: 'var(--text-3)', marginBottom: 8,
        }}>
          Career W/L by surface
        </div>
        {surfaces.length === 0 && (
          <div style={{ color: 'var(--text-3)', fontSize: 12 }}>No surface history recorded.</div>
        )}
        {surfaces.map(s => {
          const w = Number(s.wins) || 0
          const l = Number(s.losses) || 0
          const tot = w + l
          const pct = tot ? Math.round((w / tot) * 100) : 0
          return (
            <div key={s.surface} style={{
              display: 'grid',
              gridTemplateColumns: '70px 1fr 110px',
              gap: 10, alignItems: 'center',
              padding: '6px 0', borderBottom: '1px dashed var(--border-faint)',
              fontSize: 12,
            }}>
              <span style={{ color: 'var(--text-2)', fontWeight: 600 }}>{s.surface}</span>
              <span style={{
                height: 6, background: 'var(--bg-raised)', borderRadius: 3, overflow: 'hidden',
              }}>
                <span style={{
                  display: 'block', height: '100%', width: `${pct}%`, borderRadius: 3,
                  background: 'var(--green)',
                }} />
              </span>
              <span style={{
                textAlign: 'right', fontFamily: 'var(--font-mono)',
                color: 'var(--text-3)', fontVariantNumeric: 'tabular-nums',
              }}>
                <b style={{ color: 'var(--text-2)' }}>{w}-{l}</b> · {pct}%
              </span>
            </div>
          )
        })}
      </div>

      {rankings.length > 0 && (
        <div style={{
          background: 'var(--bg-card)', border: '1px solid var(--border)',
          borderRadius: 'var(--r)', padding: '14px 18px',
          gridColumn: '1 / -1',
        }}>
          <div style={{
            fontSize: 11, fontWeight: 700, textTransform: 'uppercase',
            letterSpacing: '0.6px', color: 'var(--text-3)', marginBottom: 10,
          }}>
            Year-by-year best ranking
          </div>
          <div style={{
            display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(80px, 1fr))', gap: 8,
          }}>
            {rankings.filter(r => r.best_rank != null).map(r => (
              <div key={r.season} style={{
                background: 'var(--bg-raised)', padding: '8px 10px',
                borderRadius: 6, textAlign: 'center',
              }}>
                <div style={{
                  fontSize: 16, fontWeight: 800, color: 'var(--text)',
                  fontVariantNumeric: 'tabular-nums',
                }}>
                  #{r.best_rank}
                </div>
                <div style={{ fontSize: 10, color: 'var(--text-3)', marginTop: 2 }}>
                  {r.season}
                </div>
              </div>
            ))}
          </div>
        </div>
      )}
    </div>
  )
}

// ─────────────────────────────────────────────────────────────────────────────
// Page
// ─────────────────────────────────────────────────────────────────────────────

export default function PlayerPage() {
  const { id } = useParams()
  const [data, setData] = useState(null)
  const [formData, setFormData] = useState(null)
  const [stats, setStats] = useState(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState(null)
  const [tab, setTab] = useState('Overview')

  useEffect(() => {
    let on = true
    setLoading(true); setError(null)
    Promise.all([
      api.player(id),
      api.playerForm(id, 'all', 30),
      api.playerStats(id),
    ])
    .then(([p, f, s]) => {
      if (!on) return
      setData(p); setFormData(f); setStats(s)
      setLoading(false)
    })
    .catch(e => {
      if (!on) return
      setError(e.message)
      setLoading(false)
    })
    return () => { on = false }
  }, [id])

  if (loading) {
    return (
      <div className="page">
        <div style={{ color: 'var(--text-3)', fontSize: 14, padding: 40, textAlign: 'center' }}>
          Loading player…
        </div>
      </div>
    )
  }
  if (error) {
    return (
      <div className="page">
        <div style={{
          background: 'var(--bg-card)', border: '1px solid var(--border)',
          borderRadius: 'var(--r)', padding: 24, color: 'var(--red)',
        }}>
          Couldn't load this player: {error}
        </div>
      </div>
    )
  }
  if (!data) return null

  const player = data.player || {}
  const ratings = data.ratings || {}
  const recent = data.recent_form || {}
  const history = formData?.rating_history || []

  return (
    <div className="page">
      <div style={{ marginBottom: 14 }}>
        <Link to="/players" style={{
          color: 'var(--text-3)', fontSize: 12, fontWeight: 500,
        }}>
          ← Back to player database
        </Link>
      </div>

      <Hero player={player} ratings={ratings} history={history} />

      <TabBar
        tabs={['Overview', 'Form', 'Match history', 'Stats']}
        active={tab}
        onChange={setTab}
      />

      {tab === 'Overview' && (
        <OverviewTab
          player={player}
          ratings={ratings}
          recent={recent}
          history={history}
          surfaceStats={stats}
        />
      )}
      {tab === 'Form' && (
        <FormTab player={player} formData={formData} />
      )}
      {tab === 'Match history' && (
        <MatchHistoryTab playerId={id} />
      )}
      {tab === 'Stats' && (
        <StatsTab stats={stats} />
      )}
    </div>
  )
}
