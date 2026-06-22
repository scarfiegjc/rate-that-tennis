'use client'
import { useEffect, useMemo, useState } from 'react'
import Link from 'next/link'
import { api } from '../../lib/api'
import RttLozenge from '../RttLozenge'

function playerUrl(p) {
  if (!p) return '/'
  const id = p.id ?? p.player_id
  if (id == null) return '/'
  const name = (p.full_name || p.name || '').toLowerCase().replace(/[^a-z0-9]+/g, '-').replace(/^-+|-+$/g, '')
  return name ? `/player/${id}/${name}` : `/player/${id}`
}

// ─────────────────────────────────────────────────────────────────────────────
// Constants
// ─────────────────────────────────────────────────────────────────────────────

const SORT_OPTIONS = [
  { id: 'rtt',      label: 'RTT' },
  { id: 'form',     label: 'Form' },
  { id: 'momentum', label: 'Momentum' },
]

const SURFACE_OPTIONS = [
  { id: 'all',    label: 'All',     sortKey: 'rtt' },
  { id: 'clay',   label: 'Clay',    sortKey: 'clay' },
  { id: 'hard',   label: 'Hard',    sortKey: 'hard' },
  { id: 'grass',  label: 'Grass',   sortKey: 'grass' },
  { id: 'indoor', label: 'Indoor',  sortKey: 'indoor' },
]


function MomentumArrow({ momentum }) {
  if (!momentum || momentum === 'stable') return null
  const isUp = momentum === 'rising'
  return (
    <span title={momentum} style={{
      fontSize: 12, fontWeight: 700,
      color: isUp ? 'var(--green)' : 'var(--red)',
    }}>
      {isUp ? '↑' : '↓'}
    </span>
  )
}


function HandMini({ hand }) {
  if (!hand || hand === 'Unknown') {
    return <span style={{
      fontSize: 9, color: 'var(--text-3)',
      width: 14, textAlign: 'center', fontWeight: 600,
    }}>?</span>
  }
  const isLeft = hand === 'Left'
  return (
    <span title={hand} style={{
      display: 'inline-flex', alignItems: 'center', justifyContent: 'center',
      background: isLeft ? '#e0f2fe' : '#f4f4f5',
      color:      isLeft ? '#0369a1' : '#52525b',
      borderRadius: 12, padding: '0 5px',
      fontSize: 10, fontWeight: 700, lineHeight: 1.4,
      minWidth: 14, textAlign: 'center',
    }}>
      {isLeft ? 'L' : 'R'}
    </span>
  )
}


function tierFor(score) {
  if (score == null) return null
  if (score >= 90) return { label: 'Elite',   bg: '#dcfce7', color: '#166534' }
  if (score >= 80) return { label: 'Strong',  bg: '#d9f0bb', color: '#3a5c14' }
  if (score >= 70) return { label: 'Average', bg: '#fef3c7', color: '#92400e' }
  if (score >= 55) return { label: 'Below',   bg: '#fed7aa', color: '#9a3412' }
  return                { label: 'Poor',    bg: '#fecaca', color: '#991b1b' }
}


