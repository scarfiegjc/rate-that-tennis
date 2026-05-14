// PredictionsResults — the redesigned /predictions page.
// Top stats: all-time / 30d / 7d (picks · wins · win rate · P&L · ROI%).
// 7-day bar chart, scrollable last-15 picks table, surface 2x2,
// tour 2x2, edge buckets, calibration plot, P&L trend overlay.
//
// Conventions: £1 flat stake. P&L uses RTT-implied odds (1/prob_pick).

import { useEffect, useMemo, useState } from 'react'
import { Link } from 'react-router-dom'
import { useSEO } from '../hooks/useSEO.js'
import {
  Chart as ChartJS,
  CategoryScale, LinearScale, PointElement, LineElement,
  Title, Tooltip, Legend, Filler,
} from 'chart.js'
import { Line } from 'react-chartjs-2'
import { api } from '../api'
import SurfaceBadge from '../components/SurfaceBadge.jsx'
import { matchUrl } from '../utils/matchUrl.js'
import courtClayImg  from '../assets/court-clay.jpg'
import courtGrassImg from '../assets/court-grass.jpg'
import courtHardImg  from '../assets/court-hard.jpg'

function courtBg(surface) {
  const s = (surface || '').toLowerCase()
  if (s.includes('clay'))  return courtClayImg
  if (s.includes('grass')) return courtGrassImg
  return courtHardImg
}
function courtOverlay(surface) {
  const s = (surface || '').toLowerCase()
  if (s.includes('clay'))  return 'rgba(184,72,54,0.72)'
  if (s.includes('grass')) return 'rgba(16,100,56,0.72)'
  if (s.includes('indoor') || s.includes('carpet')) return 'rgba(98,38,188,0.88)'
  return 'rgba(25,65,185,0.72)'
}

ChartJS.register(
  CategoryScale, LinearScale, PointElement, LineElement,
  Title, Tooltip, Legend, Filler
)

// ─── helpers ─────────────────────────────────────────────────────────────

const fmtMoney = (v) => {
  if (v == null || Number.isNaN(v)) return '—'
  const sign = v >= 0 ? '+' : '−'
  return `${sign}£${Math.abs(v).toFixed(2)}`
}
const fmtPct = (v) => (v == null || Number.isNaN(v)) ? '—' : `${v.toFixed(1)}%`
const fmtPctInt = (v) => (v == null || Number.isNaN(v)) ? '—' : `${Math.round(v)}%`

const profitColour = (v) =>
  v == null ? 'var(--text-3)' : v > 0 ? 'var(--green)' : v < 0 ? 'var(--red)' : 'var(--text-3)'

// Project an _agg block (returned by the API) into the four display values
// for the active odds mode. In "book" mode, picks/wins/win_rate use the
// priced subset (only matches with bookmaker odds), so the win-rate the user
// sees is calculated against the same set of picks that backs the P&L number.
function pickStats(s, mode) {
  if (!s) return { picks: 0, wins: 0, winRate: null, pnl: null, roi: null, hasData: false }
  if (mode === 'book') {
    return {
      picks:   s.priced_picks ?? 0,
      wins:    s.wins_priced  ?? 0,
      winRate: s.priced_picks ? (100 * (s.wins_priced || 0) / s.priced_picks) : null,
      pnl:     s.pnl_book,
      roi:     s.roi_book_pct,
      hasData: (s.priced_picks ?? 0) > 0,
    }
  }
  return {
    picks:   s.picks ?? 0,
    wins:    s.wins  ?? 0,
    winRate: s.win_rate_pct,
    pnl:     s.pnl_rtt ?? s.pnl,
    roi:     s.roi_rtt_pct ?? s.roi_pct,
    hasData: (s.picks ?? 0) > 0,
  }
}

// ─── small components ────────────────────────────────────────────────────

function StreakBadge({ streak }) {
  if (!streak) return null
  const isWin = streak.type === 'W'
  return (
    <div style={{
      display: 'inline-flex', alignItems: 'center', gap: 6,
      padding: '4px 10px', borderRadius: 999,
      background: isWin ? 'var(--green-bg)' : 'var(--red-bg)',
      border: `1px solid ${isWin ? 'var(--green-border)' : 'var(--red-border)'}`,
      color: isWin ? 'var(--green-text)' : 'var(--red)',
      fontSize: 12, fontWeight: 700, fontVariantNumeric: 'tabular-nums',
    }}>
      <span style={{
        width: 6, height: 6, borderRadius: '50%',
        background: isWin ? 'var(--green)' : 'var(--red)',
      }} />
      {isWin ? 'Win streak' : 'Losing streak'}: {streak.len}
    </div>
  )
}

function StatBlock({ label, picks, wins, winRate, pnl, roi, accent }) {
  const cellLabel = {
    fontSize: 10, color: 'var(--text-3)',
    textTransform: 'uppercase', letterSpacing: 0.4, marginTop: 2,
  }
  const cellValue = {
    fontSize: 16, fontWeight: 700, fontVariantNumeric: 'tabular-nums',
    lineHeight: 1.1,
  }
  return (
    <div className="card" style={{
      padding: 14,
      borderTop: `3px solid ${accent || 'var(--border)'}`,
    }}>
      <div style={{
        fontSize: 11, fontWeight: 700, color: 'var(--text-3)',
        textTransform: 'uppercase', letterSpacing: 0.5, marginBottom: 10,
      }}>
        {label}
      </div>
      <div style={{
        display: 'grid', gridTemplateColumns: 'repeat(4, 1fr)',
        gap: 8, alignItems: 'flex-start',
      }}>
        <div>
          <div style={cellValue}>
            {wins ?? 0}<span style={{ color: 'var(--text-3)', fontWeight: 500 }}>/{picks ?? 0}</span>
          </div>
          <div style={cellLabel}>Wins / picks</div>
        </div>
        <div>
          <div style={{
            ...cellValue,
            color: winRate == null ? 'var(--text-3)' : winRate >= 55 ? 'var(--green-text)' : winRate >= 50 ? 'var(--text)' : 'var(--text-3)',
          }}>
            {fmtPct(winRate)}
          </div>
          <div style={cellLabel}>Win rate</div>
        </div>
        <div>
          <div style={{ ...cellValue, color: profitColour(pnl) }}>
            {fmtMoney(pnl)}
          </div>
          <div style={cellLabel}>P&amp;L</div>
        </div>
        <div>
          <div style={{ ...cellValue, color: profitColour(pnl) }}>
            {fmtPct(roi)}
          </div>
          <div style={cellLabel}>ROI</div>
        </div>
      </div>
    </div>
  )
}

