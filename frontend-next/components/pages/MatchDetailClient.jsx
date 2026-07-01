'use client'
import { useState, useEffect, useRef, useMemo } from 'react'
import { useParams, useRouter } from 'next/navigation'
import Link from 'next/link'
import { api } from '../../lib/api'
import SurfaceBadge from '../SurfaceBadge'
import EdgeBadge from '../EdgeBadge'
import ProbBar from '../ProbBar'
import FormChart from '../FormChart'
import StarPick from '../StarPick'

// ─────────────────────────────────────────────────────────────────────────────
// Helpers
// ─────────────────────────────────────────────────────────────────────────────

function playerUrl(p) {
  if (!p) return '/'
  const id = p.id ?? p.player_id
  if (id == null) return '/'
  const name = (p.full_name || p.name || '').toLowerCase().replace(/[^a-z0-9]+/g, '-').replace(/^-+|-+$/g, '')
  return name ? `/player/${id}/${name}` : `/player/${id}`
}

function _toSlug(s) {
  return String(s || '').toLowerCase().replace(/[^a-z0-9]+/g, '-').replace(/^-+|-+$/g, '')
}

// Convert api-tennis tiebreak scores: "7.7-6.4" → "7-6(4)", "6-4" stays "6-4"
function fmtSetScore(raw) {
  if (!raw) return raw
  return raw.replace(/(\d+)\.(\d+)-(\d+)\.(\d+)/g, (_, a, b, c, d) => {
    // e.g. 7.7 - 6.4 → 7-6(4)  (higher side won the tiebreak)
    return `${a}-${c}(${Math.min(Number(b), Number(d))})`
  })
}

function fmt(val, d = 0) {
  if (val == null) return '—'
  return Number(val).toFixed(d)
}

function fmtMatchDate(d) {
  if (!d || d.length < 10) return null
  try {
    return new Date(d + 'T12:00:00Z').toLocaleDateString('en-GB', { day: 'numeric', month: 'short', year: 'numeric' })
  } catch { return d }
}

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

function inferSurfaceFromName(name) {
  const n = (name || '').toLowerCase()
  if (/roland.?garros|french open|monte.?carlo|barcelona|madrid open|foro italico|italian open|internazionali|hamburg|geneva|lyon|strasbourg|rio open|buenos aires|santiago|marrakech|charleston|palermo|lausanne|prague/.test(n))
    return 'clay'
  if (/wimbledon|queen.?s club|cinch championships|halle|eastbourne|rothesay|nottingham|mallorca|newport|den bosch|rosmalen|birmingham|bad homburg/.test(n))
    return 'grass'
  return null
}

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

function advantageColor(v1, v2) {
  const n1 = v1 ?? 50, n2 = v2 ?? 50
  const diff = n1 - n2
  if (diff > 8)  return { c1: '#166534', c2: '#991b1b' }
  if (diff < -8) return { c1: '#991b1b', c2: '#166534' }
  return { c1: '#92400e', c2: '#92400e' }
}

// ─────────────────────────────────────────────────────────────────────────────
// Card / section styles (shared)
// ─────────────────────────────────────────────────────────────────────────────

const cardStyle = {
  background: '#fff',
  borderRadius: 10,
  border: '1px solid #e5e9f0',
  padding: '14px 16px',
  marginBottom: 12,
}

const sectionLabelStyle = {
  fontSize: 11,
  color: '#9ca3af',
  fontWeight: 500,
  letterSpacing: '0.5px',
  marginBottom: 10,
  textTransform: 'uppercase',
}

// ─────────────────────────────────────────────────────────────────────────────
// CourtSVG — tennis court overhead with serve zone fills
// ─────────────────────────────────────────────────────────────────────────────

function CourtSVG({ sv, side, zoneData }) {
  const isDeuce = side === 'deuce'
  const tX    = isDeuce ? 210 : 135
  const wX    = isDeuce ? 135 : 210

  return (
    <svg viewBox="0 0 420 240" style={{ width: '100%', display: 'block', borderRadius: 6 }}>
      <rect width="420" height="240" fill="#3a7fa5" rx="4"/>
      <rect x="60" y="20" width="300" height="200" fill="none" stroke="#fff" strokeWidth="1.5"/>
      <line x1="60" y1="120" x2="360" y2="120" stroke="#fff" strokeWidth="2"/>
      <line x1="210" y1="20" x2="210" y2="220" stroke="#fff" strokeWidth="1.5"/>
      <rect x="135" y="20" width="150" height="90" fill="none" stroke="#fff" strokeWidth="1.5"/>
      <rect x="135" y="130" width="150" height="90" fill="none" stroke="#fff" strokeWidth="1.5"/>
      <line x1="210" y1="110" x2="210" y2="130" stroke="#fff" strokeWidth="2"/>

      {/* T zone */}
      <rect x={tX} y="130" width="75" height="90" fill="#0d9488" opacity={zoneData.t/100*0.55+0.08}/>
      <text x={tX+37} y="175" textAnchor="middle" fontSize="11" fontWeight="500" fill="#fff" fontFamily="system-ui">{zoneData.t}%</text>
      <text x={tX+37} y="187" textAnchor="middle" fontSize="8" fill="rgba(255,255,255,0.7)" fontFamily="system-ui">T</text>

      {/* Wide zone */}
      <rect x={wX} y="130" width="75" height="90" fill="#f59e0b" opacity={zoneData.wide/100*0.55+0.08}/>
      <text x={wX+37} y="175" textAnchor="middle" fontSize="11" fontWeight="500" fill="#fff" fontFamily="system-ui">{zoneData.wide}%</text>
      <text x={wX+37} y="187" textAnchor="middle" fontSize="8" fill="rgba(255,255,255,0.7)" fontFamily="system-ui">Wide</text>

      {/* Body zone */}
      <rect x="135" y="130" width="150" height="18" fill="#9ca3af" opacity={zoneData.body/100*0.5+0.05}/>
      <text x="210" y="142" textAnchor="middle" fontSize="9" fill="rgba(255,255,255,0.85)" fontFamily="system-ui">Body {zoneData.body}%</text>

      <rect x="135" y="130" width="150" height="90" fill="none" stroke="rgba(255,255,255,0.4)" strokeWidth="1"/>
      <line x1="210" y1="130" x2="210" y2="220" stroke="rgba(255,255,255,0.4)" strokeWidth="1"/>
      <rect x={isDeuce?210:135} y="130" width="75" height="90" fill="none" stroke="#f43f5e" strokeWidth="1.5"/>

      <circle cx="210" cy="185" r="7" fill="#f43f5e" stroke="#fff" strokeWidth="1.5"/>
      <text x="210" y="189" textAnchor="middle" fontSize="6" fill="#fff" fontFamily="system-ui" fontWeight="500">S</text>
      <circle cx="210" cy="55" r="6" fill="rgba(255,255,255,0.3)" stroke="#fff" strokeWidth="1"/>

      <text x="30" y="175" textAnchor="middle" fontSize="8" fill="rgba(255,255,255,0.4)" fontFamily="system-ui" transform="rotate(-90,30,175)">SERVER</text>
      <text x="395" y="80" textAnchor="middle" fontSize="8" fill="rgba(255,255,255,0.4)" fontFamily="system-ui" transform="rotate(90,395,80)">RETURNER</text>
      <text x="210" y="12" textAnchor="middle" fontSize="8" fill="rgba(255,255,255,0.4)" fontFamily="system-ui">NET</text>
    </svg>
  )
}