function PlayerRow({ player, surfaceKey, rank }) {
  // Pick which RTT to show based on surface filter
  const score = surfaceKey === 'rtt'
    ? player.rtt_score
    : player[`${surfaceKey}_rating`] ?? player.rtt_score
  const tier = tierFor(score)
  const delta = player.rtt_delta_30d || 0
  const showDelta = Math.abs(delta) >= 0.5

  return (
    <Link href={playerUrl(player)} style={{
      display: 'grid',
      gridTemplateColumns: '28px 36px 1fr auto',
      alignItems: 'center',
      gap: 10,
      padding: '10px 12px',
      borderBottom: '1px solid var(--border-faint)',
      background: 'var(--bg-card)',
      transition: 'background 0.1s',
    }}
    onMouseEnter={e => e.currentTarget.style.background = 'var(--bg-raised)'}
    onMouseLeave={e => e.currentTarget.style.background = 'var(--bg-card)'}
    >
      {/* Rank */}
      <div style={{
        fontSize: 12, color: 'var(--text-3)',
        fontVariantNumeric: 'tabular-nums',
        textAlign: 'right', fontWeight: 600,
      }}>
        {rank}
      </div>

      {/* RTT lozenge */}
      <RttLozenge score={score} hideIfMissing />

      {/* Name + meta */}
      <div style={{ minWidth: 0 }}>
        <div style={{
          display: 'flex', alignItems: 'center', gap: 6,
          fontSize: 13, fontWeight: 600,
        }}>
          {player.playing_today && (
            <span title="Playing today" style={{
              width: 6, height: 6, borderRadius: '50%',
              background: 'var(--green)', flexShrink: 0,
            }} />
          )}
          <span style={{
            overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap',
          }}>
            {player.name}
          </span>
          <MomentumArrow momentum={player.momentum} />
        </div>
        <div style={{
          display: 'flex', alignItems: 'center', gap: 8,
          marginTop: 2, fontSize: 11, color: 'var(--text-3)',
        }}>
          {player.country_code && <span>{player.country_code}</span>}
          <HandMini hand={player.hand} />
          {tier && (
            <span style={{
              background: tier.bg, color: tier.color,
              padding: '0 6px', borderRadius: 10,
              fontSize: 9, fontWeight: 700, letterSpacing: 0.4,
              textTransform: 'uppercase',
            }}>
              {tier.label}
            </span>
          )}
          {player.form_score != null && (
            <span title="Form score">F{Math.round(player.form_score)}</span>
          )}
          {showDelta && (
            <span style={{
              color: delta > 0 ? 'var(--green)' : 'var(--red)',
              fontWeight: 600,
            }}>
              {delta > 0 ? '+' : ''}{delta.toFixed(1)}
            </span>
          )}
        </div>
      </div>

      {/* Score on the right (so it lines up vertically) */}
      <div style={{ minWidth: 32, textAlign: 'right' }}>
        {/* score is already in the lozenge — leave column for spacing */}
      </div>
    </Link>
  )
}


