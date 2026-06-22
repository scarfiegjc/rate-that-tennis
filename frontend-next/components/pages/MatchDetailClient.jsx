'use client'
import { useState, useEffect, useRef, useMemo } from 'react'
import { useRouter } from 'next/navigation'
import Link from 'next/link'
import { api } from '../../lib/api'
import SurfaceBadge from '../SurfaceBadge'
import EdgeBadge from '../EdgeBadge'
import ProbBar from '../ProbBar'
import FormChart from '../FormChart'
import StarPick from '../StarPick'

function playerUrl(p) {
  if (!p) return '/'
  const id = p.id ?? p.player_id
  if (id == null) return '/'
  const name = (p.full_name || p.name || '').toLowerCase().replace(/[^a-z0-9]+/g, '-').replace(/^-+|-+$/g, '')
  return name ? `/player/${id}/${name}` : `/player/${id}`
}

const courtClayImg = '/court-clay.jpg'
const courtGrassImg = '/court-grass.jpg'
const courtHardImg = '/court-hard.jpg'

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
// Surface / court helpers (used by hero + legacy fallback)
// ─────────────────────────────────────────────────────────────────────────────

function inferSurfaceFromName(name) {
  const n = (name || '').toLowerCase()
  if (/roland.?garros|french open|monte.?carlo|barcelona|madrid open|foro italico|italian open|internazionali|hamburg|geneva|lyon|strasbourg|rio open|buenos aires|santiago|marrakech|charleston|palermo|lausanne|prague/.test(n))
    return 'clay'
  if (/wimbledon|queen.?s club|cinch championships|halle|eastbourne|rothesay|nottingham|mallorca|newport|den bosch|rosmalen|birmingham|bad homburg/.test(n))
    return 'grass'
  return null
}

function courtImage(surface, tournamentName = '') {
  const s = (surface || '').toLowerCase()
  if (s.includes('clay'))  return courtClayImg
  if (s.includes('grass')) return courtGrassImg
  if (s.includes('hard') || s.includes('indoor') || s.includes('carpet')) return courtHardImg
  const inferred = inferSurfaceFromName(tournamentName)
  if (inferred === 'clay')  return courtClayImg
  if (inferred === 'grass') return courtGrassImg
  return courtHardImg
}

function fmtMatchDate(d) {
  if (!d || d.length < 10) return null
  try {
    return new Date(d + 'T12:00:00Z').toLocaleDateString('en-GB', { day: 'numeric', month: 'short', year: 'numeric' })
  } catch { return d }
}

// ─────────────────────────────────────────────────────────────────────────────
// PlayerAvatar — circular photo with initials fallback
// ─────────────────────────────────────────────────────────────────────────────

function PlayerAvatar({ photoUrl, name, size = 72, accent = 'rgba(255,255,255,0.18)' }) {
  const initials = (name || '?').split(' ').map(w => w[0]).slice(0, 2).join('').toUpperCase()
  if (photoUrl) {
    return (
      <img
        src={photoUrl}
        alt={name || ''}
        style={{
          width: size, height: size,
          borderRadius: '50%',
          objectFit: 'cover',
          objectPosition: 'top center',
          border: '2px solid rgba(255,255,255,0.55)',
          background: 'rgba(255,255,255,0.1)',
          flexShrink: 0,
        }}
        onError={e => { e.currentTarget.style.display = 'none'; e.currentTarget.nextSibling && (e.currentTarget.nextSibling.style.display = 'flex') }}
      />
    )
  }
  return (
    <div style={{
      width: size, height: size,
      borderRadius: '50%',
      background: accent,
      border: '2px solid rgba(255,255,255,0.4)',
      display: 'flex', alignItems: 'center', justifyContent: 'center',
      fontSize: size * 0.32, fontWeight: 800,
      color: 'rgba(255,255,255,0.85)',
      flexShrink: 0,
      letterSpacing: '0.02em',
    }}>
      {initials}
    </div>
  )
}

// ─────────────────────────────────────────────────────────────────────────────
// MatchHero — Combatrics-style gradient hero with player details + center card
// ─────────────────────────────────────────────────────────────────────────────

