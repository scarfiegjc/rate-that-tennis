'use client'
/**
 * InPlayClient — graphical live tennis dashboard.
 *
 * Fetches /api/v1/live (FastAPI proxy) every 30 seconds.
 * Falls back to bzzoiro directly if the endpoint returns nothing.
 * Each card shows: set chips, current game score, serving indicator,
 * win probability bar, momentum indicator, RTT ratings, model edge,
 * and a 2-col serve stats panel.
 */

import { useState, useEffect, useCallback } from 'react'
import { useRouter } from 'next/navigation'

const REFRESH_MS    = 30_000
const API_BASE      = process.env.NEXT_PUBLIC_API_URL || ''
const BZZOIRO_URL   = 'https://sports.bzzoiro.com/tennis/api/v2/matches/?status=live'
const BZZOIRO_TOKEN = '4426945bd65f0798e817976bbef975bbb9d0e606'

const courtClay  = '/court-clay.jpg'
const courtHard  = '/court-hard.jpg'
const courtGrass = '/court-grass.jpg'

// ── Country flag helpers ──────────────────────────────────────────────────────

const IOC_TO_ALPHA2 = {
  USA:'US', GBR:'GB', ESP:'ES', FRA:'FR', ITA:'IT', GER:'DE', RUS:'RU', SRB:'RS',
  AUT:'AT', ARG:'AR', CAN:'CA', AUS:'AU', JPN:'JP', CHN:'CN', KOR:'KR', BRA:'BR',
  NED:'NL', BEL:'BE', SUI:'CH', CRO:'HR', GRE:'GR', POL:'PL', NOR:'NO', SWE:'SE',
  DEN:'DK', FIN:'FI', CZE:'CZ', SVK:'SK', HUN:'HU', ROU:'RO', BUL:'BG', UKR:'UA',
  BLR:'BY', LAT:'LV', LTU:'LT', EST:'EE', POR:'PT', IRL:'IE', ISL:'IS', IND:'IN',
  KAZ:'KZ', MEX:'MX', COL:'CO', CHI:'CL', URU:'UY', PER:'PE', VEN:'VE', ECU:'EC',
  PAR:'PY', RSA:'ZA', EGY:'EG', MAR:'MA', TUN:'TN', ALG:'DZ', ISR:'IL', TUR:'TR',
  LIB:'LB', JOR:'JO', KSA:'SA', QAT:'QA', UAE:'AE', NZL:'NZ', TPE:'TW', HKG:'HK',
  SIN:'SG', THA:'TH', INA:'ID', MAS:'MY', PHI:'PH', VIE:'VN', PUR:'PR', DOM:'DO',
  BAH:'BS', BAR:'BB', JAM:'JM', SLO:'SI', MNE:'ME', MDA:'MD', GEO:'GE', ARM:'AM',
  AZE:'AZ', UZB:'UZ', LUX:'LU', MON:'MC', LIE:'LI', CYP:'CY', MLT:'MT', BIH:'BA',
  MKD:'MK', ALB:'AL', KOS:'XK',
}
function flagEmoji(code) {
  if (!code) return ''
  const up = code.toUpperCase()
  const cc = up.length === 2 ? up : (IOC_TO_ALPHA2[up] || '')
  if (cc.length !== 2) return ''
  return String.fromCodePoint(...[...cc].map(c => 0x1f1a5 + c.charCodeAt(0)))
}

// ── SEO URL helpers ───────────────────────────────────────────────────────────

function toSlug(str) {
  return (str || '')
    .toLowerCase()
    .normalize('NFD').replace(/[̀-ͯ]/g, '')
    .replace(/[^a-z0-9]+/g, '-')
    .replace(/^-+|-+$/g, '')
}
function matchUrl(match) {
  const date       = (match.event_date || match.match_date || '').slice(0, 10)
  const tournName  = typeof match.tournament === 'object' ? match.tournament?.name : match.tournament
  const tournament = toSlug(tournName || match.tournament_name || '')
  const p1         = toSlug(match.first_player?.name  || match.player1?.name || 'player')
  const p2         = toSlug(match.second_player?.name || match.player2?.name || 'player')
  const slug       = [date, tournament, `${p1}-vs-${p2}`].filter(Boolean).join('-')
  const id         = match.internal_id || match.match_id || match.id
  return `/match/${id}/${slug}`
}