export default function PlayerDatabaseClient() {
const [sort, setSort]         = useState('rtt')      // user choice: rtt | form | momentum
  const [surface, setSurface]   = useState('all')      // all | clay | hard | grass | indoor
  const [search, setSearch]     = useState('')
  const [country, setCountry]   = useState('')
  const [activeOnly, setActiveOnly] = useState(true)
  const [data, setData]         = useState(null)
  const [error, setError]       = useState(null)
  const [loading, setLoading]   = useState(false)

  // Server sort key — surface filter overrides user choice if not 'all',
  // otherwise the user's sort dropdown is used.
  const apiSort = surface === 'all' ? sort
                : surface === 'clay'   ? 'clay'
                : surface === 'hard'   ? 'hard'
                : surface === 'grass'  ? 'grass'
                : surface === 'indoor' ? 'indoor'
                : 'rtt'

  // Debounced search (300ms) so we don't spam the API on every keystroke
  const [debouncedSearch, setDebouncedSearch] = useState('')
  useEffect(() => {
    const t = setTimeout(() => setDebouncedSearch(search), 300)
    return () => clearTimeout(t)
  }, [search])

  useEffect(() => {
    let on = true
    setLoading(true)
    api.playersDatabase({
      sort: apiSort,
      country: country || undefined,
      search: debouncedSearch || undefined,
      activeOnly,
      limit: 500,
    })
       .then(d => { if (on) { setData(d); setError(null); setLoading(false) } })
       .catch(e => { if (on) { setError(e.message); setLoading(false) } })
    return () => { on = false }
  }, [apiSort, country, debouncedSearch, activeOnly])

  // Surface key for the lozenge value & "what to show"
  const surfaceKey = surface === 'all' ? 'rtt' : surface

  const { men, women } = useMemo(() => {
    const list = data?.players || []
    return {
      men:   list.filter(p => p.gender === 'M'),
      women: list.filter(p => p.gender === 'W'),
    }
  }, [data])

  // Country dropdown options derived from the loaded set
  const countries = useMemo(() => {
    const set = new Set()
    for (const p of data?.players || []) {
      if (p.country_code) set.add(p.country_code)
    }
    return Array.from(set).sort()
  }, [data])

  return (
    <div className="page">
      <div className="cc-header">
        <div>
          <h1 className="cc-title">Player database</h1>
          <div className="cc-subtitle">
            Every active player ranked by RTT, form or momentum.
            {data?.summary && ` ${data.summary.total} players · ${data.summary.playing_today} playing today`}
          </div>
        </div>
        <div className="cc-meta-badges">
          {data?.summary && (
            <>
              <span className="count-badge edge">{data.summary.men} men</span>
              <span className="count-badge edge">{data.summary.women} women</span>
              {data.summary.playing_today > 0 && (
                <span className="count-badge live"><span className="live-dot" />{data.summary.playing_today} today</span>
              )}
            </>
          )}
        </div>
      </div>

      {/* Filters */}
      <div style={{
        display: 'flex', flexWrap: 'wrap', gap: 12,
        alignItems: 'center', marginBottom: 16,
      }}>
        {/* Search */}
        <input
          type="search"
          value={search}
          onChange={e => setSearch(e.target.value)}
          placeholder="Search player…"
          style={{
            padding: '6px 10px', borderRadius: 6,
            border: '1px solid var(--border)', fontSize: 13,
            background: 'var(--bg-card)', color: 'var(--text)',
            minWidth: 180, fontFamily: 'inherit',
          }}
        />

        {/* Country */}
        <select
          value={country}
          onChange={e => setCountry(e.target.value)}
          style={{
            padding: '6px 10px', borderRadius: 6,
            border: '1px solid var(--border)', fontSize: 13,
            background: 'var(--bg-card)', color: 'var(--text)',
            fontFamily: 'inherit',
          }}
        >
          <option value="">All countries</option>
          {countries.map(c => <option key={c} value={c}>{c}</option>)}
        </select>

        {/* Sort */}
        <div style={{ display: 'flex', gap: 4 }}>
          {SORT_OPTIONS.map(s => (
            <button
              key={s.id}
              onClick={() => { setSort(s.id); setSurface('all') }}
              className={`surface-pill ${surface === 'all' && sort === s.id ? 'active' : ''}`}
            >
              {s.label}
            </button>
          ))}
        </div>

        {/* Surface filter */}
        <div style={{ display: 'flex', gap: 4 }}>
          {SURFACE_OPTIONS.map(s => (
            <button
              key={s.id}
              onClick={() => setSurface(s.id)}
              className={`surface-pill ${surface === s.id ? 'active' : ''}`}
            >
              {s.label}
            </button>
          ))}
        </div>

        {/* Active only toggle */}
        <label style={{
          display: 'inline-flex', alignItems: 'center', gap: 6,
          fontSize: 12, color: 'var(--text-2)', cursor: 'pointer',
          marginLeft: 'auto',
        }}>
          <input
            type="checkbox"
            checked={activeOnly}
            onChange={e => setActiveOnly(e.target.checked)}
            style={{ cursor: 'pointer' }}
          />
          Active only (last 6 months)
        </label>
      </div>

      {error && <div className="error">{error}</div>}
      {loading && !data && <div className="loading">Loading players…</div>}

      {/* 2-column gender split */}
      {data && (
        <div style={{
          display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 16,
        }}>
          <div>
            <div style={{
              fontSize: 11, fontWeight: 700, textTransform: 'uppercase',
              letterSpacing: 0.6, color: 'var(--text-3)', marginBottom: 8,
              padding: '0 4px',
            }}>
              Men ({men.length})
            </div>
            <div className="card" style={{ overflow: 'hidden' }}>
              {men.map((p, i) => (
                <PlayerRow key={p.id} player={p} surfaceKey={surfaceKey} rank={i + 1} />
              ))}
              {men.length === 0 && (
                <div style={{ padding: 24, textAlign: 'center', color: 'var(--text-3)', fontSize: 13 }}>
                  No men match these filters.
                </div>
              )}
            </div>
          </div>
          <div>
            <div style={{
              fontSize: 11, fontWeight: 700, textTransform: 'uppercase',
              letterSpacing: 0.6, color: 'var(--text-3)', marginBottom: 8,
              padding: '0 4px',
            }}>
              Women ({women.length})
            </div>
            <div className="card" style={{ overflow: 'hidden' }}>
              {women.map((p, i) => (
                <PlayerRow key={p.id} player={p} surfaceKey={surfaceKey} rank={i + 1} />
              ))}
              {women.length === 0 && (
                <div style={{ padding: 24, textAlign: 'center', color: 'var(--text-3)', fontSize: 13 }}>
                  No women match these filters.
                </div>
              )}
            </div>
          </div>
        </div>
      )}
    </div>
  )
}
