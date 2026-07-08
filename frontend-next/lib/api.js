// lib/api.js — works in both server components (Node.js) and client components (browser)

function getServerBase() {
  return process.env.API_URL || process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8000'
}

// Server-side fetch — for use in server components and generateMetadata
export async function apiFetch(path, options = {}) {
  const url = `${getServerBase()}${path}`
  try {
    const res = await fetch(url, {
      next: options.revalidate != null ? { revalidate: options.revalidate } : { revalidate: 0 },
    })
    if (!res.ok) return null
    return res.json()
  } catch {
    return null
  }
}

// Client-side helpers
function getToken() {
  try { return localStorage.getItem('rtt_token') } catch { return null }
}

async function clientFetch(path, init = {}) {
  const base = process.env.NEXT_PUBLIC_API_URL || ''
  const headers = { ...(init.headers || {}) }
  const token = getToken()
  if (token) headers['Authorization'] = `Bearer ${token}`
  const res = await fetch(`${base}${path}`, { ...init, headers })
  if (!res.ok) {
    const data = await res.json().catch(() => ({}))
    throw new Error(data.detail || `API ${path} → ${res.status}`)
  }
  return res.json()
}

async function clientPost(path, body) {
  return clientFetch(path, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  })
}

async function clientDel(path) {
  return clientFetch(path, { method: 'DELETE' })
}

export const api = {
  matchesToday:  ()           => clientFetch('/api/v1/matches/today'),
  match:         (id)         => clientFetch(`/api/v1/matches/${id}`),
  matchOdds:     (id)         => clientFetch(`/api/v1/matches/${id}/odds`),
  bestBets:      (daysAhead = 5, minEdge = 0.02, limit = 40) =>
    clientFetch(`/api/v1/matches/best-bets?days_ahead=${daysAhead}&min_edge=${minEdge}&limit=${limit}`),
  playersDatabase: ({ sort = 'rtt', country, search, activeOnly = true, limit = 300 } = {}) => {
    const q = new URLSearchParams({ sort, active_only: activeOnly, limit })
    if (country) q.set('country', country)
    if (search)  q.set('search', search)
    return clientFetch(`/api/v1/players?${q.toString()}`)
  },
  player:        (id)         => clientFetch(`/api/v1/players/${id}`),
  playerForm:    (id, surface, limit = 15) =>
    clientFetch(`/api/v1/players/${id}/form?surface=${surface || 'all'}&limit=${limit}`),
  playerMatches: (id, { surface = 'all', limit = 20, offset = 0 } = {}) =>
    clientFetch(`/api/v1/players/${id}/matches?surface=${surface}&limit=${limit}&offset=${offset}`),
  playerStats:   (id)         => clientFetch(`/api/v1/players/${id}/stats`),
  h2h:           (p1, p2)     => clientFetch(`/api/v1/players/${p1}/h2h/${p2}`),
  matchIntelligence:    (id)  => clientFetch(`/api/v1/matches/${id}/intelligence`),
  matchPointAnalysis:   (id)  => clientFetch(`/api/v1/matches/${id}/point-analysis`),
  predictionsToday:  (daysAhead = 2) =>
    clientFetch(`/api/v1/predictions/today?days_ahead=${daysAhead}`),
  predictionsHistory: ({ date, days = 14 } = {}) =>
    date ? clientFetch(`/api/v1/predictions/history?date=${date}`)
         : clientFetch(`/api/v1/predictions/history?days=${days}`),
  predictionsStats:  ()       => clientFetch(`/api/v1/predictions/stats`),
  predictionsResults: ()      => clientFetch(`/api/v1/predictions/results`),
  systems:           ()       => clientFetch(`/api/v1/systems`),
  systemsDashboard:  ()       => clientFetch(`/api/v1/systems/dashboard`),
  systemPicks:       (code, { status = 'all', limit = 50 } = {}) =>
    clientFetch(`/api/v1/systems/${code}/picks?status=${status}&limit=${limit}`),
  systemStats:       (code)   => clientFetch(`/api/v1/systems/${code}/stats`),
  statConflicts:     (daysAhead = 2) => clientFetch(`/api/v1/stats/conflicts?days_ahead=${daysAhead}`),
  picksActive:       ()       => clientFetch('/api/v1/picks/active'),
  picksResults:      ()       => clientFetch('/api/v1/picks/results'),
  createPick:        (body)   => clientPost('/api/v1/picks', body),
  deletePick:        (id)     => clientDel(`/api/v1/picks/${id}`),
  liveMatches:       ()       => clientFetch("/api/v1/matches/live"),
  liveProxy:         ()       => clientFetch("/api/v1/live"),
  matchOuPrediction: (id)     => clientFetch(`/api/v1/matches/${id}/ou-prediction`),
}