function MiniStatRow({ label, s, mode }) {
  const v = pickStats(s, mode)
  if (!v.hasData) {
    return (
      <div style={{
        display: 'grid', gridTemplateColumns: '90px 1fr',
        padding: '7px 12px', borderBottom: '1px solid var(--border-faint)',
        fontSize: 12, color: 'var(--text-3)',
      }}>
        <div style={{ fontWeight: 600, textTransform: 'uppercase', letterSpacing: 0.4, fontSize: 10 }}>
          {label}
        </div>
        <div style={{ textAlign: 'right' }}>—</div>
      </div>
    )
  }
  return (
    <div style={{
      display: 'grid', gridTemplateColumns: '60px 1fr 48px 1fr',
      padding: '6px 10px', borderBottom: '1px solid var(--border-faint)',
      fontSize: 11, alignItems: 'center', fontVariantNumeric: 'tabular-nums',
    }}>
      <div style={{
        fontWeight: 600, textTransform: 'uppercase', letterSpacing: 0.3,
        fontSize: 9, color: 'var(--text-3)',
      }}>
        {label}
      </div>
      <div style={{ fontSize: 10 }}>
        {v.wins}/{v.picks}
      </div>
      <div style={{ color: v.winRate >= 50 ? 'var(--green-text)' : 'var(--text-3)', fontSize: 10 }}>
        {fmtPctInt(v.winRate)}%
      </div>
      <div style={{ textAlign: 'right', color: profitColour(v.pnl), fontWeight: 600, fontSize: 10 }}>
        {fmtMoney(v.pnl)} <span style={{ color: 'var(--text-3)', fontWeight: 400, fontSize: 9 }}>({fmtPctInt(v.roi)}%)</span>
      </div>
    </div>
  )
}

function BreakdownCard({ title, data, mode, surface }) {
  return (
    <div className="card" style={{ overflow: 'hidden' }}>
      <div style={{
        padding: '10px 12px',
        borderBottom: '1px solid var(--border)',
        fontSize: 13, fontWeight: 700, letterSpacing: 0.2,
        ...(surface ? {
          backgroundImage: `url(${courtBg(surface)})`,
          backgroundSize: 'cover',
          backgroundPosition: 'center',
          backgroundColor: courtOverlay(surface),
          backgroundBlendMode: 'multiply',
          color: '#fff',
        } : {
          background: 'var(--bg-raised)',
        }),
      }}>
        {title}
      </div>
      <div style={{
        display: 'grid', gridTemplateColumns: '60px 1fr 48px 1fr',
        padding: '5px 10px', background: 'var(--bg-sunken)',
        borderBottom: '1px solid var(--border-faint)',
        fontSize: 8, fontWeight: 700, letterSpacing: 0.4,
        color: 'var(--text-3)', textTransform: 'uppercase',
      }}>
        <div>Window</div>
        <div>W/P</div>
        <div>Win%</div>
        <div style={{ textAlign: 'right' }}>P&amp;L (ROI)</div>
      </div>
      <MiniStatRow label="All time" s={data?.all_time} mode={mode} />
      <MiniStatRow label="Last 30d" s={data?.last_30d} mode={mode} />
      <MiniStatRow label="Last 7d"  s={data?.last_7d}  mode={mode} />
    </div>
  )
}

// ─── 7-day bars ──────────────────────────────────────────────────────────

function WeeklyBars({ items }) {
  if (!items || items.length === 0) {
    return (
      <div style={{ padding: 24, color: 'var(--text-3)', textAlign: 'center', fontSize: 13 }}>
        No settled picks in the last 7 days yet.
      </div>
    )
  }
  // Bar height in PIXELS so it actually scales 1:1 with the prediction
  // percent — the previous `height: <pct>%` resolved against a collapsed
  // flex parent and gave near-identical visual heights regardless of the
  // underlying number. 200px reserved for the bar area; the bar itself
  // gets pct/100 of that, floored at 12px so a near-50% pick is still
  // visible. Add a 50% reference line so the eye instantly catches which
  // picks are confident vs marginal.
  const BAR_AREA_PX = 200
  const HALF_LINE_PX = BAR_AREA_PX * 0.5   // visual reference for 50%
  return (
    <div style={{
      display: 'flex', gap: 6, alignItems: 'flex-end',
      overflowX: 'auto', padding: '4px 4px 8px',
      position: 'relative',
    }}>
      {/* 50% reference line spanning the bar area */}
      <div style={{
        position: 'absolute',
        left: 0, right: 0,
        bottom: 40 + HALF_LINE_PX,   // 40 ≈ labels under the bars
        borderTop: '1px dashed var(--border)',
        pointerEvents: 'none',
      }} />
      {items.map((p) => {
        const pct = Math.round((p.pick_prob ?? 0) * 100)
        const barPx = Math.max(12, Math.min(BAR_AREA_PX, Math.round(BAR_AREA_PX * (pct / 100))))
        const won = p.won
        return (
          <Link
            key={p.match_id}
            to={matchUrl(p)}
            title={`${p.pick_name} (${pct}%) vs ${p.opp_name} · ${p.tournament || ''} · ${p.surface || ''} · ${p.score || '—'}`}
            style={{
              flex: '1 0 70px', minWidth: 70, maxWidth: 130,
              display: 'flex', flexDirection: 'column', alignItems: 'stretch', gap: 4,
              textDecoration: 'none', color: 'inherit',
            }}
          >
            {/* Fixed-height bar holder so bars align at the bottom */}
            <div style={{
              height: BAR_AREA_PX,
              display: 'flex', flexDirection: 'column-reverse',
            }}>
              <div style={{
                height: `${barPx}px`,
                background: won ? 'var(--green)' : 'var(--red)',
                borderRadius: '4px 4px 0 0',
                display: 'flex', alignItems: 'flex-start', justifyContent: 'center',
                paddingTop: 6,
                color: '#fff', fontSize: 11, fontWeight: 700,
                boxShadow: 'inset 0 -2px 0 rgba(0,0,0,.08)',
              }}>
                {pct}%
              </div>
            </div>
            <div style={{
              fontSize: 10, fontWeight: 600, color: 'var(--text-2)',
              textAlign: 'center', whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis',
            }}>
              {p.pick_name}
            </div>
            <div style={{
              fontSize: 9, color: 'var(--text-3)',
              textAlign: 'center', whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis',
            }}>
              {p.score || (won ? 'W' : 'L')}
            </div>
          </Link>
        )
      })}
    </div>
  )
}

// ─── recent picks scrollable table ───────────────────────────────────────

