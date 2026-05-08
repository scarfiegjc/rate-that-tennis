export default function EdgeBadge({ edge, playerName }) {
  if (edge === null || edge === undefined) {
    return <span className="edge-badge neutral">No odds</span>
  }
  const pct = Math.round(edge * 100)
  if (Math.abs(pct) < 2) {
    return <span className="edge-badge neutral">Market aligned</span>
  }
  if (pct >= 5) {
    return <span className="edge-badge high">+{pct}% on {playerName}</span>
  }
  if (pct > 2) {
    return <span className="edge-badge medium">+{pct}% on {playerName}</span>
  }
  return <span className="edge-badge review">Review ({pct}%)</span>
}
