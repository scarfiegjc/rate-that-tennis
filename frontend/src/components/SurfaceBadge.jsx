// Normalize multi-word surface values to a single CSS class. "Indoor Hard"
// was producing className="surface-badge indoor hard" — two classes, neither
// styled. We collapse to a known set: clay / hard / grass / indoor / carpet.
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