// ── Court background ──────────────────────────────────────────────────────────

function courtBg(surface, tournament) {
  const s = (surface || '').toLowerCase()
  let img = s.includes('clay')  ? courtClay
           : s.includes('grass') ? courtGrass
           : s.includes('hard')  ? courtHard
           : null
  if (!img) {
    const n = (tournament || '').toLowerCase()
    img = /wimbledon|queen|halle|eastbourne|grass/i.test(n) ? courtGrass
        : /roland|french|monte.?carlo|barcelona|madrid|clay/i.test(n) ? courtClay
        : courtHard
  }
  return {
    backgroundImage: `linear-gradient(rgba(0,0,0,0.55),rgba(0,0,0,0.55)),url(${img})`,
    backgroundSize: 'cover', backgroundPosition: 'center',
  }
}

// ── Implied probability from decimal odds ─────────────────────────────────────

function impliedProb(odds) {
  if (!odds || odds <= 1) return null
  return 1 / odds
}

// ── Progress bar (for serve stats) ───────────────────────────────────────────

function ProgressBar({ value, max = 1, color = '#059669', height = 6 }) {
  const pct = Math.min(100, Math.round((value || 0) * 100 / (max || 1)))
  return (
    <div style={{ position: 'relative', height, borderRadius: 99, background: 'rgba(0,0,0,0.15)', overflow: 'hidden', flex: 1 }}>
      <div style={{
        position: 'absolute', left: 0, top: 0, bottom: 0,
        width: `${pct}%`, background: color, borderRadius: 99,
        transition: 'width 0.4s ease',
      }} />
    </div>
  )
}

// ── RTT Score badge ──────────────────────────────────────────────────────────

function RttBadge({ score, side = 'left' }) {
  if (score == null) return null
  const color = score >= 85 ? '#15803d' : score >= 70 ? '#2563eb' : score >= 55 ? '#9333ea' : '#6b7280'
  return (
    <span style={{
      display: 'inline-flex', alignItems: 'center', gap: 2,
      fontSize: 9, fontWeight: 800, color,
      background: `${color}15`, borderRadius: 4,
      padding: '1px 4px', letterSpacing: '0.03em',
    }}>
      RTT {Math.round(score)}
    </span>
  )
}

// ── Momentum indicator ───────────────────────────────────────────────────────

function MomentumBadge({ momentum, p1Name, p2Name }) {
  if (!momentum) return null

  const { direction, strength, label, swing } = momentum

  let color, icon, text
  if (direction === 'neutral' || direction === 'even') {
    color = '#6b7280'
    icon = '='
    text = label
  } else if (swing) {
    color = '#f59e0b'
    icon = '⇄'  // ⇄
    text = label
  } else if (direction === 'p1') {
    color = strength === 'strong' ? '#15803d' : '#22c55e'
    icon = '↑'  // ↑
    text = `${(p1Name || '').split(' ').pop()} ${label.toLowerCase()}`
  } else {
    color = strength === 'strong' ? '#1d4ed8' : '#3b82f6'
    icon = '↑'  // ↑
    text = `${(p2Name || '').split(' ').pop()} ${label.toLowerCase()}`
  }

  return (
    <div style={{
      display: 'flex', alignItems: 'center', gap: 4,
      padding: '3px 8px', borderRadius: 6,
      background: `${color}12`, border: `1px solid ${color}30`,
    }}>
      <span style={{ fontSize: 11, color }}>{icon}</span>
      <span style={{ fontSize: 10, fontWeight: 700, color, letterSpacing: '0.02em' }}>{text}</span>
    </div>
  )
}

// ── Edge badge ───────────────────────────────────────────────────────────────

function EdgeBadge({ edge }) {
  if (!edge || !edge.edge_pct) return null
  const val = edge.edge_pct
  if (Math.abs(val) < 2) return null
  const positive = val > 0
  const color = positive ? '#15803d' : '#dc2626'
  return (
    <span style={{
      fontSize: 9, fontWeight: 800, color,
      background: `${color}12`, borderRadius: 4,
      padding: '1px 5px', letterSpacing: '0.03em',
    }}>
      {positive ? '+' : ''}{val.toFixed(1)}% edge
    </span>
  )
}

