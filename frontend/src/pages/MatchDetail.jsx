import { useState, useEffect, useRef } from 'react'
import { useParams, Link, useNavigate, useLocation } from 'react-router-dom'
import { matchUrl } from '../utils/matchUrl.js'
import { api } from '../api.js'
import SurfaceBadge from '../components/SurfaceBadge.jsx'
import EdgeBadge from '../components/EdgeBadge.jsx'
import ProbBar from '../components/ProbBar.jsx'
import FormChart from '../components/FormChart.jsx'
import StarPick from '../components/StarPick.jsx'
import courtClayImg  from '../assets/court-clay.jpg'
import courtGrassImg from '../assets/court-grass.jpg'
import courtHardImg  from '../assets/court-hard.jpg'

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
  const known = hand && hand !== 'Unknown'
  const isLeft = hand === 'Left'
  const bg   = !known ? '#f0ede8' : (isLeft ? '#e0f2fe' : '#f4f4f5')
  const txt  = !known ? '#a8a29e' : (isLeft ? '#0369a1' : '#52525b')
  const label = !known ? '?' : (isLeft ? 'L' : 'R')
  return (
    <span title={hand || 'hand unknown'} style={{
      display: 'inline-flex', alignItems: 'center', justifyContent: 'center',
      background: bg, color: txt,
      borderRadius: 20, padding: '2px 7px',
      fontSize: 11, fontWeight: 700,
      flexShrink: 0, minWidth: 18,
    }}>
      {label}
    </span>
  )
}

function OddsLozenge({ odds, edge }) {
  if (!odds) return null
  // Colour by edge: green = value, amber = marginal, neutral = no edge data
  const bg  = edge == null ? '#f0ede8' : edge >= 0.05 ? '#dcfce7' : edge >= 0.01 ? '#fef9c3' : '#f0ede8'
  const txt = edge == null ? '#78716c' : edge >= 0.05 ? '#15803d' : edge >= 0.01 ? '#a16207' : '#78716c'
  return (
    <span title={edge != null ? `RTT Edge: ${edge >= 0 ? '+' : ''}${(edge * 100).toFixed(1)}%` : 'Bookmaker odds'} style={{
      display: 'inline-flex', alignItems: 'center',
      background: bg, color: txt,
      borderRadius: 20, padding: '2px 9px',
      fontSize: 13, fontWeight: 700,
      fontVariantNumeric: 'tabular-nums', letterSpacing: '-0.3px',
      flexShrink: 0, cursor: 'default',
    }}>
      {odds.toFixed(2)}
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
// Non-sticky header (tournament info) — full-bleed court photo background
// ─────────────────────────────────────────────────────────────────────────────

function courtImage(surface) {
  const s = (surface || '').toLowerCase()
  if (s.includes('clay'))  return courtClayImg
  if (s.includes('grass')) return courtGrassImg
  if (s.includes('hard') || s.includes('indoor') || s.includes('carpet')) return courtHardImg
  return courtHardImg
}

function MatchMeta({ match }) {
  const pred   = match.prediction || {}
  const imgSrc = courtImage(match.surface)

  const confidenceColor = pred.confidence === 'high'   ? '#4ade80'
                        : pred.confidence === 'medium' ? '#fbbf24'
                        : 'rgba(255,255,255,0.5)'

  return (
    <div style={{
      position: 'relative',
      minHeight: 170,
      display: 'flex',
      flexDirection: 'column',
      justifyContent: 'center',
      alignItems: 'center',
      textAlign: 'center',
      overflow: 'hidden',
      padding: '28px 32px 24px',
      background: imgSrc ? undefined : 'var(--bg-sunken)',
    }}>

      {/* Court photo background */}
      {imgSrc && (
        <div style={{
          position: 'absolute', inset: 0,
          backgroundImage: `url(${imgSrc})`,
          backgroundSize: 'cover',
          backgroundPosition: 'center 40%',
        }} />
      )}

      {/* Dark gradient overlay for readability */}
      {imgSrc && (
        <div style={{
          position: 'absolute', inset: 0,
          background: 'linear-gradient(to bottom, rgba(0,0,0,0.55) 0%, rgba(0,0,0,0.68) 100%)',
        }} />
      )}

      {/* ← Today — top left */}
      <Link to="/" style={{
        position: 'absolute', top: 14, left: 18,
        color: 'rgba(255,255,255,0.85)',
        fontSize: 12, fontWeight: 500,
        zIndex: 2,
        textDecoration: 'none',
        letterSpacing: 0.1,
      }}>
        ← Today
      </Link>

      {/* Content — centred over image */}
      <div style={{ position: 'relative', zIndex: 2, width: '100%' }}>

        {/* Surface lozenge — centred */}
        <div style={{ marginBottom: 12 }}>
          <SurfaceBadge surface={match.surface} light />
        </div>

        {/* Tournament name */}
        <div style={{
          fontSize: 22, fontWeight: 800,
          color: '#ffffff',
          letterSpacing: '-0.4px',
          marginBottom: 4,
          textShadow: '0 1px 4px rgba(0,0,0,0.4)',
          lineHeight: 1.2,
        }}>
          {match.tournament}
        </div>

        {/* Round */}
        {match.round && (
          <div style={{
            fontSize: 14, fontWeight: 600,
            color: 'rgba(255,255,255,0.85)',
            marginBottom: 8,
            letterSpacing: 0.1,
            textShadow: '0 1px 3px rgba(0,0,0,0.4)',
          }}>
            {match.round}
          </div>
        )}

        {/* Confidence pill */}
        {pred.confidence && (
          <div style={{
            display: 'inline-flex', alignItems: 'center', gap: 6,
            background: 'rgba(0,0,0,0.35)',
            border: '1px solid rgba(255,255,255,0.18)',
            borderRadius: 999,
            padding: '4px 10px',
            fontSize: 11,
            color: 'rgba(255,255,255,0.95)',
            fontWeight: 600,
            letterSpacing: 0.2,
          }}>
            <span style={{
              display: 'inline-block',
              width: 6, height: 6, borderRadius: '50%',
              background: confidenceColor,
            }} />
            {pred.confidence} confidence
          </div>
        )}

        {/* Live score banner (in-play). Suppressed once the match is
            Finished — some matches stay stuck on is_live=true after the
            sync writes winner/final_result, and we'd rather show the
            final-score banner than a pulsing "IN PLAY" indicator on a
            match that's already over. */}
        {match.is_live && !/finished/i.test(match.status || '') &&
         (match.set_scores || match.game_result) && (
          <div style={{ marginTop: 14 }}>
            {match.set_scores && (
              <div style={{
                display: 'inline-block',
                background: 'rgba(0,0,0,0.5)',
                border: '1px solid rgba(255,255,255,0.25)',
                borderRadius: 8,
                padding: '6px 16px',
                marginBottom: 4,
              }}>
                <div style={{ fontSize: 11, fontWeight: 700, color: 'rgba(255,255,255,0.6)', textTransform: 'uppercase', letterSpacing: 1, marginBottom: 4 }}>
                  Live score
                </div>
                <div style={{ fontSize: 22, fontWeight: 900, color: '#ffffff', fontVariantNumeric: 'tabular-nums', letterSpacing: 1 }}>
                  {match.set_scores}
                </div>
                {match.game_result && (
                  <div style={{ fontSize: 13, fontWeight: 600, color: 'rgba(255,255,255,0.75)', marginTop: 2, fontVariantNumeric: 'tabular-nums' }}>
                    {match.game_result}
                  </div>
                )}
              </div>
            )}
            <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'center', gap: 5 }}>
              <span style={{ display: 'inline-block', width: 7, height: 7, borderRadius: '50%', background: '#FCD34D', animation: 'pulse 1.5s infinite' }} />
              <span style={{ fontSize: 11, fontWeight: 700, color: '#FCD34D', letterSpacing: 0.5 }}>IN PLAY</span>
            </div>
          </div>
        )}

        {/* Final-score banner (finished). Renders whenever status is
            Finished — even if is_live is stuck on (the live banner above
            already self-suppresses in that case, so there's no double
            render). Without this, finished matches show no score. */}
        {/finished/i.test(match.status || '') &&
         (match.set_scores || match.final_result) && (
          <div style={{ marginTop: 14, display: 'flex', flexDirection: 'column', alignItems: 'center', gap: 6 }}>
            <div style={{
              display: 'inline-block',
              background: 'rgba(0,0,0,0.5)',
              border: '1px solid rgba(255,255,255,0.25)',
              borderRadius: 8,
              padding: '6px 16px',
            }}>
              <div style={{ fontSize: 11, fontWeight: 700, color: 'rgba(255,255,255,0.6)', textTransform: 'uppercase', letterSpacing: 1, marginBottom: 4 }}>
                Final score
              </div>
              <div style={{ fontSize: 22, fontWeight: 900, color: '#ffffff', fontVariantNumeric: 'tabular-nums', letterSpacing: 1 }}>
                {match.set_scores || match.final_result}
              </div>
            </div>
            {match.winner && (
              <div style={{ fontSize: 11, fontWeight: 700, color: 'rgba(255,255,255,0.75)', letterSpacing: 0.5 }}>
                Winner: {match.winner === 'First Player'
                  ? (match.first_player?.name || 'First player')
                  : match.winner === 'Second Player'
                    ? (match.second_player?.name || 'Second player')
                    : match.winner}
              </div>
            )}
          </div>
        )}
      </div>
    </div>
  )
}

