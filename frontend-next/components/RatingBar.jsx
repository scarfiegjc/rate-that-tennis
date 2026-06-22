/**
 * RatingBar — single-player horizontal rating bar
 */

function tierColor(value) {
  if (value === null || value === undefined) return 'var(--text-muted)'
  if (value >= 90) return '#3B6D11'
  if (value >= 82) return '#639922'
  if (value >= 72) return '#888780'
  if (value >= 62) return '#EF9F27'
  return '#E24B4A'
}

function tierLabel(value) {
  if (value === null || value === undefined) return null
  if (value >= 90) return 'Elite'
  if (value >= 82) return 'Strong'
  if (value >= 72) return 'Average'
  if (value >= 62) return 'Below avg'
  return 'Poor'
}

export function RatingBar({ label, value, showTier = false, size = 'md' }) {
  const color  = tierColor(value)
  const pct    = value != null ? Math.min(100, Math.max(0, value)) : 0
  const isNull = value === null || value === undefined

  const trackH = size === 'sm' ? 3 : size === 'lg' ? 6 : 4
  const fontSize = size === 'sm' ? 11 : size === 'lg' ? 15 : 13

  return (
    <div className="rating-bar-row" style={{ '--rb-color': color }}>
      <div className="rating-bar-label" style={{ fontSize }}>{label}</div>
      <div className="rating-bar-track" style={{ height: trackH }}>
        <div
          className="rating-bar-fill"
          style={{ width: isNull ? 0 : `${pct}%`, background: color }}
        />
      </div>
      <div className="rating-bar-value" style={{ fontSize, color: isNull ? 'var(--text-muted)' : color }}>
        {isNull ? '—' : Math.round(value)}
        {showTier && !isNull && (
          <span className="rating-bar-tier">{tierLabel(value)}</span>
        )}
      </div>
    </div>
  )
}

export function DualRatingBar({ label, v1, v2 }) {
  const c1 = tierColor(v1)
  const c2 = '#388bfd'
  const pct1 = v1 != null ? Math.min(100, Math.max(0, v1)) : 0
  const pct2 = v2 != null ? Math.min(100, Math.max(0, v2)) : 0

  return (
    <div className="dual-rating-row">
      <div className="dual-rating-val p1" style={{ color: v1 != null ? c1 : 'var(--text-muted)' }}>
        {v1 != null ? Math.round(v1) : '—'}
      </div>
      <div className="dual-rating-track p1-track">
        <div
          className="dual-rating-fill"
          style={{ width: `${pct1}%`, background: c1, marginLeft: 'auto' }}
        />
      </div>
      <div className="dual-rating-label">{label}</div>
      <div className="dual-rating-track p2-track">
        <div
          className="dual-rating-fill"
          style={{ width: `${pct2}%`, background: c2 }}
        />
      </div>
      <div className="dual-rating-val p2" style={{ color: v2 != null ? c2 : 'var(--text-muted)' }}>
        {v2 != null ? Math.round(v2) : '—'}
      </div>
    </div>
  )
}

export function RatingTierBadge({ value }) {
  if (value === null || value === undefined) return null
  return (
    <span className="rating-tier-badge" style={{ '--tier-color': tierColor(value) }}>
      {tierLabel(value)}
    </span>
  )
}

export { tierColor, tierLabel }
export default RatingBar
