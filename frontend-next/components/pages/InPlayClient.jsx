'use client'
/**
 * InPlayPage — only matches currently in play.
 *
 * Auto-refreshes every 20 seconds.
 * Flat 3-col grid — no tournament groupings.
 * Score-first header with big set chips, tournament at the bottom with court bg.
 */

import { useState, useEffect, useCallback } from 'react'
import { useRouter } from 'next/navigation'
import { api } from '../../lib/api'
const courtClay = '/court-clay.jpg'
const courtHard = '/court-hard.jpg'
const courtGrass = '/court-grass.jpg'

const REFRESH_MS = 20_000

// ── Country flag emoji ─────────────────────────────────────────────────────────

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
  const date       = (match.event_date || '').slice(0, 10)
  const tournament = toSlug(match.tournament || '')
  const p1         = toSlug(match.first_player?.name  || 'player')
  const p2         = toSlug(match.second_player?.name || 'player')
  const slug       = [date, tournament, `${p1}-vs-${p2}`].filter(Boolean).join('-')
  return `/match/${match.match_id}/${slug}`
}

// ── Court background helper ───────────────────────────────────────────────────

function inferSurfaceFromName(name) {
  const n = (name || '').toLowerCase()
  if (/roland.?garros|french open|monte.?carlo|barcelona|madrid|clay/i.test(n)) return 'clay'
  if (/wimbledon|queen.?s club|halle|eastbourne|nottingham|grass/i.test(n)) return 'grass'
  return null
}

function courtBgStyle(surface, tournament) {
  const s = (surface || '').toLowerCase()
  let img = null
  if (s.includes('clay'))        img = courtClay
  else if (s.includes('grass'))  img = courtGrass
  else if (s.includes('hard'))   img = courtHard
  else {
    const inf = inferSurfaceFromName(tournament)
    if (inf === 'clay')       img = courtClay
    else if (inf === 'grass') img = courtGrass
    else                      img = courtHard   // default to hard
  }
  return img
    ? {
        backgroundImage: `linear-gradient(rgba(0,0,0,0.6),rgba(0,0,0,0.6)),url(${img})`,
        backgroundSize: 'cover',
        backgroundPosition: 'center',
      }
    : { background: 'rgba(0,0,0,0.5)' }
}

// ── Status check ─────────────────────────────────────────────────────────────

function isLiveStatus(status) {
  return /in play|live|set \d|game/i.test(status || '')
}

// ── Match card ────────────────────────────────────────────────────────────────

