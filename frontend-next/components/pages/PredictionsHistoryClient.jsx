'use client'
import { useEffect, useState } from 'react'
import Link from 'next/link'
import { api } from '../../lib/api'

function AccuracyBar({ pct }) {
  if (pct == null) return <span style={{ color: 'var(--text-3)' }}>—</span>
  const colour = pct >= 65 ? 'var(--green)'
               : pct >= 50 ? 'var(--amber)'
               : 'var(--red)'
  return (
    <div style={{ display: 'flex', alignItems: 'center', gap: 8, minWidth: 110 }}>
      <div className="rating-bar-track" style={{ flex: 1, height: 5 }}>
        <div className="rating-bar-fill" style={{ width: `${pct}%`, background: colour }} />
      </div>
      <span style={{ fontSize: 12, fontWeight: 700, color: colour, minWidth: 38, textAlign: 'right' }}>
        {pct}%
      </span>
    </div>
  )
}

export default function PredictionsHistoryClient() {
  const [data, setData] = useState(null)
  const [day, setDay] = useState(null)         // expanded day
  const [dayDetail, setDayDetail] = useState(null)
  const [loadingDay, setLoadingDay] = useState(false)
  const [error, setError] = useState(null)

  useEffect(() => {
    let on = true
    api.predictionsHistory({ days: 30 })
       .then(d => { if (on) setData(d) })
       .catch(e => { if (on) setError(e.message) })
    return () => { on = false }
  }, [])

  const expand = (date) => {
    if (day === date) {
      setDay(null); setDayDetail(null); return
    }
    setDay(date); setLoadingDay(true)
    api.predictionsHistory({ date })
       .then(d => { setDayDetail(d); setLoadingDay(false) })
       .catch(e => { setError(e.message); setLoadingDay(false) })
  }

  if (error) return <div className="page"><div className="error">{error}</div></div>
  if (!data) return <div className="page"><div className="loading">Loading…</div></div>

  return (
    <div className="page">
      <div className="cc-header">
        <div>
          <h1 className="cc-title">Historic results</h1>
          <div className="cc-subtitle">
            Day-by-day prediction accuracy. Click a row to see every match.
          </div>
        </div>
        <div className="cc-meta-badges">
          <Link href="/predictions" className="surface-pill">← Today</Link>
          <Link href="/systems" className="surface-pill">Systems</Link>
        </div>
      </div>

      <div className="card" style={{ overflow: 'hidden' }}>
        <div style={{
          display: 'grid',
          gridTemplateColumns: '120px 1fr 1fr 60px 80px',
          padding: '10px 16px',
          borderBottom: '1px solid var(--border)',
          fontSize: 11,
          fontWeight: 600,
          color: 'var(--text-3)',
          textTransform: 'uppercase',
          letterSpacing: 0.4,
          background: 'var(--bg-raised)',
        }}>
          <div>Date</div>
          <div>Accuracy</div>
          <div>High-conf</div>
          <div>Picks</div>
          <div></div>
        </div>
        {data.days.map(d => (
          <div key={d.date}>
            <button
              onClick={() => expand(d.date)}
              style={{
                display: 'grid',
                gridTemplateColumns: '120px 1fr 1fr 60px 80px',
                padding: '12px 16px',
                borderBottom: '1px solid var(--border-faint)',
                width: '100%',
                textAlign: 'left',
                cursor: 'pointer',
                background: day === d.date ? 'var(--bg-raised)' : 'transparent',
              }}
            >
              <div style={{ fontSize: 13, fontWeight: 600 }}>{d.date}</div>
              <AccuracyBar pct={d.accuracy_pct} />
              <AccuracyBar pct={d.high_conf_accuracy_pct} />
              <div style={{ fontSize: 12, color: 'var(--text-2)' }}>
                {d.correct}/{d.settled}
              </div>
              <div style={{ textAlign: 'right' }}>
                <span className="chevron" style={{
                  transform: day === d.date ? 'rotate(90deg)' : 'rotate(0)',
                }}>▶</span>
              </div>
            </button>

            {day === d.date && (
              <div style={{ background: 'var(--bg-sunken)', padding: '8px 16px 14px' }}>
                {loadingDay ? (
                  <div style={{ padding: 12, textAlign: 'center', color: 'var(--text-3)' }}>
                    Loading matches…
                  </div>
                ) : dayDetail?.predictions?.length ? (
                  <div className="card" style={{ overflow: 'hidden' }}>
                    {dayDetail.predictions.map(p => {
                      const isCorrect = p.is_correct
                      const winner = p.actual_winner === 'first_player' ? p.p1?.name : p.p2?.name
                      const pick   = p.predicted_winner === 'first_player' ? p.p1?.name : p.p2?.name
                      return (
                        <Link
                          key={p.match_id}
                          href={`/match/${p.match_id}`}
                          style={{
                            display: 'grid',
                            gridTemplateColumns: '40px 1fr 110px 50px',
                            padding: '8px 14px',
                            borderBottom: '1px solid var(--border-faint)',
                            alignItems: 'center',
                          }}
                        >
                          <div style={{
                            color: isCorrect ? 'var(--green)' : 'var(--red)',
                            fontSize: 14,
                            fontWeight: 700,
                          }}>{isCorrect ? '✓' : '✗'}</div>
                          <div>
                            <div style={{ fontSize: 13, fontWeight: 500 }}>
                              {p.p1?.name} <span style={{ color: 'var(--text-3)' }}>vs</span> {p.p2?.name}
                            </div>
                            <div style={{ fontSize: 11, color: 'var(--text-3)' }}>
                              Pick: {pick} · Winner: {winner || '—'}
                              {p.surface && ` · ${p.surface}`}
                              {p.tournament && ` · ${p.tournament}`}
                            </div>
                          </div>
                          <div style={{ fontSize: 12, fontVariantNumeric: 'tabular-nums' }}>
                            {Math.round((p.predicted_winner === 'first_player' ? p.p1.prob : p.p2.prob) * 100)}%
                          </div>
                          <div>
                            <span className="confidence">
                              <span className={`confidence-dot ${p.confidence}`} />
                            </span>
                          </div>
                        </Link>
                      )
                    })}
                  </div>
                ) : (
                  <div style={{ padding: 12, color: 'var(--text-3)', fontSize: 13 }}>
                    No settled predictions on this day.
                  </div>
                )}
              </div>
            )}
          </div>
        ))}
      </div>
    </div>
  )
}