function MatchHero({ match }) {
  const p1   = match.first_player  || {}
  const p2   = match.second_player || {}
  const pred = match.prediction    || {}
  const imgSrc = courtImage(match.surface, match.tournament)

  const p1Pct = pred.prob_first_player  != null ? Math.round(pred.prob_first_player  * 100) : 50
  const p2Pct = pred.prob_second_player != null ? Math.round(pred.prob_second_player * 100) : 50

  // RTT greens + blues — darker variants for backgrounds
  const P1_BG   = '#0d3b1e'   // deep tennis green (p1 side)
  const P2_BG   = '#0c1f3f'   // deep navy blue (p2 side)
  const P1_ACC  = '#16a34a'   // accent green
  const P2_ACC  = '#1d4ed8'   // accent blue

  const isFinished = /finished/i.test(match.status || '')

  const confidenceColor = pred.confidence === 'high'   ? '#4ade80'
                        : pred.confidence === 'medium' ? '#fbbf24'
                        : 'rgba(255,255,255,0.4)'

  // Stat pills shown under player name
  const P1Pill = ({ children }) => (
    <span style={{ fontSize: '0.68rem', background: 'rgba(255,255,255,0.12)', border: '1px solid rgba(255,255,255,0.2)', borderRadius: 4, padding: '2px 6px', color: 'rgba(255,255,255,0.75)', fontWeight: 500 }}>
      {children}
    </span>
  )

  return (
    <div style={{ position: 'relative', minHeight: 230, overflow: 'hidden' }}>

      {/* Gradient split at p1Pct% */}
      <div style={{
        position: 'absolute', inset: 0,
        background: `linear-gradient(to right, ${P1_BG} ${p1Pct}%, ${P2_BG} ${p1Pct}%)`,
      }} />

      {/* Content — max-width container */}
      <div style={{ position: 'relative', maxWidth: 1280, margin: '0 auto', padding: '0 24px' }}>

        {/* ← Today back-link */}
        <Link href="/" style={{
          position: 'absolute', top: 14, left: 28,
          color: 'rgba(255,255,255,0.55)', fontSize: 11, fontWeight: 500,
          textDecoration: 'none', zIndex: 20,
          letterSpacing: 0.1,
          background: 'rgba(255,255,255,0.07)',
          border: '1px solid rgba(255,255,255,0.13)',
          borderRadius: 5,
          padding: '3px 8px',
        }}>← Today</Link>

        {/* ── CENTER CARD ─────────────────────────────────────────── */}
        <div style={{
          position: 'absolute',
          top: 10, bottom: 10,
          left: '50%', transform: 'translateX(-50%)',
          width: 200,
          zIndex: 10,
        }}>
          <div style={{
            position: 'relative',
            overflow: 'hidden',
            background: 'rgba(6,6,10,0.93)',
            borderRadius: 14,
            height: '100%',
            display: 'flex',
            flexDirection: 'column',
            padding: '0 0 12px',
            boxShadow: '0 4px 24px rgba(0,0,0,0.45)',
          }}>
            {/* Court image ghost */}
            {imgSrc && (
              <div style={{
                position: 'absolute', inset: 0,
                backgroundImage: `url(${imgSrc})`,
                backgroundSize: 'cover',
                backgroundPosition: 'center 40%',
                opacity: 0.18,
              }} />
            )}

            <div style={{ position: 'relative', zIndex: 2, display: 'flex', flexDirection: 'column', height: '100%' }}>
              {/* Event header */}
              <div style={{ padding: '10px 12px 9px', borderBottom: '1px solid rgba(255,255,255,0.08)', textAlign: 'center' }}>
                <div style={{ fontWeight: 800, fontSize: '0.77rem', color: '#fff', lineHeight: 1.25, marginBottom: 4, display: '-webkit-box', WebkitLineClamp: 2, WebkitBoxOrient: 'vertical', overflow: 'hidden' }}>
                  {match.tournament || 'Match'}
                </div>
                {match.round && (
                  <div style={{ fontSize: '0.66rem', color: '#9ca3af', marginBottom: 2 }}>{match.round}</div>
                )}
                {match.event_date && (
                  <div style={{ fontSize: '0.66rem', color: '#9ca3af' }}>{fmtMatchDate(match.event_date)}</div>
                )}
              </div>

              {/* Surface + VS */}
              <div style={{ flex: 1, display: 'flex', flexDirection: 'column', alignItems: 'center', justifyContent: 'center', gap: 10, padding: '6px 12px' }}>
                <SurfaceBadge surface={match.surface} light />
                <div style={{ fontWeight: 900, fontSize: '1.8rem', color: '#fff', letterSpacing: '0.2em', lineHeight: 1 }}>VS</div>
              </div>

              {/* Probability block */}
              <div style={{ padding: '0 12px' }}>
                <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-end', marginBottom: 5 }}>
                  <div>
                    <div style={{ fontWeight: 900, fontSize: '1.5rem', color: '#4ade80', lineHeight: 1 }}>{p1Pct}%</div>
                    <div style={{ fontSize: '0.56rem', color: '#4ade80', textTransform: 'uppercase', letterSpacing: '0.07em', opacity: 0.85, marginTop: 1 }}>
                      {(p1.name || '').split(' ').pop()}
                    </div>
                  </div>
                  <div style={{ textAlign: 'right' }}>
                    <div style={{ fontWeight: 900, fontSize: '1.5rem', color: '#60a5fa', lineHeight: 1 }}>{p2Pct}%</div>
                    <div style={{ fontSize: '0.56rem', color: '#60a5fa', textTransform: 'uppercase', letterSpacing: '0.07em', opacity: 0.85, marginTop: 1 }}>
                      {(p2.name || '').split(' ').pop()}
                    </div>
                  </div>
                </div>
                <ProbBar p1={pred.prob_first_player} p2={pred.prob_second_player} name1="" name2="" />
                {pred.confidence && (
                  <div style={{ textAlign: 'center', marginTop: 6 }}>
                    <span style={{ display: 'inline-flex', alignItems: 'center', gap: 4, fontSize: '0.58rem', fontWeight: 700, color: confidenceColor, textTransform: 'uppercase', letterSpacing: '0.07em' }}>
                      <span style={{ width: 5, height: 5, borderRadius: '50%', background: confidenceColor, display: 'inline-block' }} />
                      {pred.confidence} confidence
                    </span>
                  </div>
                )}
              </div>

              {/* Live banner */}
              {match.is_live && (
                <div style={{ margin: '8px 12px 0', paddingTop: 7, borderTop: '1px solid rgba(255,255,255,0.08)', textAlign: 'center' }}>
                  {match.set_scores && (
                    <div style={{ fontWeight: 900, fontSize: '1.1rem', color: '#fff', fontVariantNumeric: 'tabular-nums', letterSpacing: 2 }}>
                      {match.set_scores}
                    </div>
                  )}
                  <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'center', gap: 4, marginTop: 3 }}>
                    <span style={{ width: 6, height: 6, borderRadius: '50%', background: '#FCD34D', animation: 'pulse 1.5s infinite', display: 'inline-block' }} />
                    <span style={{ fontSize: '0.6rem', fontWeight: 700, color: '#FCD34D', letterSpacing: 0.5 }}>IN PLAY</span>
                  </div>
                </div>
              )}
            </div>
          </div>
        </div>

        {/* ── PLAYER SIDES — horizontal rows, avatars on inner edge ── */}
        <div style={{ display: 'flex', minHeight: 240, paddingTop: 40 }}>

          {/* Player 1 — left: [text] [avatar→inner] */}
          <div style={{
            flex: 1,
            paddingRight: 116,
            display: 'flex',
            flexDirection: 'row',
            alignItems: 'center',
            gap: 16,
            minWidth: 0,
            overflow: 'hidden',
          }}>
            {/* Text grows, left-aligned */}
            <div style={{ flex: 1, minWidth: 0, display: 'flex', flexDirection: 'column', gap: 6 }}>
              <Link
                href={playerUrl({ id: p1.player_id, name: p1.name })}
                style={{ fontWeight: 800, fontSize: 'clamp(1rem, 2vw, 1.6rem)', color: '#fff', lineHeight: 1.1, textDecoration: 'none', display: 'block', wordBreak: 'break-word' }}
              >
                {p1.name || '—'}
              </Link>
              {p1.ratings?.rtt_score != null && (
                <span style={{ display: 'inline-flex', alignItems: 'center', gap: 5, background: 'rgba(22,163,74,0.25)', border: '1px solid rgba(22,163,74,0.5)', borderRadius: 6, padding: '3px 9px 3px 6px', alignSelf: 'flex-start' }}>
                  <span style={{ fontSize: '0.6rem', fontWeight: 700, color: '#4ade80', textTransform: 'uppercase', letterSpacing: '0.07em' }}>RTT</span>
                  <span style={{ fontSize: '1rem', fontWeight: 900, color: '#4ade80', lineHeight: 1, fontVariantNumeric: 'tabular-nums' }}>{Math.round(p1.ratings.rtt_score)}</span>
                </span>
              )}
              <div style={{ display: 'flex', flexWrap: 'wrap', gap: 4 }}>
                {p1.current_rank    && <P1Pill>#{p1.current_rank}</P1Pill>}
                {p1.country_code    && <P1Pill>{p1.country_code}</P1Pill>}
                {p1.hand && p1.hand !== 'Unknown' && <P1Pill>{p1.hand === 'Left' ? 'L-hand' : 'R-hand'}</P1Pill>}
                {(p1.form_dots || []).length > 0 && (
                  <span style={{ display: 'flex', gap: 3, alignItems: 'center' }}>
                    {(p1.form_dots || []).slice(0, 5).map((d, i) => (
                      <span key={i} title={d === 'W' ? 'Win' : 'Loss'} style={{
                        display: 'inline-block', width: 7, height: 7, borderRadius: '50%',
                        background: d === 'W' ? '#4ade80' : 'rgba(255,255,255,0.25)',
                        border: d === 'W' ? '1px solid rgba(74,222,128,0.5)' : '1px solid rgba(255,255,255,0.2)',
                      }} />
                    ))}
                  </span>
                )}
              </div>
              {!isFinished && p1.player_id && (
                <StarPick
                  matchId={match.match_id}
                  playerId={p1.player_id}
                  playerName={p1.name}
                  ourOdds={pred.prob_first_player ? Math.round((1 / pred.prob_first_player) * 100) / 100 : null}
                  size="sm"
                />
              )}
            </div>
            {/* Avatar — inner edge */}
            <PlayerAvatar photoUrl={p1.logo_url} name={p1.name} size={88} accent={P1_ACC} />
          </div>

          {/* Player 2 — right: [avatar→inner] [text] */}
          <div style={{
            flex: 1,
            paddingLeft: 116,
            display: 'flex',
            flexDirection: 'row',
            alignItems: 'center',
            gap: 16,
            minWidth: 0,
            overflow: 'hidden',
          }}>
            {/* Avatar — inner edge */}
            <PlayerAvatar photoUrl={p2.logo_url} name={p2.name} size={88} accent={P2_ACC} />
            {/* Text grows, right-aligned */}
            <div style={{ flex: 1, minWidth: 0, display: 'flex', flexDirection: 'column', gap: 6, alignItems: 'flex-end', textAlign: 'right' }}>
              <Link
                href={playerUrl({ id: p2.player_id, name: p2.name })}
                style={{ fontWeight: 800, fontSize: 'clamp(1rem, 2vw, 1.6rem)', color: '#fff', lineHeight: 1.1, textDecoration: 'none', display: 'block', wordBreak: 'break-word' }}
              >
                {p2.name || '—'}
              </Link>
              {p2.ratings?.rtt_score != null && (
                <span style={{ display: 'inline-flex', alignItems: 'center', gap: 5, background: 'rgba(29,78,216,0.25)', border: '1px solid rgba(29,78,216,0.5)', borderRadius: 6, padding: '3px 9px 3px 6px', alignSelf: 'flex-end' }}>
                  <span style={{ fontSize: '0.6rem', fontWeight: 700, color: '#60a5fa', textTransform: 'uppercase', letterSpacing: '0.07em' }}>RTT</span>
                  <span style={{ fontSize: '1rem', fontWeight: 900, color: '#60a5fa', lineHeight: 1, fontVariantNumeric: 'tabular-nums' }}>{Math.round(p2.ratings.rtt_score)}</span>
                </span>
              )}
              <div style={{ display: 'flex', flexWrap: 'wrap', gap: 4, justifyContent: 'flex-end' }}>
                {(p2.form_dots || []).length > 0 && (
                  <span style={{ display: 'flex', gap: 3, alignItems: 'center' }}>
                    {(p2.form_dots || []).slice(0, 5).map((d, i) => (
                      <span key={i} title={d === 'W' ? 'Win' : 'Loss'} style={{
                        display: 'inline-block', width: 7, height: 7, borderRadius: '50%',
                        background: d === 'W' ? '#60a5fa' : 'rgba(255,255,255,0.25)',
                        border: d === 'W' ? '1px solid rgba(96,165,250,0.5)' : '1px solid rgba(255,255,255,0.2)',
                      }} />
                    ))}
                  </span>
                )}
                {p2.hand && p2.hand !== 'Unknown' && <P1Pill>{p2.hand === 'Left' ? 'L-hand' : 'R-hand'}</P1Pill>}
                {p2.country_code    && <P1Pill>{p2.country_code}</P1Pill>}
                {p2.current_rank    && <P1Pill>#{p2.current_rank}</P1Pill>}
              </div>
              {!isFinished && p2.player_id && (
                <StarPick
                  matchId={match.match_id}
                  playerId={p2.player_id}
                  playerName={p2.name}
                  ourOdds={pred.prob_second_player ? Math.round((1 / pred.prob_second_player) * 100) / 100 : null}
                  size="sm"
                />
              )}
            </div>
          </div>

        </div>
      </div>
    </div>
  )
}

