export default function ProbBar({ p1, p2, name1, name2 }) {
  const pct1 = Math.round((p1 || 0.5) * 100)
  const pct2 = 100 - pct1
  return (
    <div className="prob-bar-wrapper">
      <div className="prob-bar-labels">
        <span>{name1} {pct1}%</span>
        <span>{pct2}% {name2}</span>
      </div>
      <div className="prob-bar-track">
        <div className="prob-bar-p1" style={{ width: `${pct1}%` }} />
        <div className="prob-bar-p2" style={{ width: `${pct2}%` }} />
      </div>
    </div>
  )
}
