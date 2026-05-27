/**
 * LivePage — Command Centre
 *
 * Time-ordered view of all matches. Auto-refreshes every 30 seconds.
 * Sections: Live Now · Up Next · Later Today · Tomorrow
 *
 * Uses the same green/blue split MatchCard as the homepage.
 * Live / starting-now matches use the expanded `large` variant.
 */

import { useState, useEffect, useCallback } from 'react'
import { useNavigate } from 'react-router-dom'
import { api } from '../api.js'
import { useSEO } from '../hooks/useSEO.js'
import courtClay  from '../assets/court-clay.jpg'
import courtHard  from '../assets/court-hard.jpg'
import courtGrass from '../assets/court-grass.jpg'

const REFRESH_MS = 30_000

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
  let cc = up.length === 2 ? up : (IOC_TO_ALPHA2[up] || '')
  if (cc.length !== 2) return ''
  return String.fromCodePoint(...[...cc].map(c => 0x1f1a5 + c.charCodeAt(0)))
}

// ── SEO URL helpers ─────────────────────────────────────────────────────────

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

// ── Live lozenge ─────────────────────────────────────────────────────────────

function LiveLozenge({ small = false }) {
  return (
    <span className={small ? 'live-lozenge live-lozenge--sm' : 'live-lozenge'}>
      <span className="live-lozenge-dot" />
      LIVE
    </span>
  )
}

// ── Surface inference ────────────────────────────────────────────────────────

function inferSurface(name) {
  const n = (name || '').toLowerCase()
  if (/roland.?garros|french open|monte.?carlo|barcelona|madrid open|clay/i.test(n)) return 'clay'
  if (/wimbledon|queen.?s club|halle|eastbourne|nottingham|grass/i.test(n)) return 'grass'
  return null
}

function courtBg(surface, tournament) {
  const s = (surface || '').toLowerCase()
  if (s.includes('clay'))  return courtClay
  if (s.includes('grass')) return courtGrass
  if (s.includes('hard'))  return courtHard
  const inf = inferSurface(tournament)
  if (inf === 'clay')  return courtClay
  if (inf === 'grass') return courtGrass
  if (inf === 'hard')  return courtHard
  return null
}

// ── Match card — same green/blue split as MatchList ──────────────────────────

function MatchCard({ match, large = false }) {
  const navigate = useNavigate()
  const p1   = match.first_player  || {}
  const p2   = match.second_player || {}
  const pred = match.prediction    || {}

  const isLive     = /in play|live|set \d|game/i.test(match.event_status || '')
  const isFinished = /finished/i.test(match.event_status || '')

  const p1prob = pred.prob_first_player  != null ? Math.round(pred.prob_first_player  * 100) : null
  const p2prob = pred.prob_second_player != null ? Math.round(pred.prob_second_player * 100) : null

  const winner1 = isFinished && match.winner === 'First Player'
  const winner2 = isFinished && match.winner === 'Second Player'

  let predCorrect = null
  if (isFinished && p1prob != null) {
    const predictedSide = p1prob >= 50 ? 1 : 2
    const actualWinner  = winner1 ? 1 : winner2 ? 2 : null
    if (actualWinner != null) predCorrect = predictedSide === actualWinner
  }

  const edgeVal = Math.max(pred.edge_first || 0, pred.edge_second || 0)
  const hasEdge = edgeVal > 0.02

  const timeStr = isFinished ? 'FT' : match.event_time?.slice(0, 5) || null

  const rawTourn = (match.tournament || '').trim()
  const tournDisplay = rawTourn && !['unknown tournament', 'unknown'].includes(rawTourn.toLowerCase())
    ? rawTourn
    : (match.surface && match.surface !== 'Unknown' ? match.surface : null)

  const p1w = p1prob ?? 50
  const p2w = p2prob ?? 50

  return (
    <button className={`mc-card${large ? ' mc-card--live' : ''}`} onClick={() => navigate(matchUrl(match))}>

      {/* Header strip */}
      <div className="mc-card-hdr">
        {isLive ? (
          large ? (
            <>
              <div style={{ display: 'flex', alignItems: 'center', gap: 6, width: '100%' }}>
                <LiveLozenge small />
                {tournDisplay && <span className="mc-hdr-tourn" style={{ flex: 1 }}>{tournDisplay}</span>}
                {hasEdge && <span className="mc-card-edge" style={{ flexShrink: 0 }}>+{Math.round(edgeVal * 100)}% edge</span>}
              </div>
              {(match.set_scores || match.game_result) && (
                <div style={{ display: 'flex', alignItems: 'center', gap: 4 }}>
                  {match.set_scores && match.set_scores.split(' ').map((set, i) => (
                    <span key={i} className="mc-live-set mc-live-set--lg">{set}</span>
                  ))}
                  {match.game_result && <span className="mc-live-game mc-live-game--lg">{match.game_result}</span>}
                </div>
              )}
            </>
          ) : (
            <>
              <LiveLozenge small />
              {match.set_scores && match.set_scores.split(' ').map((set, i) => (
                <span key={i} className="mc-live-set">{set}</span>
              ))}
              {match.game_result && <span className="mc-live-game">{match.game_result}</span>}
            </>
          )
        ) : (
          <>
            {timeStr && <span className="mc-hdr-time">{timeStr}</span>}
            {tournDisplay && <span className="mc-hdr-tourn">{tournDisplay}</span>}
          </>
        )}
        {hasEdge && !(isLive && large) && (
          <span className="mc-card-edge" style={{ marginLeft: 'auto', flexShrink: 0 }}>
            +{Math.round(edgeVal * 100)}% edge
          </span>
        )}
        {!hasEdge && isFinished && predCorrect === true  && (
          <span style={{ marginLeft: 'auto', color: '#4ade80', fontSize: 13, fontWeight: 700 }}>✓</span>
        )}
        {!hasEdge && isFinished && predCorrect === false && (
          <span style={{ marginLeft: 'auto', color: '#f87171', fontSize: 13, fontWeight: 700 }}>✗</span>
        )}
      </div>

      {/* Two-colour split body */}
      <div className="mc-card-body">
        <div className="mc-side mc-side-green" style={{ width: `${p1w}%`, opacity: winner2 ? 0.45 : 1 }} />
        <div className="mc-side mc-side-blue"  style={{ width: `${p2w}%`, opacity: winner1 ? 0.45 : 1 }} />
        <div className="mc-vs">VS</div>

        <div className="mc-player-info mc-player-left" style={{ opacity: winner2 ? 0.45 : 1 }}>
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

        <div className="mc-player-info mc-player-right" style={{ opacity: winner1 ? 0.45 : 1 }}>
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

    </button>
  )
}

