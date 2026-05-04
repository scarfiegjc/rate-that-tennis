import { useState, useEffect, useRef } from 'react'
import { useParams, Link } from 'react-router-dom'
import {
  Chart as ChartJS,
  RadialLinearScale,
  CategoryScale,
  LinearScale,
  BarElement,
  PointElement,
  LineElement,
  Filler,
  Tooltip,
  Legend,
} from 'chart.js'
import { Radar, Bar } from 'react-chartjs-2'
import { api } from '../api.js'
import FormDots from '../components/FormDots.jsx'
import SurfaceBadge from '../components/SurfaceBadge.jsx'

ChartJS.register(
  RadialLinearScale, CategoryScale, LinearScale, BarElement,
  PointElement, LineElement, Filler, Tooltip, Legend
)

// ─── Colour helpers ───────────────────────────────────────────────────────────

function rttColor(v) {
  if (v == null) return '#484f58'
  if (v >= 82)   return '#00cc7a'
  if (v >= 65)   return '#d29922'
  return '#8b949e'
}

function rttBg(v) {
  if (v == null) return '#21262d'
  if (v >= 82)   return 'rgba(0,204,122,0.12)'
  if (v >= 65)   return 'rgba(210,153,34,0.12)'
  return 'rgba(72,79,88,0.15)'
}

// ─── Sub-components ───────────────────────────────────────────────────────────

function RatingPill({ label, value }) {
  const v = value != null ? Math.round(value) : null
  return (
    <div style={{
      background: rttBg(v),
      borderRadius: 8,
      padding: '10px 12px',
      display: 'flex',
      flexDirection: 'column',
      gap: 2,
    }}>
      <div style={{ fontSize: 22, fontWeight: 800, color: rttColor(v) }}>{v ?? '—'}</div>
      <div style={{ fontSize: 10, color: '#8b949e', textTransform: 'uppercase', letterSpacing: '0.6px' }}>{label}</div>
    </div>
  )
}

function MomentumBadge({ momentum }) {
  const symbols = { rising: '↑ Rising', stable: '→ Stable', falling: '↓ Falling' }
  const colors  = { rising: 'var(--accent-green)', stable: 'var(--text-secondary)', falling: 'var(--accent-red)' }
  const bg      = { rising: 'rgba(0,204,122,0.1)', stable: 'rgba(139,148,158,0.1)', falling: 'rgba(248,81,73,0.1)' }
  return (
    <span style={{
      color: colors[momentum] || 'var(--text-secondary)',
      background: bg[momentum] || 'transparent',
      fontWeight: 600, fontSize: 12,
      padding: '3px 8px', borderRadius: 6,
      border: `1px solid ${colors[momentum] || 'var(--border-subtle)'}33`,
    }}>
      {symbols[momentum] || '→ Stable'}
    </span>
  )
}

function StatBox({ label, value, unit = '' }) {
  return (
    <div style={{ background: '#161b22', borderRadius: 8, padding: '12px 14px' }}>
      <div style={{ fontSize: 20, fontWeight: 700, color: '#e6edf3' }}>
        {value != null ? `${value}${unit}` : '—'}
      </div>
      <div style={{ fontSize: 11, color: '#8b949e', marginTop: 2 }}>{label}</div>
    </div>
  )
}

function TabButton({ active, onClick, children }) {
  return (
    <button
      onClick={onClick}
      style={{
        background: 'none',
        border: 'none',
        borderBottom: active ? '2px solid var(--accent-green)' : '2px solid transparent',
        color: active ? '#e6edf3' : '#8b949e',
        fontWeight: active ? 600 : 400,
        fontSize: 13,
        cursor: 'pointer',
        padding: '8px 14px',
        transition: 'color 0.15s',
      }}
    >
      {children}
    </button>
  )
}

// ─── Player Radar (single player) ────────────────────────────────────────────

