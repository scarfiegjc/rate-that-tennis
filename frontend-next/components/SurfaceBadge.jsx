function classFor(surface) {
  const s = (surface || '').toLowerCase()
  if (s.includes('clay'))   return 'clay'
  if (s.includes('grass'))  return 'grass'
  if (s.includes('indoor')) return 'indoor'
  if (s.includes('carpet')) return 'carpet'
  if (s.includes('hard'))   return 'hard'
  return 'unknown'
}

export default function SurfaceBadge({ surface }) {
  return (
    <span className={`surface-badge ${classFor(surface)}`}>{surface || '—'}</span>
  )
}
