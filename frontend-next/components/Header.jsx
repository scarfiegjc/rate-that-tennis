'use client'
import { useState } from 'react'
import Link from 'next/link'
import { usePathname, useRouter } from 'next/navigation'
import { useAuth } from '../contexts/AuthContext'
import AuthModal from './AuthModal'

export default function Header() {
  const pathname = usePathname()
  const router = useRouter()
  const { isLoggedIn, user, logout } = useAuth()
  const [showAuth, setShowAuth] = useState(false)
  const [showUserMenu, setShowUserMenu] = useState(false)

  const is = (...prefixes) => prefixes.some(p =>
    p === '/' ? pathname === '/' : pathname.startsWith(p)
  )

  return (
    <>
      <header className="app-header">
        <div className="app-header-inner">
          <Link href="/" className="app-logo" aria-label="ratethat.tennis home">
            <span className="app-logo-text">
              <span className="app-logo-ratethat">ratethat.</span><span className="app-logo-sport">tennis</span>
            </span>
          </Link>
          <nav className="app-nav">
            <Link href="/" className={`nav-link ${pathname === '/' ? 'active' : ''}`}>
              Matches
            </Link>
            <Link href="/in-play" className={`nav-link ${is('/in-play') ? 'active' : ''}`}>
              <span className="live-dot" style={{ width: 5, height: 5 }} />
              In play
            </Link>
            <Link href="/best-bets" className={`nav-link ${is('/best-bets') ? 'active' : ''}`}>
              💎 Best Bets
            </Link>
            <Link href="/predictions" className={`nav-link ${is('/predictions') ? 'active' : ''}`}>
              Predictions
            </Link>
            <Link href="/players" className={`nav-link ${is('/players') && !pathname.startsWith('/player/') ? 'active' : ''}`}>
              Players
            </Link>
            <Link href="/stats" className={`nav-link ${is('/stats') ? 'active' : ''}`}>
              Stats
            </Link>
            <Link href="/my-picks" className={`nav-link ${is('/my-picks') ? 'active' : ''}`}
                  style={{ display:'flex', alignItems:'center', gap:5 }}>
              ★ My Picks
            </Link>
            {!isLoggedIn && (
              <Link href="/join" className={`nav-link ${is('/join') ? 'active' : ''}`}
                    style={{ color:'#4ade80', fontWeight:700 }}>
                Join free
              </Link>
            )}
          </nav>

          <div style={{ marginLeft:'auto', display:'flex', alignItems:'center' }}>
            {isLoggedIn ? (
              <div style={{ position:'relative' }}>
                <button
                  onClick={() => setShowUserMenu(v => !v)}
                  style={{
                    display:'flex', alignItems:'center', gap:7,
                    padding:'5px 10px', borderRadius:'var(--r)',
                    background:'rgba(255,255,255,0.1)', border:'1px solid rgba(255,255,255,0.15)',
                    fontSize:13, fontWeight:500, color:'#fff',
                  }}
                >
                  <span style={{
                    width:24, height:24, borderRadius:'50%',
                    background:'var(--green)', color:'#fff',
                    display:'flex', alignItems:'center', justifyContent:'center',
                    fontSize:11, fontWeight:700,
                  }}>
                    {(user?.display_name || user?.email || '?')[0].toUpperCase()}
                  </span>
                  {user?.display_name || user?.email?.split('@')[0]}
                </button>
                {showUserMenu && (
                  <div style={{
                    position:'absolute', right:0, top:'110%', zIndex:200,
                    background:'var(--bg-card)', border:'1px solid var(--border)',
                    borderRadius:'var(--r)', boxShadow:'var(--shadow)',
                    minWidth:160, padding:6,
                  }}>
                    <Link href="/my-picks" onClick={() => setShowUserMenu(false)}
                      style={{ display:'block', padding:'7px 12px', fontSize:13, fontWeight:500 }}>
                      My Picks
                    </Link>
                    <Link href="/account" onClick={() => setShowUserMenu(false)}
                      style={{ display:'block', padding:'7px 12px', fontSize:13, fontWeight:500 }}>
                      Account
                    </Link>
                    {user?.is_admin && (
                      <Link href="/admin" onClick={() => setShowUserMenu(false)}
                        style={{ display:'block', padding:'7px 12px', fontSize:13, fontWeight:500, color:'var(--amber)' }}>
                        Admin
                      </Link>
                    )}
                    {user?.is_admin && (
                      <Link href="/admin/affiliates" onClick={() => setShowUserMenu(false)}
                        style={{ display:'block', padding:'7px 12px', fontSize:13, fontWeight:500, color:'var(--amber)' }}>
                        Affiliates
                      </Link>
                    )}
                    <button onClick={() => { logout(); setShowUserMenu(false) }}
                      style={{ display:'block', width:'100%', textAlign:'left',
                               padding:'7px 12px', fontSize:13, color:'var(--red)' }}>
                      Log out
                    </button>
                  </div>
                )}
              </div>
            ) : (
              <button
                onClick={() => setShowAuth(true)}
                style={{
                  padding:'6px 14px', borderRadius:'var(--r)',
                  background:'var(--text)', color:'var(--text-inv)',
                  fontSize:13, fontWeight:600,
                }}
              >
                Log in
              </button>
            )}
          </div>
        </div>
      </header>

      {showAuth && <AuthModal onClose={() => setShowAuth(false)} />}
    </>
  )
}
