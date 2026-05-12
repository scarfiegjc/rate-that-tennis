// Build the SEO-friendly URL for a player: /player/<id>/<full-name-slug>
//
// IMPORTANT: any link that targets PlayerPage should build its href via
// this helper. Linking with just /player/<id> works (the route matches
// both /player/:id and /player/:id/:slug) but loses the SEO slug — and
// numeric URLs in shared links / search results look bad and rank worse.

function toSlug(s) {
  return String(s || '')
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, '-')
    .replace(/^-+|-+$/g, '')
}

export function playerUrl(p) {
  if (!p) return '/'
  const id = p.id ?? p.player_id
  if (id == null) return '/'
  const name = p.full_name || p.name || ''
  const slug = toSlug(name)
  return slug ? `/player/${id}/${slug}` : `/player/${id}`
}

export default playerUrl
