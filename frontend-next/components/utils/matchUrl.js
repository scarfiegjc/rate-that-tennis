function toSlug(str) {
  return (str || '')
    .toLowerCase()
    .normalize('NFD').replace(/[̀-ͯ]/g, '')   // strip diacritics
    .replace(/[^a-z0-9]+/g, '-')
    .replace(/^-+|-+$/g, '')
}

export function matchUrl(match) {
  const date       = (match.event_date || '').slice(0, 10)
  const tournament = toSlug(match.tournament || '')
  const p1         = toSlug(match.first_player?.name  || 'player')
  const p2         = toSlug(match.second_player?.name || 'player')
  const slug       = [date, tournament, `${p1}-vs-${p2}`].filter(Boolean).join('-')
  return `/match/${match.match_id}/${slug}`
}