// ─────────────────────────────────────────────────────────────────────────────
// Odds Rails — sticky betting sidebar (one per player)
// ─────────────────────────────────────────────────────────────────────────────

function OddsEdgeBar({ edge }) {
  if (edge == null) return null
  const pct = Math.max(-25, Math.min(25, edge * 100))
  const fillPct  = Math.min(100, Math.abs(pct) * 4)
  const positive = pct >= 0
  const barColor = positive ? '#16a34a' : '#dc2626'
  const tooltip  = `${positive ? '+' : ''}${pct.toFixed(1)}% edge vs model`
  return (
    <div title={tooltip} style={{ position: 'relative', height: 18, background: '#18181b', borderTop: '1px solid #27272a', overflow: 'hidden' }}>
      <div style={{ position: 'absolute', top: 0, bottom: 0, left: '50%', width: 1, background: 'rgba(255,255,255,0.3)' }} />
      <div style={{ position: 'absolute', top: 0, bottom: 0, left: positive ? '50%' : `${50 - fillPct / 2}%`, width: `${fillPct / 2}%`, background: barColor }} />
      <div style={{ position: 'absolute', inset: 0, display: 'flex', alignItems: 'center', justifyContent: 'center', fontSize: '0.58rem', fontWeight: 700, color: '#fff', letterSpacing: '0.06em', textShadow: '0 1px 1px rgba(0,0,0,0.5)' }}>
        {positive ? '+' : ''}{pct.toFixed(1)}% EDGE
      </div>
    </div>
  )
}