// ─────────────────────────────────────────────────────────────────────────────
// Sticky player + tabs bar
// ─────────────────────────────────────────────────────────────────────────────

function PlayerBar({ match, activeTab, onTabClick, tabRefs }) {
  const p1   = match.first_player  || {}
  const p2   = match.second_player || {}
  const pred = match.prediction    || {}
  const mkt  = match.market        || {}
  const edge = match.edge          || {}
  const p1odds = mkt.odds_first_player
  const p2odds = mkt.odds_second_player

  const TABS = [
    { id: 'intelligence', label: 'Intelligence' },
    { id: 'ratings',      label: 'Ratings' },
    { id: 'statistics',   label: 'Statistics' },
    { id: 'points',       label: 'Points Analysis' },
    { id: 'form',         label: 'Form' },
    { id: 'h2h',          label: 'Head to head' },
  ]

  // Prediction bar state derived from prediction + result
  const isFinished = /finished/i.test(match.status || '')
  const winnerSide = isFinished
    ? (match.winner === 'First Player' ? 1 : match.winner === 'Second Player' ? 2 : null)
    : null
  const p1Prob = pred.prob_first_player
  const p2Prob = pred.prob_second_player
  const isFiftyFifty = p1Prob != null && Math.abs(p1Prob - 0.5) < 0.01
  const predictedSide = (p1Prob != null && !isFiftyFifty)
    ? (p1Prob >= 0.5 ? 1 : 2)
    : null
  const predictionCorrect = (winnerSide && predictedSide)
    ? winnerSide === predictedSide
    : null

  return (
    <div style={{
      position: 'sticky',
      top: 52,
      zIndex: 90,
      background: 'var(--bg-card)',
      borderBottom: '1px solid var(--border)',
    }}>
      {/* Prediction / result bar — full width across the top */}
      <div style={{
        height: 6,
        display: 'flex',
        overflow: 'hidden',
      }}>
        {predictionCorrect === true ? (
          <div style={{ width: '100%', background: 'var(--green)' }} />
        ) : predictionCorrect === false ? (
          <div style={{ width: '100%', background: 'var(--red)' }} />
        ) : (winnerSide && !predictedSide) ? (
          <div style={{ width: '100%', background: 'var(--border)' }} />
        ) : (p1Prob != null && !isFiftyFifty) ? (
          <>
            <div style={{
              width: `${Math.round(p1Prob * 100)}%`,
              background: 'var(--green)',
              transition: 'width 0.5s ease',
            }} title={`${match.first_player?.name}: ${Math.round(p1Prob * 100)}%`} />
            <div style={{
              width: `${Math.round(p2Prob * 100)}%`,
              background: 'var(--blue)',
              transition: 'width 0.5s ease',
            }} title={`${match.second_player?.name}: ${Math.round(p2Prob * 100)}%`} />
          </>
        ) : (
          <div style={{ width: '100%', background: 'var(--border)' }} />
        )}
      </div>

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
            {!isFinished && p1.player_id && (
              <StarPick
                matchId={match.match_id}
                playerId={p1.player_id}
                playerName={p1.name}
                ourOdds={pred.prob_first_player ? Math.round((1 / pred.prob_first_player) * 100) / 100 : null}
                size="md"
              />
            )}
          </div>
          <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
            <OddsLozenge odds={p1odds} edge={edge.p1} />
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

        {/* Centre probability + pick label */}
        <div style={{ display: 'flex', flexDirection: 'column', alignItems: 'center', gap: 6, minWidth: 110 }}>
          {pred.prob_first_player != null ? (
            isFiftyFifty ? (
              <>
                <div style={{
                  fontSize: 12, fontWeight: 700, letterSpacing: 0.5,
                  textTransform: 'uppercase', color: 'var(--amber)',
                  padding: '4px 10px', borderRadius: 999,
                  background: 'var(--amber-bg)', border: '1px solid var(--amber-border)',
                }}>
                  Coin flip · no pick
                </div>
                <div style={{ fontSize: 11, color: 'var(--text-3)', textAlign: 'center', lineHeight: 1.3 }}>
                  Model has both players at 50% — this match is excluded from the pick-tracking accuracy stats.
                </div>
              </>
            ) : (
              <>
                <div style={{ display: 'flex', gap: 10, alignItems: 'baseline' }}>
                  <span style={{
                    fontSize: 22, fontWeight: 800, fontVariantNumeric: 'tabular-nums',
                    color: predictedSide === 1 ? 'var(--green)' : 'var(--text-3)',
                  }}>
                    {Math.round(pred.prob_first_player * 100)}%
                  </span>
                  <span style={{ fontSize: 12, color: 'var(--text-3)' }}>vs</span>
                  <span style={{
                    fontSize: 22, fontWeight: 800, fontVariantNumeric: 'tabular-nums',
                    color: predictedSide === 2 ? 'var(--blue)' : 'var(--text-3)',
                  }}>
                    {Math.round(pred.prob_second_player * 100)}%
                  </span>
                </div>
                <ProbBar p1={pred.prob_first_player} p2={pred.prob_second_player} name1="" name2="" />
                <div style={{
                  fontSize: 10, fontWeight: 700, letterSpacing: 0.5,
                  textTransform: 'uppercase', color: 'var(--text-3)',
                }}>
                  Pick:{' '}
                  <span style={{
                    color: predictedSide === 1 ? 'var(--green-text)' : 'var(--blue)',
                    fontWeight: 800,
                  }}>
                    {predictedSide === 1 ? (p1.name || 'P1') : (p2.name || 'P2')}
                  </span>
                </div>
              </>
            )
          ) : (
            <span style={{ fontSize: 18, fontWeight: 700, color: 'var(--text-3)' }}>vs</span>
          )}
        </div>

        {/* Player 2 */}
        <div style={{ display: 'flex', flexDirection: 'column', alignItems: 'flex-end', gap: 6 }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: 6, flexWrap: 'wrap', justifyContent: 'flex-end' }}>
            <RttLozenge score={p2.ratings?.rtt_score} />
            {!isFinished && p2.player_id && (
              <StarPick
                matchId={match.match_id}
                playerId={p2.player_id}
                playerName={p2.name}
                ourOdds={pred.prob_second_player ? Math.round((1 / pred.prob_second_player) * 100) / 100 : null}
                size="md"
              />
            )}
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
            <OddsLozenge odds={p2odds} edge={edge.p2} />
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

function IntelColumn({ title, body, accent, isLoading, footer }) {
  return (
    <div style={{
      background: 'var(--bg-card)',
      border: '1px solid var(--border)',
      borderRadius: 'var(--r-lg)',
      overflow: 'hidden',
      display: 'flex', flexDirection: 'column',
    }}>
      {/* Coloured top bar */}
      <div style={{ height: 4, background: accent }} />
      <div style={{ padding: '14px 18px 18px', flex: 1 }}>
        <div style={{
          fontSize: 11, fontWeight: 700, textTransform: 'uppercase',
          letterSpacing: '0.7px', color: accent, marginBottom: 12,
        }}>
          {title}
        </div>
        {isLoading ? (
          <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
            <div style={{ height: 12, background: 'var(--bg-raised)', borderRadius: 4 }} />
            <div style={{ height: 12, background: 'var(--bg-raised)', borderRadius: 4, width: '90%' }} />
            <div style={{ height: 12, background: 'var(--bg-raised)', borderRadius: 4, width: '75%' }} />
          </div>
        ) : body ? (
          <p style={{ margin: 0, fontSize: 14, color: 'var(--text-2)', lineHeight: 1.75 }}>
            {body}
          </p>
        ) : (
          <div style={{
            color: 'var(--text-3)', fontSize: 13, fontStyle: 'italic',
          }}>
            Awaiting deep-reasoning pass — typically generated within an hour of match time.
          </div>
        )}
      </div>
      {footer && (
        <div style={{
          padding: '10px 18px',
          background: 'var(--bg-raised)',
          borderTop: '1px solid var(--border-faint)',
          fontSize: 12, color: 'var(--text-2)', lineHeight: 1.5,
        }}>
          {footer}
        </div>
      )}
    </div>
  )
}


function SectionIntelligence({ match }) {
  const pred = match.prediction || {}
  const p1   = match.first_player  || {}
  const p2   = match.second_player || {}
  const bets  = pred.bet_recommendations || []
  const matchId = match.match_id || match.id

  const [intel, setIntel]     = useState(null)
  const [error, setError]     = useState(null)

  useEffect(() => {
    if (!matchId) return
    let on = true
    api.matchIntelligence(matchId)
       .then(d => { if (on) setIntel(d) })
       .catch(e => { if (on) setError(e.message) })
    return () => { on = false }
  }, [matchId])

  const loading = intel == null && !error
  const i = intel?.intel || {}
  const generatedAt = i.generated_at

  return (
    <div>
      {/* 3-column journalistic layout */}
      <div style={{
        display: 'grid',
        gridTemplateColumns: '1fr 1.4fr 1fr',
        gap: 12,
        marginBottom: 16,
      }}>
        <IntelColumn
          title={p1.name || 'Player 1'}
          body={i.p1_intel}
          accent="var(--green)"
          isLoading={loading}
        />
        <IntelColumn
          title="Match preview"
          body={i.match_preview}
          accent="var(--text)"
          isLoading={loading}
          footer={i.confidence_line ? (
            <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
              <span style={{
                width: 6, height: 6, borderRadius: '50%',
                background: pred.confidence === 'high' ? 'var(--green)'
                          : pred.confidence === 'medium' ? 'var(--amber)'
                          : 'var(--text-3)',
                flexShrink: 0,
              }} />
              <span><strong style={{ textTransform: 'capitalize' }}>{pred.confidence || 'low'} confidence</strong> · {i.confidence_line}</span>
            </div>
          ) : null}
        />
        <IntelColumn
          title={p2.name || 'Player 2'}
          body={i.p2_intel}
          accent="var(--blue)"
          isLoading={loading}
        />
      </div>

      {/* "Did you know" highlight bar */}
      {i.did_you_know && (
        <div style={{
          background: 'linear-gradient(90deg, #fef9e7 0%, #fef3c7 100%)',
          border: '1px solid #fde68a',
          borderRadius: 'var(--r-lg)',
          padding: '12px 18px',
          display: 'flex', alignItems: 'center', gap: 12,
          marginBottom: 16,
        }}>
          <span style={{
            fontSize: 10, fontWeight: 700,
            background: '#92400e', color: '#fffbeb',
            padding: '3px 8px', borderRadius: 12,
            textTransform: 'uppercase', letterSpacing: 0.6,
            flexShrink: 0,
          }}>
            Did you know
          </span>
          <span style={{ fontSize: 14, color: '#78350f', lineHeight: 1.5 }}>
            {i.did_you_know}
          </span>
        </div>
      )}


      {/* Bet recommendations — kept below the journalistic block */}
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

      {error && (
        <div className="error" style={{ marginTop: 12 }}>
          Couldn't load intelligence: {error}
        </div>
      )}

      {/* Bookmaker odds — split panel */}
      {(() => {
        const mkt    = match.market || {}
        const allBk  = mkt.all_bookmakers || []
        const p1prob = pred.prob_first_player
        const p2prob = pred.prob_second_player

        const calcEdge  = (odds, prob) => (!odds || !prob) ? null : Math.round((prob - (1 / odds)) * 1000) / 1000
        const fmtEdge   = (e) => e == null ? null : (e >= 0 ? '+' : '') + (e * 100).toFixed(1) + '%'

        // Best odds per player across all bookmakers
        const bestP1bk = allBk.reduce((best, bk) => (!bk.p1_odds ? best : (!best || bk.p1_odds > best.p1_odds ? bk : best)), null)
        const bestP2bk = allBk.reduce((best, bk) => (!bk.p2_odds ? best : (!best || bk.p2_odds > best.p2_odds ? bk : best)), null)
        const bestP1   = bestP1bk?.p1_odds ?? mkt.odds_first_player
        const bestP2   = bestP2bk?.p2_odds ?? mkt.odds_second_player
        const bk1name  = bestP1bk?.bookmaker ?? mkt.bookmaker
        const bk2name  = bestP2bk?.bookmaker ?? mkt.bookmaker
        const e1       = calcEdge(bestP1, p1prob)
        const e2       = calcEdge(bestP2, p2prob)
        const hasOdds  = bestP1 || bestP2

        const EdgePill = ({ edge }) => {
          if (edge == null) return null
          const positive = edge > 0
          const neutral  = Math.abs(edge) < 0.01
          const bg  = neutral ? 'var(--bg-sunken)' : positive ? 'rgba(22,101,52,0.12)' : 'rgba(220,38,38,0.10)'
          const col = neutral ? 'var(--text-3)'    : positive ? '#15803d'               : '#dc2626'
          const bdr = neutral ? 'var(--border)'    : positive ? 'rgba(22,101,52,0.3)'   : 'rgba(220,38,38,0.3)'
          return (
            <span style={{
              display: 'inline-block',
              background: bg, color: col, border: `1px solid ${bdr}`,
              borderRadius: 20, padding: '3px 10px',
              fontSize: 13, fontWeight: 800, letterSpacing: '-0.2px',
            }}>
              RTT Edge {fmtEdge(edge)}
            </span>
          )
        }

        const OddsPill = ({ odds }) => odds == null ? <span style={{ fontSize: 22, fontWeight: 800, color: 'var(--text-3)' }}>—</span> : (
          <span style={{
            display: 'inline-block',
            background: 'var(--bg-card)', border: '2px solid var(--border)',
            borderRadius: 10, padding: '6px 16px',
            fontSize: 24, fontWeight: 900, color: 'var(--text)',
            fontVariantNumeric: 'tabular-nums', letterSpacing: '-0.5px',
          }}>
            {odds.toFixed(2)}
          </span>
        )

        return (
          <div style={{
            marginTop: 20,
            border: '1px solid var(--border)',
            borderRadius: 'var(--r-lg)',
            overflow: 'hidden',
          }}>
            {/* Header */}
            <div style={{
              padding: '8px 16px',
              background: 'var(--bg-raised)',
              borderBottom: '1px solid var(--border)',
              fontSize: 10, fontWeight: 700, textTransform: 'uppercase',
              letterSpacing: '0.7px', color: 'var(--text-3)',
            }}>
              Best bookmaker odds
            </div>

            {hasOdds ? (
              <div style={{
                display: 'grid', gridTemplateColumns: '1fr 1fr',
                background: 'var(--bg-card)',
              }}>
                {/* P1 — left aligned */}
                <div style={{
                  padding: '20px 24px',
                  borderRight: '1px solid var(--border)',
                  display: 'flex', flexDirection: 'column', gap: 10, alignItems: 'flex-start',
                }}>
                  <div style={{ fontSize: 11, fontWeight: 600, color: 'var(--text-3)', textTransform: 'uppercase', letterSpacing: '0.5px' }}>
                    {p1.name}
                  </div>
                  <OddsPill odds={bestP1} />
                  {bk1name && (
                    <span style={{ fontSize: 12, color: 'var(--text-3)' }}>{bk1name}</span>
                  )}
                  <EdgePill edge={e1} />
                </div>

                {/* P2 — right aligned */}
                <div style={{
                  padding: '20px 24px',
                  display: 'flex', flexDirection: 'column', gap: 10, alignItems: 'flex-end',
                }}>
                  <div style={{ fontSize: 11, fontWeight: 600, color: 'var(--text-3)', textTransform: 'uppercase', letterSpacing: '0.5px' }}>
                    {p2.name}
                  </div>
                  <OddsPill odds={bestP2} />
                  {bk2name && (
                    <span style={{ fontSize: 12, color: 'var(--text-3)' }}>{bk2name}</span>
                  )}
                  <EdgePill edge={e2} />
                </div>
              </div>
            ) : (
              <div style={{ padding: '20px 24px', fontSize: 12, color: 'var(--text-3)', fontStyle: 'italic', textAlign: 'center' }}>
                Odds not yet available — fetched automatically at 07:00 and 19:00 UTC
              </div>
            )}

            {/* Collapsible all-bookmakers dropdown */}
            {allBk.length > 1 && (
              <details style={{ borderTop: '1px solid var(--border-faint)' }}>
                <summary style={{
                  padding: '8px 16px', fontSize: 11, color: 'var(--text-3)', cursor: 'pointer',
                  listStyle: 'none', display: 'flex', alignItems: 'center', gap: 6, userSelect: 'none',
                }}>
                  <span style={{ fontSize: 9 }}>▸</span>
                  All bookmakers ({allBk.length})
                </summary>
                <div style={{ borderTop: '1px solid var(--border-faint)' }}>
                  <div style={{
                    display: 'grid', gridTemplateColumns: '1fr auto auto auto',
                    padding: '6px 16px', background: 'var(--bg-sunken)',
                    fontSize: 10, fontWeight: 700, textTransform: 'uppercase',
                    letterSpacing: '0.5px', color: 'var(--text-3)', gap: 16,
                  }}>
                    <span>Bookmaker</span>
                    <span style={{ minWidth: 44, textAlign: 'right' }}>{p1.name?.split(' ').pop()}</span>
                    <span style={{ minWidth: 44, textAlign: 'right' }}>{p2.name?.split(' ').pop()}</span>
                    <span style={{ minWidth: 70, textAlign: 'right' }}>RTT Edge</span>
                  </div>
                  {allBk.map((bk, idx) => {
                    const re1 = calcEdge(bk.p1_odds, p1prob)
                    const re2 = calcEdge(bk.p2_odds, p2prob)
                    const topEdge = re1 != null && (re2 == null || Math.abs(re1) >= Math.abs(re2))
                      ? { name: p1.name?.split(' ').pop(), val: re1 }
                      : re2 != null ? { name: p2.name?.split(' ').pop(), val: re2 } : null
                    const edgeCol = topEdge ? (topEdge.val > 0.01 ? '#15803d' : topEdge.val < -0.01 ? '#dc2626' : 'var(--text-3)') : 'var(--text-3)'
                    return (
                      <div key={bk.bookmaker} style={{
                        display: 'grid', gridTemplateColumns: '1fr auto auto auto',
                        padding: '8px 16px', gap: 16,
                        borderTop: '1px solid var(--border-faint)', alignItems: 'center',
                        background: idx === 0 ? 'rgba(99,153,34,0.04)' : 'transparent',
                      }}>
                        <span style={{ fontSize: 12, color: 'var(--text-2)', fontWeight: idx === 0 ? 600 : 400 }}>
                          {idx === 0 && <span style={{ fontSize: 9, background: 'var(--green)', color: '#fff', padding: '1px 5px', borderRadius: 4, marginRight: 5, fontWeight: 700 }}>BEST</span>}
                          {bk.bookmaker}
                        </span>
                        <span style={{ minWidth: 44, textAlign: 'right', fontSize: 13, fontWeight: 700, fontVariantNumeric: 'tabular-nums' }}>{bk.p1_odds?.toFixed(2) ?? '—'}</span>
                        <span style={{ minWidth: 44, textAlign: 'right', fontSize: 13, fontWeight: 700, fontVariantNumeric: 'tabular-nums' }}>{bk.p2_odds?.toFixed(2) ?? '—'}</span>
                        <span style={{ minWidth: 70, textAlign: 'right', fontSize: 11, fontWeight: 700, color: edgeCol }}>
                          {topEdge ? `${topEdge.name} ${fmtEdge(topEdge.val)}` : '—'}
                        </span>
                      </div>
                    )
                  })}
                </div>
              </details>
            )}

            <div style={{ padding: '6px 16px', borderTop: '1px solid var(--border-faint)', fontSize: 10, color: 'var(--text-3)', fontStyle: 'italic' }}>
              RTT Edge = our model probability minus bookmaker implied probability · For reference only · Please gamble responsibly
            </div>
          </div>
        )
      })()}
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
  const surface = (match.surface || '').toLowerCase()
  const round = (match.round || '').toUpperCase()

  // Map current surface to the right column key
  const surfaceKey = surface.includes('clay') ? 'clay_rating'
                   : surface.includes('grass') ? 'grass_rating'
                   : surface.includes('indoor') || surface.includes('carpet') ? 'indoor_rating'
                   : 'hard_rating'
  const surfaceLabel = surface.includes('clay') ? 'Clay'
                     : surface.includes('grass') ? 'Grass'
                     : surface.includes('indoor') || surface.includes('carpet') ? 'Indoor'
                     : 'Hard'

  const isLateRound = ['F', 'SF', 'QF'].includes(round)
  // Heuristic: opponent in top 10 = rtt_score >= 90. (Approximation — we don't store rank.)
  const opp1IsTop10 = (r2.rtt_score || 0) >= 90
  const opp2IsTop10 = (r1.rtt_score || 0) >= 90
  const isBigMatch = (match.event_type || '').toLowerCase().includes('grand slam')
                  || (match.event_type || '').toLowerCase().includes('masters')

  // The vs-hand rating shows P1's record vs P2's hand, and vice versa.
  // The label here describes from P1's perspective (the column on the left of the bar).
  // If P2's hand is unknown, we default to "right-handers" (~88% of pros) and
  // suffix the label with a tiny "?" so it's clear we're guessing.
  const p1OppHand = (match.context?.p2_hand || p2.hand || '').toLowerCase()
  const p2OppHand = (match.context?.p1_hand || p1.hand || '').toLowerCase()
  const labelHand = (h) => h.startsWith('l') ? 'left-handers'
                          : h.startsWith('r') ? 'right-handers'
                          : 'right-handers (assumed)'
  const vsHandLabel = `vs ${labelHand(p1OppHand)}`

  // ALL relevant ratings, always shown (with — for missing). We don't hide rows
  // when there's no data — the user wants to see what we track.
  const rows = [
    { label: 'RTT Score',                          k: 'rtt_score',          always: true },
    { label: `${surfaceLabel} rating`,             k: surfaceKey,           always: true },
    { label: 'Form',                               k: 'form_score',         always: true },
    { label: 'Serve',                              k: 'serve_rating',       always: true },
    { label: 'Return',                             k: 'return_rating',      always: true },
    { label: vsHandLabel,                           k: 'vs_hand',            always: true },
    { label: 'Endurance (long matches)',           k: 'endurance',          always: true },
    { label: 'Tournament level',                   k: 'tournament_level',   always: true },
    { label: 'Pressure rating',                    k: 'pressure_rating',    show: isLateRound, hint: 'Late round' },
    { label: 'Big match rating',                   k: 'big_match_rating',   show: isBigMatch, hint: 'Slam / Masters' },
    { label: 'vs Top 10',                          k: 'vs_top10_rating',    show: opp1IsTop10 || opp2IsTop10, hint: 'Top-10 opponent' },
  ].filter(r => r.always || r.show)

  return (
    <div>
      {/* Player name header */}
      <div style={{
        display: 'flex', justifyContent: 'space-between',
        fontSize: 13, fontWeight: 700,
        marginBottom: 12, padding: '0 4px',
      }}>
        <span style={{ color: 'var(--green)' }}>{p1.name}</span>
        <span style={{ color: 'var(--blue)' }}>{p2.name}</span>
      </div>

      <div style={{
        background: 'var(--bg-card)', border: '1px solid var(--border)',
        borderRadius: 'var(--r-lg)', padding: '18px 22px',
        marginBottom: 10,
      }}>
        <div style={{
          fontSize: 10, fontWeight: 700, textTransform: 'uppercase',
          letterSpacing: '0.7px', color: 'var(--text-3)', marginBottom: 14,
        }}>
          Ratings — every dimension relevant to {surfaceLabel.toLowerCase()} {match.round ? `· ${match.round}` : ''}
        </div>
        <div style={{ display: 'flex', flexDirection: 'column', alignItems: 'center' }}>
          {rows.map(({ label, k, hint }) => (
            <RatingRow key={k} label={hint ? `${label}` : label} v1={r1[k]} v2={r2[k]} />
          ))}
        </div>
      </div>

      <div style={{ fontSize: 11, color: 'var(--text-3)', marginTop: 8, textAlign: 'center' }}>
        Ratings are 0–100. Missing values show as — and indicate not enough match data yet.
      </div>
    </div>
  )
}

// ─────────────────────────────────────────────────────────────────────────────
// Form — chart + racecard rows
// ─────────────────────────────────────────────────────────────────────────────

// Format ISO date as short "8 May" / "23 Jan" form.
function fmtShortDate(iso) {
  if (!iso) return ''
  const s = String(iso).slice(0, 10)
  const m = s.match(/(\d{4})-(\d{2})-(\d{2})/)
  if (!m) return s
  const months = ['Jan','Feb','Mar','Apr','May','Jun','Jul','Aug','Sep','Oct','Nov','Dec']
  const day = parseInt(m[3], 10)
  const mon = months[parseInt(m[2], 10) - 1] || ''
  const yearShort = m[1].slice(2)
  return `${day} ${mon} '${yearShort}`
}

// FormRacecard: chip on the INSIDE of the column (right edge of left col,
// left edge of right col — i.e. closest to the centre divider). Reading
// from the centre outward: chip → W/L → opponent → ... → date+score on the
// far edge (left-aligned in left col, right-aligned in right col).
//
// L→R reading order:
//   align='left'  (P1)  → [date · score]              [opponent] [W/L] [chip]   ← chip hugs centre
//   align='right' (P2)  → [chip] [W/L] [opponent]              [date · score]   ← chip hugs centre
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

        // Date + score on a SINGLE line, sitting on the outside edge of the column.
        const dateScoreBlock = (
          <div style={{
            flexShrink: 0,
            textAlign: isRight ? 'right' : 'left',
            fontSize: 11, fontWeight: 500, color: 'var(--text-3)',
            whiteSpace: 'nowrap',
            display: 'flex', gap: 6, alignItems: 'baseline',
            justifyContent: isRight ? 'flex-end' : 'flex-start',
          }}>
            <span style={{ color: 'var(--text-2)', fontWeight: 600 }}>
              {fmtShortDate(m.date)}
            </span>
            {m.score && (
              <span style={{
                fontFamily: 'var(--font-mono)', fontSize: 10,
                color: 'var(--text-3)',
              }}>
                {m.score}
              </span>
            )}
          </div>
        )

        // Opponent text aligns toward the chip (= toward the centre divider):
        // LEFT col → opponent is right-aligned (toward chip on its right)
        // RIGHT col → opponent is left-aligned (toward chip on its left)
        const opponentText = (
          <div style={{ flex: 1, minWidth: 0, textAlign: isRight ? 'left' : 'right' }}>
            <div style={{
              fontSize: 12, fontWeight: 500, color: 'var(--text-2)',
              whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis',
            }}>
              {m.opponent_name || 'Unknown'}
            </div>
          </div>
        )

        // Layout (chip on the INSIDE = closest to centre divider,
        //         date+score on the OUTSIDE = column edge):
        //   LEFT col, left→right:  [date · score] [opponent] [W/L] [chip]
        //   RIGHT col, left→right: [chip] [W/L] [opponent] [date · score]
        return (
          <div key={i} style={{
            display: 'flex',
            alignItems: 'center',
            gap: 8,
            padding: '6px 0',
            borderBottom: i < Math.min(matches.length, 10) - 1 ? '1px solid var(--border-faint)' : 'none',
          }}>
            {isRight ? (
              <>
                {chip}
                {wlBadge}
                {opponentText}
                {dateScoreBlock}
              </>
            ) : (
              <>
                {dateScoreBlock}
                {opponentText}
                {wlBadge}
                {chip}
              </>
            )}
          </div>
        )
      })}
    </div>
  )
}

