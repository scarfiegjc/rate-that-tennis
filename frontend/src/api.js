// ratethat.tennis — API client
// In dev: Vite proxies /api → http://localhost:8000
// In production: set VITE_API_URL to the Railway API base URL

const BASE = import.meta.env.VITE_API_URL || ''

async function get(path) {
  const res = await fetch(`${BASE}${path}`)
  if (!res.ok) {
    const text = await res.text().catch(() => res.statusText)
    throw new Error(`API ${path} → ${res.status}: ${text}`)
  }
  return res.json()
}

export const api = {
  matchesToday:  ()           => get('/api/v1/matches/today'),
  match:         (id)         => get(`/api/v1/matches/${id}`),
  player:        (id)         => get(`/api/v1/players/${id}`),
  playerForm:    (id, surface, limit = 15) =>
    get(`/api/v1/players/${id}/form?surface=${surface || 'all'}&limit=${limit}`),
  playerMatches: (id, { surface = 'all', limit = 20, offset = 0 } = {}) =>
    get(`/api/v1/players/${id}/matches?surface=${surface}&limit=${limit}&offset=${offset}`),
  playerStats:   (id)         => get(`/api/v1/players/${id}/stats`),
  h2h:           (p1, p2)     => get(`/api/v1/players/${p1}/h2h/${p2}`),
  health:        ()           => get('/health'),

  // Predictions tracker
  predictionsToday:  (daysAhead = 2) =>
    get(`/api/v1/predictions/today?days_ahead=${daysAhead}`),
  predictionsHistory: ({ date, days = 14 } = {}) =>
    date
      ? get(`/api/v1/predictions/history?date=${date}`)
      : get(`/api/v1/predictions/history?days=${days}`),
  predictionsStats:  ()          => get(`/api/v1/predictions/stats`),

  // Systems
  systems:           ()          => get(`/api/v1/systems`),
  systemPicks:       (code, { status = 'all', limit = 50 } = {}) =>
    get(`/api/v1/systems/${code}/picks?status=${status}&limit=${limit}`),
  systemStats:       (code)      => get(`/api/v1/systems/${code}/stats`),
}