function RecentPicksTable({ items }) {
  const [outcome, setOutcome] = useState('all')  // all | won | lost

  if (!items || items.length === 0) {
    return (
      <div style={{ padding: 24, color: 'var(--text-3)', textAlign: 'center', fontSize: 13 }}>
        No settled picks yet.
      </div>
    )
  }

  const wins   = items.filter(p => p.won)
  const losses = items.filter(p => !p.won)
  const visible = outcome === 'won' ? wins : outcome === 'lost' ? losses : items

  return (
    <>
      {/* Filter tabs + count */}
      <div style={{
        display: 'flex', gap: 4, alignItems: 'center',
        padding: '6px 12px', borderBottom: '1px solid var(--border-faint)',
        background: 'var(--bg-sunken)',
      }}>
        {[
          { id: 'all',  label: `All (${items.length})` },
          { id: 'won',  label: `✓ Wins (${wins.length})`,   colour: 'var(--green)' },
          { id: 'lost', label: `✗ Losses (${losses.length})`, colour: 'var(--red)' },
        ].map(tab => (
          <button
            key={tab.id}
            onClick={() => setOutcome(tab.id)}
            style={{
              padding: '3px 9px', borderRadius: 4, border: 'none', cursor: 'pointer',
              fontSize: 11, fontWeight: 700,
              background: outcome === tab.id ? (tab.colour || 'var(--text)') : 'transparent',
              color: outcome === tab.id
                ? (tab.id === 'all' ? 'var(--text-inv)' : '#fff')
                : (tab.colour || 'var(--text-3)'),
              opacity: outcome === tab.id ? 1 : 0.7,
            }}
          >
            {tab.label}
          </button>
        ))}
        <span style={{ marginLeft: 'auto', fontSize: 10, color: 'var(--text-3)' }}>
          Click a row · * = RTT-implied odds
        </span>
      </div>

      <div style={{ maxHeight: 520, overflowY: 'auto' }}>
        <div style={{
          display: 'grid',
          gridTemplateColumns: '70px 1fr 1fr 130px 90px 80px 70px 70px',
          padding: '8px 12px', borderBottom: '1px solid var(--border)',
          background: 'var(--bg-raised)', position: 'sticky', top: 0, zIndex: 1,
          fontSize: 9, fontWeight: 700, letterSpacing: 0.4,
          color: 'var(--text-3)', textTransform: 'uppercase',
        }}>
          <div>Date</div>
          <div>Pick</div>
          <div>vs</div>
          <div>Tournament</div>
          <div>Surface</div>
          <div style={{ textAlign: 'right' }}>Pred.</div>
          <div style={{ textAlign: 'right' }}>Score</div>
          <div style={{ textAlign: 'right' }}>Odds</div>
        </div>
        {visible.length === 0 ? (
          <div style={{ padding: 20, textAlign: 'center', color: 'var(--text-3)', fontSize: 12 }}>
            No {outcome === 'won' ? 'wins' : 'losses'} yet.
          </div>
        ) : visible.map((p) => (
          <Link
            key={p.match_id}
            to={matchUrl(p)}
            style={{
              display: 'grid',
              gridTemplateColumns: '70px 1fr 1fr 130px 90px 80px 70px 70px',
              padding: '9px 12px', borderBottom: '1px solid var(--border-faint)',
              fontSize: 12, alignItems: 'center', fontVariantNumeric: 'tabular-nums',
              background: p.won ? 'var(--green-bg)' : 'var(--red-bg)',
              borderLeft: `3px solid ${p.won ? 'var(--green)' : 'var(--red)'}`,
              textDecoration: 'none', color: 'inherit',
            }}
          >
            <div style={{ fontSize: 11 }}>{p.event_date?.slice(5) /* MM-DD */}</div>
            <div style={{ fontWeight: 600 }}>
              {p.pick_name}
              {p.confidence === 'high' && (
                <span style={{ marginLeft: 4, fontSize: 9, color: 'var(--green-text)' }}>★</span>
              )}
            </div>
            <div style={{ color: 'var(--text-3)' }}>{p.opp_name}</div>
            <div style={{ fontSize: 11, whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis' }}>
              {p.tournament || '—'}
            </div>
            <div>
              {p.surface ? <SurfaceBadge surface={p.surface} /> : <span style={{ color: 'var(--text-3)' }}>—</span>}
            </div>
            <div style={{ textAlign: 'right', fontWeight: 600 }}>
              {fmtPctInt((p.pick_prob ?? 0) * 100)}
            </div>
            <div style={{ textAlign: 'right', fontSize: 11 }}>{p.score || '—'}</div>
            <div style={{ textAlign: 'right', fontSize: 11, color: 'var(--text-3)' }}>
              {p.book_odds ? p.book_odds.toFixed(2) : `${p.rtt_odds?.toFixed(2) || '—'}*`}
            </div>
          </Link>
        ))}
      </div>
    </>
  )
}

// ─── edge buckets ────────────────────────────────────────────────────────

function EdgeBuckets({ buckets }) {
  if (!buckets || buckets.length === 0 || buckets.every(b => (b.picks ?? 0) === 0)) {
    return (
      <div style={{ padding: 16, color: 'var(--text-3)', fontSize: 12 }}>
        Edge buckets will populate once bookmaker odds are fetched. Showing model probability vs market implied probability.
      </div>
    )
  }
  const maxN = Math.max(1, ...buckets.map(b => b.picks ?? 0))
  return (
    <div style={{ padding: 14 }}>
      {buckets.map(b => {
        const widthN  = ((b.picks || 0) / maxN) * 100
        const colour  = b.roi_pct == null ? 'var(--text-3)'
                      : b.roi_pct > 0 ? 'var(--green)' : 'var(--red)'
        return (
          <div key={b.label} style={{ marginBottom: 8 }}>
            <div style={{
              display: 'flex', justifyContent: 'space-between', alignItems: 'center',
              fontSize: 11, marginBottom: 3,
            }}>
              <span style={{ fontWeight: 700 }}>{b.label}</span>
              <span style={{ fontVariantNumeric: 'tabular-nums', color: 'var(--text-3)' }}>
                {b.wins}/{b.picks} · {fmtPct(b.win_rate_pct)} ·
                {' '}<span style={{ color: profitColour(b.pnl_book), fontWeight: 600 }}>
                  {fmtMoney(b.pnl_book)} ({fmtPct(b.roi_pct)})
                </span>
              </span>
            </div>
            <div style={{ height: 8, background: 'var(--bg-sunken)', borderRadius: 4, overflow: 'hidden' }}>
              <div style={{
                width: `${widthN}%`, height: '100%',
                background: colour, opacity: 0.85,
              }} />
            </div>
          </div>
        )
      })}
      <div style={{ fontSize: 10, color: 'var(--text-3)', marginTop: 6 }}>
        Edge = model probability − market implied probability. ROI uses bookmaker odds where available.
      </div>
    </div>
  )
}

// ─── calibration plot ────────────────────────────────────────────────────

function Calibration({ data }) {
  if (!data || data.length === 0 || data.every(d => (d.picks ?? 0) === 0)) {
    return (
      <div style={{ padding: 16, color: 'var(--text-3)', fontSize: 12 }}>
        Not enough settled picks to plot calibration yet.
      </div>
    )
  }
  return (
    <div style={{ padding: 14 }}>
      {data.map(d => {
        if (!d.picks) {
          return (
            <div key={d.label} style={{
              padding: '6px 0', borderBottom: '1px solid var(--border-faint)',
              fontSize: 11, color: 'var(--text-3)',
            }}>
              <span style={{ fontWeight: 700 }}>{d.label}</span> — no picks
            </div>
          )
        }
        const pred   = d.predicted_pct ?? 0
        const actual = d.actual_pct ?? 0
        const diff = actual - pred
        const isOver = actual >= pred  // model's pick wins more than predicted = under-confident (good)
        return (
          <div key={d.label} style={{ marginBottom: 10 }}>
            <div style={{
              display: 'flex', justifyContent: 'space-between',
              fontSize: 11, marginBottom: 3,
            }}>
              <span style={{ fontWeight: 700 }}>{d.label}</span>
              <span style={{ fontVariantNumeric: 'tabular-nums', color: 'var(--text-3)' }}>
                {d.picks} picks · predicted <b>{fmtPct(pred)}</b>, actual{' '}
                <b style={{ color: isOver ? 'var(--green-text)' : 'var(--red)' }}>{fmtPct(actual)}</b>
                {' '}({diff >= 0 ? '+' : ''}{diff.toFixed(1)}pp)
              </span>
            </div>
            <div style={{ height: 8, background: 'var(--bg-sunken)', borderRadius: 4, position: 'relative', overflow: 'hidden' }}>
              {/* expected (predicted) marker */}
              <div style={{
                position: 'absolute', left: `${pred}%`, top: 0, bottom: 0,
                width: 2, background: 'var(--text-3)',
              }} />
              {/* actual fill */}
              <div style={{
                width: `${actual}%`, height: '100%',
                background: isOver ? 'var(--green)' : 'var(--red)',
                opacity: 0.7,
              }} />
            </div>
          </div>
        )
      })}
      <div style={{ fontSize: 10, color: 'var(--text-3)', marginTop: 4 }}>
        Filled bar = actual win rate. Vertical line = predicted average. Green = picks over-perform their stated probability.
      </div>
    </div>
  )
}

// ─── P&L trend overlay (Chart.js Line) ───────────────────────────────────

function PnlTrendOverlay({ trend, onClose }) {
  const labels = useMemo(() => trend.map(p => p.date), [trend])
  const cum    = useMemo(() => trend.map(p => p.cumulative_pnl), [trend])
  const roi    = useMemo(() => trend.map(p => p.roi_pct),        [trend])

  const cfg = {
    labels,
    datasets: [
      {
        label: 'Cumulative P&L (£)',
        data: cum,
        borderColor: '#059669',
        backgroundColor: 'rgba(5,150,105,0.12)',
        fill: true,
        tension: 0.25,
        yAxisID: 'y',
        pointRadius: 0,
      },
      {
        label: 'Cumulative ROI %',
        data: roi,
        borderColor: '#D97706',
        borderDash: [4, 4],
        backgroundColor: 'transparent',
        tension: 0.25,
        yAxisID: 'y1',
        pointRadius: 0,
      },
    ],
  }
  const opts = {
    responsive: true,
    maintainAspectRatio: false,
    interaction: { mode: 'index', intersect: false },
    scales: {
      x: { ticks: { autoSkip: true, maxTicksLimit: 8, font: { size: 10 } } },
      y:  { position: 'left',  title: { display: true, text: 'P&L (£)' } },
      y1: { position: 'right', grid: { display: false }, title: { display: true, text: 'ROI %' } },
    },
    plugins: { legend: { position: 'bottom' } },
  }

  return (
    <div
      onClick={onClose}
      style={{
        position: 'fixed', inset: 0, background: 'rgba(0,0,0,0.5)',
        display: 'flex', alignItems: 'center', justifyContent: 'center',
        zIndex: 200, padding: 24,
      }}
    >
      <div
        onClick={(e) => e.stopPropagation()}
        className="card"
        style={{
          width: '100%', maxWidth: 900, padding: 20,
          background: 'var(--bg-card)',
        }}
      >
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 12 }}>
          <div>
            <h3 style={{ margin: 0, fontSize: 16 }}>P&amp;L trend</h3>
            <div style={{ fontSize: 11, color: 'var(--text-3)' }}>
              Cumulative profit and ROI over time, £1 stake at RTT-implied odds.
            </div>
          </div>
          <button
            onClick={onClose}
            style={{
              padding: '6px 12px', borderRadius: 'var(--r)',
              background: 'var(--bg-raised)', fontSize: 13, fontWeight: 600,
            }}
          >
            ✕ Close
          </button>
        </div>
        <div style={{ height: 380 }}>
          {trend.length === 0
            ? <div style={{ padding: 40, textAlign: 'center', color: 'var(--text-3)' }}>No trend data yet.</div>
            : <Line data={cfg} options={opts} />}
        </div>
      </div>
    </div>
  )
}

