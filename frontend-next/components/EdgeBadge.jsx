export default function EdgeBadge({ edge, playerName }) {
  if (edge === null || edge === undefined) {
    return <span className="edge-badge neutral">No odds</span>
  }
  const pct = Math.round(edge * 100)
  if (Math.abs(pct) < 2) {
    return <span className="edge-badge neutral">Market aligned</span>
  }
  if (pct >= 5) {
    return <span className="edge-badge high">RTT Edge: {pct}%</span>
  }
  if (pct > 2) {
    return <span className="edge-badge medium">RTT Edge: {pct}%</span>
  }
  return <span className="edge-badge review">Review ({pct}%)</span>
}
