'use client'
import { useState, useEffect, useCallback } from 'react'
import { useAuth } from '../../contexts/AuthContext'
import { useRouter } from 'next/navigation'

const API = process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8000'

// ── Sub-dot: green if any subscriptions active ─────────────────────────────
function SubDot({ count }) {
  return (
    <span style={{
      display: 'inline-block', width: 8, height: 8, borderRadius: '50%',
      background: count > 0 ? 'var(--green)' : 'var(--border)',
      marginRight: 6, verticalAlign: 'middle',
    }} title={count > 0 ? `${count} active subscription(s)` : 'No subscriptions'} />
  )
}

// ── Status badge ───────────────────────────────────────────────────────────
function StatusBadge({ status }) {
  const col = status === 'sent' ? 'var(--green)' : 'var(--red)'
  return (
    <span style={{
      padding: '2px 8px', borderRadius: 4, fontSize: 11, fontWeight: 700,
      background: `${col}22`, color: col, textTransform: 'uppercase', letterSpacing: '0.04em',
    }}>
      {status}
    </span>
  )
}

// ── Users tab ─────────────────────────────────────────────────────────────
function UsersTab({ headers }) {
  const [users, setUsers] = useState([])
  const [total, setTotal] = useState(0)
  const [search, setSearch] = useState('')
  const [page, setPage] = useState(1)
  const [loading, setLoading] = useState(false)
  const [emailTarget, setEmailTarget] = useState(null) // user to email

  const load = useCallback(async () => {
    setLoading(true)
    try {
      const q = new URLSearchParams({ page, page_size: 50, ...(search ? { search } : {}) })
      const r = await fetch(`${API}/api/v1/admin/users?${q}`, { headers })
      const d = await r.json()
      setUsers(d.users || [])
      setTotal(d.total || 0)
    } finally {
      setLoading(false)
    }
  }, [page, search])

  useEffect(() => { load() }, [load])

  async function sendQuickEmail(user) {
    setEmailTarget(user)
  }

  return (
    <div>
      <div style={{ display: 'flex', gap: 12, marginBottom: 16, alignItems: 'center' }}>
        <input
          value={search}
          onChange={e => { setSearch(e.target.value); setPage(1) }}
          placeholder="Search email or name…"
          style={{
            flex: 1, padding: '8px 12px', borderRadius: 'var(--r)',
            border: '1px solid var(--border)', background: 'var(--bg-raised)',
            color: 'var(--text)', fontSize: 13,
          }}
        />
        <span style={{ fontSize: 12, color: 'var(--text-muted)', whiteSpace: 'nowrap' }}>
          {total} user{total !== 1 ? 's' : ''}
        </span>
      </div>

      {loading ? (
        <p style={{ color: 'var(--text-muted)', textAlign: 'center', padding: 32 }}>Loading…</p>
      ) : (
        <div style={{ overflowX: 'auto' }}>
          <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: 13 }}>
            <thead>
              <tr style={{ color: 'var(--text-muted)', textAlign: 'left' }}>
                <th style={{ padding: '8px 12px', fontWeight: 600, borderBottom: '1px solid var(--border)' }}>User</th>
                <th style={{ padding: '8px 12px', fontWeight: 600, borderBottom: '1px solid var(--border)' }}>Subs</th>
                <th style={{ padding: '8px 12px', fontWeight: 600, borderBottom: '1px solid var(--border)' }}>Joined</th>
                <th style={{ padding: '8px 12px', fontWeight: 600, borderBottom: '1px solid var(--border)' }}></th>
              </tr>
            </thead>
            <tbody>
              {users.map(u => (
                <tr key={u.id} style={{ borderBottom: '1px solid var(--border)' }}>
                  <td style={{ padding: '10px 12px' }}>
                    <div style={{ fontWeight: 600, color: 'var(--text)' }}>
                      {u.is_admin && <span style={{ fontSize: 10, background: 'var(--green)22', color: 'var(--green)', padding: '1px 5px', borderRadius: 3, marginRight: 6, fontWeight: 700 }}>ADMIN</span>}
                      {u.display_name || <span style={{ color: 'var(--text-muted)' }}>—</span>}
                    </div>
                    <div style={{ color: 'var(--text-muted)', fontSize: 12 }}>{u.email}</div>
                  </td>
                  <td style={{ padding: '10px 12px' }}>
                    <SubDot count={u.sub_count} />
                    <span style={{ color: 'var(--text-muted)', fontSize: 12 }}>{u.sub_count}</span>
                  </td>
                  <td style={{ padding: '10px 12px', color: 'var(--text-muted)', fontSize: 12 }}>
                    {u.created_at ? new Date(u.created_at).toLocaleDateString('en-GB', { day: 'numeric', month: 'short', year: 'numeric' }) : '—'}
                  </td>
                  <td style={{ padding: '10px 12px', textAlign: 'right' }}>
                    <button
                      onClick={() => sendQuickEmail(u)}
                      style={{
                        padding: '4px 12px', borderRadius: 'var(--r)',
                        background: 'var(--bg-raised)', border: '1px solid var(--border)',
                        color: 'var(--text)', fontSize: 12, cursor: 'pointer',
                      }}
                    >
                      Email →
                    </button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      {/* Pagination */}
      {total > 50 && (
        <div style={{ display: 'flex', gap: 8, justifyContent: 'center', marginTop: 16 }}>
          <button disabled={page === 1} onClick={() => setPage(p => p - 1)}
            style={{ padding: '5px 14px', borderRadius: 'var(--r)', background: 'var(--bg-raised)', border: '1px solid var(--border)', color: 'var(--text)', cursor: page === 1 ? 'default' : 'pointer' }}>
            ← Prev
          </button>
          <span style={{ padding: '5px 10px', fontSize: 13, color: 'var(--text-muted)' }}>Page {page}</span>
          <button disabled={page * 50 >= total} onClick={() => setPage(p => p + 1)}
            style={{ padding: '5px 14px', borderRadius: 'var(--r)', background: 'var(--bg-raised)', border: '1px solid var(--border)', color: 'var(--text)', cursor: page * 50 >= total ? 'default' : 'pointer' }}>
            Next →
          </button>
        </div>
      )}

      {/* Quick email modal */}
      {emailTarget && (
        <QuickEmailModal
          user={emailTarget}
          headers={headers}
          onClose={() => setEmailTarget(null)}
        />
      )}
    </div>
  )
}

// ── Quick individual email modal ──────────────────────────────────────────
function QuickEmailModal({ user, headers, onClose }) {
  const [subject, setSubject] = useState('')
  const [body, setBody] = useState('')
  const [sending, setSending] = useState(false)
  const [result, setResult] = useState(null)

  async function send() {
    if (!subject.trim() || !body.trim()) return
    setSending(true)
    try {
      const r = await fetch(`${API}/api/v1/admin/email/send-individual`, {
        method: 'POST', headers,
        body: JSON.stringify({ user_id: user.id, subject, body_html: body }),
      })
      const d = await r.json()
      if (d.ok) setResult({ ok: true, msg: `Sent to ${d.sent_to}` })
      else setResult({ ok: false, msg: d.detail || 'Send failed' })
    } catch (e) {
      setResult({ ok: false, msg: e.message })
    } finally {
      setSending(false)
    }
  }

  return (
    <div style={{
      position: 'fixed', inset: 0, background: 'rgba(0,0,0,0.7)', zIndex: 400,
      display: 'flex', alignItems: 'center', justifyContent: 'center', padding: 16,
    }} onClick={e => e.target === e.currentTarget && onClose()}>
      <div style={{
        background: 'var(--bg-card)', borderRadius: 12, padding: 28,
        width: '100%', maxWidth: 520, boxShadow: 'var(--shadow)',
      }}>
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 16 }}>
          <h3 style={{ margin: 0, fontSize: 16, fontWeight: 700 }}>Email {user.display_name || user.email}</h3>
          <button onClick={onClose} style={{ background: 'none', border: 'none', color: 'var(--text-muted)', fontSize: 18, cursor: 'pointer' }}>✕</button>
        </div>
        <input
          value={subject} onChange={e => setSubject(e.target.value)}
          placeholder="Subject"
          style={{ width: '100%', boxSizing: 'border-box', marginBottom: 10, padding: '9px 12px', borderRadius: 'var(--r)', border: '1px solid var(--border)', background: 'var(--bg-raised)', color: 'var(--text)', fontSize: 13 }}
        />
        <textarea
          value={body} onChange={e => setBody(e.target.value)}
          placeholder="Email body (HTML supported)"
          rows={7}
          style={{ width: '100%', boxSizing: 'border-box', marginBottom: 14, padding: '9px 12px', borderRadius: 'var(--r)', border: '1px solid var(--border)', background: 'var(--bg-raised)', color: 'var(--text)', fontSize: 13, resize: 'vertical' }}
        />
        {result && (
          <p style={{ fontSize: 13, color: result.ok ? 'var(--green)' : 'var(--red)', marginBottom: 10 }}>{result.msg}</p>
        )}
        <div style={{ display: 'flex', gap: 10, justifyContent: 'flex-end' }}>
          <button onClick={onClose} style={{ padding: '8px 18px', borderRadius: 'var(--r)', background: 'var(--bg-raised)', border: '1px solid var(--border)', color: 'var(--text)', cursor: 'pointer' }}>Cancel</button>
          <button onClick={send} disabled={sending || !subject.trim() || !body.trim()}
            style={{ padding: '8px 18px', borderRadius: 'var(--r)', background: 'var(--green)', color: '#000', fontWeight: 700, cursor: 'pointer', opacity: sending ? 0.7 : 1 }}>
            {sending ? 'Sending…' : 'Send email'}
          </button>
        </div>
      </div>
    </div>
  )
}

// ── Send tab ──────────────────────────────────────────────────────────────
function SendTab({ headers }) {
  const [mode, setMode] = useState('broadcast') // broadcast | daily
  const [subject, setSubject] = useState('')
  const [body, setBody] = useState('')
  const [filter, setFilter] = useState('all')
  const [sending, setSending] = useState(false)
  const [result, setResult] = useState(null)

  async function send() {
    setSending(true); setResult(null)
    try {
      if (mode === 'daily') {
        const r = await fetch(`${API}/api/v1/admin/email/send-daily-predictions`, { method: 'POST', headers })
        const d = await r.json()
        setResult({ ok: d.ok, msg: d.ok ? `Sent ${d.picks} picks to ${d.sent} subscribers` : (d.detail || 'Failed') })
      } else {
        if (!subject.trim() || !body.trim()) { setResult({ ok: false, msg: 'Subject and body required' }); setSending(false); return }
        const payload = { subject, body_html: body }
        if (filter !== 'all') payload.subscription_filter = filter
        const r = await fetch(`${API}/api/v1/admin/email/send-announcement`, {
          method: 'POST', headers, body: JSON.stringify(payload),
        })
        const d = await r.json()
        setResult({ ok: d.ok, msg: d.ok ? `Sent to ${d.sent} recipients` : (d.detail || 'Failed') })
      }
    } catch (e) {
      setResult({ ok: false, msg: e.message })
    } finally {
      setSending(false)
    }
  }

  return (
    <div>
      {/* Mode selector */}
      <div style={{ display: 'flex', gap: 8, marginBottom: 20 }}>
        {[['broadcast', '📢 Announcement'], ['daily', '🎾 Daily predictions']].map(([k, label]) => (
          <button key={k} onClick={() => setMode(k)}
            style={{
              padding: '7px 16px', borderRadius: 'var(--r)', fontSize: 13, fontWeight: 600, cursor: 'pointer',
              background: mode === k ? 'var(--green)' : 'var(--bg-raised)',
              color: mode === k ? '#000' : 'var(--text)',
              border: mode === k ? 'none' : '1px solid var(--border)',
            }}>
            {label}
          </button>
        ))}
      </div>

      {mode === 'daily' ? (
        <div style={{ background: 'var(--bg-card)', borderRadius: 'var(--r)', padding: 24 }}>
          <p style={{ margin: '0 0 16px', fontSize: 14, color: 'var(--text-muted)', lineHeight: 1.6 }}>
            Pulls today's ML predictions and emails all users subscribed to <strong style={{ color: 'var(--text)' }}>Daily predictions</strong>.
          </p>
          {result && <p style={{ fontSize: 13, marginBottom: 12, color: result.ok ? 'var(--green)' : 'var(--red)', fontWeight: 600 }}>{result.msg}</p>}
          <button onClick={send} disabled={sending}
            style={{ padding: '10px 24px', borderRadius: 'var(--r)', background: 'var(--green)', color: '#000', fontWeight: 700, fontSize: 14, cursor: sending ? 'default' : 'pointer', opacity: sending ? 0.7 : 1 }}>
            {sending ? 'Sending…' : '🎾 Send daily predictions now'}
          </button>
        </div>
      ) : (
        <div style={{ background: 'var(--bg-card)', borderRadius: 'var(--r)', padding: 24 }}>
          <label style={{ display: 'block', marginBottom: 14 }}>
            <span style={{ fontSize: 12, fontWeight: 600, textTransform: 'uppercase', letterSpacing: '0.05em', color: 'var(--text-muted)', display: 'block', marginBottom: 6 }}>
              Send to
            </span>
            <select value={filter} onChange={e => setFilter(e.target.value)}
              style={{ padding: '8px 12px', borderRadius: 'var(--r)', border: '1px solid var(--border)', background: 'var(--bg-raised)', color: 'var(--text)', fontSize: 13, width: '100%' }}>
              <option value="all">All users</option>
              <option value="daily_predictions">Daily predictions subscribers</option>
              <option value="my_picks_digest">My picks digest subscribers</option>
            </select>
          </label>
          <label style={{ display: 'block', marginBottom: 14 }}>
            <span style={{ fontSize: 12, fontWeight: 600, textTransform: 'uppercase', letterSpacing: '0.05em', color: 'var(--text-muted)', display: 'block', marginBottom: 6 }}>Subject</span>
            <input value={subject} onChange={e => setSubject(e.target.value)} placeholder="Email subject…"
              style={{ width: '100%', boxSizing: 'border-box', padding: '9px 12px', borderRadius: 'var(--r)', border: '1px solid var(--border)', background: 'var(--bg-raised)', color: 'var(--text)', fontSize: 13 }} />
          </label>
          <label style={{ display: 'block', marginBottom: 16 }}>
            <span style={{ fontSize: 12, fontWeight: 600, textTransform: 'uppercase', letterSpacing: '0.05em', color: 'var(--text-muted)', display: 'block', marginBottom: 6 }}>Body (HTML)</span>
            <textarea value={body} onChange={e => setBody(e.target.value)} rows={10} placeholder="<p>Your message here...</p>"
              style={{ width: '100%', boxSizing: 'border-box', padding: '9px 12px', borderRadius: 'var(--r)', border: '1px solid var(--border)', background: 'var(--bg-raised)', color: 'var(--text)', fontSize: 13, resize: 'vertical' }} />
          </label>
          {result && <p style={{ fontSize: 13, marginBottom: 12, color: result.ok ? 'var(--green)' : 'var(--red)', fontWeight: 600 }}>{result.msg}</p>}
          <button onClick={send} disabled={sending}
            style={{ padding: '10px 24px', borderRadius: 'var(--r)', background: 'var(--green)', color: '#000', fontWeight: 700, fontSize: 14, cursor: sending ? 'default' : 'pointer', opacity: sending ? 0.7 : 1 }}>
            {sending ? 'Sending…' : '📢 Send announcement'}
          </button>
        </div>
      )}
    </div>
  )
}

// ── History tab ────────────────────────────────────────────────────────────
function HistoryTab({ headers }) {
  const [sends, setSends] = useState([])
  const [total, setTotal] = useState(0)
  const [loading, setLoading] = useState(true)
  const [page, setPage] = useState(1)

  useEffect(() => {
    setLoading(true)
    fetch(`${API}/api/v1/admin/email/history?page=${page}&page_size=50`, { headers })
      .then(r => r.json())
      .then(d => { setSends(d.sends || []); setTotal(d.total || 0) })
      .catch(() => {})
      .finally(() => setLoading(false))
  }, [page])

  const typeLabel = {
    individual: '👤 Individual',
    announcement: '📢 Announcement',
    daily_predictions: '🎾 Daily picks',
  }

  return (
    <div>
      <p style={{ fontSize: 13, color: 'var(--text-muted)', marginBottom: 16 }}>{total} send{total !== 1 ? 's' : ''} recorded</p>
      {loading ? (
        <p style={{ color: 'var(--text-muted)', textAlign: 'center', padding: 32 }}>Loading…</p>
      ) : sends.length === 0 ? (
        <p style={{ color: 'var(--text-muted)', textAlign: 'center', padding: 32 }}>No sends yet.</p>
      ) : (
        <div style={{ display: 'flex', flexDirection: 'column', gap: 1 }}>
          {sends.map(s => (
            <div key={s.id} style={{ background: 'var(--bg-card)', borderRadius: 6, padding: '12px 16px' }}>
              <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', gap: 12 }}>
                <div style={{ flex: 1, minWidth: 0 }}>
                  <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 4 }}>
                    <span style={{ fontSize: 12, color: 'var(--text-muted)' }}>{typeLabel[s.send_type] || s.send_type}</span>
                    <StatusBadge status={s.status} />
                  </div>
                  <div style={{ fontWeight: 600, fontSize: 14, color: 'var(--text)', marginBottom: 2 }}>
                    {s.subject || '(no subject)'}
                  </div>
                  {s.body_preview && (
                    <div style={{ fontSize: 12, color: 'var(--text-muted)', whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis' }}>
                      {s.body_preview}
                    </div>
                  )}
                </div>
                <div style={{ textAlign: 'right', flexShrink: 0 }}>
                  <div style={{ fontSize: 12, color: 'var(--text-muted)' }}>
                    {s.sent_at ? new Date(s.sent_at).toLocaleString('en-GB', { day: 'numeric', month: 'short', hour: '2-digit', minute: '2-digit' }) : '—'}
                  </div>
                  {s.recipient_count != null && (
                    <div style={{ fontSize: 12, color: 'var(--text-muted)' }}>
                      {s.recipient_email || `${s.recipient_count} recipient${s.recipient_count !== 1 ? 's' : ''}`}
                    </div>
                  )}
                  {s.sent_by_email && (
                    <div style={{ fontSize: 11, color: 'var(--text-muted)' }}>by {s.sent_by_email}</div>
                  )}
                </div>
              </div>
            </div>
          ))}
        </div>
      )}
      {total > 50 && (
        <div style={{ display: 'flex', gap: 8, justifyContent: 'center', marginTop: 16 }}>
          <button disabled={page === 1} onClick={() => setPage(p => p - 1)} style={{ padding: '5px 14px', borderRadius: 'var(--r)', background: 'var(--bg-raised)', border: '1px solid var(--border)', color: 'var(--text)', cursor: page === 1 ? 'default' : 'pointer' }}>← Prev</button>
          <span style={{ padding: '5px 10px', fontSize: 13, color: 'var(--text-muted)' }}>Page {page}</span>
          <button disabled={page * 50 >= total} onClick={() => setPage(p => p + 1)} style={{ padding: '5px 14px', borderRadius: 'var(--r)', background: 'var(--bg-raised)', border: '1px solid var(--border)', color: 'var(--text)', cursor: page * 50 >= total ? 'default' : 'pointer' }}>Next →</button>
        </div>
      )}
    </div>
  )
}

// ── Main AdminPage ─────────────────────────────────────────────────────────
export default function AdminClient() {
  const { isLoggedIn, token } = useAuth()
  const router = useRouter()
  const [tab, setTab] = useState('users')
  const [authChecked, setAuthChecked] = useState(false)
  const [isAdmin, setIsAdmin] = useState(false)

  const headers = {
    'Content-Type': 'application/json',
    Authorization: `Bearer ${token}`,
  }

  useEffect(() => {
    if (!isLoggedIn) { router.push('/'); return }
    // Verify admin access by hitting a protected endpoint
    fetch(`${API}/api/v1/admin/users?page=1&page_size=1`, { headers })
      .then(r => {
        if (r.status === 403) { router.push('/'); return }
        setIsAdmin(true)
      })
      .catch(() => router.push('/'))
      .finally(() => setAuthChecked(true))
  }, [isLoggedIn])

  if (!authChecked) {
    return <div style={{ textAlign: 'center', padding: 64, color: 'var(--text-muted)' }}>Checking access…</div>
  }

  if (!isAdmin) return null

  const TABS = [
    ['users', '👥 Users'],
    ['send', '✉ Send email'],
    ['history', '📋 History'],
  ]

  return (
    <div style={{ maxWidth: 900, margin: '0 auto', padding: '32px 16px' }}>
      <div style={{ marginBottom: 24 }}>
        <h1 style={{ fontSize: 24, fontWeight: 800, marginBottom: 4, color: 'var(--text)' }}>
          Admin · Marketing
        </h1>
        <p style={{ color: 'var(--text-muted)', fontSize: 14 }}>
          User management and email campaigns
        </p>
      </div>

      {/* Tab bar */}
      <div style={{ display: 'flex', gap: 4, marginBottom: 24, borderBottom: '1px solid var(--border)' }}>
        {TABS.map(([k, label]) => (
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

      {tab === 'users' && <UsersTab headers={headers} />}
      {tab === 'send' && <SendTab headers={headers} />}
      {tab === 'history' && <HistoryTab headers={headers} />}
    </div>
  )
}