// ─── systems tracker (bottom of page) ────────────────────────────────────

function SystemCard({ sys }) {
  const s = sys.stats || {}
  const settled = s.picks_settled || 0
  const correct = s.picks_correct || 0
  const accent = sys.accent_colour || 'var(--text-2)'

  return (
    <div className="card" style={{ overflow: 'hidden' }}>
      {/* Header: icon, name, description */}
      <div style={{
        padding: '12px 14px',
        borderBottom: '1px solid var(--border-faint)',
        borderLeft: `3px solid ${accent}`,
        background: 'var(--bg-card)',
      }}>
        <div style={{ display: 'flex', alignItems: 'baseline', gap: 10, marginBottom: 4 }}>
          <span style={{ fontSize: 18 }}>{sys.icon || '·'}</span>
          <span style={{ fontSize: 14, fontWeight: 700 }}>{sys.name}</span>
          {settled > 0 && (
            <span style={{
              marginLeft: 'auto', fontSize: 10, fontWeight: 700,
              color: 'var(--text-3)', textTransform: 'uppercase', letterSpacing: 0.4,
            }}>
              {settled} settled
            </span>
          )}
        </div>
        <div style={{ fontSize: 11, color: 'var(--text-3)', lineHeight: 1.4 }}>
          {sys.description}
        </div>
      </div>

      {/* All-time stats row */}
      <div style={{
        display: 'grid', gridTemplateColumns: 'repeat(4, 1fr)',
        padding: '10px 14px', gap: 8,
        background: 'var(--bg-raised)',
        borderBottom: '1px solid var(--border-faint)',
        fontVariantNumeric: 'tabular-nums',
      }}>
        <div>
          <div style={{ fontSize: 16, fontWeight: 700 }}>
            {correct}<span style={{ color: 'var(--text-3)', fontWeight: 500 }}>/{settled}</span>
          </div>
          <div style={{ fontSize: 9, color: 'var(--text-3)', textTransform: 'uppercase', letterSpacing: 0.4, marginTop: 2 }}>
            Wins / picks
          </div>
        </div>
        <div>
          <div style={{
            fontSize: 16, fontWeight: 700,
            color: s.accuracy_pct == null ? 'var(--text-3)'
                 : s.accuracy_pct >= 75 ? 'var(--green)'
                 : s.accuracy_pct >= 60 ? 'var(--green-text)'
                 : s.accuracy_pct >= 50 ? 'var(--text)' : 'var(--red)',
          }}>
            {fmtPct(s.accuracy_pct)}
          </div>
          <div style={{ fontSize: 9, color: 'var(--text-3)', textTransform: 'uppercase', letterSpacing: 0.4, marginTop: 2 }}>
            Win rate
          </div>
        </div>
        <div>
          <div style={{ fontSize: 16, fontWeight: 700, color: profitColour(s.profit_units) }}>
            {fmtMoney(s.profit_units)}
          </div>
          <div style={{ fontSize: 9, color: 'var(--text-3)', textTransform: 'uppercase', letterSpacing: 0.4, marginTop: 2 }}>
            P&amp;L
          </div>
        </div>
        <div>
          <div style={{ fontSize: 16, fontWeight: 700, color: profitColour(s.roi_pct) }}>
            {fmtPct(s.roi_pct)}
          </div>
          <div style={{ fontSize: 9, color: 'var(--text-3)', textTransform: 'uppercase', letterSpacing: 0.4, marginTop: 2 }}>
            ROI
          </div>
        </div>
      </div>

      {/* Recent settled results */}
      <div>
        <div style={{
          padding: '6px 14px',
          fontSize: 9, fontWeight: 700, letterSpacing: 0.4,
          color: 'var(--text-3)', textTransform: 'uppercase',
          background: 'var(--bg-sunken)',
          borderBottom: '1px solid var(--border-faint)',
          display: 'flex', justifyContent: 'space-between', alignItems: 'center',
        }}>
          <span>Recent results</span>
          <Link
            to={`/systems/${sys.code}`}
            style={{ fontSize: 9, color: 'var(--accent)', textTransform: 'none', letterSpacing: 0 }}
            onClick={e => e.stopPropagation()}
          >
            View all →
          </Link>
        </div>
        {(!sys.recent_picks || sys.recent_picks.length === 0) ? (
          <div style={{
            padding: '12px 14px', fontSize: 11,
            color: 'var(--text-3)', textAlign: 'center',
          }}>
            No settled picks yet.
          </div>
        ) : (
          sys.recent_picks.map(p => {
            const correct = p.is_correct === true
            const wrong   = p.is_correct === false
            const colour  = correct ? 'var(--green)' : wrong ? 'var(--red)' : 'var(--text-3)'
            return (
              <Link
                key={p.pick_id}
                to={matchUrl({
                  match_id: p.match_id,
                  event_date: p.event_date,
                  tournament: p.tournament,
                  p1: p.pick,
                  p2: p.opponent,
                })}
                style={{
                  display: 'grid',
                  gridTemplateColumns: '22px 1fr auto',
                  padding: '8px 14px',
                  borderBottom: '1px solid var(--border-faint)',
                  fontSize: 12, alignItems: 'center',
                  textDecoration: 'none', color: 'inherit',
                }}
              >
                <div style={{ fontSize: 14, fontWeight: 700, color: colour }}>
                  {correct ? '✓' : wrong ? '✗' : '·'}
                </div>
                <div>
                  <div style={{ fontWeight: 600 }}>
                    {p.pick.name}
                    <span style={{ color: 'var(--text-3)', fontWeight: 400 }}> vs {p.opponent.name}</span>
                  </div>
                  <div style={{ fontSize: 10, color: 'var(--text-3)', marginTop: 2 }}>
                    {p.event_date?.slice(5)}{p.tournament ? ` · ${p.tournament}` : ''}
                    {p.surface ? ` · ${p.surface}` : ''}
                  </div>
                </div>
                <div style={{ display: 'flex', flexDirection: 'column', alignItems: 'flex-end', gap: 2 }}>
                  {p.pick_prob != null && (
                    <span style={{ fontSize: 11, fontWeight: 700, fontVariantNumeric: 'tabular-nums' }}>
                      {Math.round(p.pick_prob * 100)}%
                    </span>
                  )}
                  {p.profit_loss != null && (
                    <span style={{
                      fontSize: 10, fontVariantNumeric: 'tabular-nums',
                      color: p.profit_loss > 0 ? 'var(--green)' : p.profit_loss < 0 ? 'var(--red)' : 'var(--text-3)',
                    }}>
                      {p.profit_loss > 0 ? '+' : ''}{p.profit_loss.toFixed(2)}u
                    </span>
                  )}
                </div>
              </Link>
            )
          })
        )}
      </div>
    </div>
  )
}

