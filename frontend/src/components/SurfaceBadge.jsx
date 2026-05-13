export default function SurfaceBadge({ surface }) {
  const cls = (surface || '').toLowerCase()
  return (
    <span className={`surface-badge ${cls}`}>{surface || '—'}</span>
  )
}