// ── Classify each match into a time bucket ───────────────────────────────────

function classifyMatch(match) {
  const status = (match.event_status || '').toLowerCase()
  if (/in play|live|set \d|game/i.test(match.event_status || '')) return 'live'
  if (status === 'finished' || status === 'complete' || status === 'completed') return 'finished'

  const now = new Date()
  const today = now.toDateString()
  const matchDate = match.event_date ? new Date(match.event_date + 'T00:00:00') : null
  const isToday    = matchDate ? matchDate.toDateString() === today : false
  const isTomorrow = matchDate
    ? matchDate.toDateString() === new Date(now.getTime() + 86400000).toDateString()
    : false

  if (!isToday && isTomorrow) return 'tomorrow'
  if (!isToday && !isTomorrow) return 'other'

  if (match.event_time) {
    try {
      const [h, m] = match.event_time.split(':').map(Number)
      const matchTime = new Date(now)
      matchTime.setHours(h, m, 0, 0)
      const diffMin = (matchTime - now) / 60000
      if (diffMin <= 0)  return 'now'
      if (diffMin <= 90) return 'next'
      return 'later'
    } catch {
      return 'later'
    }
  }
  return 'later'
}

function bucketOrder(bucket) {
  return { live: 0, now: 1, next: 2, later: 3, finished: 4, tomorrow: 5, other: 6 }[bucket] ?? 7
}

function bucketLabel(bucket) {
  return {
    live:     '🔴 Live Now',
    now:      '⏱ Starting Now',
    next:     'Up Next',
    later:    'Later Today',
    finished: 'Finished',
    tomorrow: 'Tomorrow',
    other:    'Upcoming',
  }[bucket] || bucket
}

// ── Bucket section ────────────────────────────────────────────────────────────

