// ratethat.tennis — API client
// In dev: Vite proxies /api → http://localhost:8000
// In production: set VITE_API_URL to the Railway API base URL

const BASE = import.meta.env.VITE_API_URL || ''

function getToken() {
  return localStorage.getItem('rtt_token')
}

async function get(path) {
  const headers = {}
  const token = getToken()
  if (token) headers['Authorization'] = `Bearer ${token}`
  const res = await fetch(`${BASE}${path}`, { headers })
  if (!res.ok) {
    const text = await res.text().catch(() => res.statusText)
    throw new Error(`API ${path} → ${res.status}: ${text}`)
  }
  return res.json()
}

async function post(path, body) {
  const headers = { 'Content-Type': 'application/json' }
  const token = getToken()
  if (token) headers['Authorization'] = `Bearer ${token}`
  const res = await fetch(`${BASE}${path}`, {
    method: 'POST',
    headers,
    body: JSON.stringify(body),
  })
  if (!res.ok) {
    const data = await res.json().catch(() => ({}))
    throw new Error(data.detail || `API ${path} → ${res.status}`)
  }
  return res.json()
}

async function del(path) {
  const headers = {}
  const token = getToken()
  if (token) headers['Authorization'] = `Bearer ${token}`
  const res = await fetch(`${BASE}${path}`, { method: 'DELETE', headers })
  if (!res.ok) {
    const data = await res.json().catch(() => ({}))
    throw new Error(data.detail || `API ${path} → ${res.status}`)
  }
  return res.json()
}

export const api = {
  matchesToday:  ()           => get('/api/v1/matches/today'),
  match:         (id)         => get(`/api/v1/matches/${id}`),
  playersDatabase: ({ sort = 'rtt', country, search, activeOnly = true, limit = 300 } = {}) => {
    const q = new URLSearchParams({ sort, active_only: activeOnly, limit })
    if (country) q.set('country', country)
    if (search)  q.set('search', search)
    return get(`/api/v1/players?${q.toString()}`)
  },
  player:        (id)         => get(`/api/v1/players/${id}`),
  playerForm:    (id, surface, limit = 15) =>
    get(`/api/v1/players/${id}/form?surface=${surface || 'all'}&limit=${limit}`),
  playerMatches: (id, { surface = 'all', limit = 20, offset = 0 } = {}) =>
    get(`/api/v1/players/${id}/matches?surface=${surface}&limit=${limit}&offset=${offset}`),
  playerStats:   (id)         => get(`/api/v1/players/${id}/stats`),
  h2h:           (p1, p2)     => get(`/api/v1/players/${p1}/h2h/${p2}`),
  health:        ()           => get('/health'),

  matchIntelligence:    (id) => get(`/api/v1/matches/${id}/intelligence`),
  matchPointAnalysis:   (id) => get(`/api/v1/matches/${id}/point-analysis`),

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

  // My Picks
  picksActive:       ()          => get('/api/v1/picks/active'),
  picksResults:      ()          => get('/api/v1/picks/results'),
  createPick:        (body)      => post('/api/v1/picks', body),
  deletePick:        (id)        => del(`/api/v1/picks/${id}`),
}