function MatchCard({ match }) {
  const router = useRouter()
  const p1   = match.first_player  || {}
  const p2   = match.second_player || {}
  const pred = match.prediction    || {}

  const p1prob = pred.prob_first_player  != null ? Math.round(pred.prob_first_player  * 100) : null
  const p2prob = pred.prob_second_player != null ? Math.round(pred.prob_second_player * 100) : null

  const edgeVal = Math.max(pred.edge_first || 0, pred.edge_second || 0)
  const hasEdge = edgeVal > 0.02

  const p1w = p1prob ?? 50
  const p2w = p2prob ?? 50

  const rawTourn = (match.tournament || '').trim()
  const tournDisplay = rawTourn && !['unknown tournament', 'unknown'].includes(rawTourn.toLowerCase())
    ? rawTourn : null

  const footBg = courtBgStyle(match.surface || '', match.tournament || '')

  return (
    <button className="mc-card" onClick={() => router.push(matchUrl(match))}>

      {/* Score header — dark bg, big score chips */}
      <div className="mc-card-hdr" style={{ height: 38, gap: 5 }}>
        <span className="live-lozenge live-lozenge--sm">
          <span className="live-lozenge-dot" />
          LIVE
        </span>
        {match.set_scores
          ? match.set_scores.split(' ').map((set, i) => (
              <span key={i} className="mc-live-set--lg">{set}</span>
            ))
          : null
        }
        {match.game_result && (
          <span className="mc-live-game--lg">{match.game_result}</span>
        )}
        {hasEdge && (
          <span className="mc-card-edge" style={{ marginLeft: 'auto', flexShrink: 0 }}>
            +{Math.round(edgeVal * 100)}% edge
          </span>
        )}
      </div>

      {/* Two-colour split body */}
      <div className="mc-card-body">
        <div className="mc-side mc-side-green" style={{ width: `${p1w}%` }} />
        <div className="mc-side mc-side-blue"  style={{ width: `${p2w}%` }} />
        <div className="mc-vs">VS</div>

        <div className="mc-player-info mc-player-left">
          <div className="mc-side-top">
            {p1.photo_url
              ? <img src={p1.photo_url} className="mc-side-photo" alt="" />
              : <span className="mc-side-flag">{flagEmoji(p1.country_code)}</span>
            }
          </div>
          <div className="mc-side-name-row">
            <span className="mc-side-name">{p1.name || '—'}</span>
            {p1.rtt_score != null && <span className="mc-side-rtt">{Math.round(p1.rtt_score)}</span>}
          </div>
          {p1prob != null && <div className="mc-side-prob">{p1prob}%</div>}
        </div>

        <div className="mc-player-info mc-player-right">
          <div className="mc-side-top" style={{ flexDirection: 'row-reverse' }}>
            {p2.photo_url
              ? <img src={p2.photo_url} className="mc-side-photo" alt="" />
              : <span className="mc-side-flag">{flagEmoji(p2.country_code)}</span>
            }
          </div>
          <div className="mc-side-name-row right">
            <span className="mc-side-name">{p2.name || '—'}</span>
            {p2.rtt_score != null && <span className="mc-side-rtt">{Math.round(p2.rtt_score)}</span>}
          </div>
          {p2prob != null && <div className="mc-side-prob" style={{ textAlign: 'right' }}>{p2prob}%</div>}
        </div>
      </div>

      {/* Tournament footer — court photo background */}
      {tournDisplay && (
        <div className="mc-card-foot" style={footBg}>
          {tournDisplay}
        </div>
      )}

    </button>
  )
}

// ── Main ──────────────────────────────────────────────────────────────────────

export default function InPlayClient() {
const [matches,   setMatches]   = useState([])
  const [loading,   setLoading]   = useState(true)
  const [error,     setError]     = useState(null)
  const [lastFetch, setLastFetch] = useState(null)

  const load = useCallback(() => {
    api.matchesToday()
      .then(data => {
        const all  = Array.isArray(data) ? data : data.matches || []
        const live = all.filter(m => !m.is_doubles && isLiveStatus(m.event_status))
        setMatches(live)
        setLastFetch(new Date())
        setLoading(false)
      })
      .catch(e => { setError(e.message); setLoading(false) })
  }, [])

  useEffect(() => {
    load()
    const t = setInterval(load, REFRESH_MS)
    return () => clearInterval(t)
  }, [load])

  if (loading) return <div className="page"><div className="loading">Loading live matches…</div></div>
  if (error)   return <div className="page"><div className="error">{error}</div></div>

  return (
    <div className="page">
      <div className="cc-header">
        <div>
          <h1 className="cc-title">In play</h1>
          <div className="cc-subtitle">Matches happening right now · refreshes every 20s</div>
        </div>
        <div style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
          <span className="count-badge live">
            <span className="live-dot" />{matches.length} live
          </span>
          {lastFetch && (
            <span style={{ fontSize: 11, color: 'var(--text-3)' }}>
              {lastFetch.toLocaleTimeString('en-GB', { hour: '2-digit', minute: '2-digit', second: '2-digit' })}
            </span>
          )}
          <button
            onClick={load}
            style={{ fontSize: 13, color: 'rgba(255,255,255,0.5)', padding: '4px 6px', borderRadius: 'var(--r-sm)' }}
            title="Refresh"
          >↻</button>
        </div>
      </div>

      {matches.length === 0 ? (
        <div className="card" style={{ padding: 40, textAlign: 'center' }}>
          <div style={{ fontSize: 16, fontWeight: 600, marginBottom: 4 }}>Nothing in play right now</div>
          <div style={{ fontSize: 13, color: 'var(--text-3)' }}>
            Come back when matches are underway. Page refreshes automatically.
          </div>
        </div>
      ) : (
        <div className="mc-card-grid">
          {matches.map(m => <MatchCard key={m.match_id} match={m} />)}
        </div>
      )}
    </div>
  )
}