function OddsSquare({ label, price, edge, affiliateUrl, accent, footer }) {
  if (!price) return null
  const frac = (() => {
    if (!price || price <= 1) return null
    const profit = price - 1
    let bestErr = null, bestNum = 0, bestDen = 1
    for (let den = 1; den <= 20; den++) {
      const num = Math.round(profit * den)
      if (num <= 0) continue
      const err = Math.abs(profit - num / den)
      if (bestErr === null || err < bestErr) { bestErr = err; bestNum = num; bestDen = den }
    }
    return bestErr === null ? null : `${bestNum}/${bestDen}`
  })()

  return (
    <a href={affiliateUrl || '#'} target="_blank" rel="noopener noreferrer sponsored" style={{ textDecoration: 'none', color: 'inherit', display: 'block' }}>
      <div
        style={{ background: '#fff', border: '1px solid #d4d4d8', borderRadius: 10, overflow: 'hidden', boxShadow: '0 2px 10px rgba(0,0,0,0.1)', transition: 'box-shadow 0.15s, transform 0.15s', cursor: 'pointer' }}
        onMouseEnter={e => { e.currentTarget.style.boxShadow = '0 5px 18px rgba(0,0,0,0.18)'; e.currentTarget.style.transform = 'translateY(-1px)' }}
        onMouseLeave={e => { e.currentTarget.style.boxShadow = '0 2px 10px rgba(0,0,0,0.1)'; e.currentTarget.style.transform = 'none' }}
      >
        {/* Label strip */}
        <div style={{ background: 'linear-gradient(135deg, #111 0%, #1a1a2e 100%)', padding: '5px 8px', textAlign: 'center' }}>
          <div style={{ fontWeight: 800, fontSize: '0.6rem', color: '#fff', letterSpacing: '0.12em', textTransform: 'uppercase' }}>{label}</div>
        </div>
        {/* Price */}
        <div style={{ padding: '8px 8px 6px', textAlign: 'center' }}>
          <div style={{ fontWeight: 900, fontSize: '1.5rem', color: accent, lineHeight: 1 }}>{price.toFixed(2)}</div>
          {frac && <div style={{ fontSize: '0.65rem', color: '#52525b', marginTop: 2, fontWeight: 600 }}>{frac}</div>}
          <div style={{ fontSize: '0.55rem', color: '#71717a', marginTop: 3, letterSpacing: '0.06em', textTransform: 'uppercase', fontWeight: 600 }}>Cloudbet</div>
        </div>
        {/* Edge bar */}
        <OddsEdgeBar edge={edge} />
        {/* Footer CTA */}
        <div style={{ background: '#111', padding: '5px 6px', textAlign: 'center' }}>
          <span style={{ fontSize: '0.56rem', color: '#fff', fontWeight: 700, letterSpacing: '0.08em', textTransform: 'uppercase' }}>
            {footer || 'Bet at Cloudbet →'}
          </span>
        </div>
      </div>
    </a>
  )
}