// ── Score flow mini-chart ────────────────────────────────────────────────────

function ScoreFlow({ sets }) {
  if (!sets || sets.length <= 1) return null
  // Show game margins per set as a tiny bar chart
  return (
    <div style={{
      display: 'flex', alignItems: 'center', gap: 2,
      padding: '4px 0',
    }}>
      {sets.map((s, i) => {
        const g1 = s.p1 ?? 0
        const g2 = s.p2 ?? 0
        const total = g1 + g2
        if (total === 0) return null
        const p1Pct = Math.round((g1 / total) * 100)
        return (
          <div key={i} style={{
            flex: 1, height: 4, borderRadius: 2,
            background: '#e5e9f0', overflow: 'hidden',
            display: 'flex',
          }}>
            <div style={{ width: `${p1Pct}%`, background: '#15803d', borderRadius: '2px 0 0 2px' }} />
            <div style={{ flex: 1, background: '#1d4ed8', borderRadius: '0 2px 2px 0' }} />
          </div>
        )
      })}
    </div>
  )
}

// ── Animated "No matches" empty state ────────────────────────────────────────

function EmptyState() {
  return (
    <div style={{
      display: 'flex', flexDirection: 'column', alignItems: 'center',
      justifyContent: 'center', padding: '80px 24px', textAlign: 'center',
      gap: 16,
    }}>
      <div style={{
        fontSize: 48, lineHeight: 1,
        animation: 'bounce 2s ease-in-out infinite',
      }}>&#127934;</div>
      <div style={{ fontSize: 18, fontWeight: 700, color: 'var(--text)' }}>
        No matches in play right now
      </div>
      <div style={{ fontSize: 13, color: 'var(--text-3)', maxWidth: 300, lineHeight: 1.6 }}>
        Check back soon — the page refreshes automatically every 30 seconds.
      </div>
      <style>{`
        @keyframes bounce {
          0%, 100% { transform: translateY(0); }
          50% { transform: translateY(-12px); }
        }
      `}</style>
    </div>
  )
}

// ── Serve stat row ────────────────────────────────────────────────────────────

function ServeRow({ label, p1Val, p2Val, asPercent = true }) {
  const fmt = v => v == null ? '—' : asPercent ? `${Math.round(v * 100)}%` : String(v)
  return (
    <div style={{ display: 'contents' }}>
      <div style={{ display: 'flex', alignItems: 'center', gap: 5, justifyContent: 'flex-end' }}>
        <span style={{ fontSize: 11, fontWeight: 700, color: '#15803d', minWidth: 28, textAlign: 'right', fontVariantNumeric: 'tabular-nums' }}>{fmt(p1Val)}</span>
        <ProgressBar value={asPercent ? p1Val : (p1Val / 20)} color="#16a34a" height={5} />
      </div>
      <div style={{ fontSize: 10, color: '#9ca3af', textAlign: 'center', fontWeight: 600, textTransform: 'uppercase', letterSpacing: '0.05em', padding: '0 4px' }}>{label}</div>
      <div style={{ display: 'flex', alignItems: 'center', gap: 5 }}>
        <ProgressBar value={asPercent ? p2Val : (p2Val / 20)} color="#1d4ed8" height={5} />
        <span style={{ fontSize: 11, fontWeight: 700, color: '#1d4ed8', minWidth: 28, fontVariantNumeric: 'tabular-nums' }}>{fmt(p2Val)}</span>
      </div>
    </div>
  )
}

// ── Main match card ───────────────────────────────────────────────────────────