// ─────────────────────────────────────────────────────────────────────────────
// Statistics tab — 8 metrics per player as pastel-coloured stat cards
// ─────────────────────────────────────────────────────────────────────────────

function StatCard({ label, value }) {
  // value is { value, label, tier, context }
  const v = value || {}
  const tier = v.tier || 'neutral'
  // Stronger pastels — designed to read at a glance
  const palette = {
    good:    { bg: '#dcfce7', border: '#86efac', headline: '#15803d', muted: '#166534' },
    average: { bg: '#fef3c7', border: '#fcd34d', headline: '#b45309', muted: '#92400e' },
    bad:     { bg: '#fee2e2', border: '#fca5a5', headline: '#b91c1c', muted: '#991b1b' },
    neutral: { bg: '#FFFFFF', border: '#E0DBCF', headline: '#78716c', muted: '#a8a29e' },
  }[tier] || { bg: '#FFFFFF', border: '#E0DBCF', headline: '#78716c', muted: '#a8a29e' }

  const isMissing = v.value == null
  const headlineText = isMissing ? '—' : (v.label || String(v.value))
  return (
    <div style={{
      background: palette.bg, border: `1px solid ${palette.border}`,
      borderRadius: 10, padding: '14px 16px',
      display: 'flex', flexDirection: 'column', gap: 4,
      minHeight: 84,
    }}>
      <div style={{
        fontSize: 10, color: palette.muted,
        textTransform: 'uppercase', letterSpacing: 0.6, fontWeight: 700,
        opacity: isMissing ? 0.55 : 0.85,
      }}>
        {label}
      </div>
      <div style={{
        fontSize: 22, fontWeight: 800, color: palette.headline,
        fontVariantNumeric: 'tabular-nums', letterSpacing: '-0.6px',
        lineHeight: 1.1,
        opacity: isMissing ? 0.4 : 1,
      }}>
        {headlineText}
      </div>
      {v.context && !isMissing && (
        <div style={{
          fontSize: 10, color: palette.muted, opacity: 0.7,
          fontWeight: 500, marginTop: 'auto',
        }}>
          {v.context}
        </div>
      )}
      {isMissing && (
        <div style={{
          fontSize: 10, color: palette.muted, opacity: 0.55,
          fontStyle: 'italic', marginTop: 'auto',
        }}>
          Not enough match data yet
        </div>
      )}
    </div>
  )
}