function OddsRail({ side, match, cloudbetMarkets, affiliateUrl }) {
  const isRight  = side === 'right'
  const player   = isRight ? (match.second_player || {}) : (match.first_player  || {})
  const pred     = match.prediction || {}
  const modelProb = isRight ? pred.prob_second_player : pred.prob_first_player
  const accent   = isRight ? '#1d4ed8' : '#16a34a'
  const bgAccent = isRight ? '#0c1f3f' : '#0d3b1e'

  if (!cloudbetMarkets && !match.market?.cloudbet_link) return <div />

  const mkts     = cloudbetMarkets || {}
  const winner   = mkts.winner   || {}
  const hdp      = mkts.handicap || {}
  const scores   = mkts.correct_score || {}
  const totals   = mkts.total_sets   || {}

  const winPrice  = isRight ? winner.p2 : winner.p1
  const hdpPrice  = isRight ? hdp.p2    : hdp.p1
  const hdpLine   = hdp.line

  // "Win 2-0" for each side
  const score20   = isRight ? scores['0-2'] : scores['2-0']
  // "Win 2-1"
  const score21   = isRight ? scores['1-2'] : scores['2-1']
  // Total sets: left rail = over (more sets = more action), right = under
  const totalPrice = isRight ? totals.under : totals.over
  const totalLine  = totals.line
  const totalLabel = totalLine != null
    ? (isRight ? `Under ${totalLine} Sets` : `Over ${totalLine} Sets`)
    : (isRight ? 'Under Sets' : 'Over Sets')

  const edge = (winPrice && modelProb != null)
    ? modelProb - (1 / winPrice)
    : null

  // Hide rail entirely if no useful data
  if (!winPrice && !hdpPrice && !score20) return <div />

  return (
    <div style={{
      position: 'sticky',
      top: 100,
      alignSelf: 'flex-start',
      width: '100%',
      display: 'flex',
      flexDirection: 'column',
      gap: 10,
    }}>
      {/* Player header */}
      <div style={{
        background: `linear-gradient(160deg, ${bgAccent} 0%, #111 120%)`,
        borderRadius: 12,
        padding: '10px 8px 12px',
        textAlign: 'center',
        color: '#fff',
        boxShadow: '0 2px 10px rgba(0,0,0,0.15)',
      }}>
        <div style={{ display: 'flex', justifyContent: 'center', marginBottom: 6 }}>
          <PlayerAvatar photoUrl={player.logo_url} name={player.name} size={52} accent={accent} />
        </div>
        <div style={{ fontWeight: 800, fontSize: '0.72rem', lineHeight: 1.2, letterSpacing: '0.01em' }}>
          {player.name || '—'}
        </div>
        {player.current_rank && (
          <div style={{ fontSize: '0.6rem', color: 'rgba(255,255,255,0.55)', marginTop: 2 }}>
            Rank #{player.current_rank}
          </div>
        )}
      </div>

      {/* To Win */}
      {winPrice && (
        <OddsSquare label="To Win" price={winPrice} edge={edge} affiliateUrl={affiliateUrl} accent={accent} />
      )}

      {/* Win 2-0 — clean sweep */}
      {score20 && (
        <OddsSquare label="Win 2-0" price={score20} affiliateUrl={affiliateUrl} accent={accent} />
      )}

      {/* Win 2-1 */}
      {score21 && (
        <OddsSquare label="Win 2-1" price={score21} affiliateUrl={affiliateUrl} accent={accent} />
      )}

      {/* Set handicap */}
      {hdpPrice && (
        <OddsSquare
          label={hdpLine != null ? `Hcap ${hdpLine > 0 ? '+' : ''}${hdpLine}` : 'Handicap'}
          price={hdpPrice}
          affiliateUrl={affiliateUrl}
          accent={accent}
        />
      )}

      {/* Total sets */}
      {totalPrice && (
        <OddsSquare label={totalLabel} price={totalPrice} affiliateUrl={affiliateUrl} accent={accent} />
      )}

      {/* Responsible gambling */}
      <div style={{ textAlign: 'center', fontSize: '0.52rem', color: '#71717a', textTransform: 'uppercase', letterSpacing: '0.07em', fontWeight: 600, lineHeight: 1.6 }}>
        18+ · BeGambleAware
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

      {/* Tabs */}
      <div className="player-bar-tabs-row" style={{
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

      {/* Bookmaker odds panel removed — odds shown in sticky OddsRail sidebars instead */}
      {false && (() => {
        const mkt         = match.market || {}
        const allBk       = mkt.all_bookmakers || []
        const ctaLink     = mkt.cloudbet_link || mkt.bresbet_link || null
        const ctaLabel    = mkt.cloudbet_link ? 'Bet at Cloudbet →' : 'Bet at BresBet →'
        const bresbetLink = ctaLink
        const p1prob = pred.prob_first_player
        const p2prob = pred.prob_second_player

        const calcEdge  = (odds, prob) => (!odds || !prob) ? null : Math.round((prob - (1 / odds)) * 1000) / 1000
        const fmtEdge   = (e) => e == null ? null : (e >= 0 ? '+' : '') + (e * 100).toFixed(1) + '%'

        // all_bookmakers is now pre-filtered server-side to only books we
        // have affiliate deals with (Pinnacle etc are excluded). So the
        // best-priced book here is always one the punter can actually
        // click — no anonymisation needed.
        const bestP1bk = allBk.reduce((best, bk) => (!bk.p1_odds ? best : (!best || bk.p1_odds > best.p1_odds ? bk : best)), null)
        const bestP2bk = allBk.reduce((best, bk) => (!bk.p2_odds ? best : (!best || bk.p2_odds > best.p2_odds ? bk : best)), null)
        const bestP1   = bestP1bk?.p1_odds ?? mkt.odds_first_player
        const bestP2   = bestP2bk?.p2_odds ?? mkt.odds_second_player
        const bk1name  = bestP1bk?.display_name ?? bestP1bk?.bookmaker ?? mkt.display_name_p1 ?? mkt.bookmaker
        const bk2name  = bestP2bk?.display_name ?? bestP2bk?.bookmaker ?? mkt.display_name_p2 ?? mkt.bookmaker
        const bk1link  = bestP1bk?.link_url ?? mkt.link_url_p1 ?? null
        const bk2link  = bestP2bk?.link_url ?? mkt.link_url_p2 ?? null
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
                    bk1link
                      ? <a href={bk1link} target="_blank" rel="noopener noreferrer sponsored" style={{ fontSize: 12, color: 'var(--text-3)', textDecoration: 'underline', textDecorationStyle: 'dotted', textUnderlineOffset: 2 }}>{bk1name} ↗</a>
                      : <span style={{ fontSize: 12, color: 'var(--text-3)' }}>{bk1name}</span>
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
                    bk2link
                      ? <a href={bk2link} target="_blank" rel="noopener noreferrer sponsored" style={{ fontSize: 12, color: 'var(--text-3)', textDecoration: 'underline', textDecorationStyle: 'dotted', textUnderlineOffset: 2 }}>{bk2name} ↗</a>
                      : <span style={{ fontSize: 12, color: 'var(--text-3)' }}>{bk2name}</span>
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
                          {bk.link_url
                            ? <a href={bk.link_url} target="_blank" rel="noopener noreferrer sponsored" style={{ color: 'inherit', textDecoration: 'underline', textDecorationStyle: 'dotted', textUnderlineOffset: 2 }}>{bk.display_name || bk.bookmaker}</a>
                            : (bk.display_name || bk.bookmaker)
                          }
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

            {/* Affiliate strip — prefers Cloudbet when available */}
            {bresbetLink && (
              <div style={{
                borderTop: '1px solid var(--border-faint)',
                padding: '10px 16px',
                display: 'flex', alignItems: 'center', justifyContent: 'space-between', gap: 12,
                background: 'var(--bg-raised)',
              }}>
                <span style={{ fontSize: 12, color: 'var(--text-3)' }}>
                  {mkt.cloudbet_link ? 'Bet on this match at Cloudbet' : 'Bet on this match at BresBet'}
                </span>
                <a
                  href={bresbetLink}
                  target="_blank"
                  rel="noopener noreferrer sponsored"
                  style={{
                    padding: '6px 14px', borderRadius: 6, fontSize: 12, fontWeight: 700,
                    background: 'var(--green)', color: '#fff', textDecoration: 'none',
                    whiteSpace: 'nowrap', flexShrink: 0,
                  }}
                >
                  {mkt.cloudbet_link ? 'Bet at Cloudbet ↗' : 'Bet at BresBet ↗'}
                </a>
              </div>
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

function _toSlug(s) {
  return String(s || '').toLowerCase().replace(/[^a-z0-9]+/g, '-').replace(/^-+|-+$/g, '')
}

export default function MatchDetailClient({ initialMatch = null, matchId }) {
  const router = useRouter()
  const [match,   setMatch]   = useState(initialMatch)
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
    api.match(matchId)
      .then(data => {
        const p1   = data.players?.first  || {}
        const p2   = data.players?.second || {}
        const pred = data.prediction || {}
        const mkt  = data.market    || {}
        const edge = data.edge      || {}
        setMatch({
          ...data.match,
          first_player:  {
            ...p1,
            player_id:   p1.id,
            logo_url:    p1.logo_url    || null,
            current_rank: p1.current_rank || null,
          },
          second_player: {
            ...p2,
            player_id:   p2.id,
            logo_url:    p2.logo_url    || null,
            current_rank: p2.current_rank || null,
          },
          prediction: {
            ...pred,
            edge_first:  edge.p1,
            edge_second: edge.p2,
          },
          market: {
            odds_first_player:   mkt.p1?.decimal_odds,
            odds_second_player:  mkt.p2?.decimal_odds,
            bookmaker:           mkt.p1?.bookmaker || mkt.p2?.bookmaker,
            display_name_p1:     mkt.p1?.display_name || mkt.p1?.bookmaker,
            display_name_p2:     mkt.p2?.display_name || mkt.p2?.bookmaker,
            link_url_p1:         mkt.p1?.link_url,
            link_url_p2:         mkt.p2?.link_url,
            all_bookmakers:      mkt.all_bookmakers || [],
            bresbet_link:        mkt.bresbet_link || null,
            cloudbet_link:       mkt.cloudbet_link || null,
            cloudbet_event_url:  mkt.cloudbet_event_url || null,
            cloudbet_markets:    mkt.cloudbet_markets   || null,
          },
          edge,
        })
        setLoading(false)
      })
      .catch(e => { setError(e.message); setLoading(false) })
  }, [matchId])

  // Redirect bare /match/<id> → /match/<id>/<slug> once data is available
  useEffect(() => {
    if (!match) return
    const p1   = match.first_player?.name  || ''
    const p2   = match.second_player?.name || ''
    const date = (match.event_date || '').slice(0, 10)
    const tourn = match.tournament || ''
    const expectedSlug = [date, _toSlug(tourn), `${_toSlug(p1)}-vs-${_toSlug(p2)}`].filter(Boolean).join('-')
    if (expectedSlug && slug !== expectedSlug) {
      router.replace(`/match/${matchId}/${expectedSlug}`)
    }
  }, [match, matchId, router])

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

  // ── SEO ──────────────────────────────────────────────────────────────────
  const _p1Name = match?.first_player?.name  || ''
  const _p2Name = match?.second_player?.name || ''
  const _tourn  = match?.tournament || ''
  const _date   = match?.event_date ? new Date(match.event_date).toLocaleDateString('en-GB', { day: 'numeric', month: 'long', year: 'numeric' }) : ''
  const _seoTitle = _p1Name && _p2Name
    ? `${_p1Name} vs ${_p2Name} | ${_tourn}${_date ? ' · ' + _date : ''} | RateThatTennis`
    : 'Match Detail | RateThatTennis'
  const _seoDesc = _p1Name && _p2Name
    ? `${_p1Name} vs ${_p2Name} — ML win prediction, RTT ratings, form, H2H and bookmaker odds${_tourn ? ' at ' + _tourn : ''}. Free tennis analytics.`
    : undefined
  const _jsonLd = useMemo(() => !_p1Name ? null : ({
    '@context': 'https://schema.org',
    '@type': 'SportsEvent',
    'name': `${_p1Name} vs ${_p2Name}`,
    'sport': 'Tennis',
    ...(match?.event_date ? { 'startDate': match.event_date } : {}),
    ...(match?.surface    ? { 'location': { '@type': 'Place', 'name': _tourn, 'description': match.surface + ' court' } } : {}),
    'competitor': [
      { '@type': 'Person', 'name': _p1Name },
      { '@type': 'Person', 'name': _p2Name },
    ],
    'url': `https://ratethat.tennis/match/${matchId}`,
    'organizer': { '@type': 'Organization', 'name': 'RateThatTennis', 'url': 'https://ratethat.tennis' },
  }), [_p1Name, _p2Name, _tourn, match?.event_date, match?.surface])  // eslint-disable-line

  if (loading) return <div className="page"><div className="loading">Loading match…</div></div>
  if (error)   return <div className="page"><div className="error">{error}</div></div>
  if (!match)  return null

  const mkt             = match.market || {}
  const cloudbetMarkets = mkt.cloudbet_markets || null
  const affiliateUrl    = mkt.cloudbet_link || mkt.bresbet_link || null

  return (
    <div>

      {/* ── HERO — full-bleed, outside any max-width container ── */}
      <MatchHero match={match} />

      {/* ── LIVE SCORE BAR — only shown when match is in play ── */}
      {match.is_live && (match.set_scores || match.game_result) && (
        <div style={{
          background: '#000',
          borderBottom: '1px solid rgba(255,255,255,0.08)',
          padding: '10px 24px',
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'center',
          gap: 12,
        }}>
          <span className="live-lozenge">
            <span className="live-lozenge-dot" />
            LIVE
          </span>
          {match.set_scores && match.set_scores.split(' ').map((set, i) => (
            <span key={i} style={{
              fontSize: 22,
              fontWeight: 900,
              color: '#fff',
              fontVariantNumeric: 'tabular-nums',
              letterSpacing: 1,
              background: 'rgba(255,255,255,0.1)',
              borderRadius: 6,
              padding: '2px 12px',
            }}>{set}</span>
          ))}
          {match.game_result && (
            <span style={{
              fontSize: 15,
              fontWeight: 700,
              color: 'rgba(255,255,255,0.7)',
              fontVariantNumeric: 'tabular-nums',
              background: 'rgba(255,255,255,0.07)',
              borderRadius: 5,
              padding: '2px 10px',
            }}>{match.game_result}</span>
          )}
        </div>
      )}

      {/* ── STICKY PLAYER + TABS BAR — full-width ── */}
      <PlayerBar
        match={match}
        activeTab={activeTab}
        onTabClick={handleTabClick}
        tabRefs={refs}
      />

      {/* ── 3-COLUMN LAYOUT: odds rail | content | odds rail ── */}
      <div style={{
        display: 'grid',
        gridTemplateColumns: '156px 1fr 156px',
        gap: '0 16px',
        maxWidth: 1280,
        margin: '0 auto',
        padding: '20px 16px 60px',
        alignItems: 'start',
      }}>

        {/* Left rail — Player 1 odds */}
        <OddsRail
          side="left"
          match={match}
          cloudbetMarkets={cloudbetMarkets}
          affiliateUrl={affiliateUrl}
        />

        {/* Centre — all existing content sections */}
        <div style={{ minWidth: 0 }}>
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

        {/* Right rail — Player 2 odds */}
        <OddsRail
          side="right"
          match={match}
          cloudbetMarkets={cloudbetMarkets}
          affiliateUrl={affiliateUrl}
        />

      </div>
    </div>
  )
}