function getZoneData(serveZones, playerId, surfaceId, svNum, side) {
  if (!serveZones || !serveZones.length) {
    if (svNum === 1 && side === 'deuce') return { t: 45, wide: 38, body: 17 }
    if (svNum === 1 && side === 'ad')    return { t: 28, wide: 52, body: 20 }
    if (svNum === 2 && side === 'deuce') return { t: 38, wide: 42, body: 20 }
    return { t: 22, wide: 52, body: 26 }
  }
  const zones = serveZones.filter(z =>
    z.player_id === playerId &&
    z.serve_number === svNum &&
    z.court_side === side
  )
  const t    = zones.find(z => z.zone === 't')?.pct    || 33
  const wide = zones.find(z => z.zone === 'wide')?.pct || 34
  const body = zones.find(z => z.zone === 'body')?.pct || 33
  return { t: Math.round(t), wide: Math.round(wide), body: Math.round(body) }
}

// ─────────────────────────────────────────────────────────────────────────────
// Small lozenges
// ─────────────────────────────────────────────────────────────────────────────

function RttBadge({ score }) {
  if (score == null) return null
  const c = rttPastel(Math.round(score))
  return (
    <span style={{
      display: 'inline-flex', alignItems: 'center', gap: 4,
      background: c.bg, color: c.text,
      borderRadius: 6, padding: '2px 8px',
      fontSize: 12, fontWeight: 700,
      fontVariantNumeric: 'tabular-nums',
      flexShrink: 0,
    }}>
      <span style={{ fontSize: 9, fontWeight: 600, opacity: 0.7, textTransform: 'uppercase' }}>RTT</span>
      {Math.round(score)}
    </span>
  )
}