const STATS_LIST = [
  { key: 'days_rest',   label: 'Days since last match' },
  { key: 'streak',      label: 'Current streak' },
  { key: 'comeback',    label: 'Comeback rate' },
  { key: 'closeout',    label: 'Closeout rate' },
  { key: 'vs_higher',   label: 'Perf. vs higher rank' },
  { key: 'vs_lower',    label: 'Perf. vs lower rank' },
  { key: 'endurance',   label: 'Endurance win rate' },
  { key: 'time_of_day', label: 'Time-of-day preference' },
]

function SectionStatistics({ match }) {
  const p1 = match.first_player  || {}
  const p2 = match.second_player || {}
  const m1 = p1.metrics || {}
  const m2 = p2.metrics || {}

  // Each player gets its own 2-column grid (4 stats wide, 4 rows tall = 8 cards).
  // The two players sit side-by-side with a divider between them.
  const renderPlayerGrid = (m, accentColor) => (
    <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 8 }}>
      {STATS_LIST.map(({ key, label }) => (
        <StatCard key={key} label={label} value={m[key]} />
      ))}
    </div>
  )

  return (
    <div>
      <div style={{
        display: 'grid',
        gridTemplateColumns: '1fr 1fr',
        gap: 16,
      }}>
        {/* P1 column */}
        <div>
          <div style={{
            fontSize: 13, fontWeight: 700,
            color: 'var(--green)', letterSpacing: '-0.2px',
            marginBottom: 10, padding: '0 2px',
          }}>
            {p1.name}
          </div>
          {renderPlayerGrid(m1, 'green')}
        </div>

        {/* P2 column */}
        <div>
          <div style={{
            fontSize: 13, fontWeight: 700,
            color: 'var(--blue)', letterSpacing: '-0.2px',
            marginBottom: 10, padding: '0 2px', textAlign: 'right',
          }}>
            {p2.name}
          </div>
          {renderPlayerGrid(m2, 'blue')}
        </div>
      </div>

      <div style={{ fontSize: 11, color: 'var(--text-3)', marginTop: 16, textAlign: 'center' }}>
        From production matches in the last 24 months. Green = good, amber = average, red = bad.
      </div>

      {/* Career serve averages — sourced from sa_matches historical data.
          Wired through /api/v1/matches/{id} → player.career_serve. These
          numbers were previously available at /players/{id}/stats but had
          no home on the match page. */}
      <CareerServePanel p1={p1} p2={p2} />
    </div>
  )
}


