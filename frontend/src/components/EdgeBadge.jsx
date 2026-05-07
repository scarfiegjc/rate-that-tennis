export default function EdgeBadge({ edge, playerName }) {
  if (edge === null || edge === undefined) {
    return <span className="edge-badge neutral">No odds</span>
  }
  const pct = Math.round(edge * 100)
  if (Math.abs(pct) < 2) {
    return <span className="edge-badge neutral">Market aligned</span>
  }
  // Use just the last name to keep the badge compact and prevent overflow on
  // the match row meta column.
  const lastName = (playerName || '').trim().split(/\s+/).pop() || playerName || ''
  if (pct >= 5) {
    return <span className="edge-badge high" title={`+${pct}% edge on ${playerName}`}>+{pct}% {lastName}</span>
  }
  if (pct > 2) {
    return <span className="edge-badge medium" title={`+${pct}% edge on ${playerName}`}>+{pct}% {lastName}</span>
  }
  return <span className="edge-badge review">Review ({pct}%)</span>
}