function PlayerRadar({ ratings, name }) {
  if (!ratings) return null
  const labels = ['Serve', 'Return', 'Pressure', 'Consistency', 'Big match', 'vs Top10']
  const values = [
    ratings.serve_rating        || 0,
    ratings.return_rating       || 0,
    ratings.pressure_rating     || 0,
    ratings.consistency_rating  || 0,
    ratings.big_match_rating    || 0,
    ratings.vs_top10_rating     || 0,
  ]
  if (values.every(v => v === 0)) return null

  const data = {
    labels,
    datasets: [{
      label: name || 'Player',
      data: values,
      backgroundColor: 'rgba(0,204,122,0.12)',
      borderColor: 'rgba(0,204,122,0.8)',
      borderWidth: 2,
      pointBackgroundColor: 'rgba(0,204,122,0.8)',
      pointRadius: 3,
    }],
  }
  const options = {
    responsive: true,
    maintainAspectRatio: true,
    scales: {
      r: {
        min: 0, max: 100,
        ticks: { stepSize: 25, color: '#484f58', font: { size: 9 }, backdropColor: 'transparent' },
        grid: { color: '#21262d' },
        angleLines: { color: '#21262d' },
        pointLabels: { color: '#8b949e', font: { size: 11 } },
      },
    },
    plugins: {
      legend: { display: false },
      tooltip: {
        backgroundColor: '#161b22', borderColor: '#30363d', borderWidth: 1,
        titleColor: '#e6edf3', bodyColor: '#8b949e',
      },
    },
  }
  return (
    <div style={{ maxWidth: 320, margin: '0 auto' }}>
      <Radar data={data} options={options} />
    </div>
  )
}

// ─── Surface Bar Chart ────────────────────────────────────────────────────────

function SurfaceWinLossChart({ surfaceStats }) {
  if (!surfaceStats || surfaceStats.length === 0) return null

  const surfaces = surfaceStats.map(s => s.surface || 'Unknown')
  const wins   = surfaceStats.map(s => Number(s.wins)   || 0)
  const losses = surfaceStats.map(s => Number(s.losses) || 0)

  const data = {
    labels: surfaces,
    datasets: [
      {
        label: 'Wins',
        data: wins,
        backgroundColor: 'rgba(0,204,122,0.7)',
        borderRadius: 4,
      },
      {
        label: 'Losses',
        data: losses,
        backgroundColor: 'rgba(248,81,73,0.5)',
        borderRadius: 4,
      },
    ],
  }
  const options = {
    responsive: true,
    maintainAspectRatio: false,
    plugins: {
      legend: {
        position: 'bottom',
        labels: { color: '#8b949e', font: { size: 11 }, boxWidth: 12, padding: 12 },
      },
      tooltip: {
        backgroundColor: '#161b22', borderColor: '#30363d', borderWidth: 1,
        titleColor: '#e6edf3', bodyColor: '#8b949e',
      },
    },
    scales: {
      x: { grid: { color: '#21262d' }, ticks: { color: '#8b949e', font: { size: 11 } } },
      y: { grid: { color: '#21262d' }, ticks: { color: '#8b949e', font: { size: 11 } } },
    },
  }

  return (
    <div style={{ height: 220 }}>
      <Bar data={data} options={options} />
    </div>
  )
}

// ─── Match row ────────────────────────────────────────────────────────────────

function MatchRow({ m, isLast }) {
  const won = m.result === 'W'
  return (
    <div style={{
      display: 'grid',
      gridTemplateColumns: '28px 1fr auto auto auto',
      alignItems: 'center',
      gap: 10,
      padding: '8px 0',
      borderBottom: isLast ? 'none' : '1px solid var(--border-subtle)',
      fontSize: 13,
    }}>
      {/* W/L dot */}
      <div style={{
        width: 24, height: 24, borderRadius: '50%',
        background: won ? 'rgba(0,204,122,0.15)' : 'rgba(248,81,73,0.12)',
        border: `1px solid ${won ? 'rgba(0,204,122,0.4)' : 'rgba(248,81,73,0.35)'}`,
        color: won ? '#00cc7a' : '#f85149',
        display: 'flex', alignItems: 'center', justifyContent: 'center',
        fontWeight: 700, fontSize: 11, flexShrink: 0,
      }}>
        {m.result || '?'}
      </div>

      {/* Opponent + meta */}
      <div>
        <div style={{ fontWeight: 500 }}>
          {m.opponent_id
            ? <Link to={`/player/${m.opponent_id}`} style={{ color: '#e6edf3', textDecoration: 'none' }}>
                vs {m.opponent_name || '—'}
              </Link>
            : `vs ${m.opponent_name || '—'}`
          }
        </div>
        <div style={{ fontSize: 11, color: 'var(--text-muted)', marginTop: 1 }}>
          {[m.tournament, m.round].filter(Boolean).join(' · ')}
        </div>
      </div>

      {/* Surface */}
      <SurfaceBadge surface={m.surface} />

      {/* Score */}
      <div style={{ fontSize: 11, color: 'var(--text-muted)', fontFamily: 'var(--font-mono)', textAlign: 'right', minWidth: 70 }}>
        {m.score || ''}
      </div>

      {/* Date */}
      <div style={{ fontSize: 11, color: 'var(--text-muted)', textAlign: 'right', minWidth: 70 }}>
        {m.date ? String(m.date).slice(0, 10) : ''}
      </div>
    </div>
  )
}