function CareerServePanel({ p1, p2 }) {
  const cs1 = p1.career_serve || {}
  const cs2 = p2.career_serve || {}
  // Hide if neither side has any career data — common for ITF / Challenger
  if (!cs1.sample_size && !cs2.sample_size) return null

  return (
    <div style={{ marginTop: 24 }}>
      <div style={{
        fontSize: 13, fontWeight: 700, color: 'var(--text-2)',
        marginBottom: 10, borderTop: '1px solid var(--border-faint)',
        paddingTop: 14, textAlign: 'center',
      }}>
        Career serve averages
      </div>

      {/* Same centred bar/lozenge/label/lozenge/bar layout as the Points
          Analysis section so the eye reads the comparison consistently. */}
      <PointsBar label="1st serve in"     v1={cs1.avg_1st_serve_pct} v2={cs2.avg_1st_serve_pct}
                 good={65} avg={55} betterIsHigher
                 sample1={cs1.sample_size} sample2={cs2.sample_size} />
      <PointsBar label="1st serve won"    v1={cs1.avg_1st_won_pct}   v2={cs2.avg_1st_won_pct}
                 good={75} avg={65} betterIsHigher
                 sample1={cs1.sample_size} sample2={cs2.sample_size} />
      <PointsBar label="2nd serve won"    v1={cs1.avg_2nd_won_pct}   v2={cs2.avg_2nd_won_pct}
                 good={55} avg={45} betterIsHigher
                 sample1={cs1.sample_size} sample2={cs2.sample_size} />
      <PointsBar label="Ace rate"         v1={cs1.avg_ace_pct}       v2={cs2.avg_ace_pct}
                 good={10} avg={5}  betterIsHigher
                 sample1={cs1.sample_size} sample2={cs2.sample_size} />
      <PointsBar label="Double-fault rate" v1={cs1.avg_df_pct}        v2={cs2.avg_df_pct}
                 good={3}  avg={5}  betterIsHigher={false}
                 sample1={cs1.sample_size} sample2={cs2.sample_size} />
      <PointsBar label="BP saved"         v1={cs1.avg_bp_save_pct}   v2={cs2.avg_bp_save_pct}
                 good={65} avg={55} betterIsHigher
                 sample1={cs1.sample_size} sample2={cs2.sample_size} />

      <div style={{ fontSize: 10, color: 'var(--text-3)', marginTop: 8, textAlign: 'center' }}>
        Lifetime averages from our training data ({cs1.sample_size || 0} / {cs2.sample_size || 0} matches respectively).
      </div>
    </div>
  )
}


