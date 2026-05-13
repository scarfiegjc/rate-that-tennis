import { useState, useEffect } from 'react'
import { useAuth } from '../contexts/AuthContext.jsx'
import { useNavigate } from 'react-router-dom'

const API = import.meta.env.VITE_API_URL || 'http://localhost:8000'

function Toggle({ label, description, checked, onChange, loading }) {
  return (
    <div style={{
      display: 'flex', alignItems: 'flex-start', justifyContent: 'space-between',
      padding: '16px 0', borderBottom: '1px solid var(--border)',
    }}>
      <div style={{ flex: 1, paddingRight: 20 }}>
        <div style={{ fontWeight: 600, fontSize: 14, color: 'var(--text)', marginBottom: 3 }}>{label}</div>
        <div style={{ fontSize: 13, color: 'var(--text-muted)' }}>{description}</div>
      </div>
      <button
        onClick={() => !loading && onChange(!checked)}
        disabled={loading}
        style={{
          width: 44, height: 24, borderRadius: 12, flexShrink: 0,
          background: checked ? 'var(--green)' : 'var(--border)',
          position: 'relative', cursor: loading ? 'default' : 'pointer',
          transition: 'background 0.2s', border: 'none', outline: 'none',
          opacity: loading ? 0.6 : 1,
        }}
        aria-checked={checked}
        role="switch"
      >
        <span style={{
          display: 'block', width: 18, height: 18, borderRadius: '50%',
          background: '#fff', position: 'absolute',
          top: 3, left: checked ? 23 : 3,
          transition: 'left 0.2s',
        }} />
      </button>
    </div>
  )
}

