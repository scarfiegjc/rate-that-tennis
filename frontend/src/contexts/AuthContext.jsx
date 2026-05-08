/**
 * AuthContext — global user session for ratethat.tennis
 * JWT stored in localStorage under "rtt_token".
 * Exposes: user, token, login(), register(), logout(), isLoggedIn
 */
import { createContext, useContext, useState, useEffect, useCallback } from 'react'

const AuthContext = createContext(null)

const BASE = import.meta.env.VITE_API_URL || ''

async function authPost(path, body) {
  const res = await fetch(`${BASE}${path}`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  })
  const data = await res.json()
  if (!res.ok) throw new Error(data.detail || 'Request failed')
  return data
}

export function AuthProvider({ children }) {
  const [user,  setUser]  = useState(null)
  const [token, setToken] = useState(() => localStorage.getItem('rtt_token'))
  const [loading, setLoading] = useState(true)

  // On mount (or token change) validate the stored token
  useEffect(() => {
    if (!token) { setLoading(false); return }
    fetch(`${BASE}/api/v1/auth/me`, {
      headers: { Authorization: `Bearer ${token}` },
    })
      .then(r => r.ok ? r.json() : Promise.reject())
      .then(data => setUser(data.user))
      .catch(() => { setToken(null); localStorage.removeItem('rtt_token') })
      .finally(() => setLoading(false))
  }, [token])

  const _storeSession = useCallback(({ token: t, user: u }) => {
    localStorage.setItem('rtt_token', t)
    setToken(t)
    setUser(u)
  }, [])

  const login = useCallback(async (email, password) => {
    const data = await authPost('/api/v1/auth/login', { email, password })
    _storeSession(data)
    return data.user
  }, [_storeSession])

  const register = useCallback(async (email, password, displayName) => {
    const data = await authPost('/api/v1/auth/register', {
      email, password, display_name: displayName || undefined,
    })
    _storeSession(data)
    return data.user
  }, [_storeSession])

  const logout = useCallback(() => {
    localStorage.removeItem('rtt_token')
    setToken(null)
    setUser(null)
  }, [])

  return (
    <AuthContext.Provider value={{ user, token, loading, isLoggedIn: !!user, login, register, logout }}>
      {children}
    </AuthContext.Provider>
  )
}

export function useAuth() {
  const ctx = useContext(AuthContext)
  if (!ctx) throw new Error('useAuth must be used inside AuthProvider')
  return ctx
}
