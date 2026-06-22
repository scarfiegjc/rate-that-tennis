'use client'
/**
 * StarPick — the ★ button placed next to a player's name on match cards and detail pages.
 */
import { useState, useEffect, useCallback } from 'react'
import { useAuth } from '../contexts/AuthContext'
import { api } from '../lib/api'
import ConfidenceModal from './ConfidenceModal'

const _pickedSet = new Set()
const _subscribers = new Set()

function notify() { _subscribers.forEach(fn => fn()) }

export function usePickedSet() {
  const [, rerender] = useState(0)
  useEffect(() => {
    const fn = () => rerender(n => n + 1)
    _subscribers.add(fn)
    return () => _subscribers.delete(fn)
  }, [])
  return _pickedSet
}

export function seedPickedSet(picks) {
  _pickedSet.clear()
  picks.forEach(p => _pickedSet.add(`${p.match_id}:${p.player_id}`))
  notify()
}

export default function StarPick({
  matchId, playerId, playerName,
  ourOdds = null, bestOdds = null, bestOddsBookie = null,
  size = 'md',
  onPickChange,
}) {
  const { isLoggedIn } = useAuth()
  const pickedSet = usePickedSet()
  const key = `${matchId}:${playerId}`
  const isPicked = pickedSet.has(key)

  const [showLoginHint, setLoginHint]   = useState(false)
  const [showConfModal, setConfModal]   = useState(false)
  const [busy, setBusy]                 = useState(false)

  const sz = size === 'sm' ? 16 : 20

  async function handleRemove() {
    if (busy) return
    const active = window._rttActivePicks || []
    const pick = active.find(p => p.match_id === matchId && p.player_id === playerId)
    if (!pick) {
      _pickedSet.delete(key)
      notify()
      onPickChange?.()
      return
    }
    if (pick.status === 'live') return

    setBusy(true)
    try {
      await api.deletePick(pick.id)
      _pickedSet.delete(key)
      window._rttActivePicks = (window._rttActivePicks || []).filter(p => p.id !== pick.id)
      notify()
      onPickChange?.()
    } catch (e) {
      console.warn('delete pick failed', e)
    } finally {
      setBusy(false)
    }
  }

  function handleClick(e) {
    e.stopPropagation()
    if (!isLoggedIn) { setLoginHint(true); setTimeout(() => setLoginHint(false), 2500); return }
    if (isPicked) {
      handleRemove()
    } else {
      setConfModal(true)
    }
  }

  async function handleConfirm(stars) {
    setConfModal(false)
    if (busy) return
    setBusy(true)
    try {
      const result = await api.createPick({
        match_id: matchId,
        player_id: playerId,
        confidence_stars: stars,
        our_odds:  ourOdds,
        best_odds: bestOdds,
        best_odds_bookie: bestOddsBookie,
      })
      _pickedSet.add(key)
      if (result.pick) {
        window._rttActivePicks = [...(window._rttActivePicks || []), result.pick]
      }
      notify()
      onPickChange?.()
    } catch (e) {
      if (e.message && (e.message.includes('already exists') || e.message.includes('409'))) {
        _pickedSet.add(key)
        notify()
        onPickChange?.()
      } else {
        console.warn('create pick failed', e)
      }
    } finally {
      setBusy(false)
    }
  }

  return (
    <span style={{ position: 'relative', display: 'inline-flex', alignItems: 'center' }}>
      <button
        onClick={handleClick}
        title={isPicked ? `Remove ${playerName} from My Picks` : `Pick ${playerName}`}
        disabled={busy}
        style={{
          fontSize: sz,
          lineHeight: 1,
          color: isPicked ? '#F59E0B' : 'transparent',
          WebkitTextStroke: isPicked ? 'none' : `1.5px var(--text-3)`,
          textShadow: isPicked ? '0 0 2px rgba(245,158,11,0.4)' : 'none',
          transition: 'color 0.15s, text-shadow 0.15s',
          opacity: busy ? 0.5 : 1,
          padding: '1px 3px',
        }}
      >
        ★
      </button>

      {showLoginHint && (
        <span style={{
          position:'absolute', bottom:'130%', left:'50%', transform:'translateX(-50%)',
          background:'var(--text)', color:'var(--text-inv)',
          fontSize:11, fontWeight:500, whiteSpace:'nowrap',
          padding:'4px 8px', borderRadius:'var(--r-sm)', zIndex:100,
          pointerEvents: 'none',
        }}>
          Log in to save picks
        </span>
      )}

      {showConfModal && (
        <ConfidenceModal
          playerName={playerName}
          onConfirm={handleConfirm}
          onClose={() => setConfModal(false)}
        />
      )}
    </span>
  )
}