function SystemsTracker() {
  const [data, setData] = useState(null)
  const [error, setError] = useState(null)

  useEffect(() => {
    let on = true
    api.systemsDashboard()
       .then(d => { if (on) setData(d) })
       .catch(e => { if (on) setError(e.message) })
    return () => { on = false }
  }, [])

  if (error) {
    return (
      <div style={{ fontSize: 11, color: 'var(--text-3)', padding: 12, textAlign: 'center' }}>
        Couldn&apos;t load systems: {error}
      </div>
    )
  }
  if (!data) {
    return (
      <div style={{ fontSize: 11, color: 'var(--text-3)', padding: 12, textAlign: 'center' }}>
        Loading systems…
      </div>
    )
  }

  const systems = data.systems || []
  if (systems.length === 0) {
    return (
      <div style={{ fontSize: 11, color: 'var(--text-3)', padding: 12, textAlign: 'center' }}>
        No active systems.
      </div>
    )
  }

  return (
    <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(360px, 1fr))', gap: 12 }}>
      {systems.map(s => <SystemCard key={s.code} sys={s} />)}
    </div>
  )
}


// ─── highlight cards (best/worst) ────────────────────────────────────────

function HighlightCard({ title, pick, accent, mode }) {
  if (!pick) {
    return (
      <div className="card" style={{ padding: 12, opacity: 0.6 }}>
        <div style={{
          fontSize: 10, fontWeight: 700, color: 'var(--text-3)',
          textTransform: 'uppercase', letterSpacing: 0.4, marginBottom: 6,
        }}>{title}</div>
        <div style={{ fontSize: 12, color: 'var(--text-3)' }}>No 7-day data</div>
      </div>
    )
  }
  const won = pick.won
  return (
    <Link
      to={matchUrl(pick)}
      className="card"
      style={{
        padding: 12, display: 'block',
        borderLeft: `3px solid ${accent}`,
        textDecoration: 'none', color: 'inherit',
      }}
    >
      <div style={{
        fontSize: 10, fontWeight: 700, color: 'var(--text-3)',
        textTransform: 'uppercase', letterSpacing: 0.4, marginBottom: 6,
      }}>{title}</div>
      <div style={{ fontSize: 13, fontWeight: 600, marginBottom: 2 }}>
        {pick.pick_name} <span style={{ color: 'var(--text-3)', fontWeight: 400 }}>vs {pick.opp_name}</span>
      </div>
      <div style={{ fontSize: 11, color: 'var(--text-3)', marginBottom: 6 }}>
        {pick.tournament || '—'}{pick.surface ? ` · ${pick.surface}` : ''}
      </div>
      <div style={{ display: 'flex', gap: 12, fontSize: 12, alignItems: 'center' }}>
        <span style={{ fontWeight: 700 }}>{fmtPctInt((pick.pick_prob ?? 0) * 100)}</span>
        <span style={{ color: won ? 'var(--green)' : 'var(--red)', fontWeight: 700 }}>
          {won ? '✓ Won' : '✗ Lost'}
        </span>
        {(() => {
          // pl_book if priced and book mode selected, else pl_rtt
          const pl = (mode === 'book' && pick.pl_book != null) ? pick.pl_book : pick.pl_rtt
          return (
            <span style={{ color: profitColour(pl), fontWeight: 700, marginLeft: 'auto' }}>
              {fmtMoney(pl)}
            </span>
          )
        })()}
      </div>
    </Link>
  )
}

// ─── today's matches strip ───────────────────────────────────────────────