// ─── Main page ────────────────────────────────────────────────────────────────

const TABS = ['Overview', 'Form', 'Match History', 'Stats']
const SURFACE_FILTERS = ['all', 'clay', 'hard', 'grass', 'indoor']

export default function PlayerPage() {
  const { id } = useParams()
  const [tab, setTab]   = useState('Overview')
  const [data, setData] = useState(null)
  const [form, setForm] = useState(null)
  const [history, setHistory] = useState(null)
  const [stats, setStats]     = useState(null)
  const [loading, setLoading] = useState(true)
  const [error, setError]     = useState(null)

  // History tab state
  const [histSurface, setHistSurface]     = useState('all')
  const [histOffset, setHistOffset]       = useState(0)
  const [histLoading, setHistLoading]     = useState(false)
  const HIST_LIMIT = 25

  // Form tab state
  const [formSurface, setFormSurface] = useState('all')
  const [formLoading, setFormLoading] = useState(false)

  // Initial load
  useEffect(() => {
    setLoading(true)
    Promise.all([
      api.player(id),
      api.playerForm(id, 'all', 20),
    ])
      .then(([p, f]) => { setData(p); setForm(f); setLoading(false) })
      .catch(e => { setError(e.message); setLoading(false) })
  }, [id])

  // Load history when tab selected or filters change
  useEffect(() => {
    if (tab !== 'Match History') return
    setHistLoading(true)
    api.playerMatches(id, { surface: histSurface, limit: HIST_LIMIT, offset: histOffset })
      .then(h => { setHistory(h); setHistLoading(false) })
      .catch(() => setHistLoading(false))
  }, [id, tab, histSurface, histOffset])

  // Load stats when tab selected
  useEffect(() => {
    if (tab !== 'Stats' || stats) return
    api.playerStats(id)
      .then(s => setStats(s))
      .catch(() => {})
  }, [id, tab])

  // Reload form on surface change
  useEffect(() => {
    if (tab !== 'Form') return
    setFormLoading(true)
    api.playerForm(id, formSurface, 30)
      .then(f => { setForm(f); setFormLoading(false) })
      .catch(() => setFormLoading(false))
  }, [id, formSurface])

  if (loading) return <div className="page"><div className="loading">Loading player…</div></div>
  if (error)   return <div className="page"><div className="error">{error}</div></div>
  if (!data)   return null

  const player  = data.player  || {}
  const ratings = data.ratings || {}
  const recent  = data.recent_form || {}
  const rttVal  = ratings.rtt_score != null ? Math.round(ratings.rtt_score) : null

  // ── Render ──────────────────────────────────────────────────────────────────
  return (
    <div className="page">
      <Link to="/" style={{ fontSize: 12, color: 'var(--text-muted)' }}>← Today's matches</Link>

      {/* ── Player header card ─────────────────────────────────────────────── */}
      <div className="card" style={{ marginTop: 16, marginBottom: 0 }}>
        <div style={{ display: 'flex', alignItems: 'flex-start', gap: 20 }}>
          {/* Left: identity */}
          <div style={{ flex: 1 }}>
            <div style={{ fontSize: 28, fontWeight: 900, lineHeight: 1.1 }}>
              {player.full_name || player.name || '—'}
            </div>

            <div style={{ fontSize: 13, color: 'var(--text-muted)', marginTop: 4 }}>
              {[
                player.country || player.country_code,
                player.hand && `${player.hand}-handed`,
                player.height_cm && `${player.height_cm} cm`,
                player.turned_pro && `Pro since ${player.turned_pro}`,
              ].filter(Boolean).join(' · ')}
            </div>

            <div style={{ display: 'flex', alignItems: 'center', gap: 10, marginTop: 10, flexWrap: 'wrap' }}>
              {ratings.momentum && <MomentumBadge momentum={ratings.momentum} />}
              {recent.wins != null && (
                <span style={{ fontSize: 12, color: 'var(--text-secondary)' }}>
                  Last 10: <strong>{recent.wins}W – {recent.losses}L</strong>
                </span>
              )}
            </div>

            {recent.last_10 && (
              <div style={{ marginTop: 8 }}>
                <FormDots dots={recent.last_10.split(' ').filter(Boolean)} />
              </div>
            )}
          </div>

          {/* Right: RTT Score */}
          {rttVal != null && (
            <div style={{ textAlign: 'center', flexShrink: 0 }}>
              <div style={{ fontSize: 56, fontWeight: 900, color: rttColor(rttVal), lineHeight: 1 }}>
                {rttVal}
              </div>
              <div style={{ fontSize: 10, color: 'var(--text-muted)', textTransform: 'uppercase', letterSpacing: '0.8px', marginTop: 2 }}>
                RTT Score
              </div>
            </div>
          )}
        </div>
      </div>

      {/* ── Tabs ────────────────────────────────────────────────────────────── */}
      <div style={{
        display: 'flex', gap: 0, borderBottom: '1px solid var(--border-subtle)',
        marginTop: 16, marginBottom: 20,
      }}>
        {TABS.map(t => (
          <TabButton key={t} active={tab === t} onClick={() => setTab(t)}>{t}</TabButton>
        ))}
      </div>

      {/* ══════════════════════════════════════════════════════════════════════
          TAB: OVERVIEW
      ══════════════════════════════════════════════════════════════════════ */}
      {tab === 'Overview' && (
        <div>
          {/* Surface ratings */}
          <div className="section-title">Surface ratings</div>
          <div style={{ display: 'grid', gridTemplateColumns: 'repeat(4, 1fr)', gap: 8, marginBottom: 24 }}>
            {[
              { label: 'Clay',   key: 'clay_rating' },
              { label: 'Hard',   key: 'hard_rating' },
              { label: 'Grass',  key: 'grass_rating' },
              { label: 'Indoor', key: 'indoor_rating' },
            ].map(({ label, key }) => (
              <RatingPill key={key} label={label} value={ratings[key]} />
            ))}
          </div>

          {/* Skill ratings grid + radar */}
          <div className="section-title">Skill ratings</div>
          <div style={{ display: 'grid', gridTemplateColumns: '1fr 320px', gap: 24, alignItems: 'start', marginBottom: 24 }}>
            <div style={{ display: 'grid', gridTemplateColumns: 'repeat(2, 1fr)', gap: 8 }}>
              {[
                { label: 'Serve',       key: 'serve_rating' },
                { label: 'Return',      key: 'return_rating' },
                { label: 'Pressure',    key: 'pressure_rating' },
                { label: 'Consistency', key: 'consistency_rating' },
                { label: 'Big match',   key: 'big_match_rating' },
                { label: 'vs Top 10',   key: 'vs_top10_rating' },
                { label: 'Net game',    key: 'net_game_rating' },
                { label: 'Form',        key: 'form_rating' },
              ].map(({ label, key }) => (
                <RatingPill key={key} label={label} value={ratings[key]} />
              ))}
            </div>
            <PlayerRadar ratings={ratings} name={player.full_name || player.name} />
          </div>

          {/* Recent form (from form endpoint) */}
          {form?.matches?.length > 0 && (
            <>
              <div className="section-title">Recent form</div>
              <div className="card" style={{ padding: '4px 16px' }}>
                {form.matches.slice(0, 10).map((m, i) => (
                  <div key={i} style={{
                    display: 'flex', alignItems: 'center', gap: 10,
                    padding: '7px 0',
                    borderBottom: i < Math.min(form.matches.length, 10) - 1 ? '1px solid var(--border-subtle)' : 'none',
                  }}>
                    <div style={{
                      width: 8, height: 8, borderRadius: '50%', flexShrink: 0,
                      background: m.won ? 'var(--accent-green)' : 'var(--accent-red)',
                    }} />
                    <div style={{ flex: 1 }}>
                      <div style={{ fontSize: 13, fontWeight: 500 }}>
                        vs {m.opponent_name || '—'}
                        {m.opponent_rank && (
                          <span style={{ fontSize: 11, color: 'var(--text-muted)', marginLeft: 4 }}>
                            (#{m.opponent_rank})
                          </span>
                        )}
                      </div>
                      <div style={{ fontSize: 11, color: 'var(--text-muted)' }}>
                        {[m.tournament, m.date?.slice?.(0, 10) || String(m.date || '').slice(0, 10)].filter(Boolean).join(' · ')}
                      </div>
                    </div>
                    <SurfaceBadge surface={m.surface} />
                  </div>
                ))}
              </div>
            </>
          )}
        </div>
      )}

      {/* ══════════════════════════════════════════════════════════════════════
          TAB: FORM
      ══════════════════════════════════════════════════════════════════════ */}
      {tab === 'Form' && (
        <div>
          {/* Surface filter */}
          <div style={{ display: 'flex', gap: 6, marginBottom: 16, flexWrap: 'wrap' }}>
            {SURFACE_FILTERS.map(s => (
              <button key={s} onClick={() => { setFormSurface(s) }}
                style={{
                  padding: '4px 12px', borderRadius: 20, fontSize: 12, cursor: 'pointer',
                  border: `1px solid ${formSurface === s ? 'var(--accent-green)' : 'var(--border-subtle)'}`,
                  background: formSurface === s ? 'rgba(0,204,122,0.1)' : 'transparent',
                  color: formSurface === s ? 'var(--accent-green)' : 'var(--text-secondary)',
                }}>
                {s.charAt(0).toUpperCase() + s.slice(1)}
              </button>
            ))}
          </div>

          {formLoading && <div className="loading">Loading…</div>}

          {!formLoading && form?.matches?.length > 0 ? (
            <div className="card" style={{ padding: '4px 16px' }}>
              {form.matches.map((m, i) => (
                <div key={i} style={{
                  display: 'grid',
                  gridTemplateColumns: '28px 1fr auto auto',
                  alignItems: 'center', gap: 10,
                  padding: '8px 0',
                  borderBottom: i < form.matches.length - 1 ? '1px solid var(--border-subtle)' : 'none',
                }}>
                  <div style={{
                    width: 24, height: 24, borderRadius: '50%',
                    background: m.won ? 'rgba(0,204,122,0.15)' : 'rgba(248,81,73,0.12)',
                    color: m.won ? '#00cc7a' : '#f85149',
                    display: 'flex', alignItems: 'center', justifyContent: 'center',
                    fontWeight: 700, fontSize: 11,
                  }}>
                    {m.won ? 'W' : 'L'}
                  </div>
                  <div>
                    <div style={{ fontSize: 13, fontWeight: 500 }}>
                      vs {m.opponent_name || '—'}
                      {m.opponent_rank && (
                        <span style={{ fontSize: 11, color: 'var(--text-muted)', marginLeft: 4 }}>(#{m.opponent_rank})</span>
                      )}
                    </div>
                    <div style={{ fontSize: 11, color: 'var(--text-muted)' }}>
                      {[m.tournament, String(m.date || '').slice(0, 10)].filter(Boolean).join(' · ')}
                    </div>
                  </div>
                  <SurfaceBadge surface={m.surface} />
                  {m.performance_index != null && (
                    <div style={{ fontSize: 12, color: 'var(--text-muted)', fontFamily: 'var(--font-mono)', textAlign: 'right' }}>
                      {Number(m.performance_index).toFixed(0)}
                    </div>
                  )}
                </div>
              ))}
            </div>
          ) : !formLoading ? (
            <div className="loading">No form data for this surface filter.</div>
          ) : null}

          {/* Rating history snapshots */}
          {form?.rating_history?.length > 0 && (
            <>
              <div className="section-title" style={{ marginTop: 28 }}>RTT Score history</div>
              <div className="card" style={{ padding: '4px 16px' }}>
                {form.rating_history.map((r, i) => (
                  <div key={i} style={{
                    display: 'flex', alignItems: 'center', justifyContent: 'space-between',
                    padding: '7px 0',
                    borderBottom: i < form.rating_history.length - 1 ? '1px solid var(--border-subtle)' : 'none',
                    fontSize: 13,
                  }}>
                    <div style={{ color: 'var(--text-muted)' }}>{String(r.date || '').slice(0, 10)}</div>
                    <div style={{ display: 'flex', gap: 16, alignItems: 'center' }}>
                      {r.momentum && <MomentumBadge momentum={r.momentum} />}
                      {r.rtt_score != null && (
                        <div style={{ fontWeight: 700, color: rttColor(Math.round(r.rtt_score)) }}>
                          {Math.round(r.rtt_score)} RTT
                        </div>
                      )}
                    </div>
                  </div>
                ))}
              </div>
            </>
          )}
        </div>
      )}

      {/* ══════════════════════════════════════════════════════════════════════
          TAB: MATCH HISTORY
      ══════════════════════════════════════════════════════════════════════ */}
      {tab === 'Match History' && (
        <div>
          {/* Surface filter */}
          <div style={{ display: 'flex', gap: 6, marginBottom: 16, flexWrap: 'wrap' }}>
            {SURFACE_FILTERS.map(s => (
              <button key={s} onClick={() => { setHistSurface(s); setHistOffset(0) }}
                style={{
                  padding: '4px 12px', borderRadius: 20, fontSize: 12, cursor: 'pointer',
                  border: `1px solid ${histSurface === s ? 'var(--accent-green)' : 'var(--border-subtle)'}`,
                  background: histSurface === s ? 'rgba(0,204,122,0.1)' : 'transparent',
                  color: histSurface === s ? 'var(--accent-green)' : 'var(--text-secondary)',
                }}>
                {s.charAt(0).toUpperCase() + s.slice(1)}
              </button>
            ))}
          </div>

          {histLoading && <div className="loading">Loading match history…</div>}

          {!histLoading && history && (
            <>
              <div style={{ fontSize: 12, color: 'var(--text-muted)', marginBottom: 10 }}>
                {history.total} matches{histSurface !== 'all' ? ` on ${histSurface}` : ''}
                {' · '}showing {histOffset + 1}–{Math.min(histOffset + HIST_LIMIT, history.total)}
              </div>

              <div className="card" style={{ padding: '4px 16px' }}>
                {history.matches.length === 0 ? (
                  <div style={{ padding: '16px 0', color: 'var(--text-muted)', fontSize: 13 }}>
                    No matches found.
                  </div>
                ) : history.matches.map((m, i) => (
                  <MatchRow key={i} m={m} isLast={i === history.matches.length - 1} />
                ))}
              </div>

              {/* Pagination */}
              {history.total > HIST_LIMIT && (
                <div style={{ display: 'flex', gap: 10, marginTop: 16, justifyContent: 'center' }}>
                  <button
                    disabled={histOffset === 0}
                    onClick={() => setHistOffset(Math.max(0, histOffset - HIST_LIMIT))}
                    style={{
                      padding: '6px 16px', borderRadius: 6, border: '1px solid var(--border-subtle)',
                      background: 'transparent', color: histOffset === 0 ? 'var(--text-muted)' : '#e6edf3',
                      cursor: histOffset === 0 ? 'default' : 'pointer', fontSize: 13,
                    }}>
                    ← Previous
                  </button>
                  <span style={{ fontSize: 13, color: 'var(--text-muted)', padding: '6px 4px' }}>
                    Page {Math.floor(histOffset / HIST_LIMIT) + 1} / {Math.ceil(history.total / HIST_LIMIT)}
                  </span>
                  <button
                    disabled={histOffset + HIST_LIMIT >= history.total}
                    onClick={() => setHistOffset(histOffset + HIST_LIMIT)}
                    style={{
                      padding: '6px 16px', borderRadius: 6, border: '1px solid var(--border-subtle)',
                      background: 'transparent',
                      color: histOffset + HIST_LIMIT >= history.total ? 'var(--text-muted)' : '#e6edf3',
                      cursor: histOffset + HIST_LIMIT >= history.total ? 'default' : 'pointer', fontSize: 13,
                    }}>
                    Next →
                  </button>
                </div>
              )}
            </>
          )}
        </div>
      )}

      {/* ══════════════════════════════════════════════════════════════════════
          TAB: STATS
      ══════════════════════════════════════════════════════════════════════ */}
      {tab === 'Stats' && (
        <div>
          {!stats ? (
            <div className="loading">Loading stats…</div>
          ) : (
            <>
              {/* Serve averages */}
              {stats.career_serve_averages?.sample_size > 0 && (
                <>
                  <div className="section-title">Career serve stats (as winner, n={stats.career_serve_averages.sample_size})</div>
                  <div style={{ display: 'grid', gridTemplateColumns: 'repeat(3, 1fr)', gap: 8, marginBottom: 24 }}>
                    <StatBox label="1st serve %"  value={stats.career_serve_averages.avg_1st_serve_pct} unit="%" />
                    <StatBox label="1st serve won %" value={stats.career_serve_averages.avg_1st_won_pct} unit="%" />
                    <StatBox label="2nd serve won %" value={stats.career_serve_averages.avg_2nd_won_pct} unit="%" />
                    <StatBox label="Ace %"        value={stats.career_serve_averages.avg_ace_pct} unit="%" />
                    <StatBox label="Double fault %" value={stats.career_serve_averages.avg_df_pct} unit="%" />
                    <StatBox label="BP save %"    value={stats.career_serve_averages.avg_bp_save_pct} unit="%" />
                  </div>
                </>
              )}

              {/* Win/loss by surface — chart */}
              {stats.surface_stats?.length > 0 && (
                <>
                  <div className="section-title">Win / loss by surface (career)</div>
                  <div className="card" style={{ marginBottom: 20 }}>
                    <SurfaceWinLossChart surfaceStats={stats.surface_stats} />
                    <div style={{ marginTop: 16 }}>
                      {stats.surface_stats.map((s, i) => {
                        const total = Number(s.wins) + Number(s.losses)
                        const pct = total > 0 ? Math.round((Number(s.wins) / total) * 100) : 0
                        return (
                          <div key={i} style={{
                            display: 'flex', justifyContent: 'space-between', alignItems: 'center',
                            padding: '6px 0',
                            borderBottom: i < stats.surface_stats.length - 1 ? '1px solid var(--border-subtle)' : 'none',
                            fontSize: 13,
                          }}>
                            <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
                              <SurfaceBadge surface={s.surface} />
                              <span>{s.surface}</span>
                            </div>
                            <div style={{ display: 'flex', gap: 16 }}>
                              <span style={{ color: 'var(--text-muted)' }}>{s.wins}W – {s.losses}L</span>
                              <span style={{ fontWeight: 600, color: pct >= 55 ? 'var(--accent-green)' : pct >= 45 ? '#d29922' : 'var(--accent-red)' }}>
                                {pct}%
                              </span>
                            </div>
                          </div>
                        )
                      })}
                    </div>
                  </div>
                </>
              )}

              {/* Rankings history */}
              {stats.rankings_history?.length > 0 && (
                <>
                  <div className="section-title">Best ranking by year</div>
                  <div className="card" style={{ padding: '4px 16px' }}>
                    {stats.rankings_history.map((r, i) => (
                      <div key={i} style={{
                        display: 'flex', justifyContent: 'space-between',
                        padding: '7px 0', fontSize: 13,
                        borderBottom: i < stats.rankings_history.length - 1 ? '1px solid var(--border-subtle)' : 'none',
                      }}>
                        <span style={{ color: 'var(--text-muted)' }}>{r.season}</span>
                        <span style={{ fontWeight: 500 }}>
                          {r.best_rank ? `#${r.best_rank}` : '—'}
                        </span>
                      </div>
                    ))}
                  </div>
                </>
              )}

              {/* No data fallback */}
              {(!stats.career_serve_averages?.sample_size || stats.career_serve_averages.sample_size === 0)
                && (!stats.surface_stats || stats.surface_stats.length === 0)
                && (
                <div className="loading" style={{ marginTop: 32 }}>
                  No detailed career stats available yet for this player.
                  <br />
                  <span style={{ fontSize: 12 }}>Stats populate after running the TML / Sackmann data ingestion.</span>
                </div>
              )}
            </>
          )}
        </div>
      )}
    </div>
  )
}