export default function AccountPage() {
  const { isLoggedIn, token, user } = useAuth()
  const navigate = useNavigate()

  const [tab, setTab] = useState('email')
  const [prefs, setPrefs] = useState({ daily_predictions: false, my_picks_digest: false })
  const [profile, setProfile] = useState({ display_name: '', email: '', created_at: '' })
  const [displayNameInput, setDisplayNameInput] = useState('')
  const [saving, setSaving] = useState(false)
  const [togglingKey, setTogglingKey] = useState(null)
  const [msg, setMsg] = useState(null)

  const headers = {
    'Content-Type': 'application/json',
    Authorization: `Bearer ${token}`,
  }

  useEffect(() => {
    if (!isLoggedIn) { navigate('/'); return }
    fetch(`${API}/api/v1/account/email-prefs`, { headers })
      .then(r => r.json()).then(d => setPrefs(d)).catch(() => {})
    fetch(`${API}/api/v1/account/profile`, { headers })
      .then(r => r.json()).then(d => {
        setProfile(d)
        setDisplayNameInput(d.display_name || '')
      }).catch(() => {})
  }, [isLoggedIn])

  async function togglePref(key, val) {
    setTogglingKey(key)
    try {
      await fetch(`${API}/api/v1/account/email-prefs`, {
        method: 'PUT', headers,
        body: JSON.stringify({ [key]: val }),
      })
      setPrefs(p => ({ ...p, [key]: val }))
    } finally {
      setTogglingKey(null)
    }
  }

  async function saveProfile(e) {
    e.preventDefault()
    setSaving(true)
    setMsg(null)
    try {
      await fetch(`${API}/api/v1/account/profile`, {
        method: 'PUT', headers,
        body: JSON.stringify({ display_name: displayNameInput }),
      })
      setMsg({ ok: true, text: 'Saved!' })
    } catch {
      setMsg({ ok: false, text: 'Save failed.' })
    } finally {
      setSaving(false)
      setTimeout(() => setMsg(null), 3000)
    }
  }

  const memberSince = profile.created_at
    ? new Date(profile.created_at).toLocaleDateString('en-GB', { day: 'numeric', month: 'long', year: 'numeric' })
    : ''

  return (
    <div style={{ maxWidth: 640, margin: '0 auto', padding: '32px 16px' }}>
      <h1 style={{ fontSize: 24, fontWeight: 800, marginBottom: 4, color: 'var(--text)' }}>
        Account settings
      </h1>
      <p style={{ color: 'var(--text-muted)', fontSize: 14, marginBottom: 28 }}>
        {profile.email}
        {memberSince && <> · Member since {memberSince}</>}
      </p>

      {/* Tab bar */}
      <div style={{ display: 'flex', gap: 4, marginBottom: 28, borderBottom: '1px solid var(--border)' }}>
        {[['email', '✉ Email subscriptions'], ['profile', '👤 Profile']].map(([k, label]) => (
          <button
            key={k}
            onClick={() => setTab(k)}
            style={{
              padding: '8px 16px', fontSize: 13, fontWeight: 600, borderRadius: '6px 6px 0 0',
              background: tab === k ? 'var(--bg-card)' : 'transparent',
              color: tab === k ? 'var(--text)' : 'var(--text-muted)',
              borderBottom: tab === k ? '2px solid var(--green)' : '2px solid transparent',
              cursor: 'pointer',
            }}
          >
            {label}
          </button>
        ))}
      </div>

      {tab === 'email' && (
        <div style={{ background: 'var(--bg-card)', borderRadius: 'var(--r)', padding: '8px 20px 4px' }}>
          <Toggle
            label="Daily predictions"
            description="Get today's top ML picks and RTT edge signals delivered to your inbox each morning."
            checked={prefs.daily_predictions}
            onChange={v => togglePref('daily_predictions', v)}
            loading={togglingKey === 'daily_predictions'}
          />
          <Toggle
            label="My picks digest"
            description="A weekly summary of your picks: upcoming matches, recent results, hit rate and P&L."
            checked={prefs.my_picks_digest}
            onChange={v => togglePref('my_picks_digest', v)}
            loading={togglingKey === 'my_picks_digest'}
          />
          <p style={{ fontSize: 12, color: 'var(--text-muted)', padding: '16px 0' }}>
            You can unsubscribe at any time. We never spam or share your address.
          </p>
        </div>
      )}

      {tab === 'profile' && (
        <div style={{ background: 'var(--bg-card)', borderRadius: 'var(--r)', padding: 24 }}>
          <form onSubmit={saveProfile}>
            <label style={{ display: 'block', marginBottom: 16 }}>
              <span style={{ fontSize: 12, fontWeight: 600, textTransform: 'uppercase',
                             letterSpacing: '0.05em', color: 'var(--text-muted)', display: 'block', marginBottom: 6 }}>
                Display name
              </span>
              <input
                value={displayNameInput}
                onChange={e => setDisplayNameInput(e.target.value)}
                placeholder="How should we address you?"
                style={{
                  width: '100%', boxSizing: 'border-box',
                  padding: '10px 14px', borderRadius: 'var(--r)',
                  border: '1px solid var(--border)', background: 'var(--bg-raised)',
                  color: 'var(--text)', fontSize: 14, outline: 'none',
                }}
              />
            </label>

            <label style={{ display: 'block', marginBottom: 20 }}>
              <span style={{ fontSize: 12, fontWeight: 600, textTransform: 'uppercase',
                             letterSpacing: '0.05em', color: 'var(--text-muted)', display: 'block', marginBottom: 6 }}>
                Email address
              </span>
              <input
                value={profile.email}
                readOnly
                style={{
                  width: '100%', boxSizing: 'border-box',
                  padding: '10px 14px', borderRadius: 'var(--r)',
                  border: '1px solid var(--border)', background: 'var(--bg-raised)',
                  color: 'var(--text-muted)', fontSize: 14, cursor: 'default',
                }}
              />
            </label>

            <div style={{ display: 'flex', alignItems: 'center', gap: 12 }}>
              <button
                type="submit"
                disabled={saving}
                style={{
                  padding: '9px 22px', borderRadius: 'var(--r)',
                  background: 'var(--green)', color: '#000',
                  fontWeight: 700, fontSize: 14, cursor: saving ? 'default' : 'pointer',
                  opacity: saving ? 0.7 : 1,
                }}
              >
                {saving ? 'Saving…' : 'Save changes'}
              </button>
              {msg && (
                <span style={{ fontSize: 13, color: msg.ok ? 'var(--green)' : 'var(--red)', fontWeight: 600 }}>
                  {msg.text}
                </span>
              )}
            </div>
          </form>
        </div>
      )}
    </div>
  )
}