function TodayRow({ p }) {
  const p1Pct = p.p1?.prob != null ? Math.round(p.p1.prob * 100) : null
  const p2Pct = p.p2?.prob != null ? Math.round(p.p2.prob * 100) : null
  const isPending = p1Pct == null
  // A 50/50 prob isn't really a pick — show neutral, not red-on-settle.
  const isFiftyFifty = p.p1?.prob != null && Math.abs(p.p1.prob - 0.5) < 0.05
  const isSettled = !isFiftyFifty && (p.is_correct === true || p.is_correct === false)
  const winnerSide = p.actual_winner === 'first_player' ? 'p1'
                   : p.actual_winner === 'second_player' ? 'p2' : null
  // Derive pick from probs (not stored predicted_winner, which can be stale)
  const predictedSide = (p.p1?.prob != null && !isFiftyFifty)
    ? (p.p1.prob >= 0.5 ? 'p1' : 'p2')
    : null

  let bg = 'transparent', border = '3px solid var(--border)'
  if (isSettled) {
    bg = p.is_correct ? 'var(--green-bg)' : 'var(--red-bg)'
    border = `3px solid ${p.is_correct ? 'var(--green)' : 'var(--red)'}`
  } else if (isFiftyFifty) {
    bg = 'var(--bg-raised)'
    border = '3px solid var(--amber)'
  }

  return (
    <Link
      to={matchUrl(p)}
      style={{
        display: 'grid',
        gridTemplateColumns: '50px 1fr 90px 1fr 90px 24px',
        padding: '8px 12px',
        borderBottom: '1px solid var(--border-faint)',
        borderLeft: border,
        background: bg,
        textDecoration: 'none', color: 'inherit',
        alignItems: 'center', fontSize: 12,
      }}
    >
      <div style={{ fontSize: 11, color: 'var(--text-3)' }}>
        {p.event_time ? p.event_time.slice(0, 5) : '—'}
      </div>
      <div style={{
        fontWeight: winnerSide === 'p1' ? 700 : (predictedSide === 'p1' ? 600 : 400),
        color: winnerSide === 'p1' ? 'var(--green-text)' :
               winnerSide === 'p2' ? 'var(--text-3)' : 'inherit',
        whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis',
      }}>
        {p.p1?.name}
        {predictedSide === 'p1' && <span style={{ color: 'var(--text-3)', fontSize: 10, marginLeft: 4 }}>· pick</span>}
      </div>
      <div style={{ textAlign: 'center', fontVariantNumeric: 'tabular-nums' }}>
        {isPending
          ? <span style={{ color: 'var(--text-3)', fontStyle: 'italic', fontSize: 11 }}>pending</span>
          : isFiftyFifty
            ? <span style={{ color: 'var(--amber)', fontSize: 10, fontWeight: 700, letterSpacing: 0.3, textTransform: 'uppercase' }}>50/50 · no pick</span>
            : <><b>{p1Pct}%</b> · <b>{p2Pct}%</b></>}
      </div>
      <div style={{
        fontWeight: winnerSide === 'p2' ? 700 : (predictedSide === 'p2' ? 600 : 400),
        color: winnerSide === 'p2' ? 'var(--green-text)' :
               winnerSide === 'p1' ? 'var(--text-3)' : 'inherit',
        whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis',
      }}>
        {predictedSide === 'p2' && <span style={{ color: 'var(--text-3)', fontSize: 10, marginRight: 4 }}>pick ·</span>}
        {p.p2?.name}
      </div>
      <div style={{ fontSize: 10, color: 'var(--text-3)' }}>
        {p.surface ? <SurfaceBadge surface={p.surface} /> : ''}
      </div>
      <div style={{ textAlign: 'right', fontSize: 14, fontWeight: 700,
                    color: isSettled ? (p.is_correct ? 'var(--green)' : 'var(--red)')
                          : isFiftyFifty ? 'var(--amber)' : 'var(--text-3)' }}>
        {isSettled ? (p.is_correct ? '✓' : '✗') : isFiftyFifty ? '—' : ''}
      </div>
    </Link>
  )
}

function TodayStrip({ today }) {
  const [showNoPicks, setShowNoPicks] = useState(false)
  if (!today) return null
  if (!today.predictions || today.predictions.length === 0) {
    return (
      <div className="card" style={{ padding: 18, color: 'var(--text-3)', textAlign: 'center', fontSize: 13 }}>
        No matches today.
      </div>
    )
  }
  const isNoPick = p => p.p1?.prob != null && Math.abs(p.p1.prob - 0.5) < 0.05
  const noPickCount = today.predictions.filter(isNoPick).length
  // Sort: settled first (results), then live, then upcoming
  const sorted = [...today.predictions]
    .filter(p => showNoPicks || !isNoPick(p))
    .sort((a, b) => {
      const aSettled = a.actual_winner ? 0 : 1
      const bSettled = b.actual_winner ? 0 : 1
      if (aSettled !== bSettled) return aSettled - bSettled
      const ta = a.event_time || '99:99'
      const tb = b.event_time || '99:99'
      return ta < tb ? -1 : 1
    })

  return (
    <div className="card" style={{ overflow: 'hidden', maxHeight: 360, overflowY: 'auto' }}>
      <div style={{
        display: 'grid', gridTemplateColumns: '50px 1fr 90px 1fr 90px 24px',
        padding: '8px 12px', background: 'var(--bg-raised)',
        borderBottom: '1px solid var(--border)', position: 'sticky', top: 0,
        fontSize: 9, fontWeight: 700, letterSpacing: 0.4,
        color: 'var(--text-3)', textTransform: 'uppercase',
      }}>
        <div>Time</div>
        <div>Player 1</div>
        <div style={{ textAlign: 'center' }}>Probability</div>
        <div>Player 2</div>
        <div></div>
        <div style={{ textAlign: 'right' }}>
          {noPickCount > 0 && (
            <button
              onClick={() => setShowNoPicks(v => !v)}
              title={showNoPicks ? 'Hide 50/50 no-picks' : `Show ${noPickCount} 50/50 no-picks`}
              style={{
                background: 'none', border: 'none', cursor: 'pointer', padding: 0,
                fontSize: 9, color: showNoPicks ? 'var(--amber)' : 'var(--text-3)',
                fontWeight: 700, letterSpacing: 0.3,
              }}
            >
              {showNoPicks ? '50/50 ✕' : `+${noPickCount}`}
            </button>
          )}
        </div>
      </div>
      {sorted.map(p => <TodayRow key={p.match_id} p={p} />)}
    </div>
  )
}

// ─── main page ───────────────────────────────────────────────────────────

