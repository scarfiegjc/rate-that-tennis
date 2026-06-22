'use client'
import { useState, useEffect } from 'react'

const API = process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8000'

function StatusPill({ active }) {
  return (
    <span style={{
      padding: '2px 8px', borderRadius: 4, fontSize: 11, fontWeight: 700,
      background: active ? 'var(--green-bg)' : 'var(--bg-raised)',
      color: active ? 'var(--green-text)' : 'var(--text-3)',
      textTransform: 'uppercase', letterSpacing: '0.04em',
    }}>
      {active ? 'active' : 'inactive'}
    </span>
  )
}

function BookmakerRow({ bm, onSave }) {
  const [editing, setEditing] = useState(false)
  const [saving, setSaving] = useState(false)
  const [form, setForm] = useState({
    affiliate_url: bm.affiliate_url || '',
    homepage_url:  bm.homepage_url  || '',
    display_name:  bm.display_name  || bm.bookmaker_key,
    priority:      bm.priority      ?? 50,
    is_active:     bm.is_active     ?? true,
    notes:         bm.notes         || '',
  })

  async function handleSave() {
    setSaving(true)
    try {
      const r = await fetch(`${API}/admin/affiliates/${encodeURIComponent(bm.bookmaker_key)}`, {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          affiliate_url: form.affiliate_url || null,
          homepage_url:  form.homepage_url  || null,
          display_name:  form.display_name  || bm.bookmaker_key,
          priority:      Number(form.priority),
          is_active:     form.is_active,
          notes:         form.notes || null,
        }),
      })
      if (r.ok) {
        const data = await r.json()
        onSave(data.updated)
        setEditing(false)
      }
    } finally {
      setSaving(false)
    }
  }

  const effectiveLink = bm.affiliate_url || bm.homepage_url

  return (
    <div className="card" style={{ marginBottom: 12, padding: '16px 20px' }}>
      <div style={{ display: 'flex', alignItems: 'center', gap: 12, marginBottom: editing ? 16 : 0 }}>
        <div style={{ flex: 1 }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
            <span style={{ fontWeight: 700, fontSize: 15 }}>{bm.display_name}</span>
            <StatusPill active={bm.is_active} />
            {bm.affiliate_url && (
              <span style={{
                padding: '2px 8px', borderRadius: 4, fontSize: 11, fontWeight: 700,
                background: 'var(--clay-bg)', color: 'var(--clay)',
              }}>
                affiliate ✓
              </span>
            )}
            <span style={{ fontSize: 12, color: 'var(--text-3)' }}>
              {bm.matches_with_odds} match{bm.matches_with_odds !== 1 ? 'es' : ''} with odds
            </span>
          </div>
          {!editing && (
            <div style={{ marginTop: 4, fontSize: 12, color: 'var(--text-3)' }}>
              {bm.affiliate_url
                ? <span>🔗 <a href={bm.affiliate_url} target="_blank" rel="noreferrer" style={{ color: 'var(--green-text)' }}>{bm.affiliate_url}</a></span>
                : bm.homepage_url
                  ? <span>Homepage: <a href={bm.homepage_url} target="_blank" rel="noreferrer" style={{ color: 'var(--text-2)' }}>{bm.homepage_url}</a></span>
                  : <span style={{ fontStyle: 'italic' }}>No URL set</span>
              }
            </div>
          )}
        </div>
        <button
          onClick={() => setEditing(!editing)}
          style={{
            padding: '6px 14px', fontSize: 12, borderRadius: 6, cursor: 'pointer',
            background: editing ? 'var(--bg-raised)' : 'var(--bg-sunken)',
            color: 'var(--text-2)', fontWeight: 600,
          }}
        >
          {editing ? 'Cancel' : 'Edit'}
        </button>
      </div>

      {editing && (
        <div style={{ display: 'grid', gap: 12 }}>
          <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 12 }}>
            <label style={{ fontSize: 12 }}>
              <div style={{ color: 'var(--text-3)', marginBottom: 4 }}>Display name</div>
              <input
                value={form.display_name}
                onChange={e => setForm(f => ({ ...f, display_name: e.target.value }))}
                style={inputStyle}
              />
            </label>
            <label style={{ fontSize: 12 }}>
              <div style={{ color: 'var(--text-3)', marginBottom: 4 }}>Priority (lower = shown first)</div>
              <input
                type="number"
                value={form.priority}
                onChange={e => setForm(f => ({ ...f, priority: e.target.value }))}
                style={inputStyle}
              />
            </label>
          </div>

          <label style={{ fontSize: 12 }}>
            <div style={{ color: 'var(--text-3)', marginBottom: 4 }}>
              Affiliate URL <span style={{ color: 'var(--clay)' }}>(use this once you have a deal)</span>
            </div>
            <input
              value={form.affiliate_url}
              onChange={e => setForm(f => ({ ...f, affiliate_url: e.target.value }))}
              placeholder="https://www.bet365.com/?af=YOUR_CODE"
              style={inputStyle}
            />
          </label>

          <label style={{ fontSize: 12 }}>
            <div style={{ color: 'var(--text-3)', marginBottom: 4 }}>Homepage URL (fallback)</div>
            <input
              value={form.homepage_url}
              onChange={e => setForm(f => ({ ...f, homepage_url: e.target.value }))}
              placeholder="https://www.bet365.com"
              style={inputStyle}
            />
          </label>

          <label style={{ fontSize: 12 }}>
            <div style={{ color: 'var(--text-3)', marginBottom: 4 }}>Notes</div>
            <input
              value={form.notes}
              onChange={e => setForm(f => ({ ...f, notes: e.target.value }))}
              placeholder="e.g. Affiliate manager: John, 25% rev share"
              style={inputStyle}
            />
          </label>

          <div style={{ display: 'flex', alignItems: 'center', gap: 12 }}>
            <label style={{ display: 'flex', alignItems: 'center', gap: 8, fontSize: 13, cursor: 'pointer' }}>
              <input
                type="checkbox"
                checked={form.is_active}
                onChange={e => setForm(f => ({ ...f, is_active: e.target.checked }))}
              />
              Active (show odds from this bookmaker)
            </label>
            <div style={{ flex: 1 }} />
            <button
              onClick={handleSave}
              disabled={saving}
              style={{
                padding: '8px 20px', fontSize: 13, fontWeight: 700, borderRadius: 6,
                background: 'var(--green)', color: '#fff', cursor: 'pointer',
                opacity: saving ? 0.6 : 1,
              }}
            >
              {saving ? 'Saving…' : 'Save'}
            </button>
          </div>
        </div>
      )}
    </div>
  )
}

