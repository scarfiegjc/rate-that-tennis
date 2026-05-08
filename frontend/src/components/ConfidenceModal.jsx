/**
 * ConfidenceModal — asks the user to rate their confidence (1-5 stars)
 * before adding a pick.
 *
 * Props:
 *   playerName  string
 *   onConfirm(stars: number)
 *   onClose()
 */
import { useState } from 'react'

const LABELS = ['Speculative', 'Moderate', 'Confident', 'Strong', 'Maximum']

export default function ConfidenceModal({ playerName, onConfirm, onClose }) {
  const [hovered, setHovered] = useState(0)
  const [selected, setSelected] = useState(0)

  const active = hovered || selected

  return (
    <div
      className="modal-overlay"
      onClick={e => { if (e.target === e.currentTarget) onClose() }}
      style={{ zIndex: 300 }}
    >
      <div className="modal-box" style={{ width: 340, textAlign: 'center' }}>
        <h3 style={{ margin: '0 0 6px', fontSize: 16, fontWeight: 700 }}>
          Pick {playerName}
        </h3>
        <p style={{ margin: '0 0 20px', fontSize: 13, color: 'var(--text-3)' }}>
          Rate your confidence — this sets the stake for P&amp;L tracking
          (1★ = £1, 5★ = £5)
        </p>

        {/* Stars row */}
        <div style={{ display: 'flex', justifyContent: 'center', gap: 10, marginBottom: 10 }}>
          {[1, 2, 3, 4, 5].map(n => (
            <button
              key={n}
              onMouseEnter={() => setHovered(n)}
              onMouseLeave={() => setHovered(0)}
              onClick={() => setSelected(n)}
              style={{
                fontSize: 30,
                color: n <= active ? '#F59E0B' : 'transparent',
                WebkitTextStroke: n <= active ? 'none' : '1.5px var(--text-3)',
                transition: 'color 0.1s',
                lineHeight: 1,
              }}
            >
              ★
            </button>
          ))}
        </div>

        <p style={{ margin: '0 0 20px', fontSize: 13, fontWeight: 600, minHeight: 20,
                    color: active ? 'var(--amber)' : 'var(--text-3)' }}>
          {active ? `${active} star${active > 1 ? 's' : ''} — ${LABELS[active - 1]}` : 'Choose your confidence'}
        </p>

        <div style={{ display: 'flex', gap: 10 }}>
          <button
            onClick={onClose}
            style={{
              flex: 1, padding: '9px 0', borderRadius: 'var(--r)',
              border: '1px solid var(--border)', background: 'var(--bg-raised)',
              fontSize: 13, fontWeight: 500,
            }}
          >
            Cancel
          </button>
          <button
            onClick={() => selected > 0 && onConfirm(selected)}
            disabled={selected === 0}
            style={{
              flex: 2, padding: '9px 0', borderRadius: 'var(--r)',
              background: selected > 0 ? 'var(--text)' : 'var(--bg-sunken)',
              color: selected > 0 ? 'var(--text-inv)' : 'var(--text-3)',
              fontSize: 13, fontWeight: 600,
            }}
          >
            Add to My Picks
          </button>
        </div>
      </div>
    </div>
  )
}