function MomentumSquares({ momentum, form_dots }) {
  const dots = (form_dots || []).slice(0, 3)
  if (!dots.length) {
    const color = momentum === 'rising' ? '#bbf0d0' : momentum === 'falling' ? '#fecaca' : '#f0ede8'
    const border = momentum === 'rising' ? '#166534' : momentum === 'falling' ? '#991b1b' : '#a8a29e'
    return (
      <div style={{ display: 'flex', gap: 4 }}>
        {[0,1,2].map(i => (
          <div key={i} style={{ width: 10, height: 10, borderRadius: 2, background: color, border: `1px solid ${border}` }} />
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
// Sticky header
// ─────────────────────────────────────────────────────────────────────────────

function StickyHeader({ match }) {
  const p1   = match.first_player  || {}
  const p2   = match.second_player || {}
  const pred = match.prediction    || {}
  const mkt  = match.market        || {}
  const edge = match.edge          || {}

  const isFinished = /finished/i.test(match.status || '') || !!match.winner
  const isLive     = !!match.is_live && !isFinished

  const p1Prob = pred.prob_first_player  != null ? pred.prob_first_player  : 0.5
  const p2Prob = pred.prob_second_player != null ? pred.prob_second_player : 0.5
  const p1Pct  = Math.round(p1Prob * 100)
  const p2Pct  = Math.round(p2Prob * 100)

  const p1odds = mkt.odds_first_player
  const p2odds = mkt.odds_second_player

  const e1 = (p1odds && p1Prob) ? (p1Prob - 1/p1odds) : null
  const e2 = (p2odds && p2Prob) ? (p2Prob - 1/p2odds) : null

  // Best edge
  const bestEdge  = (e1 != null && e2 != null) ? (Math.abs(e1) >= Math.abs(e2) ? e1 : e2) : (e1 ?? e2)
  const bestPlayer = bestEdge === e1 ? (p1.name || '').split(' ').pop() : (p2.name || '').split(' ').pop()

  // bzzoiro O/U
  const bp = match.bzzoiro_prediction
  const ouLine  = bp?.total_games_line  || bp?.total_sets_line  || null
  const ouLabel = bp?.total_games_line  ? 'games' : bp?.total_sets_line ? 'sets' : null
  const ouOver  = bp?.total_games_over  != null ? Math.round(bp.total_games_over  * 100)
                : bp?.total_sets_over   != null ? Math.round(bp.total_sets_over   * 100) : null

  // Surface colour
  const surface = (match.surface || '').toLowerCase()
  const surfaceAccent = surface.includes('clay') ? '#c2410c' : surface.includes('grass') ? '#166534' : '#0369a1'

  const tourCat = match.tour_category || match.event_type || ''

  return (
    <div style={{ position: 'sticky', top: 0, zIndex: 50, background: '#fff', borderBottom: '1px solid #e5e9f0', boxShadow: '0 2px 8px rgba(0,0,0,0.06)' }}>
      <div style={{ maxWidth: 900, margin: '0 auto', padding: '0 20px' }}>

        {/* Breadcrumb row — centred */}
        <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'center', gap: 8, padding: '10px 0 6px', flexWrap: 'wrap' }}>
          <Link href="/" style={{ fontSize: 11, color: '#6b7280', textDecoration: 'none', fontWeight: 500 }}>← Today</Link>
          <span style={{ color: '#d1d5db', fontSize: 11 }}>·</span>
          {match.surface && (
            <span style={{ fontSize: 10, fontWeight: 700, textTransform: 'uppercase', letterSpacing: '0.5px', color: '#fff', background: surfaceAccent, padding: '1px 6px', borderRadius: 4 }}>
              {match.surface}
            </span>
          )}
          {match.tournament && (
            <span style={{ fontSize: 11, color: '#374151', fontWeight: 500, maxWidth: 220, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
              {match.tournament}
            </span>
          )}
          {match.round && <span style={{ fontSize: 11, color: '#9ca3af' }}>{match.round}</span>}
          {match.event_date && <span style={{ fontSize: 11, color: '#9ca3af' }}>{fmtMatchDate(match.event_date)}</span>}
          {isLive && (
            <span style={{ display: 'inline-flex', alignItems: 'center', gap: 4, background: '#f43f5e', color: '#fff', fontSize: 10, fontWeight: 800, letterSpacing: '0.5px', padding: '2px 7px', borderRadius: 4 }}>
              <span style={{ width: 5, height: 5, borderRadius: '50%', background: '#fff', display: 'inline-block' }} />
              LIVE
            </span>
          )}
        </div>

        {/* Facing-players matchup row */}
        <div style={{ display: 'grid', gridTemplateColumns: '1fr auto 1fr', gap: 16, alignItems: 'center', paddingBottom: 14 }}>

          {/* P1 — left side */}
          <div style={{ minWidth: 0, display: 'flex', alignItems: 'center', gap: 12 }}>
            {/* Photo */}
            <div style={{ flexShrink: 0 }}>
              {p1.logo_url ? (
                <img src={p1.logo_url} alt="" style={{ width: 56, height: 56, borderRadius: '50%', objectFit: 'cover', border: '2px solid #e5e9f0' }} />
              ) : (
                <div style={{ width: 56, height: 56, borderRadius: '50%', background: '#f0f9ff', border: '2px solid #bae6fd', display: 'flex', alignItems: 'center', justifyContent: 'center', fontSize: 20, fontWeight: 700, color: '#0369a1' }}>
                  {(p1.name || '?')[0].toUpperCase()}
                </div>
              )}
            </div>
            {/* Name + badges */}
            <div style={{ minWidth: 0 }}>
              {p1.country_code && (
                <div style={{ fontSize: 11, color: '#9ca3af', fontWeight: 600, marginBottom: 2 }}>{p1.country_code}</div>
              )}
              <Link href={playerUrl(p1)} style={{ fontWeight: 700, fontSize: 17, color: '#111827', textDecoration: 'none', display: 'block', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
                {p1.name || '—'}
              </Link>
              <div style={{ display: 'flex', alignItems: 'center', gap: 6, marginTop: 5 }}>
                <RttBadge score={p1.ratings?.rtt_score} />
                {!isFinished && p1.player_id && (
                  <StarPick matchId={match.match_id} playerId={p1.player_id} playerName={p1.name} ourOdds={p1Pct ? Math.round((1/(p1Pct/100))*100)/100 : null} size="sm" />
                )}
              </div>
            </div>
          </div>

          {/* Centre — prob + bar + chips */}
          <div style={{ display: 'flex', flexDirection: 'column', alignItems: 'center', gap: 5, minWidth: 160 }}>
            {/* Live/finished score or prob percentages */}
            {(isLive || isFinished) && (match.set_scores || match.game_result) ? (
              <div style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
                {match.set_scores && match.set_scores.split(' ').map((set, i) => (
                  <span key={i} style={{ fontSize: 18, fontWeight: 900, color: '#111827', fontVariantNumeric: 'tabular-nums', background: '#f4f6f9', borderRadius: 5, padding: '2px 8px' }}>{fmtSetScore(set)}</span>
                ))}
                {isLive && match.game_result && (
                  <span style={{ fontSize: 14, fontWeight: 700, color: '#6b7280', fontVariantNumeric: 'tabular-nums' }}>{match.game_result}</span>
                )}
              </div>
            ) : (
              <div style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
                <span style={{ fontSize: 26, fontWeight: 800, color: '#111827', fontVariantNumeric: 'tabular-nums' }}>{p1Pct}%</span>
                <span style={{ fontSize: 11, fontWeight: 600, color: '#9ca3af' }}>vs</span>
                <span style={{ fontSize: 26, fontWeight: 800, color: '#111827', fontVariantNumeric: 'tabular-nums' }}>{p2Pct}%</span>
              </div>
            )}

            {/* Probability bar */}
            <div style={{ width: '100%', height: 6, borderRadius: 99, background: '#e5e9f0', overflow: 'hidden', display: 'flex' }}>
              <div style={{ width: `${p1Pct}%`, background: '#0d9488', transition: 'width 0.5s ease' }} />
              <div style={{ flex: 1, background: '#6366f1' }} />
            </div>

            {/* Confidence or live indicator */}
            {!isLive && pred.confidence && (
              <div style={{ fontSize: 10, fontWeight: 600, textTransform: 'uppercase', letterSpacing: '0.5px', color: pred.confidence === 'high' ? '#15803d' : pred.confidence === 'medium' ? '#b45309' : '#6b7280' }}>
                {pred.confidence} confidence
              </div>
            )}

            {/* Edge + O/U chips */}
            <div style={{ display: 'flex', gap: 6, flexWrap: 'wrap', justifyContent: 'center' }}>
              {bestEdge != null && (
                <div style={{
                  background: bestEdge > 0.02 ? '#dcfce7' : bestEdge > 0 ? '#fef9c3' : '#f3f4f6',
                  border: `1px solid ${bestEdge > 0.02 ? '#86efac' : bestEdge > 0 ? '#fcd34d' : '#e5e7eb'}`,
                  borderRadius: 7, padding: '4px 9px', textAlign: 'center',
                }}>
                  <div style={{ fontSize: 12, fontWeight: 800, color: bestEdge > 0.02 ? '#15803d' : bestEdge > 0 ? '#b45309' : '#6b7280', fontVariantNumeric: 'tabular-nums' }}>
                    {bestEdge > 0 ? '+' : ''}{(bestEdge * 100).toFixed(1)}%
                  </div>
                  <div style={{ fontSize: 9, color: '#9ca3af', fontWeight: 600, textTransform: 'uppercase', letterSpacing: '0.4px' }}>
                    RTT edge{bestPlayer ? ` · ${bestPlayer}` : ''}
                  </div>
                </div>
              )}
              {ouLine != null && ouOver != null && (
                <div style={{ background: '#f0f9ff', border: '1px solid #bae6fd', borderRadius: 7, padding: '4px 9px', textAlign: 'center' }}>
                  <div style={{ fontSize: 12, fontWeight: 800, color: '#0369a1', fontVariantNumeric: 'tabular-nums' }}>O{ouLine} {ouOver}%</div>
                  <div style={{ fontSize: 9, color: '#9ca3af', fontWeight: 600, textTransform: 'uppercase', letterSpacing: '0.4px' }}>over {ouLabel}</div>
                </div>
              )}
            </div>
          </div>

          {/* P2 — right side */}
          <div style={{ minWidth: 0, display: 'flex', alignItems: 'center', gap: 12, justifyContent: 'flex-end' }}>
            {/* Name + badges */}
            <div style={{ minWidth: 0, textAlign: 'right' }}>
              {p2.country_code && (
                <div style={{ fontSize: 11, color: '#9ca3af', fontWeight: 600, marginBottom: 2 }}>{p2.country_code}</div>
              )}
              <Link href={playerUrl(p2)} style={{ fontWeight: 700, fontSize: 17, color: '#111827', textDecoration: 'none', display: 'block', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
                {p2.name || '—'}
              </Link>
              <div style={{ display: 'flex', alignItems: 'center', gap: 6, marginTop: 5, justifyContent: 'flex-end' }}>
                {!isFinished && p2.player_id && (
                  <StarPick matchId={match.match_id} playerId={p2.player_id} playerName={p2.name} ourOdds={p2Pct ? Math.round((1/(p2Pct/100))*100)/100 : null} size="sm" />
                )}
                <RttBadge score={p2.ratings?.rtt_score} />
              </div>
            </div>
            {/* Photo */}
            <div style={{ flexShrink: 0 }}>
              {p2.logo_url ? (
                <img src={p2.logo_url} alt="" style={{ width: 56, height: 56, borderRadius: '50%', objectFit: 'cover', border: '2px solid #e5e9f0' }} />
              ) : (
                <div style={{ width: 56, height: 56, borderRadius: '50%', background: '#f5f3ff', border: '2px solid #c4b5fd', display: 'flex', alignItems: 'center', justifyContent: 'center', fontSize: 20, fontWeight: 700, color: '#6d28d9' }}>
                  {(p2.name || '?')[0].toUpperCase()}
                </div>
              )}
            </div>
          </div>

        </div>
      </div>
    </div>
  )
}

// ─────────────────────────────────────────────────────────────────────────────
// Anchor tab nav (sticky, below header)
// ─────────────────────────────────────────────────────────────────────────────

const NAV_TABS = [
  { id: 'section-intel',     label: 'Intelligence' },
  { id: 'section-overview',  label: 'Overview'     },
  { id: 'section-form',      label: 'Form'         },
  { id: 'section-h2h',       label: 'H2H'          },
  { id: 'section-serve',     label: 'Serve'        },
]

function scrollToSection(id) {
  const el = document.getElementById(id)
  if (el) el.scrollIntoView({ behavior: 'smooth' })
}

function AnchorNav({ activeSection }) {
  return (
    <div style={{ position: 'sticky', top: 108, zIndex: 49, background: '#fff', borderBottom: '1px solid #e5e9f0' }}>
      <div style={{ maxWidth: 900, margin: '0 auto', display: 'flex', justifyContent: 'center', gap: 0 }}>
        {NAV_TABS.map(t => (
          <button
            key={t.id}
            onClick={() => scrollToSection(t.id)}
            style={{
              padding: '10px 16px',
              fontSize: 13,
              fontWeight: activeSection === t.id ? 700 : 500,
              color: activeSection === t.id ? '#0d9488' : '#6b7280',
              background: 'none',
              border: 'none',
              borderBottom: activeSection === t.id ? '2px solid #0d9488' : '2px solid transparent',
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
// Intelligence section
// ─────────────────────────────────────────────────────────────────────────────

function IntelColumn({ title, body, accent, isLoading, footer }) {
  return (
    <div style={{ ...cardStyle, display: 'flex', flexDirection: 'column', padding: 0, overflow: 'hidden' }}>
      <div style={{ height: 4, background: accent }} />
      <div style={{ padding: '14px 16px', flex: 1 }}>
        <div style={{ fontSize: 11, fontWeight: 700, textTransform: 'uppercase', letterSpacing: '0.7px', color: accent, marginBottom: 10 }}>
          {title}
        </div>
        {isLoading ? (
          <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
            <div style={{ height: 12, background: '#f4f6f9', borderRadius: 4 }} />
            <div style={{ height: 12, background: '#f4f6f9', borderRadius: 4, width: '90%' }} />
            <div style={{ height: 12, background: '#f4f6f9', borderRadius: 4, width: '75%' }} />
          </div>
        ) : body ? (
          <p style={{ margin: 0, fontSize: 14, color: '#374151', lineHeight: 1.75 }}>{body}</p>
        ) : (
          <div style={{ color: '#9ca3af', fontSize: 13, fontStyle: 'italic' }}>
            Awaiting deep-reasoning pass — typically generated within an hour of match time.
          </div>
        )}
      </div>
      {footer && (
        <div style={{ padding: '10px 16px', background: '#f9fafb', borderTop: '1px solid #e5e9f0', fontSize: 12, color: '#374151', lineHeight: 1.5 }}>
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

  const [intel, setIntel] = useState(null)
  const [error, setError] = useState(null)

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

  return (
    <div>
      {/* 3-col journalistic layout */}
      <div style={{ display: 'grid', gridTemplateColumns: '1fr 1.4fr 1fr', gap: 10, marginBottom: 12 }}>
        <IntelColumn
          title={p1.name || 'Player 1'}
          body={i.p1_intel}
          accent="#0d9488"
          isLoading={loading}
        />
        <IntelColumn
          title="Match preview"
          body={i.match_preview}
          accent="#374151"
          isLoading={loading}
          footer={i.confidence_line ? (
            <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
              <span style={{
                width: 6, height: 6, borderRadius: '50%',
                background: pred.confidence === 'high' ? '#15803d' : pred.confidence === 'medium' ? '#b45309' : '#9ca3af',
                flexShrink: 0,
              }} />
              <span><strong style={{ textTransform: 'capitalize' }}>{pred.confidence || 'low'} confidence</strong> · {i.confidence_line}</span>
            </div>
          ) : null}
        />
        <IntelColumn
          title={p2.name || 'Player 2'}
          body={i.p2_intel}
          accent="#6366f1"
          isLoading={loading}
        />
      </div>

      {/* Did you know */}
      {i.did_you_know && (
        <div style={{
          background: 'linear-gradient(90deg,#fef9e7,#fef3c7)',
          border: '1px solid #fde68a',
          borderRadius: 10, padding: '12px 16px',
          display: 'flex', alignItems: 'center', gap: 12, marginBottom: 12,
        }}>
          <span style={{
            fontSize: 10, fontWeight: 700, background: '#92400e', color: '#fffbeb',
            padding: '3px 8px', borderRadius: 12, textTransform: 'uppercase', letterSpacing: 0.6, flexShrink: 0,
          }}>Did you know</span>
          <span style={{ fontSize: 14, color: '#78350f', lineHeight: 1.5 }}>{i.did_you_know}</span>
        </div>
      )}

      {/* Bet signals */}
      {bets.length > 0 && (
        <div style={cardStyle}>
          <div style={sectionLabelStyle}>Value signals</div>
          {bets.map((b, idx) => (
            <div key={idx} style={{
              display: 'flex', justifyContent: 'space-between', alignItems: 'center',
              padding: '8px 0',
              borderBottom: idx < bets.length - 1 ? '1px solid #f3f4f6' : 'none',
            }}>
              <span style={{ fontSize: 13, fontWeight: 500, color: '#374151' }}>{b.description || b.type}</span>
              <EdgeBadge edge={b.edge} playerName={b.player} />
            </div>
          ))}
        </div>
      )}

      {/* Over/Under markets */}
      {match.bzzoiro_prediction && (() => {
        const bp  = match.bzzoiro_prediction
        const p1n = p1.name || 'P1'
        const p2n = p2.name || 'P2'
        const rows = []

        if (bp.total_sets_over != null && bp.total_sets_line != null) {
          rows.push({ label: 'Total Sets', market: `Over ${bp.total_sets_line}`, pct: Math.round(bp.total_sets_over * 100) })
        }
        if (bp.total_games_lines) {
          for (const [line, prob] of Object.entries(bp.total_games_lines)) {
            rows.push({ label: rows.some(r => r.label === 'Total Games') ? '' : 'Total Games', market: `Over ${line}`, pct: Math.round(prob * 100) })
          }
        } else if (bp.total_games_over != null && bp.total_games_line != null) {
          rows.push({ label: 'Total Games', market: `Over ${bp.total_games_line}`, pct: Math.round(bp.total_games_over * 100) })
        }
        if (bp.first_set_winner != null) {
          const name = bp.first_set_winner === 'first' ? p1n.split(' ').pop() : p2n.split(' ').pop()
          rows.push({ label: 'First Set', market: name, pct: Math.round((bp.first_set_prob || 0.5) * 100) })
        }
        if (!rows.length) return null

        const expSets  = bp.expected_sets  != null ? bp.expected_sets.toFixed(1)  : null
        const expGames = bp.expected_games != null ? bp.expected_games.toFixed(1) : null

        return (
          <div style={{ ...cardStyle, marginTop: 0 }}>
            <div style={sectionLabelStyle}>Over/Under Markets <span style={{ fontWeight: 400, textTransform: 'none', letterSpacing: 0, color: '#9ca3af' }}>(bzzoiro model)</span></div>
            <div style={{ display: 'flex', flexDirection: 'column', gap: 6 }}>
              {rows.map((row, idx) => (
                <div key={idx} style={{
                  display: 'grid', gridTemplateColumns: '90px 80px 40px 1fr',
                  alignItems: 'center', gap: 10,
                  padding: '4px 0',
                  borderTop: idx > 0 ? '1px solid #f3f4f6' : 'none',
                }}>
                  <span style={{ fontSize: 12, fontWeight: 600, color: '#6b7280' }}>{row.label}</span>
                  <span style={{ fontSize: 12, color: '#374151' }}>{row.market}</span>
                  <span style={{ fontSize: 13, fontWeight: 700, color: '#111827', fontVariantNumeric: 'tabular-nums', textAlign: 'right' }}>{row.pct}%</span>
                  <div style={{ position: 'relative', height: 8, background: '#e5e9f0', borderRadius: 99, overflow: 'hidden' }}>
                    <div style={{
                      position: 'absolute', left: 0, top: 0, bottom: 0, width: `${row.pct}%`,
                      background: row.pct >= 60 ? '#0d9488' : row.pct >= 45 ? '#f59e0b' : '#9ca3af',
                      borderRadius: 99,
                    }} />
                  </div>
                </div>
              ))}
            </div>
            {(expSets || expGames) && (
              <div style={{ marginTop: 10, paddingTop: 8, borderTop: '1px solid #f3f4f6', fontSize: 12, color: '#9ca3af', display: 'flex', gap: 16 }}>
                {expSets  && <span>Expected <strong style={{ color: '#374151' }}>{expSets} sets</strong></span>}
                {expGames && <span>Expected <strong style={{ color: '#374151' }}>{expGames} games</strong></span>}
              </div>
            )}
          </div>
        )
      })()}

      {error && (
        <div style={{ fontSize: 13, color: '#dc2626', padding: '8px 0' }}>
          Couldn&apos;t load intelligence: {error}
        </div>
      )}
    </div>
  )
}

// ─────────────────────────────────────────────────────────────────────────────
// Overview section — ratings + in-play block
// ─────────────────────────────────────────────────────────────────────────────

function RatingRow({ label, v1, v2 }) {
  const n1 = v1 != null ? Math.round(v1) : null
  const n2 = v2 != null ? Math.round(v2) : null
  const maxBar = 80
  const w1 = n1 != null ? Math.round((n1 / 100) * maxBar) : 0
  const w2 = n2 != null ? Math.round((n2 / 100) * maxBar) : 0
  const chip1 = n1 != null ? rttPastel(n1) : null
  const chip2 = n2 != null ? rttPastel(n2) : null

  const bg1 = n1 != null ? (n1 > (n2 ?? 50) ? '#bbf0d0' : n1 < (n2 ?? 50) - 8 ? '#fecaca' : '#fef3c7') : '#e5e9f0'
  const bg2 = n2 != null ? (n2 > (n1 ?? 50) ? '#bbf0d0' : n2 < (n1 ?? 50) - 8 ? '#fecaca' : '#fef3c7') : '#e5e9f0'

  return (
    <div style={{ display: 'grid', gridTemplateColumns: `${maxBar}px 44px 130px 44px ${maxBar}px`, alignItems: 'center', gap: 6, margin: '5px 0' }}>
      <div style={{ display: 'flex', justifyContent: 'flex-end' }}>
        <div style={{ width: w1, height: 6, borderRadius: 3, background: bg1, transition: 'width 0.5s ease' }} />
      </div>
      {chip1 ? (
        <div style={{ background: chip1.bg, color: chip1.text, borderRadius: 6, padding: '2px 6px', fontSize: 13, fontWeight: 700, textAlign: 'center', fontVariantNumeric: 'tabular-nums' }}>{n1}</div>
      ) : (
        <div style={{ fontSize: 12, color: '#9ca3af', textAlign: 'center' }}>—</div>
      )}
      <div style={{ textAlign: 'center', fontSize: 11, color: '#9ca3af', fontWeight: 500 }}>{label}</div>
      {chip2 ? (
        <div style={{ background: chip2.bg, color: chip2.text, borderRadius: 6, padding: '2px 6px', fontSize: 13, fontWeight: 700, textAlign: 'center', fontVariantNumeric: 'tabular-nums' }}>{n2}</div>
      ) : (
        <div style={{ fontSize: 12, color: '#9ca3af', textAlign: 'center' }}>—</div>
      )}
      <div style={{ display: 'flex', justifyContent: 'flex-start' }}>
        <div style={{ width: w2, height: 6, borderRadius: 3, background: bg2, transition: 'width 0.5s ease' }} />
      </div>
    </div>
  )
}

function SectionOverview({ match }) {
  const p1 = match.first_player  || {}
  const p2 = match.second_player || {}
  const r1 = p1.ratings || {}
  const r2 = p2.ratings || {}
  const surface = (match.surface || '').toLowerCase()
  const isFinished2 = /finished/i.test(match.status || '') || !!match.winner
  const isLive  = !!match.is_live && !isFinished2

  const surfaceKey   = surface.includes('clay') ? 'clay_rating' : surface.includes('grass') ? 'grass_rating' : surface.includes('indoor') || surface.includes('carpet') ? 'indoor_rating' : 'hard_rating'
  const surfaceLabel = surface.includes('clay') ? 'Clay' : surface.includes('grass') ? 'Grass' : surface.includes('indoor') || surface.includes('carpet') ? 'Indoor' : 'Hard'

  const round = (match.round || '').toUpperCase()
  const isLateRound = ['F','SF','QF'].includes(round)
  const isBigMatch  = (match.event_type || '').toLowerCase().includes('grand slam') || (match.event_type || '').toLowerCase().includes('masters')
  const opp1IsTop10 = (r2.rtt_score || 0) >= 90
  const opp2IsTop10 = (r1.rtt_score || 0) >= 90

  const p1OppHand = (match.context?.p2_hand || p2.hand || '').toLowerCase()
  const labelHand = (h) => h.startsWith('l') ? 'left-handers' : h.startsWith('r') ? 'right-handers' : 'right-handers (assumed)'
  const vsHandLabel = `vs ${labelHand(p1OppHand)}`

  const rows = [
    { label: 'RTT Score',                 k: 'rtt_score',        always: true },
    { label: `${surfaceLabel} rating`,    k: surfaceKey,         always: true },
    { label: 'Form',                      k: 'form_score',       always: true },
    { label: 'Serve',                     k: 'serve_rating',     always: true },
    { label: 'Return',                    k: 'return_rating',    always: true },
    { label: vsHandLabel,                 k: 'vs_hand',          always: true },
    { label: 'Endurance',                 k: 'endurance',        always: true },
    { label: 'Pressure rating',          k: 'pressure_rating',  show: isLateRound },
    { label: 'Big match rating',         k: 'big_match_rating', show: isBigMatch },
    { label: 'vs Top 10',               k: 'vs_top10_rating',  show: opp1IsTop10 || opp2IsTop10 },
  ].filter(r => r.always || r.show)

  // In-play serve zones state
  const [svNum,  setSvNum]  = useState(1)
  const [svSide, setSvSide] = useState('deuce')
  const [svPlayer, setSvPlayer] = useState('p1')

  const currentPlayer = svPlayer === 'p1' ? p1 : p2
  const zoneData = getZoneData(
    currentPlayer.serve_zones || [],
    currentPlayer.player_id,
    null,
    svNum,
    svSide
  )

  return (
    <div>
      {/* In-play block */}
      {isLive && (
        <div style={{ ...cardStyle, marginBottom: 16 }}>
          <div style={sectionLabelStyle}>In-play</div>
          <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 12 }}>
            {/* Court SVG + toggles */}
            <div>
              <div style={{ display: 'flex', gap: 4, marginBottom: 8, flexWrap: 'wrap' }}>
                {/* Player toggle */}
                {[['p1', (p1.name||'P1').split(' ').pop()], ['p2', (p2.name||'P2').split(' ').pop()]].map(([k, label]) => (
                  <button key={k} onClick={() => setSvPlayer(k)} style={{
                    padding: '3px 8px', fontSize: 11, fontWeight: 600,
                    background: svPlayer === k ? '#0d9488' : '#f3f4f6',
                    color: svPlayer === k ? '#fff' : '#6b7280',
                    border: 'none', borderRadius: 5, cursor: 'pointer',
                  }}>{label}</button>
                ))}
                {[1, 2].map(n => (
                  <button key={n} onClick={() => setSvNum(n)} style={{
                    padding: '3px 8px', fontSize: 11, fontWeight: 600,
                    background: svNum === n ? '#374151' : '#f3f4f6',
                    color: svNum === n ? '#fff' : '#6b7280',
                    border: 'none', borderRadius: 5, cursor: 'pointer',
                  }}>{n === 1 ? '1st' : '2nd'}</button>
                ))}
                {['deuce','ad'].map(s => (
                  <button key={s} onClick={() => setSvSide(s)} style={{
                    padding: '3px 8px', fontSize: 11, fontWeight: 600, textTransform: 'capitalize',
                    background: svSide === s ? '#374151' : '#f3f4f6',
                    color: svSide === s ? '#fff' : '#6b7280',
                    border: 'none', borderRadius: 5, cursor: 'pointer',
                  }}>{s}</button>
                ))}
              </div>
              <CourtSVG sv={svNum} side={svSide} zoneData={zoneData} />
            </div>

            {/* Live stats */}
            <div>
              {match.set_scores && (
                <div style={{ marginBottom: 12 }}>
                  <div style={sectionLabelStyle}>Score</div>
                  <div style={{ display: 'flex', gap: 6 }}>
                    {match.set_scores.split(' ').map((set, i) => (
                      <div key={i} style={{
                        fontSize: 22, fontWeight: 800, color: '#111827',
                        fontVariantNumeric: 'tabular-nums',
                        background: '#f4f6f9', borderRadius: 6, padding: '4px 10px',
                      }}>{fmtSetScore(set)}</div>
                    ))}
                    {isLive && match.game_result && (
                      <div style={{ fontSize: 16, fontWeight: 700, color: '#6b7280', alignSelf: 'center', paddingLeft: 4 }}>{match.game_result}</div>
                    )}
                  </div>
                </div>
              )}

              {/* Live serve stats if available */}
              {currentPlayer.stats?.overall && (() => {
                const s = currentPlayer.stats.overall
                return (
                  <div>
                    <div style={sectionLabelStyle}>{(currentPlayer.name || '').split(' ').pop()} — serve</div>
                    <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 6 }}>
                      {[
                        { label: '1st serve %', v: s.first_serve_pct != null ? `${(s.first_serve_pct*100).toFixed(0)}%` : '—' },
                        { label: 'Aces/match',  v: s.aces_per_match  != null ? Number(s.aces_per_match).toFixed(1) : '—' },
                        { label: 'Serve rating', v: currentPlayer.ratings?.serve_rating != null ? Math.round(currentPlayer.ratings.serve_rating) : '—' },
                        { label: 'BP saved',    v: s.bp_saved_pct != null ? `${(s.bp_saved_pct*100).toFixed(0)}%` : '—' },
                      ].map(({ label, v }) => (
                        <div key={label} style={{ background: '#f4f6f9', borderRadius: 8, padding: '8px 10px' }}>
                          <div style={{ fontSize: 16, fontWeight: 800, color: '#111827', fontVariantNumeric: 'tabular-nums' }}>{v}</div>
                          <div style={{ fontSize: 10, color: '#9ca3af', fontWeight: 600, textTransform: 'uppercase', letterSpacing: '0.5px', marginTop: 2 }}>{label}</div>
                        </div>
                      ))}
                    </div>
                  </div>
                )
              })()}
            </div>
          </div>
        </div>
      )}

      {/* Ratings comparison */}
      <div style={cardStyle}>
        <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: 13, fontWeight: 700, marginBottom: 10 }}>
          <span style={{ color: '#0d9488' }}>{p1.name}</span>
          <span style={{ color: '#6366f1' }}>{p2.name}</span>
        </div>
        <div style={{ ...sectionLabelStyle, textAlign: 'center' }}>
          Ratings — {surfaceLabel}{match.round ? ` · ${match.round}` : ''}
        </div>
        <div style={{ display: 'flex', flexDirection: 'column', alignItems: 'center' }}>
          {rows.map(({ label, k }) => (
            <RatingRow key={k} label={label} v1={r1[k]} v2={r2[k]} />
          ))}
        </div>
        <div style={{ fontSize: 11, color: '#9ca3af', marginTop: 10, textAlign: 'center' }}>
          Ratings are 0–100. — indicates insufficient match data.
        </div>
      </div>
    </div>
  )
}

// ─────────────────────────────────────────────────────────────────────────────
// Form section
// ─────────────────────────────────────────────────────────────────────────────

function FormRacecard({ matches, align = 'left' }) {
  if (!matches || !matches.length) {
    return <div style={{ fontSize: 12, color: '#9ca3af', padding: '12px 0' }}>No recent form data</div>
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
            minWidth: 36, textAlign: 'center', flexShrink: 0,
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
        const dateScore = (
          <div style={{
            flexShrink: 0, fontSize: 11, fontWeight: 500, color: '#9ca3af',
            whiteSpace: 'nowrap', display: 'flex', gap: 6, alignItems: 'baseline',
            justifyContent: isRight ? 'flex-end' : 'flex-start',
          }}>
            <span style={{ color: '#374151', fontWeight: 600 }}>{fmtShortDate(m.date)}</span>
            {m.score && <span style={{ fontSize: 10, color: '#9ca3af' }}>{m.score}</span>}
          </div>
        )
        const opponent = (
          <div style={{ flex: 1, minWidth: 0, textAlign: isRight ? 'left' : 'right' }}>
            <div style={{ fontSize: 12, fontWeight: 500, color: '#374151', whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis' }}>
              {m.opponent_name || 'Unknown'}
            </div>
          </div>
        )
        return (
          <div key={i} style={{
            display: 'flex', alignItems: 'center', gap: 8,
            padding: '6px 0',
            borderBottom: i < Math.min(matches.length, 10) - 1 ? '1px solid #f3f4f6' : 'none',
          }}>
            {isRight ? <>{chip}{wlBadge}{opponent}{dateScore}</> : <>{dateScore}{opponent}{wlBadge}{chip}</>}
          </div>
        )
      })}
    </div>
  )
}

function SectionForm({ match }) {
  const [surface, setSurface] = useState('all')
  const [p1Form,  setP1Form]  = useState(null)
  const [p2Form,  setP2Form]  = useState(null)
  const [loading, setLoading] = useState(true)

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

  const p1Matches = p1Form?.matches || []
  const p2Matches = p2Form?.matches || []

  function summary(ms) {
    if (!ms.length) return null
    const avg    = ms.reduce((s, m) => s + (m.performance_index || 0), 0) / ms.length
    const wins   = ms.filter(m => m.won).length
    const last5  = ms.slice(0, 5)
    const prior5 = ms.slice(5, 10)
    const trend  = last5.length && prior5.length
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
      <div style={{ display: 'flex', gap: 6, marginBottom: 14 }}>
        {['all','Clay','Hard','Grass'].map(s => (
          <button key={s} onClick={() => setSurface(s)} style={{
            padding: '4px 10px', fontSize: 12, fontWeight: 600,
            background: surface === s ? '#0d9488' : '#f3f4f6',
            color: surface === s ? '#fff' : '#6b7280',
            border: 'none', borderRadius: 6, cursor: 'pointer',
          }}>{s}</button>
        ))}
      </div>

      {loading ? (
        <div style={{ fontSize: 14, color: '#9ca3af', padding: '16px 0' }}>Loading form data…</div>
      ) : (
        <>
          <div style={{ marginBottom: 16 }}>
            <FormChart p1Form={p1Form} p2Form={p2Form} p1Name={p1.name} p2Name={p2.name} />
          </div>

          {/* Summary stats */}
          <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 10, marginBottom: 14 }}>
            {[
              { name: p1.name, s: s1, r: p1.ratings, fd: p1.form_dots },
              { name: p2.name, s: s2, r: p2.ratings, fd: p2.form_dots },
            ].map(({ name, s, r, fd }) => (
              <div key={name} style={cardStyle}>
                <div style={{ fontSize: 11, fontWeight: 600, color: '#6b7280', marginBottom: 8 }}>{name}</div>
                {s ? (
                  <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr 1fr', gap: 6, marginBottom: 10 }}>
                    {[
                      { v: s.avg, label: 'Avg idx' },
                      { v: `${s.wins}/${s.total}`, label: 'W/L' },
                      { v: `${Number(s.trend) > 0 ? '+' : ''}${s.trend}`, label: 'Trend', color: Number(s.trend) > 0 ? '#15803d' : Number(s.trend) < 0 ? '#991b1b' : '#111827' },
                    ].map(({ v, label, color }) => (
                      <div key={label} style={{ background: '#f9fafb', border: '1px solid #e5e9f0', borderRadius: 8, padding: '8px 6px', textAlign: 'center' }}>
                        <div style={{ fontSize: 18, fontWeight: 800, letterSpacing: '-0.5px', lineHeight: 1, color: color || '#111827', fontVariantNumeric: 'tabular-nums' }}>{v}</div>
                        <div style={{ fontSize: 9, textTransform: 'uppercase', letterSpacing: '0.5px', color: '#9ca3af', marginTop: 3 }}>{label}</div>
                      </div>
                    ))}
                  </div>
                ) : (
                  <div style={{ fontSize: 12, color: '#9ca3af', marginBottom: 10 }}>No data</div>
                )}
                <div style={{ display: 'flex', alignItems: 'center', gap: 8, paddingTop: 8, borderTop: '1px solid #f3f4f6' }}>
                  <MomentumSquares momentum={r?.momentum} form_dots={fd} />
                  <span style={{
                    fontSize: 11, fontWeight: 600,
                    color: r?.momentum === 'rising' ? '#166534' : r?.momentum === 'falling' ? '#991b1b' : '#9ca3af',
                  }}>
                    Momentum: {r?.momentum ? r.momentum.charAt(0).toUpperCase() + r.momentum.slice(1) : 'Stable'}
                  </span>
                </div>
              </div>
            ))}
          </div>

          {/* Racecard */}
          <div style={cardStyle}>
            <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 24 }}>
              <div>
                <div style={{ fontSize: 11, fontWeight: 700, color: '#0d9488', marginBottom: 10 }}>{p1.name}</div>
                <FormRacecard matches={p1Matches} align="left" />
              </div>
              <div>
                <div style={{ fontSize: 11, fontWeight: 700, color: '#6366f1', marginBottom: 10, textAlign: 'right' }}>{p2.name}</div>
                <FormRacecard matches={p2Matches} align="right" />
              </div>
            </div>
          </div>
        </>
      )}
    </div>
  )
}

// ─────────────────────────────────────────────────────────────────────────────
// H2H section
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

  if (loading) return <div style={{ fontSize: 14, color: '#9ca3af', padding: '16px 0' }}>Loading H2H…</div>

  const summary  = h2h?.summary  || {}
  const meetings = h2h?.matches  || []

  return (
    <div>
      {/* Headline numbers */}
      <div style={{ ...cardStyle, display: 'grid', gridTemplateColumns: '1fr auto 1fr', alignItems: 'center', gap: 16, padding: '20px 16px' }}>
        <div style={{ textAlign: 'center' }}>
          <div style={{ fontSize: 40, fontWeight: 900, color: '#0d9488', lineHeight: 1, fontVariantNumeric: 'tabular-nums' }}>{summary.p1_wins ?? 0}</div>
          <div style={{ fontSize: 12, color: '#6b7280', marginTop: 4 }}>{p1.name}</div>
        </div>
        <div style={{ fontSize: 12, color: '#9ca3af', textAlign: 'center', textTransform: 'uppercase', letterSpacing: 0.6, fontWeight: 700 }}>
          {summary.total ?? 0} meetings
        </div>
        <div style={{ textAlign: 'center' }}>
          <div style={{ fontSize: 40, fontWeight: 900, color: '#6366f1', lineHeight: 1, fontVariantNumeric: 'tabular-nums' }}>{summary.p2_wins ?? 0}</div>
          <div style={{ fontSize: 12, color: '#6b7280', marginTop: 4 }}>{p2.name}</div>
        </div>
      </div>

      {summary.by_surface && Object.keys(summary.by_surface).length > 0 && (
        <div style={cardStyle}>
          <div style={sectionLabelStyle}>By surface</div>
          <div style={{ display: 'flex', flexDirection: 'column', gap: 10 }}>
            {Object.entries(summary.by_surface).map(([surf, counts]) => (
              <div key={surf} style={{ display: 'grid', gridTemplateColumns: '40px 1fr 40px', alignItems: 'center', gap: 12 }}>
                <div style={{ textAlign: 'right', fontSize: 14, fontWeight: 700, fontVariantNumeric: 'tabular-nums' }}>{counts.p1}</div>
                <div style={{ display: 'flex', justifyContent: 'center' }}><SurfaceBadge surface={surf} /></div>
                <div style={{ textAlign: 'left', fontSize: 14, fontWeight: 700, fontVariantNumeric: 'tabular-nums' }}>{counts.p2}</div>
              </div>
            ))}
          </div>
        </div>
      )}

      {meetings.length === 0 ? (
        <div style={{ ...cardStyle, textAlign: 'center', color: '#9ca3af', fontSize: 14, padding: '28px 16px' }}>
          No H2H meetings on record
        </div>
      ) : (
        <div style={cardStyle}>
          <div style={sectionLabelStyle}>Recent meetings</div>
          <div style={{ display: 'flex', flexDirection: 'column' }}>
            {meetings.slice(0, 10).map((m, i) => (
              <div key={i} style={{
                display: 'grid', gridTemplateColumns: '12px 1fr auto',
                alignItems: 'center', gap: 14,
                padding: '10px 0',
                borderBottom: i < Math.min(meetings.length, 10) - 1 ? '1px solid #f3f4f6' : 'none',
              }}>
                <div style={{
                  width: 10, height: 10, borderRadius: '50%',
                  background: m.winner === 'first_player' ? '#0d9488' : '#6366f1',
                }} />
                <div>
                  <div style={{ fontSize: 14, fontWeight: 600, color: '#111827', fontVariantNumeric: 'tabular-nums' }}>
                    {m.score || '—'}
                  </div>
                  <div style={{ fontSize: 11, color: '#9ca3af', marginTop: 2 }}>
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
// Serve section (with CourtSVG)
// ─────────────────────────────────────────────────────────────────────────────

const ZONE_LABELS = { wide: 'Wide', body: 'Body', t: 'T' }

function SectionServe({ match }) {
  const [player,   setPlayer]   = useState('p1')
  const [serveNum, setServeNum] = useState(1)
  const [side,     setSide]     = useState('deuce')

  const p1 = match.first_player  || {}
  const p2 = match.second_player || {}
  const current = player === 'p1' ? p1 : p2
  const stats   = current.stats?.overall || {}

  const zoneData = getZoneData(
    current.serve_zones || [],
    current.player_id,
    null,
    serveNum,
    side
  )

  return (
    <div>
      {/* Toggles */}
      <div style={{ display: 'flex', gap: 16, marginBottom: 14, flexWrap: 'wrap' }}>
        <div style={{ display: 'flex', gap: 4 }}>
          {[['p1', p1.name || 'P1'], ['p2', p2.name || 'P2']].map(([key, label]) => (
            <button key={key} onClick={() => setPlayer(key)} style={{
              padding: '4px 10px', fontSize: 12, fontWeight: 600,
              background: player === key ? '#0d9488' : '#f3f4f6',
              color: player === key ? '#fff' : '#6b7280',
              border: 'none', borderRadius: 6, cursor: 'pointer',
            }}>{label?.split(' ').pop()}</button>
          ))}
        </div>
        <div style={{ display: 'flex', gap: 4 }}>
          {[1, 2].map(n => (
            <button key={n} onClick={() => setServeNum(n)} style={{
              padding: '4px 10px', fontSize: 12, fontWeight: 600,
              background: serveNum === n ? '#374151' : '#f3f4f6',
              color: serveNum === n ? '#fff' : '#6b7280',
              border: 'none', borderRadius: 6, cursor: 'pointer',
            }}>{n}{n === 1 ? 'st' : 'nd'} serve</button>
          ))}
        </div>
        <div style={{ display: 'flex', gap: 4 }}>
          {['deuce','ad'].map(s => (
            <button key={s} onClick={() => setSide(s)} style={{
              padding: '4px 10px', fontSize: 12, fontWeight: 600, textTransform: 'capitalize',
              background: side === s ? '#374151' : '#f3f4f6',
              color: side === s ? '#fff' : '#6b7280',
              border: 'none', borderRadius: 6, cursor: 'pointer',
            }}>{s}</button>
          ))}
        </div>
      </div>

      <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 12 }}>
        {/* Court SVG */}
        <div style={cardStyle}>
          <div style={sectionLabelStyle}>Serve placement zones</div>
          {current.serve_zones_estimated && (
            <div style={{ fontSize: 11, color: '#9ca3af', marginBottom: 8 }}>Estimated from serve stats — charting data pending</div>
          )}
          <CourtSVG sv={serveNum} side={side} zoneData={zoneData} />
        </div>

        {/* Serve stats */}
        <div style={cardStyle}>
          <div style={sectionLabelStyle}>Serve stats — {(current.name || '').split(' ').pop()}</div>
          <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 8 }}>
            {[
              { label: '1st serve in',  v: stats.first_serve_pct != null ? `${(stats.first_serve_pct*100).toFixed(0)}%` : '—' },
              { label: 'Aces / match',  v: stats.aces_per_match  != null ? Number(stats.aces_per_match).toFixed(1) : '—' },
              { label: 'Serve rating',  v: current.ratings?.serve_rating != null ? Math.round(current.ratings.serve_rating) : '—' },
              { label: 'BP saved',      v: stats.bp_saved_pct != null ? `${(stats.bp_saved_pct*100).toFixed(0)}%` : '—' },
            ].map(({ label, v }) => (
              <div key={label} style={{ background: '#f9fafb', border: '1px solid #e5e9f0', borderRadius: 8, padding: '10px 12px' }}>
                <div style={{ fontSize: 20, fontWeight: 800, color: '#111827', fontVariantNumeric: 'tabular-nums' }}>{v}</div>
                <div style={{ fontSize: 10, color: '#9ca3af', fontWeight: 600, textTransform: 'uppercase', letterSpacing: '0.5px', marginTop: 3 }}>{label}</div>
              </div>
            ))}
          </div>
        </div>
      </div>
    </div>
  )
}

// ─────────────────────────────────────────────────────────────────────────────
// Main
// ─────────────────────────────────────────────────────────────────────────────

export default function MatchDetailClient({ initialMatch = null, matchId }) {
  const params = useParams()
  const slug   = params?.slug ? (Array.isArray(params.slug) ? params.slug.join('/') : params.slug) : ''
  const router = useRouter()

  const [match,   setMatch]   = useState(initialMatch)
  const [loading, setLoading] = useState(true)
  const [error,   setError]   = useState(null)
  const [activeSection, setActiveSection] = useState('section-intel')

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
          first_player: {
            ...p1,
            player_id:    p1.id,
            logo_url:     p1.logo_url     || null,
            current_rank: p1.current_rank || null,
          },
          second_player: {
            ...p2,
            player_id:    p2.id,
            logo_url:     p2.logo_url     || null,
            current_rank: p2.current_rank || null,
          },
          prediction: {
            ...pred,
            edge_first:  edge.p1,
            edge_second: edge.p2,
          },
          market: {
            odds_first_player:  mkt.p1?.decimal_odds,
            odds_second_player: mkt.p2?.decimal_odds,
            bookmaker:          mkt.p1?.bookmaker || mkt.p2?.bookmaker,
            display_name_p1:    mkt.p1?.display_name || mkt.p1?.bookmaker,
            display_name_p2:    mkt.p2?.display_name || mkt.p2?.bookmaker,
            link_url_p1:        mkt.p1?.link_url,
            link_url_p2:        mkt.p2?.link_url,
            all_bookmakers:     mkt.all_bookmakers || [],
            bresbet_link:       mkt.bresbet_link       || null,
            cloudbet_link:      mkt.cloudbet_link      || null,
            cloudbet_event_url: mkt.cloudbet_event_url || null,
            cloudbet_markets:   mkt.cloudbet_markets   || null,
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
    const p1    = match.first_player?.name  || ''
    const p2    = match.second_player?.name || ''
    const date  = (match.event_date || '').slice(0, 10)
    const tourn = match.tournament || ''
    const expectedSlug = [date, _toSlug(tourn), `${_toSlug(p1)}-vs-${_toSlug(p2)}`].filter(Boolean).join('-')
    if (expectedSlug && slug !== expectedSlug) {
      router.replace(`/match/${matchId}/${expectedSlug}`)
    }
  }, [match, matchId, slug, router])

  // IntersectionObserver — track active section for nav highlight
  useEffect(() => {
    const sections = ['section-intel','section-overview','section-form','section-h2h','section-serve']
    const observer = new IntersectionObserver(
      entries => {
        entries.forEach(e => { if (e.isIntersecting) setActiveSection(e.target.id) })
      },
      { rootMargin: '-40% 0px -55% 0px' }
    )
    sections.forEach(id => {
      const el = document.getElementById(id)
      if (el) observer.observe(el)
    })
    return () => observer.disconnect()
  }, [match])

  // SEO
  const _p1Name  = match?.first_player?.name  || ''
  const _p2Name  = match?.second_player?.name || ''
  const _tourn   = match?.tournament || ''
  const _date    = match?.event_date ? new Date(match.event_date).toLocaleDateString('en-GB', { day: 'numeric', month: 'long', year: 'numeric' }) : ''
  const _jsonLd  = useMemo(() => !_p1Name ? null : ({
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
  }), [_p1Name, _p2Name, _tourn, match?.event_date, match?.surface]) // eslint-disable-line

  if (loading) return <div style={{ minHeight: '100vh', display: 'flex', alignItems: 'center', justifyContent: 'center', fontSize: 14, color: '#9ca3af' }}>Loading match…</div>
  if (error)   return <div style={{ minHeight: '100vh', display: 'flex', alignItems: 'center', justifyContent: 'center', fontSize: 14, color: '#dc2626' }}>{error}</div>
  if (!match)  return null

  const SCROLL_MARGIN = 150  // px below both sticky bars

  return (
    <div style={{ background: '#f4f6f9', minHeight: '100vh' }}>

      {/* STICKY HEADER */}
      <StickyHeader match={match} />

      {/* STICKY ANCHOR NAV */}
      <AnchorNav activeSection={activeSection} />

      {/* SCROLLING CONTENT */}
      <div style={{ maxWidth: 900, margin: '0 auto', padding: '16px 20px 60px' }}>

        <section id="section-intel" style={{ scrollMarginTop: SCROLL_MARGIN, marginTop: 8 }}>
          <div style={{ fontSize: 13, fontWeight: 700, color: '#374151', marginBottom: 12 }}>Intelligence</div>
          <SectionIntelligence match={match} />
        </section>

        <section id="section-overview" style={{ scrollMarginTop: SCROLL_MARGIN, marginTop: 28 }}>
          <div style={{ fontSize: 13, fontWeight: 700, color: '#374151', marginBottom: 12 }}>Overview</div>
          <SectionOverview match={match} />
        </section>

        <section id="section-form" style={{ scrollMarginTop: SCROLL_MARGIN, marginTop: 28 }}>
          <div style={{ fontSize: 13, fontWeight: 700, color: '#374151', marginBottom: 12 }}>Form</div>
          <SectionForm match={match} />
        </section>

        <section id="section-h2h" style={{ scrollMarginTop: SCROLL_MARGIN, marginTop: 28 }}>
          <div style={{ fontSize: 13, fontWeight: 700, color: '#374151', marginBottom: 12 }}>Head to Head</div>
          <SectionH2H match={match} />
        </section>

        <section id="section-serve" style={{ scrollMarginTop: SCROLL_MARGIN, marginTop: 28 }}>
          <div style={{ fontSize: 13, fontWeight: 700, color: '#374151', marginBottom: 12 }}>Serve</div>
          <SectionServe match={match} />
        </section>

      </div>

    </div>
  )
}
