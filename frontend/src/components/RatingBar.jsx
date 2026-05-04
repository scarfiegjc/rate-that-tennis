/**
 * RatingBar — single-player horizontal rating bar
 *
 * Inspired by ratethat.dog line-style rating display.
 * Shows a label, filled bar coloured by tier, and numeric score.
 *
 * Usage:
 *   <RatingBar label="Serve" value={84} />
 *   <RatingBar label="Clay" value={null} />          // shows — for missing data
 */

function tierColor(value) {
  if (value === null || value === undefined) return 'var(--text-muted)'
  if (value >= 90) return '#3B6D11'   // Elite — deep green
  if (value >= 82) return '#639922'   // Strong — green
  if (value >= 72) return '#888780'   // Average — gray
  if (value >= 62) return '#EF9F27'   // Below average — amber
  return '#E24B4A'                     // Poor — red
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

/**
 * DualRatingBar — side-by-side comparison bar for two players
 *
 * P1 bar fills left→right in green; P2 bar fills right→left in blue.
 * The label sits in the centre.
 *
 * Usage:
 *   <DualRatingBar label="Serve" v1={84} v2={76} />
 */
export function DualRatingBar({ label, v1, v2 }) {
  const c1 = tierColor(v1)
  const c2 = '#388bfd'   // always blue for P2 for contrast
  const pct1 = v1 != null ? Math.min(100, Math.max(0, v1)) : 0
  const pct2 = v2 != null ? Math.min(100, Math.max(0, v2)) : 0

  return (
    <div className="dual-rating-row">
      {/* P1 score */}
      <div className="dual-rating-val p1" style={{ color: v1 != null ? c1 : 'var(--text-muted)' }}>
        {v1 != null ? Math.round(v1) : '—'}
      </div>

      {/* P1 bar (right-aligned) */}
      <div className="dual-rating-track p1-track">
        <div
          className="dual-rating-fill"
          style={{ width: `${pct1}%`, background: c1, marginLeft: 'auto' }}
        />
      </div>

      {/* Label */}
      <div className="dual-rating-label">{label}</div>

      {/* P2 bar (left-aligned) */}
      <div className="dual-rating-track p2-track">
        <div
          className="dual-rating-fill"
          style={{ width: `${pct2}%`, background: c2 }}
        />
      </div>

      {/* P2 score */}
      <div className="dual-rating-val p2" style={{ color: v2 != null ? c2 : 'var(--text-muted)' }}>
        {v2 != null ? Math.round(v2) : '—'}
      </div>
    </div>
  )
}

/**
 * RatingTierBadge — compact coloured label showing tier name
 */
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