function LiveMatchCard({ match }) {
  const router = useRouter()

  // Normalise both our API shape and bzzoiro direct shape
  const p1Name = match.first_player?.name  || match.player1?.name || '—'
  const p2Name = match.second_player?.name || match.player2?.name || '—'
  const p1Flag = match.first_player?.country_code  || match.player1?.country_code || match.player1?.country || ''
  const p2Flag = match.second_player?.country_code || match.player2?.country_code || match.player2?.country || ''

  const tournObj   = typeof match.tournament === 'object' ? match.tournament : null
  const tournament = tournObj?.name || match.tournament_name || (typeof match.tournament === 'string' ? match.tournament : '') || ''
  const surface    = match.surface || tournObj?.surface || match.tournament_surface || ''
  const roundName  = match.round_name || match.round || ''

  // Scores
  const p1Sets = match.player1_sets ?? null
  const p2Sets = match.player2_sets ?? null
  const setsDetail = match.sets_detail || []
  const currentPoint = match.current_point || match.point_score || null
  const p1Games = match.player1_games ?? null
  const p2Games = match.player2_games ?? null
  const p1Serving = match.is_serving_p1 ?? null

  // RTT data
  const rtt = match.rtt || {}
  const prediction = match.prediction || {}
  const edge = match.edge || null
  const momentum = match.momentum || null

  // Rankings
  const p1Rank = match.player1?.current_ranking?.position || null
  const p2Rank = match.player2?.current_ranking?.position || null

  // Odds → implied probability
  const odds1 = match.odds_player1 ?? null
  const odds2 = match.odds_player2 ?? null
  let p1Prob = prediction.prob_p1 || impliedProb(odds1)
  let p2Prob = prediction.prob_p2 || impliedProb(odds2)
  if (p1Prob != null && p2Prob != null) {
    const tot = p1Prob + p2Prob
    p1Prob = p1Prob / tot
    p2Prob = p2Prob / tot
  } else if (p1Prob != null) {
    p2Prob = 1 - p1Prob
  } else {
    p1Prob = 0.5; p2Prob = 0.5
  }
  const p1ProbPct = Math.round(p1Prob * 100)
  const p2ProbPct = Math.round(p2Prob * 100)
  const probSource = prediction.prob_p1 ? 'Model' : (odds1 ? 'Market' : null)

  // Serve stats (from merged DB data or top-level bzzoiro)
  const ss = match.serve_stats || {}
  const p1_1stPct  = ss.p1_first_serve_pct       ?? match.p1_first_serve_pct       ?? null
  const p1_1stWon  = ss.p1_first_serve_won_pct   ?? match.p1_first_serve_won_pct   ?? null
  const p1_2ndWon  = ss.p1_second_serve_won_pct  ?? match.p1_second_serve_won_pct  ?? null
  const p1Aces     = ss.p1_aces                   ?? match.p1_aces                   ?? null
  const p1Dfs      = ss.p1_double_faults          ?? match.p1_double_faults          ?? null
  const p2_1stPct  = ss.p2_first_serve_pct       ?? match.p2_first_serve_pct       ?? null
  const p2_1stWon  = ss.p2_first_serve_won_pct   ?? match.p2_first_serve_won_pct   ?? null
  const p2_2ndWon  = ss.p2_second_serve_won_pct  ?? match.p2_second_serve_won_pct  ?? null
  const p2Aces     = ss.p2_aces                   ?? match.p2_aces                   ?? null
  const p2Dfs      = ss.p2_double_faults          ?? match.p2_double_faults          ?? null
  const hasServeStats = p1_1stPct != null || p1_1stWon != null

  const hdrStyle = courtBg(surface, tournament)
  const hasLink = !!match.internal_id

  return (
    <button
      onClick={() => hasLink && router.push(matchUrl(match))}
      style={{
        display: 'flex', flexDirection: 'column',
        width: '100%', textAlign: 'left',
        background: '#fff',
        border: '1px solid #e5e9f0',
        borderRadius: 10,
        overflow: 'hidden',
        cursor: hasLink ? 'pointer' : 'default',
        fontFamily: 'inherit',
        transition: 'box-shadow 0.15s, transform 0.15s',
        boxShadow: '0 1px 4px rgba(0,0,0,0.06)',
      }}
      onMouseEnter={e => { if (hasLink) { e.currentTarget.style.boxShadow = '0 4px 16px rgba(0,0,0,0.1)'; e.currentTarget.style.transform = 'translateY(-2px)' }}}
      onMouseLeave={e => { e.currentTarget.style.boxShadow = '0 1px 4px rgba(0,0,0,0.06)'; e.currentTarget.style.transform = 'none' }}
    >

      {/* ── Tournament header ── */}
      <div style={{
        ...hdrStyle,
        padding: '7px 12px',
        display: 'flex', alignItems: 'center', justifyContent: 'space-between', gap: 8,
      }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: 6, overflow: 'hidden', flex: 1 }}>
          <span style={{ fontSize: 11, fontWeight: 700, color: 'rgba(255,255,255,0.9)', letterSpacing: '0.02em', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
            {tournament || 'Live Match'}
          </span>
          {roundName && (
            <span style={{ fontSize: 9, color: 'rgba(255,255,255,0.6)', whiteSpace: 'nowrap', flexShrink: 0 }}>
              {roundName}
            </span>
          )}
        </div>
        <div style={{ display: 'flex', alignItems: 'center', gap: 6, flexShrink: 0 }}>
          {edge && <EdgeBadge edge={edge} />}
          <span style={{
            display: 'inline-flex', alignItems: 'center', gap: 5,
            background: 'rgba(220,38,38,0.85)', color: '#fff',
            borderRadius: 20, padding: '2px 8px',
            fontSize: 10, fontWeight: 800, letterSpacing: '0.07em',
            flexShrink: 0,
          }}>
            <span style={{
              width: 5, height: 5, borderRadius: '50%', background: '#fff',
              animation: 'livePulse 1.2s ease-in-out infinite',
              display: 'inline-block', flexShrink: 0,
            }} />
            LIVE
          </span>
        </div>
      </div>

      {/* ── Score strip ── */}
      <div style={{ padding: '10px 14px', display: 'flex', alignItems: 'center', gap: 0 }}>
        {/* P1 name + serving ball + sets */}
        <div style={{ flex: 1, minWidth: 0 }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: 5, marginBottom: 2 }}>
            <span style={{ fontSize: 12, fontWeight: 700, color: '#111827', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
              {p1Flag && <span style={{ marginRight: 4 }}>{flagEmoji(p1Flag)}</span>}
              {p1Name}
            </span>
            {p1Serving === true && (
              <span style={{ fontSize: 12, lineHeight: 1, flexShrink: 0 }} title="Serving">&#127934;</span>
            )}
          </div>
          {/* Rank + RTT */}
          <div style={{ display: 'flex', alignItems: 'center', gap: 4, marginBottom: 5 }}>
            {p1Rank && <span style={{ fontSize: 9, color: '#9ca3af', fontWeight: 600 }}>#{p1Rank}</span>}
            <RttBadge score={rtt.p1_score} />
          </div>
          <div style={{ display: 'flex', alignItems: 'center', gap: 5 }}>
            {setsDetail.map((s, i) => {
              const sp1 = s.p1 ?? 0
              const sp2 = s.p2 ?? 0
              const won = sp1 > sp2
              const complete = (sp1 + sp2) >= 6
              return (
                <span key={i} style={{
                  fontSize: 15, fontWeight: 900,
                  color: complete ? (won ? '#15803d' : '#9ca3af') : '#111827',
                  fontVariantNumeric: 'tabular-nums',
                  minWidth: 14, textAlign: 'center',
                }}>
                  {sp1}
                </span>
              )
            })}
            {p1Games != null && (
              <span style={{
                fontSize: 17, fontWeight: 900, color: '#111827',
                fontVariantNumeric: 'tabular-nums',
                background: '#f4f6f9', borderRadius: 5,
                padding: '1px 7px', minWidth: 24, textAlign: 'center',
              }}>
                {p1Games}
              </span>
            )}
          </div>
        </div>

        {/* Centre: current point + set indicator */}
        <div style={{ display: 'flex', flexDirection: 'column', alignItems: 'center', gap: 2, padding: '0 12px', flexShrink: 0 }}>
          {currentPoint && (
            <span style={{ fontSize: 13, fontWeight: 800, color: '#f59e0b', letterSpacing: '0.02em', whiteSpace: 'nowrap' }}>
              {currentPoint}
            </span>
          )}
          <span style={{ fontSize: 9, fontWeight: 600, color: '#9ca3af', textTransform: 'uppercase', letterSpacing: '0.07em' }}>
            {setsDetail.length > 0 ? `Set ${setsDetail.length}` : 'Live'}
          </span>
        </div>

        {/* P2 name + serving ball + sets */}
        <div style={{ flex: 1, minWidth: 0, textAlign: 'right' }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: 5, marginBottom: 2, justifyContent: 'flex-end' }}>
            {p1Serving === false && (
              <span style={{ fontSize: 12, lineHeight: 1, flexShrink: 0 }} title="Serving">&#127934;</span>
            )}
            <span style={{ fontSize: 12, fontWeight: 700, color: '#111827', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
              {p2Name}
              {p2Flag && <span style={{ marginLeft: 4 }}>{flagEmoji(p2Flag)}</span>}
            </span>
          </div>
          {/* Rank + RTT */}
          <div style={{ display: 'flex', alignItems: 'center', gap: 4, marginBottom: 5, justifyContent: 'flex-end' }}>
            <RttBadge score={rtt.p2_score} side="right" />
            {p2Rank && <span style={{ fontSize: 9, color: '#9ca3af', fontWeight: 600 }}>#{p2Rank}</span>}
          </div>
          <div style={{ display: 'flex', alignItems: 'center', gap: 5, justifyContent: 'flex-end' }}>
            {p2Games != null && (
              <span style={{
                fontSize: 17, fontWeight: 900, color: '#111827',
                fontVariantNumeric: 'tabular-nums',
                background: '#f4f6f9', borderRadius: 5,
                padding: '1px 7px', minWidth: 24, textAlign: 'center',
              }}>
                {p2Games}
              </span>
            )}
            {[...setsDetail].reverse().map((s, i) => {
              const sp2 = s.p2 ?? 0
              const sp1 = s.p1 ?? 0
              const won = sp2 > sp1
              const complete = (sp1 + sp2) >= 6
              return (
                <span key={i} style={{
                  fontSize: 15, fontWeight: 900,
                  color: complete ? (won ? '#1d4ed8' : '#9ca3af') : '#111827',
                  fontVariantNumeric: 'tabular-nums',
                  minWidth: 14, textAlign: 'center',
                }}>
                  {sp2}
                </span>
              )
            }).reverse()}
          </div>
        </div>
      </div>

      {/* ── Momentum + Score flow ── */}
      {(momentum || setsDetail.length > 1) && (
        <div style={{ padding: '0 14px 6px', display: 'flex', alignItems: 'center', gap: 8 }}>
          <MomentumBadge momentum={momentum} p1Name={p1Name} p2Name={p2Name} />
          <div style={{ flex: 1 }}>
            <ScoreFlow sets={setsDetail} />
          </div>
        </div>
      )}

      {/* ── Win probability bar ── */}
      <div style={{ padding: '0 14px 10px' }}>
        <div style={{ position: 'relative', height: 18, borderRadius: 99, overflow: 'hidden', background: '#e5e9f0', display: 'flex' }}>
          <div style={{
            width: `${p1ProbPct}%`, background: 'linear-gradient(to right, #15803d, #16a34a)',
            transition: 'width 0.5s ease',
          }} />
          <div style={{ flex: 1, background: 'linear-gradient(to right, #2563eb, #1d4ed8)' }} />
          <div style={{
            position: 'absolute', inset: 0,
            display: 'flex', alignItems: 'center', justifyContent: 'space-between',
            padding: '0 8px',
          }}>
            <span style={{ fontSize: 10, fontWeight: 800, color: '#fff' }}>{p1ProbPct}%</span>
            <span style={{ fontSize: 9, fontWeight: 600, color: 'rgba(255,255,255,0.8)', textTransform: 'uppercase', letterSpacing: '0.05em' }}>
              {probSource ? `${probSource} prob` : 'Win prob'}
            </span>
            <span style={{ fontSize: 10, fontWeight: 800, color: '#fff' }}>{p2ProbPct}%</span>
          </div>
        </div>
      </div>

      {/* ── Serve stats panel ── */}
      {hasServeStats && (
        <div style={{ padding: '10px 14px 12px', borderTop: '1px solid #e5e9f0' }}>
          <div style={{ fontSize: 10, fontWeight: 700, textTransform: 'uppercase', letterSpacing: '0.06em', color: '#9ca3af', marginBottom: 8, textAlign: 'center' }}>
            Serve stats
          </div>
          <div style={{ display: 'grid', gridTemplateColumns: '1fr auto 1fr', gap: '5px 6px', alignItems: 'center' }}>
            <ServeRow label="1st Srv" p1Val={p1_1stPct}  p2Val={p2_1stPct} />
            {p1_1stWon != null && <ServeRow label="1st Won" p1Val={p1_1stWon} p2Val={p2_1stWon} />}
            {p1_2ndWon != null && <ServeRow label="2nd Won" p1Val={p1_2ndWon} p2Val={p2_2ndWon} />}
          </div>
          {(p1Aces != null || p1Dfs != null) && (
            <div style={{
              display: 'flex', justifyContent: 'space-between',
              marginTop: 8, padding: '6px 0 0',
              borderTop: '1px solid #e5e9f0',
            }}>
              <div style={{ display: 'flex', gap: 10 }}>
                {p1Aces != null && (
                  <span style={{ fontSize: 11, color: '#6b7280' }}>
                    <span style={{ fontWeight: 700, color: '#15803d' }}>{p1Aces}</span>
                    <span style={{ marginLeft: 2 }}>Aces</span>
                  </span>
                )}
                {p1Dfs != null && (
                  <span style={{ fontSize: 11, color: '#6b7280' }}>
                    <span style={{ fontWeight: 700, color: '#dc2626' }}>{p1Dfs}</span>
                    <span style={{ marginLeft: 2 }}>DFs</span>
                  </span>
                )}
              </div>
              <div style={{ display: 'flex', gap: 10 }}>
                {p2Dfs != null && (
                  <span style={{ fontSize: 11, color: '#6b7280', textAlign: 'right' }}>
                    <span style={{ fontWeight: 700, color: '#dc2626' }}>{p2Dfs}</span>
                    <span style={{ marginLeft: 2 }}>DFs</span>
                  </span>
                )}
                {p2Aces != null && (
                  <span style={{ fontSize: 11, color: '#6b7280', textAlign: 'right' }}>
                    <span style={{ fontWeight: 700, color: '#1d4ed8' }}>{p2Aces}</span>
                    <span style={{ marginLeft: 2 }}>Aces</span>
                  </span>
                )}
              </div>
            </div>
          )}
        </div>
      )}

    </button>
  )
}

// ── Data fetching ─────────────────────────────────────────────────────────────

async function fetchLiveMatches() {
  // Try our FastAPI proxy first (enriched with RTT, predictions, momentum)
  try {
    const res = await fetch(`${API_BASE}/api/v1/live`, { cache: 'no-store' })
    if (res.ok) {
      const data = await res.json()
      const matches = Array.isArray(data) ? data : data.matches || data.results || []
      if (matches.length > 0) return matches
    }
  } catch {}

  // Fallback: hit bzzoiro directly (no enrichment)
  try {
    const res = await fetch(BZZOIRO_URL, {
      headers: { Authorization: `Token ${BZZOIRO_TOKEN}` },
      cache: 'no-store',
    })
    if (res.ok) {
      const data = await res.json()
      return Array.isArray(data) ? data : data.results || data.matches || []
    }
  } catch {}

  return []
}

// ── Sort helpers ─────────────────────────────────────────────────────────────

function tournamentTier(match) {
  const tourn = typeof match.tournament === 'object' ? match.tournament : { name: match.tournament || '' }
  const name = (tourn.name || '').toLowerCase()
  const cat = (tourn.category || '').toLowerCase()
  if (/wimbledon|roland|australian|us open/i.test(name) || cat === 'grand_slam') return 0
  if (/masters|1000/i.test(name) || cat === 'masters') return 1
  if (/500|queen|halle|barcelona/i.test(name)) return 2
  if (/250|atp|wta/i.test(name)) return 3
  if (/challenger/i.test(name) || cat === 'challenger') return 4
  return 5
}

// ── Main component ────────────────────────────────────────────────────────────

export default function InPlayClient() {
  const [matches,   setMatches]   = useState([])
  const [loading,   setLoading]   = useState(true)
  const [error,     setError]     = useState(null)
  const [lastFetch, setLastFetch] = useState(null)
  const [tick,      setTick]      = useState(0)

  const load = useCallback(async () => {
    try {
      const data = await fetchLiveMatches()
      // Sort: Slams/Masters first, then by RTT score sum
      data.sort((a, b) => {
        const ta = tournamentTier(a)
        const tb = tournamentTier(b)
        if (ta !== tb) return ta - tb
        // Higher combined RTT scores = more interesting match
        const rttA = ((a.rtt?.p1_score || 0) + (a.rtt?.p2_score || 0))
        const rttB = ((b.rtt?.p1_score || 0) + (b.rtt?.p2_score || 0))
        return rttB - rttA
      })
      setMatches(data)
      setLastFetch(new Date())
      setLoading(false)
      setTick(REFRESH_MS / 1000)
    } catch (e) {
      setError(e.message)
      setLoading(false)
    }
  }, [])

  useEffect(() => {
    load()
    const interval = setInterval(load, REFRESH_MS)
    return () => clearInterval(interval)
  }, [load])

  useEffect(() => {
    const t = setInterval(() => setTick(n => Math.max(0, n - 1)), 1000)
    return () => clearInterval(t)
  }, [])

  if (loading) return (
    <div className="page">
      <div className="loading">Loading live matches…</div>
    </div>
  )

  if (error) return (
    <div className="page">
      <div className="error">Error loading live data: {error}</div>
    </div>
  )

  // Count matches with edge
  const withEdge = matches.filter(m => m.edge && Math.abs(m.edge.edge_pct) >= 2).length

  return (
    <div className="page">

      {/* ── Page header ── */}
      <div className="cc-header">
        <div>
          <h1 className="cc-title" style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
            <span style={{
              display: 'inline-flex', alignItems: 'center', gap: 5,
              background: '#dc2626', color: '#fff',
              borderRadius: 20, padding: '3px 10px',
              fontSize: 12, fontWeight: 800, letterSpacing: '0.08em',
            }}>
              <span style={{
                width: 6, height: 6, borderRadius: '50%', background: '#fff',
                animation: 'livePulse 1.2s ease-in-out infinite', display: 'inline-block',
              }} />
              LIVE
            </span>
            In Play
          </h1>
          <div className="cc-subtitle">
            {matches.length} match{matches.length !== 1 ? 'es' : ''} in progress
            {withEdge > 0 && ` · ${withEdge} with model edge`}
            {' · refreshes every 30s'}
          </div>
        </div>
        <div style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
          {lastFetch && (
            <span style={{ fontSize: 11, color: 'var(--text-3)' }}>
              Updated {lastFetch.toLocaleTimeString('en-GB', { hour: '2-digit', minute: '2-digit', second: '2-digit' })}
            </span>
          )}
          {tick > 0 && (
            <span style={{ fontSize: 11, color: 'var(--text-3)' }}>
              Next refresh in {tick}s
            </span>
          )}
          <button
            onClick={load}
            style={{ fontSize: 15, color: 'var(--text-3)', padding: '4px 6px', borderRadius: 'var(--r-sm)' }}
            title="Refresh now"
          >↻</button>
        </div>
      </div>

      {/* ── Content ── */}
      {matches.length === 0 ? (
        <div className="card">
          <EmptyState />
        </div>
      ) : (
        <div style={{ display: 'grid', gap: 16, gridTemplateColumns: '1fr' }}>
          <style>{`
            @keyframes livePulse {
              0%, 100% { opacity: 1; transform: scale(1); }
              50% { opacity: 0.4; transform: scale(0.8); }
            }
            @media (min-width: 768px) {
              .live-grid { grid-template-columns: repeat(2, 1fr) !important; }
            }
            @media (min-width: 1200px) {
              .live-grid { grid-template-columns: repeat(3, 1fr) !important; }
            }
          `}</style>
          <div className="live-grid" style={{
            display: 'grid', gap: 16,
            gridTemplateColumns: '1fr',
          }}>
            {matches.map((m, i) => (
              <LiveMatchCard key={m.match_id || m.id || i} match={m} />
            ))}
          </div>
        </div>
      )}
    </div>
  )
}