function BucketSection({ bucket, matches }) {
  const isHot = bucket === 'live' || bucket === 'now'
  return (
    <div style={{ marginBottom: 28 }}>
      {/* Section header */}
      <div style={{
        display: 'flex', alignItems: 'center', gap: 8,
        padding: '4px 2px 10px',
        borderBottom: `1px solid ${isHot ? 'rgba(239,68,68,0.35)' : 'var(--border-faint)'}`,
        marginBottom: 10,
      }}>
        <span style={{
          fontSize: 13, fontWeight: 700,
          color: isHot ? '#ef4444' : 'var(--text-2)',
        }}>
          {bucketLabel(bucket)}
        </span>
        <span style={{ fontSize: 11, color: 'var(--text-3)' }}>
          {matches.length} match{matches.length !== 1 ? 'es' : ''}
        </span>
      </div>

      {/* Cards — 2-col for live/now, 3-col for everything else */}
      <div className={isHot ? 'mc-card-grid mc-card-grid--live' : 'mc-card-grid'}>
        {matches.map(m => (
          <MatchCard key={m.match_id} match={m} large={isHot} />
        ))}
      </div>
    </div>
  )
}

// ── Surface filter pills ──────────────────────────────────────────────────────

const SURFACES = ['all', 'Hard', 'Clay', 'Grass']

// ── Main LivePage ─────────────────────────────────────────────────────────────

export default function LivePage() {
  const [matches,     setMatches]     = useState([])
  const [loading,     setLoading]     = useState(true)
  const [error,       setError]       = useState(null)
  const [surface,     setSurface]     = useState('all')
  const [lastRefresh, setLastRefresh] = useState(null)

  useSEO({
    title: 'Live Tennis — RateThatTennis Command Centre',
    description: 'Live tennis scores, upcoming matches and ML predictions. Auto-refreshing every 30 seconds.',
  })

  const load = useCallback(() => {
    api.matchesToday()
      .then(data => {
        setMatches(Array.isArray(data) ? data : data.matches || [])
        setLastRefresh(new Date())
        setLoading(false)
      })
      .catch(e => { setError(e.message); setLoading(false) })
  }, [])

  useEffect(() => {
    load()
    const interval = setInterval(load, REFRESH_MS)
    return () => clearInterval(interval)
  }, [load])

  const filtered = surface === 'all'
    ? matches.filter(m => !m.is_doubles)
    : matches.filter(m => !m.is_doubles && (m.surface || '').toLowerCase() === surface.toLowerCase())

  // Group into buckets
  const buckets = {}
  for (const m of filtered) {
    const b = classifyMatch(m)
    if (!buckets[b]) buckets[b] = []
    buckets[b].push(m)
  }

  // Sort within each bucket by time
  for (const b of Object.keys(buckets)) {
    buckets[b].sort((a, c) => (a.event_time || '99:99').localeCompare(c.event_time || '99:99'))
  }

  const orderedBuckets = Object.keys(buckets).sort((a, b) => bucketOrder(a) - bucketOrder(b))
  const liveCount = (buckets.live?.length || 0) + (buckets.now?.length || 0)

  if (loading) return <div className="page"><div className="loading">Loading matches…</div></div>
  if (error)   return <div className="page"><div className="error">Error: {error}</div></div>

  return (
    <div className="page">
      {/* Header */}
      <div className="mc-filter-panel">
        <div className="cc-header">
          <div>
            <h1 className="cc-title">Command Centre</h1>
            <div className="cc-subtitle">Live scores · upcoming matches · auto-refresh every 30s</div>
          </div>
          <div style={{ display: 'flex', flexDirection: 'column', alignItems: 'flex-end', gap: 8 }}>
            <div className="cc-meta-badges">
              {liveCount > 0 && (
                <span className="count-badge live">
                  <span className="live-dot" />{liveCount} live
                </span>
              )}
            </div>
            <div style={{ display: 'flex', gap: 4 }}>
              {SURFACES.map(s => (
                <button
                  key={s}
                  className={`surface-pill ${surface === s ? 'active' : ''}`}
                  onClick={() => setSurface(s)}
                >
                  {s === 'all' ? 'All' : s}
                </button>
              ))}
            </div>
            <button
              onClick={load}
              style={{ fontSize: 13, color: 'rgba(255,255,255,0.5)', padding: '4px 6px', borderRadius: 'var(--r-sm)' }}
              title="Refresh"
            >↻</button>
            {lastRefresh && (
              <div style={{ fontSize: 11, color: 'rgba(255,255,255,0.4)' }}>
                Updated {lastRefresh.toLocaleTimeString('en-GB', { hour: '2-digit', minute: '2-digit' })}
              </div>
            )}
          </div>
        </div>
      </div>

      {orderedBuckets.length === 0 ? (
        <div className="loading" style={{ marginTop: 40 }}>No matches found.</div>
      ) : (
        orderedBuckets.map(b => (
          <BucketSection key={b} bucket={b} matches={buckets[b]} />
        ))
      )}
    </div>
  )
}