// ─────────────────────────────────────────────────────────────────────────────
// Points Analysis tab — service hold %, break %, BP save/conversion, etc.
// ─────────────────────────────────────────────────────────────────────────────

// Pastel colour scaled per-metric — each stat has its own "good / average / bad" thresholds.
function pointsPastel(value, good, avg, betterIsHigher = true) {
  if (value == null) return null
  const v = Number(value)
  const passes = (threshold) => betterIsHigher ? v >= threshold : v <= threshold
  if (passes(good))  return { bg: '#bbf0d0', text: '#166534' }   // green — strong
  if (passes(avg))   return { bg: '#fef3c7', text: '#92400e' }   // amber — average
  return                    { bg: '#fecaca', text: '#991b1b' }   // red   — below par
}


function PointsBar({ label, v1, v2, suffix = '%', good = 70, avg = 55,
                     betterIsHigher = true, sample1, sample2 }) {
  const n1 = v1 != null ? Number(v1) : null
  const n2 = v2 != null ? Number(v2) : null
  const maxBar = 80

  // Bar widths
  const w1 = n1 != null ? Math.round((Math.min(n1, 100) / 100) * maxBar) : 0
  const w2 = n2 != null ? Math.round((Math.min(n2, 100) / 100) * maxBar) : 0

  // Lozenge colour — per-metric threshold instead of generic RTT scale
  const chip1 = pointsPastel(n1, good, avg, betterIsHigher)
  const chip2 = pointsPastel(n2, good, avg, betterIsHigher)

  // Which side has the advantage? Drives the bar colour
  const advantage = (n1 != null && n2 != null)
    ? (betterIsHigher ? (n1 > n2 ? 'p1' : n2 > n1 ? 'p2' : 'eq')
                      : (n1 < n2 ? 'p1' : n2 < n1 ? 'p2' : 'eq'))
    : null

  const t1 = sample1 != null ? `Based on ${sample1} samples` : ''
  const t2 = sample2 != null ? `Based on ${sample2} samples` : ''

  // Format: "75%" or "8.4 pts" — drop suffix-only when 0
  const fmt = (n) => n == null ? '—' :
    suffix === '%' ? `${Math.round(n)}` :
    `${n.toFixed(1)}${suffix}`

  return (
    <div style={{
      display: 'grid',
      gridTemplateColumns: `${maxBar}px 44px 160px 44px ${maxBar}px`,
      alignItems: 'center',
      gap: 6,
      margin: '6px auto',
      maxWidth: 460,
    }}>
      {/* P1 bar (grows left) */}
      <div title={t1} style={{ display: 'flex', justifyContent: 'flex-end', alignItems: 'center' }}>
        <div style={{
          width: w1, height: 6, borderRadius: 3,
          background: advantage === 'p1' ? '#bbf0d0' :
                      advantage === 'p2' ? '#fecaca' :
                      n1 != null ? '#fef3c7' : 'var(--bg-raised)',
          transition: 'width 0.5s ease',
        }} />
      </div>

      {/* P1 lozenge */}
      {chip1 ? (
        <div title={t1} style={{
          background: chip1.bg, color: chip1.text,
          borderRadius: 6, padding: '2px 6px',
          fontSize: 13, fontWeight: 700, textAlign: 'center',
          fontVariantNumeric: 'tabular-nums',
        }}>
          {fmt(n1)}{suffix === '%' && n1 != null ? '%' : ''}
        </div>
      ) : (
        <div style={{ fontSize: 12, color: 'var(--text-3)', textAlign: 'center' }}>—</div>
      )}

      {/* Label */}
      <div style={{ textAlign: 'center', fontSize: 11,
                    color: 'var(--text-3)', fontWeight: 500 }}>
        {label}
      </div>

      {/* P2 lozenge */}
      {chip2 ? (
        <div title={t2} style={{
          background: chip2.bg, color: chip2.text,
          borderRadius: 6, padding: '2px 6px',
          fontSize: 13, fontWeight: 700, textAlign: 'center',
          fontVariantNumeric: 'tabular-nums',
        }}>
          {fmt(n2)}{suffix === '%' && n2 != null ? '%' : ''}
        </div>
      ) : (
        <div style={{ fontSize: 12, color: 'var(--text-3)', textAlign: 'center' }}>—</div>
      )}

      {/* P2 bar (grows right) */}
      <div title={t2}>
        <div style={{
          width: w2, height: 6, borderRadius: 3,
          background: advantage === 'p2' ? '#bbf0d0' :
                      advantage === 'p1' ? '#fecaca' :
                      n2 != null ? '#fef3c7' : 'var(--bg-raised)',
          transition: 'width 0.5s ease',
        }} />
      </div>
    </div>
  )
}


