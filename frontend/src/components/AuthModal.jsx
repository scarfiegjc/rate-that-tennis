/**
 * AuthModal — login / signup overlay.
 * Props: onClose()
 * Opens in "login" mode by default; user can switch to "register".
 */
import { useState } from 'react'
import { useAuth } from '../contexts/AuthContext.jsx'

export default function AuthModal({ onClose }) {
  const { login, register } = useAuth()
  const [mode, setMode]       = useState('login')   // 'login' | 'register'
  const [email, setEmail]     = useState('')
  const [password, setPass]   = useState('')
  const [name, setName]       = useState('')
  const [error, setError]     = useState('')
  const [busy, setBusy]       = useState(false)

  async function handleSubmit(e) {
    e.preventDefault()
    setError('')
    setBusy(true)
    try {
      if (mode === 'login') {
        await login(email, password)
      } else {
        await register(email, password, name)
      }
      onClose()
    } catch (err) {
      setError(err.message || 'Something went wrong')
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="modal-overlay" onClick={e => { if (e.target === e.currentTarget) onClose() }}>
      <div className="modal-box" style={{ width: 380 }}>
        {/* Header */}
        <div style={{ display:'flex', justifyContent:'space-between', alignItems:'center', marginBottom: 20 }}>
          <h2 style={{ margin:0, fontSize:18, fontWeight:700 }}>
            {mode === 'login' ? 'Log in to ratethat.tennis' : 'Create your account'}
          </h2>
          <button onClick={onClose} style={{ fontSize:20, color:'var(--text-3)', lineHeight:1 }}>×</button>
        </div>

        <form onSubmit={handleSubmit} style={{ display:'flex', flexDirection:'column', gap:12 }}>
          {mode === 'register' && (
            <div>
              <label className="form-label">Name (optional)</label>
              <input
                className="form-input"
                type="text"
                placeholder="Your display name"
                value={name}
                onChange={e => setName(e.target.value)}
                autoComplete="name"
              />
            </div>
          )}
          <div>
            <label className="form-label">Email address</label>
            <input
              className="form-input"
              type="email"
              placeholder="you@example.com"
              value={email}
              onChange={e => setEmail(e.target.value)}
              required
              autoComplete="email"
            />
          </div>
          <div>
            <label className="form-label">Password</label>
            <input
              className="form-input"
              type="password"
              placeholder={mode === 'register' ? 'At least 6 characters' : ''}
              value={password}
              onChange={e => setPass(e.target.value)}
              required
              autoComplete={mode === 'login' ? 'current-password' : 'new-password'}
            />
          </div>

          {error && (
            <p style={{ margin:0, color:'var(--red)', fontSize:13 }}>{error}</p>
          )}

          <button
            type="submit"
            disabled={busy}
            style={{
              marginTop:4, padding:'10px 0', borderRadius:'var(--r)',
              background:'var(--text)', color:'var(--text-inv)',
              fontWeight:600, fontSize:14,
              opacity: busy ? 0.6 : 1,
            }}
          >
            {busy ? '…' : mode === 'login' ? 'Log in' : 'Create account'}
          </button>
        </form>

        <p style={{ marginTop:16, textAlign:'center', fontSize:13, color:'var(--text-3)' }}>
          {mode === 'login' ? "Don't have an account? " : 'Already have an account? '}
          <button
            onClick={() => { setMode(mode === 'login' ? 'register' : 'login'); setError('') }}
            style={{ color:'var(--green)', fontWeight:600, textDecoration:'underline' }}
          >
            {mode === 'login' ? 'Sign up' : 'Log in'}
          </button>
        </p>
      </div>
    </div>
  )
}
