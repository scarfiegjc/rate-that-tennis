// Build the SEO-friendly URL for a match: /match/<id>/<date>-<tournament>-<p1>-vs-<p2>
//
// IMPORTANT: any `<Link to="/match/...">` that targets MatchDetail must build
// its href via this helper. Linking with just /match/<id> works (the route
// matches both /match/:id and /match/:id/:slug) but loses the SEO slug —
// search engines and the canonical URL on the match page then point at a
// numeric URL instead of a descriptive one.
//
// Accepts either of the two shapes used across the codebase:
//   - MatchList shape: { match_id, event_date, tournament, first_player, second_player }
//   - PredictionsResults shape: { match_id, event_date, tournament, p1: {name}, p2: {name}, pick_name, opp_name }

function toSlug(s) {
  return String(s || '')
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, '-')
    .replace(/^-+|-+$/g, '')
}

export function matchUrl(m) {
  if (!m) return '/'
  const id = m.match_id ?? m.id
  if (id == null) return '/'
  const date       = (m.event_date || '').slice(0, 10)
  const tournament = toSlug(m.tournament || '')
  const p1Name     = m.first_player?.name ?? m.p1?.name ?? m.p1_name ?? m.pick_name ?? 'player'
  const p2Name     = m.second_player?.name ?? m.p2?.name ?? m.p2_name ?? m.opp_name  ?? 'player'
  const p1 = toSlug(p1Name)
  const p2 = toSlug(p2Name)
  const slug = [date, tournament, `${p1}-vs-${p2}`].filter(Boolean).join('-')
  return slug ? `/match/${id}/${slug}` : `/match/${id}`
}

export default matchUrl