const inputStyle = {
  width: '100%', padding: '7px 10px', fontSize: 13, borderRadius: 6,
  border: '1px solid var(--border)', background: 'var(--bg-raised)',
  color: 'var(--text)', boxSizing: 'border-box',
}

export default function AffiliatesAdminClient() {
  const [bookmakers, setBookmakers] = useState([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState(null)
  const [running, setRunning] = useState(false)
  const [runResult, setRunResult] = useState(null)

  useEffect(() => {
    fetch(`${API}/admin/affiliates`)
      .then(r => r.json())
      .then(d => setBookmakers(d.bookmakers || []))
      .catch(e => setError(e.message))
      .finally(() => setLoading(false))
  }, [])

  function handleSave(updated) {
    if (!updated) return
    setBookmakers(bms =>
      bms.map(b => b.bookmaker_key === updated.bookmaker_key ? { ...b, ...updated } : b)
    )
  }

  async function handleRunOddsIO() {
    setRunning(true)
    setRunResult(null)
    try {
      const r = await fetch(`${API}/admin/run-odds-io`)
      const d = await r.json()
      setRunResult(d)
      // Reload bookmakers to get updated match counts
      const r2 = await fetch(`${API}/admin/affiliates`)
      const d2 = await r2.json()
      setBookmakers(d2.bookmakers || [])
    } finally {
      setRunning(false)
    }
  }

  if (loading) return <div className="page"><div className="loading">Loading…</div></div>
  if (error)   return <div className="page"><div className="error">{error}</div></div>

  const activeCount = bookmakers.filter(b => b.is_active).length
  const affiliateCount = bookmakers.filter(b => b.affiliate_url).length

  return (
    <div className="page">
      <div className="cc-header">
        <div>
          <h1 className="cc-title">Bookmaker Affiliates</h1>
          <div className="cc-subtitle">
            Manage affiliate links — set your tracking URL when deals go live
          </div>
        </div>
        <div className="cc-meta-badges">
          <span className="count-badge">{activeCount} active</span>
          <span className="count-badge edge">{affiliateCount} with affiliate link</span>
        </div>
      </div>

      {/* Quick info box */}
      <div className="card" style={{ marginBottom: 24, padding: '14px 18px', background: 'var(--bg-raised)' }}>
        <div style={{ fontSize: 13, color: 'var(--text-2)', lineHeight: 1.6 }}>
          <strong>How it works:</strong> When a user clicks a bookmaker's odds on a match page,
          they'll be taken to the <strong>affiliate URL</strong> if one is set — earning you commission.
          Without an affiliate URL, they go to the homepage instead.
          Set affiliate URLs here as you sign deals with each bookmaker.
        </div>
      </div>

      {/* Run odds fetch */}
      <div style={{ marginBottom: 24, display: 'flex', alignItems: 'center', gap: 12 }}>
        <button
          onClick={handleRunOddsIO}
          disabled={running}
          style={{
            padding: '9px 20px', fontSize: 13, fontWeight: 700, borderRadius: 8,
            background: 'var(--bg-card)', border: '1px solid var(--border)',
            color: 'var(--text)', cursor: 'pointer', opacity: running ? 0.6 : 1,
          }}
        >
          {running ? '⏳ Fetching odds…' : '↻ Refresh odds now'}
        </button>
        {runResult && (
          <span style={{ fontSize: 12, color: 'var(--text-3)' }}>
            {runResult.skipped
              ? `Skipped: ${runResult.reason}`
              : `Fetched ${runResult.fetched}, matched ${runResult.matched}, wrote ${runResult.written}`
            }
          </span>
        )}
      </div>

      {/* Bookmaker list */}
      {bookmakers.length === 0 ? (
        <div className="card" style={{ padding: 32, textAlign: 'center', color: 'var(--text-3)' }}>
          No bookmakers yet. Click "Refresh odds now" to populate from the odds pipeline.
        </div>
      ) : (
        bookmakers.map(bm => (
          <BookmakerRow key={bm.bookmaker_key} bm={bm} onSave={handleSave} />
        ))
      )}
    </div>
  )
}
