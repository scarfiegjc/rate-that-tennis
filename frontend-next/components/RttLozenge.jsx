export default function RttLozenge({ score, hideIfMissing = false }) {
  if (score == null) {
    if (hideIfMissing) return null
    return <span className="rtt-lozenge unknown">—</span>
  }
  const n = Math.round(Number(score))
  let cls = 'poor'
  if (n >= 80)      cls = 'elite'
  else if (n >= 65) cls = 'strong'
  else if (n >= 50) cls = 'average'
  else if (n >= 35) cls = 'below'
  return <span className={`rtt-lozenge ${cls}`} title={`RTT ${n}`}>{n}</span>
}
