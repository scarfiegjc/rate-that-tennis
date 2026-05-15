/**
 * StarPick — the ★ button placed next to a player's name on match cards and detail pages.
 *
 * Props:
 *   matchId         int
 *   playerId        int
 *   playerName      string
 *   ourOdds         number|null    — implied decimal odds from our model probability
 *   bestOdds        number|null    — best available bookmaker odds
 *   bestOddsBookie  string|null
 *   size            'sm' | 'md'   default 'md'
 *   onPickChange    () => void     optional callback after pick created/removed
 *
 * The component reads the global picks list from a context/cache so the star
 * stays yellow when navigating back to the match list.
 */
import { useState, useEffect, useCallback } from 'react'
import { useAuth } from '../contexts/AuthContext.jsx'
import { api } from '../api.js'
import ConfidenceModal from './ConfidenceModal.jsx'

// Module-level pick cache so all instances share state without prop-drilling.
// Keys are "matchId:playerId" → pick id (or true if pending creation).
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
    // Find the pick id — stored in active picks cache
    const active = window._rttActivePicks || []
    const pick = active.find(p => p.match_id === matchId && p.player_id === playerId)
    if (!pick) {
      // Optimistic remove
      _pickedSet.delete(key)
      notify()
      onPickChange?.()
      return
    }
    if (pick.status === 'live') return  // can't remove live picks

    setBusy(true)
    try {
      await api.deletePick(pick.id)
      _pickedSet.delete(key)
      // Remove from cache
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
      // Add to active picks cache
      if (result.pick) {
        window._rttActivePicks = [...(window._rttActivePicks || []), result.pick]
      }
      notify()
      onPickChange?.()
    } catch (e) {
      // 409 = pick already exists in DB — treat as success, turn star yellow
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
          color: isPicked ? '#F59E0B' : '#ffffff',
          WebkitTextStroke: 'none',
          textShadow: isPicked ? '0 0 2px rgba(245,158,11,0.4)' : 'none',
          opacity: isPicked ? 1 : 0.55,
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