export default function PredictionsResults() {
  useSEO({
    title: 'Tennis Predictions — P&L Tracker, ROI & Win Rate | RateThatTennis',
    description: 'Track AI tennis prediction performance: surface breakdown, P&L, ROI and accuracy by tour, confidence and edge. Free ML-powered predictions for ATP, WTA and Challenger.',
    canonical: 'https://ratethat.tennis/predictions',
  })
  const [data, setData]    = useState(null)
  const [today, setToday]  = useState(null)
  const [error, setError]  = useState(null)
  const [showTrend, setShowTrend] = useState(false)
  // Odds-mode toggle: 'rtt' = model-implied fair odds (1/prob_pick),
  //                   'book' = best bookmaker decimal odds at settle time.
  // Persists across reloads via localStorage.
  const [oddsMode, setOddsMode] = useState(() => {
    try { return localStorage.getItem('rtt_odds_mode') || 'rtt' }
    catch { return 'rtt' }
  })
  useEffect(() => {
    try { localStorage.setItem('rtt_odds_mode', oddsMode) } catch {}
  }, [oddsMode])

  useEffect(() => {
    let on = true
    Promise.all([api.predictionsResults(), api.predictionsToday(2)])
      .then(([d, t]) => { if (on) { setData(d); setToday(t) } })
      .catch(e => { if (on) setError(e.message) })
    return () => { on = false }
  }, [])

  if (error) return <div className="page"><div className="error">{error}</div></div>
  if (!data) return <div className="page"><div className="loading">Loading results…</div></div>
  // If the API error-wrapper returned {"error": "..."} as HTTP 200, catch it here
  // before the destructuring below causes a render crash on undefined all_time etc.
  if (data.error) return (
    <div className="page">
      <div className="card" style={{ padding: 20, margin: 20 }}>
        <div style={{ color: 'var(--red)', fontWeight: 700, marginBottom: 8 }}>Results API error</div>
        <div style={{ fontSize: 12, color: 'var(--text-3)', fontFamily: 'monospace' }}>{data.error}</div>
      </div>
    </div>
  )

  const { model_cutover, today: todayStats, all_time, last_30d, last_7d,
          streak, best_7d, worst_7d, weekly_bars, recent_picks,
          by_surface, by_tour, edge_buckets, calibration, pnl_trend } = data

  const todayStr = new Date().toISOString().slice(0, 10)
  const isCutoverToday = model_cutover === todayStr

  return (
    <div className="page">
      <div className="cc-header">
        <div>
          <h1 className="cc-title">Predictions</h1>
          <div className="cc-subtitle" style={{ display: 'flex', alignItems: 'center', gap: 10, flexWrap: 'wrap' }}>
            Today&apos;s matches and how the model is doing on its picks.
            {streak && <StreakBadge streak={streak} />}
          </div>
        </div>
        <div className="cc-meta-badges" style={{ display: 'flex', gap: 8, alignItems: 'center' }}>
          {/* Odds mode toggle: RTT (model fair odds) vs Best bookmaker price */}
          <div
            role="group"
            aria-label="Odds source"
            style={{
              display: 'inline-flex', padding: 2,
              border: '1px solid var(--border)',
              borderRadius: 'var(--r)',
              background: 'var(--bg-raised)',
            }}
          >
            {[
              { id: 'rtt',  label: 'RTT odds',     hint: 'P&L at the model\'s implied fair odds (1 / prob_pick)' },
              { id: 'book', label: 'Bookmaker odds', hint: 'P&L at the best bookmaker decimal odds we recorded' },
            ].map(opt => {
              const active = oddsMode === opt.id
              return (
                <button
                  key={opt.id}
                  onClick={() => setOddsMode(opt.id)}
                  title={opt.hint}
                  style={{
                    padding: '5px 10px',
                    fontSize: 11, fontWeight: 700, letterSpacing: 0.2,
                    borderRadius: 6,
                    background: active ? 'var(--text)' : 'transparent',
                    color:      active ? 'var(--text-inv)' : 'var(--text-3)',
                    border: 'none', cursor: 'pointer',
                  }}
                >
                  {opt.label}
                </button>
              )
            })}
          </div>
          <button
            onClick={() => setShowTrend(true)}
            style={{
              padding: '6px 12px', borderRadius: 'var(--r)',
              background: 'var(--bg-raised)', fontSize: 12, fontWeight: 600,
            }}
          >
            📈 P&amp;L trend
          </button>
        </div>
      </div>

      {/* Model-cutover banner */}
      {model_cutover && (
        <div className="card" style={{
          marginTop: 4, marginBottom: 12,
          padding: '10px 14px',
          background: 'var(--amber-bg)',
          border: '1px solid var(--amber-border)',
          fontSize: 12, color: 'var(--amber)',
          display: 'flex', alignItems: 'center', gap: 8,
        }}>
          <span style={{ fontSize: 14 }}>🆕</span>
          <span>
            <b>New model live since {model_cutover}{isCutoverToday ? ' (today)' : ''}.</b>
            {' '}Results cover predictions made on or after that date — the
            previous additive-logit predictor was retired and its history is excluded.
          </span>
        </div>
      )}

      {/* TODAY's results — uses today.summary so the numbers match the strip exactly */}
      {(() => {
        const s = today?.summary || {}
        const wins    = s.correct  ?? 0
        const settled = s.settled  ?? 0
        const winRate = settled > 0 ? Math.round(100 * wins / settled) : null
        const hasData = settled > 0
        // P&L from the /results todayStats (bookmaker-aware) — shown as a bonus column
        const v = pickStats(todayStats, oddsMode)
        const oddsLabel = oddsMode === 'book' ? 'book odds' : 'RTT odds'
        return (
          <div className="card" style={{
            padding: '10px 14px', marginBottom: 12,
            borderTop: `3px solid ${winRate == null ? 'var(--border)' : winRate >= 55 ? 'var(--green)' : winRate >= 45 ? 'var(--amber)' : 'var(--red)'}`,
            background: hasData ? 'var(--bg-card)' : 'var(--bg-raised)',
          }}>
            <div style={{
              display: 'flex', justifyContent: 'space-between', alignItems: 'baseline',
              marginBottom: 8,
            }}>
              <div style={{
                fontSize: 11, fontWeight: 700, color: 'var(--text-3)',
                textTransform: 'uppercase', letterSpacing: 0.5,
              }}>
                Today
              </div>
              <div style={{ fontSize: 10, color: 'var(--text-3)' }}>
                {hasData
                  ? `${settled} real picks settled (55%+ confidence) · matches below`
                  : 'No picks settled yet today'}
              </div>
            </div>
            <div style={{ display: 'grid', gridTemplateColumns: 'repeat(4, 1fr)', gap: 10 }}>
              <div>
                <div style={{ fontSize: 20, fontWeight: 700, fontVariantNumeric: 'tabular-nums', lineHeight: 1.1 }}>
                  {wins}<span style={{ color: 'var(--text-3)', fontWeight: 500 }}>/{settled}</span>
                </div>
                <div style={{ fontSize: 10, color: 'var(--text-3)', textTransform: 'uppercase', letterSpacing: 0.4, marginTop: 3 }}>
                  Wins / picks
                </div>
              </div>
              <div>
                <div style={{
                  fontSize: 20, fontWeight: 700, fontVariantNumeric: 'tabular-nums', lineHeight: 1.1,
                  color: winRate == null ? 'var(--text-3)'
                       : winRate >= 55 ? 'var(--green-text)'
                       : winRate >= 50 ? 'var(--text)' : 'var(--text-3)',
                }}>
                  {winRate != null ? `${winRate}%` : '—'}
                </div>
                <div style={{ fontSize: 10, color: 'var(--text-3)', textTransform: 'uppercase', letterSpacing: 0.4, marginTop: 3 }}>
                  Win rate
                </div>
              </div>
              <div>
                <div style={{
                  fontSize: 20, fontWeight: 700, fontVariantNumeric: 'tabular-nums', lineHeight: 1.1,
                  color: profitColour(v.pnl),
                }}>
                  {fmtMoney(v.pnl)}
                </div>
                <div style={{ fontSize: 10, color: 'var(--text-3)', textTransform: 'uppercase', letterSpacing: 0.4, marginTop: 3 }}>
                  P&amp;L · {oddsLabel}, £1 stake
                </div>
              </div>
              <div>
                <div style={{
                  fontSize: 20, fontWeight: 700, fontVariantNumeric: 'tabular-nums', lineHeight: 1.1,
                  color: profitColour(v.pnl),
                }}>
                  {fmtPct(v.roi)}
                </div>
                <div style={{ fontSize: 10, color: 'var(--text-3)', textTransform: 'uppercase', letterSpacing: 0.4, marginTop: 3 }}>
                  ROI
                </div>
              </div>
            </div>
          </div>
        )
      })()}

      {/* Today's matches list (still useful — shows pending and tomorrow too) */}
      <div style={{ marginBottom: 16 }}>
        <h3 style={{
          fontSize: 13, fontWeight: 700, marginBottom: 8,
          color: 'var(--text-2)', display: 'flex', alignItems: 'center',
          justifyContent: 'space-between',
        }}>
          <span>Today &amp; tomorrow's matches</span>
          {today?.summary && (
            <span style={{ fontSize: 11, fontWeight: 400, color: 'var(--text-3)' }}>
              {today.summary.total} matches · {today.summary.settled} settled · {today.summary.pending} pending
            </span>
          )}
        </h3>
        <TodayStrip today={today} />
      </div>

      {/* ─── Historic results section ─── */}
      <h3 style={{
        fontSize: 14, fontWeight: 700, marginTop: 28, marginBottom: 10,
        color: 'var(--text-2)', borderTop: '1px solid var(--border)',
        paddingTop: 18,
      }}>
        Historic results
      </h3>

      {(all_time?.picks ?? 0) === 0 && (
        <div className="card" style={{
          padding: 14, marginBottom: 12,
          background: 'var(--bg-raised)',
          fontSize: 12, color: 'var(--text-3)', textAlign: 'center',
        }}>
          No settled picks yet — results will start populating as today&apos;s matches finish.
        </div>
      )}

      {/* Top 3 stat blocks (use the active odds mode) */}
      {(() => {
        const a = pickStats(all_time, oddsMode)
        const m = pickStats(last_30d, oddsMode)
        const w = pickStats(last_7d,  oddsMode)
        // Label the leftmost block honestly: until the new model has been
        // live for >7 days, "All time" is identical to "Last 7 days" and
        // looks like a bug. Show "Since launch (YYYY-MM-DD)" instead.
        const cutoverLabel = model_cutover
          ? `Since launch (${model_cutover})`
          : 'All time'
        return (
          <div style={{
            display: 'grid', gridTemplateColumns: 'repeat(3, 1fr)',
            gap: 12,
          }}>
            <StatBlock label={cutoverLabel}
              picks={a.picks} wins={a.wins} winRate={a.winRate} pnl={a.pnl} roi={a.roi}
              accent="var(--text-2)" />
            <StatBlock label="Last 30 days"
              picks={m.picks} wins={m.wins} winRate={m.winRate} pnl={m.pnl} roi={m.roi}
              accent="var(--amber)" />
            <StatBlock label="Last 7 days"
              picks={w.picks} wins={w.wins} winRate={w.winRate} pnl={w.pnl} roi={w.roi}
              accent="var(--green)" />
          </div>
        )
      })()}

      {/* Best / worst pick of the week */}
      <div style={{
        display: 'grid', gridTemplateColumns: '1fr 1fr',
        gap: 12, marginTop: 12,
      }}>
        <HighlightCard title="Best pick · last 7d"  pick={best_7d}  accent="var(--green)" mode={oddsMode} />
        <HighlightCard title="Worst miss · last 7d" pick={worst_7d} accent="var(--red)"   mode={oddsMode} />
      </div>

      {/* 7-day bars */}
      <div className="card" style={{ marginTop: 16, padding: 14 }}>
        <div style={{
          fontSize: 13, fontWeight: 700, marginBottom: 8,
          display: 'flex', alignItems: 'center', justifyContent: 'space-between',
        }}>
          <span>Last 7 days</span>
          <span style={{ fontSize: 11, fontWeight: 400, color: 'var(--text-3)' }}>
            Bar height = predicted probability · green = won, red = lost
          </span>
        </div>
        <WeeklyBars items={weekly_bars} />
      </div>

      {/* Last 15 picks */}
      <div className="card" style={{ marginTop: 16, overflow: 'hidden' }}>
        <div style={{
          padding: '10px 14px', borderBottom: '1px solid var(--border)',
          background: 'var(--bg-raised)', fontSize: 13, fontWeight: 700,
          display: 'flex', alignItems: 'center', justifyContent: 'space-between',
        }}>
          <span>Recent picks</span>
          <span style={{ fontSize: 10, fontWeight: 400, color: 'var(--text-3)' }}>
            Last {recent_picks?.length ?? 0} settled picks — filter by outcome below
          </span>
        </div>
        <RecentPicksTable items={recent_picks} />
      </div>

      {/* Surface breakdown — 2x2 */}
      <div style={{ marginTop: 24 }}>
        <h3 style={{ fontSize: 14, fontWeight: 700, marginBottom: 10, color: 'var(--text-2)' }}>
          By surface
        </h3>
        <div style={{ display: 'grid', gridTemplateColumns: 'repeat(2, 1fr)', gap: 12 }}>
          <BreakdownCard title="🟧 Clay"   data={by_surface.Clay}   mode={oddsMode} surface="Clay" />
          <BreakdownCard title="🟦 Hard"   data={by_surface.Hard}   mode={oddsMode} surface="Hard" />
          <BreakdownCard title="🟩 Grass"  data={by_surface.Grass}  mode={oddsMode} surface="Grass" />
          <BreakdownCard title="🟪 Indoor" data={by_surface.Indoor} mode={oddsMode} surface="Indoor" />
        </div>
      </div>

      {/* Tour breakdown — 2x2 */}
      <div style={{ marginTop: 24 }}>
        <h3 style={{ fontSize: 14, fontWeight: 700, marginBottom: 10, color: 'var(--text-2)' }}>
          By tour
        </h3>
        <div style={{ display: 'grid', gridTemplateColumns: 'repeat(2, 1fr)', gap: 12 }}>
          <BreakdownCard title="ATP"        data={by_tour.ATP}        mode={oddsMode} />
          <BreakdownCard title="WTA"        data={by_tour.WTA}        mode={oddsMode} />
          <BreakdownCard title="Challenger" data={by_tour.Challenger} mode={oddsMode} />
          <BreakdownCard title="ITF"        data={by_tour.ITF}        mode={oddsMode} />
        </div>
      </div>

      {/* Edge buckets + calibration — 2 columns */}
      <div style={{
        display: 'grid', gridTemplateColumns: 'repeat(2, 1fr)',
        gap: 12, marginTop: 24,
      }}>
        <div className="card" style={{ overflow: 'hidden' }}>
          <div style={{
            padding: '10px 14px', borderBottom: '1px solid var(--border)',
            background: 'var(--bg-raised)', fontSize: 13, fontWeight: 700,
          }}>
            Edge buckets
          </div>
          <EdgeBuckets buckets={edge_buckets} />
        </div>
        <div className="card" style={{ overflow: 'hidden' }}>
          <div style={{
            padding: '10px 14px', borderBottom: '1px solid var(--border)',
            background: 'var(--bg-raised)', fontSize: 13, fontWeight: 700,
          }}>
            Calibration · predicted vs actual
          </div>
          <Calibration data={calibration} />
        </div>
      </div>

      {/* Systems tracker — historical performance + today's open picks */}
      <div style={{ marginTop: 28 }}>
        <h3 style={{
          fontSize: 14, fontWeight: 700, marginBottom: 4,
          color: 'var(--text-2)', borderTop: '1px solid var(--border)',
          paddingTop: 18,
        }}>
          Systems
        </h3>
        <div style={{ fontSize: 11, color: 'var(--text-3)', marginBottom: 12 }}>
          Strict-trigger picks — each system fires only when several
          independent edges align. Targeting 80%+ win rates with positive ROI.
          History accumulates with every settled pick.
        </div>
        <SystemsTracker />
      </div>

      {/* Footnote */}
      <div style={{ marginTop: 16, padding: 12, fontSize: 11, color: 'var(--text-3)', textAlign: 'center' }}>
        £1 flat stake. {oddsMode === 'book'
          ? <>P&amp;L computed at the best bookmaker decimal odds we recorded for each pick. Only picks with bookmaker odds count toward the totals — others are in the &quot;RTT odds&quot; view.</>
          : <>P&amp;L computed at RTT-implied odds (1/prob_pick), so the model only books a profit when it&apos;s under-confident — actual win rate beats stated probability.</>
        } 50/50 picks excluded.
      </div>

      {showTrend && <PnlTrendOverlay trend={pnl_trend || []} onClose={() => setShowTrend(false)} />}
    </div>
  )
}