function SectionPointsAnalysis({ match }) {
  const p1 = match.first_player  || {}
  const p2 = match.second_player || {}
  const matchId = match.match_id || match.id

  const [data, setData]   = useState(null)
  const [error, setError] = useState(null)

  useEffect(() => {
    if (!matchId) return
    let on = true
    api.matchPointAnalysis(matchId)
       .then(d => { if (on) setData(d) })
       .catch(e => { if (on) setError(e.message) })
    return () => { on = false }
  }, [matchId])

  if (error)   return <div className="error">{error}</div>
  if (!data)   return <div className="loading">Loading point analysis…</div>
  if (!data.has_data) {
    return (
      <div style={{
        background: 'var(--bg-card)', border: '1px solid var(--border)',
        borderRadius: 'var(--r-lg)', padding: 32,
        textAlign: 'center', color: 'var(--text-3)', fontSize: 14,
      }}>
        No point-by-point data yet for these players. Stats appear after they've played
        ~10 matches we have point data on (typically tour-level only).
      </div>
    )
  }

  const s1 = data.p1 || {}
  const s2 = data.p2 || {}

  return (
    <div>
      {/* Player header */}
      <div style={{
        display: 'flex', justifyContent: 'space-between',
        fontSize: 13, fontWeight: 700,
        marginBottom: 12, padding: '0 4px',
      }}>
        <span style={{ color: 'var(--green)' }}>{p1.name}</span>
        <span style={{ color: 'var(--blue)' }}>{p2.name}</span>
      </div>

      {/* Service group */}
      <div style={{
        background: 'var(--bg-card)', border: '1px solid var(--border)',
        borderRadius: 'var(--r-lg)', padding: '14px 18px', marginBottom: 8,
      }}>
        <div style={{ fontSize: 10, fontWeight: 700, textTransform: 'uppercase',
                      letterSpacing: 0.7, color: 'var(--text-3)', marginBottom: 8 }}>
          Service
        </div>
        <PointsBar label="Hold %"           v1={s1.service_hold_pct}     v2={s2.service_hold_pct}
                   good={80} avg={70}
                   sample1={s1.service_games} sample2={s2.service_games} />
        <PointsBar label="BP save %"        v1={s1.bp_save_pct}          v2={s2.bp_save_pct}
                   good={65} avg={55}
                   sample1={s1.bp_faced}      sample2={s2.bp_faced} />
        <PointsBar label="Love hold %"      v1={s1.love_hold_pct}        v2={s2.love_hold_pct}
                   good={15} avg={8}
                   sample1={s1.service_games} sample2={s2.service_games} />
        <PointsBar label="Avg pts / game"   v1={s1.avg_service_game_pts} v2={s2.avg_service_game_pts}
                   suffix=" pts" betterIsHigher={false} good={5} avg={6}
                   sample1={s1.service_games} sample2={s2.service_games} />
      </div>

      {/* Return group */}
      <div style={{
        background: 'var(--bg-card)', border: '1px solid var(--border)',
        borderRadius: 'var(--r-lg)', padding: '14px 18px', marginBottom: 8,
      }}>
        <div style={{ fontSize: 10, fontWeight: 700, textTransform: 'uppercase',
                      letterSpacing: 0.7, color: 'var(--text-3)', marginBottom: 8 }}>
          Return
        </div>
        <PointsBar label="Break %"          v1={s1.break_pct}            v2={s2.break_pct}
                   good={25} avg={15}
                   sample1={s1.return_games} sample2={s2.return_games} />
        <PointsBar label="BP conversion"    v1={s1.bp_conversion_pct}    v2={s2.bp_conversion_pct}
                   good={45} avg={30}
                   sample1={s1.bp_chances}   sample2={s2.bp_chances} />
      </div>

      {/* Pressure / Clutch group */}
      <div style={{
        background: 'var(--bg-card)', border: '1px solid var(--border)',
        borderRadius: 'var(--r-lg)', padding: '14px 18px', marginBottom: 8,
      }}>
        <div style={{ fontSize: 10, fontWeight: 700, textTransform: 'uppercase',
                      letterSpacing: 0.7, color: 'var(--text-3)', marginBottom: 8 }}>
          Pressure & clutch
        </div>
        <PointsBar label="Pressure point %"  v1={s1.pressure_win_pct}     v2={s2.pressure_win_pct}
                   good={55} avg={45}
                   sample1={s1.pressure_pts_faced} sample2={s2.pressure_pts_faced} />
        <PointsBar label="Tiebreak win %"    v1={s1.tiebreak_win_pct}     v2={s2.tiebreak_win_pct}
                   good={55} avg={45}
                   sample1={s1.tiebreaks_played} sample2={s2.tiebreaks_played} />
        <PointsBar label="Set point save"    v1={s1.set_point_save_pct}   v2={s2.set_point_save_pct}
                   good={65} avg={50}
                   sample1={s1.set_points_faced} sample2={s2.set_points_faced} />
        <PointsBar label="Match point save"  v1={s1.match_point_save_pct} v2={s2.match_point_save_pct}
                   good={70} avg={55}
                   sample1={s1.match_points_faced} sample2={s2.match_points_faced} />
        <PointsBar label="Set 1 recovery"    v1={s1.set1_recovery_pct}    v2={s2.set1_recovery_pct}
                   good={35} avg={20}
                   sample1={s1.set1_lost}     sample2={s2.set1_lost} />
        <PointsBar label="Longest game run"  v1={s1.longest_game_run}     v2={s2.longest_game_run}
                   suffix=" g" good={8} avg={5}
                   sample1={s1.matches_analyzed} sample2={s2.matches_analyzed} />
        <PointsBar label="Deuce win % (ret)" v1={s1.deuce_win_pct_ret}    v2={s2.deuce_win_pct_ret}
                   good={55} avg={45}
                   sample1={s1.deuce_pts_total_ret} sample2={s2.deuce_pts_total_ret} />
      </div>

      <div style={{ fontSize: 11, color: 'var(--text-3)', textAlign: 'center', marginTop: 12 }}>
        Computed from production point-by-point data over the last 24 months.
        Sample sizes show alongside each metric.
      </div>
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

  const cardStyle = {
    background: 'var(--bg-card)',
    border: '1px solid var(--border)',
    borderRadius: 'var(--r-lg)',
    padding: '18px 22px',
    marginBottom: 16,
  }

  const cardHeaderStyle = {
    fontSize: 11,
    color: 'var(--text-3)',
    textTransform: 'uppercase',
    letterSpacing: 0.6,
    fontWeight: 700,
    marginBottom: 12,
  }

  return (
    <div>
      {/* Headline summary */}
      <div style={{
        ...cardStyle,
        display: 'grid',
        gridTemplateColumns: '1fr auto 1fr',
        alignItems: 'center',
        gap: 16,
        padding: '24px 22px',
      }}>
        <div style={{ textAlign: 'center' }}>
          <div className="h2h-wins p1" style={{ fontSize: 36, fontWeight: 800 }}>
            {summary.p1_wins ?? 0}
          </div>
          <div style={{ fontSize: 12, color: 'var(--text-2)', marginTop: 4 }}>{p1.name}</div>
        </div>
        <div style={{ fontSize: 12, color: 'var(--text-3)', textAlign: 'center', textTransform: 'uppercase', letterSpacing: 0.6, fontWeight: 700 }}>
          {summary.total ?? 0} meetings
        </div>
        <div style={{ textAlign: 'center' }}>
          <div className="h2h-wins p2" style={{ fontSize: 36, fontWeight: 800 }}>
            {summary.p2_wins ?? 0}
          </div>
          <div style={{ fontSize: 12, color: 'var(--text-2)', marginTop: 4 }}>{p2.name}</div>
        </div>
      </div>

      {summary.by_surface && Object.keys(summary.by_surface).length > 0 && (
        <div style={cardStyle}>
          <div style={cardHeaderStyle}>By surface</div>
          <div style={{ display: 'flex', flexDirection: 'column', gap: 10 }}>
            {Object.entries(summary.by_surface).map(([surf, counts]) => (
              <div key={surf} style={{
                display: 'grid',
                gridTemplateColumns: '40px 1fr 40px',
                alignItems: 'center',
                gap: 12,
              }}>
                <div style={{ textAlign: 'right', fontSize: 14, fontWeight: 700, fontVariantNumeric: 'tabular-nums' }}>
                  {counts.p1}
                </div>
                <div style={{ display: 'flex', justifyContent: 'center' }}>
                  <SurfaceBadge surface={surf} />
                </div>
                <div style={{ textAlign: 'left', fontSize: 14, fontWeight: 700, fontVariantNumeric: 'tabular-nums' }}>
                  {counts.p2}
                </div>
              </div>
            ))}
          </div>
        </div>
      )}

      {meetings.length === 0 ? (
        <div style={{ ...cardStyle, textAlign: 'center', color: 'var(--text-3)', fontSize: 14, padding: '32px 22px' }}>
          No H2H meetings on record
        </div>
      ) : (
        <div style={cardStyle}>
          <div style={cardHeaderStyle}>Recent meetings</div>
          <div style={{ display: 'flex', flexDirection: 'column' }}>
            {meetings.slice(0, 10).map((m, i) => (
              <div key={i} style={{
                display: 'grid',
                gridTemplateColumns: '12px 1fr auto',
                alignItems: 'center',
                gap: 14,
                padding: '10px 0',
                borderBottom: i < Math.min(meetings.length, 10) - 1
                  ? '1px solid var(--border-faint)'
                  : 'none',
              }}>
                <div style={{
                  width: 10, height: 10, borderRadius: '50%',
                  background: m.winner === 'first_player' ? 'var(--accent-green)' : 'var(--accent-blue)',
                }} />
                <div>
                  <div style={{
                    fontSize: 14, fontWeight: 600, fontFamily: 'var(--font-mono)',
                    color: 'var(--text-1)',
                  }}>
                    {m.score || '—'}
                  </div>
                  <div style={{ fontSize: 11, color: 'var(--text-3)', marginTop: 2 }}>
                    {m.tournament} · {m.round} · {fmtShortDate(m.date)}
                  </div>
                </div>
                <SurfaceBadge surface={m.surface} />
              </div>
            ))}
          </div>
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
  { id: 'statistics',   label: 'Statistics'   },
  { id: 'points',       label: 'Points Analysis' },
  { id: 'form',         label: 'Form'          },
  { id: 'h2h',          label: 'Head to head'  },
]

export default function MatchDetail() {
  const { id } = useParams()
  const navigate = useNavigate()
  const location = useLocation()
  const [match,   setMatch]   = useState(null)
  const [loading, setLoading] = useState(true)
  const [error,   setError]   = useState(null)
  const [activeTab, setActiveTab] = useState('intelligence')

  // One ref per section for scroll-to
  const refs = {
    intelligence: useRef(null),
    ratings:      useRef(null),
    statistics:   useRef(null),
    points:       useRef(null),
    form:         useRef(null),
    h2h:          useRef(null),
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
            all_bookmakers:     mkt.all_bookmakers || [],
          },
          edge,
        })
        setLoading(false)

        // SEO: if the URL is just /match/:id (no slug), replace it in
        // place with /match/:id/:slug so canonical/share/back-button URLs
        // are descriptive. We use replace (not push) so the user's history
        // doesn't get a duplicate entry.
        try {
          const onlyId = /^\/match\/\d+\/?$/.test(location.pathname)
          if (onlyId) {
            const target = matchUrl({
              match_id:   data.match?.match_id ?? id,
              event_date: data.match?.event_date,
              tournament: data.match?.tournament,
              p1:         { name: p1?.name },
              p2:         { name: p2?.name },
            })
            if (target && target !== location.pathname && target !== '/') {
              navigate(target + (location.search || '') + (location.hash || ''),
                       { replace: true })
            }
          }
        } catch { /* non-fatal */ }
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

        <Section id="statistics" sectionRef={refs.statistics} title="Statistics">
          <SectionStatistics match={match} />
        </Section>

        <Section id="points" sectionRef={refs.points} title="Points Analysis">
          <SectionPointsAnalysis match={match} />
        </Section>

        <Section id="form" sectionRef={refs.form} title="Form">
          <SectionForm match={match} />
        </Section>

        <Section id="h2h" sectionRef={refs.h2h} title="Head to head">
          <SectionH2H match={match} />
        </Section>
      </div>
    </div>
  )
}
