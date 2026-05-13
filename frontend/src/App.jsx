import { useEffect, useState } from 'react'
import { Routes, Route, Link, Navigate, useLocation } from 'react-router-dom'
import { AuthProvider, useAuth } from './contexts/AuthContext.jsx'
import AuthModal from './components/AuthModal.jsx'
import MatchList from './pages/MatchList.jsx'
import MatchDetail from './pages/MatchDetail.jsx'
import PlayerPage from './pages/PlayerPage.jsx'
import InPlayPage from './pages/InPlayPage.jsx'
import PredictionsHistory from './pages/PredictionsHistory.jsx'
import PredictionsResults from './pages/PredictionsResults.jsx'
import SystemsList from './pages/SystemsList.jsx'
import SystemDetail from './pages/SystemDetail.jsx'
import PlayerDatabase from './pages/PlayerDatabase.jsx'
import MyPicks from './pages/MyPicks.jsx'
import StatConflicts from './pages/StatConflicts.jsx'
import JoinPage from './pages/JoinPage.jsx'
import AccountPage from './pages/AccountPage.jsx'
import AdminPage from './pages/AdminPage.jsx'
import rttLogo from './assets/rtt_logo.png'

function Header() {
  const loc = useLocation()
  const { isLoggedIn, user, logout } = useAuth()
  const [showAuth, setShowAuth]      = useState(false)
  const [showUserMenu, setShowUserMenu] = useState(false)

  const is = (...prefixes) => prefixes.some(p =>
    p === '/' ? loc.pathname === '/' : loc.pathname.startsWith(p)
  )

  const matchesActive = is('/') && !is('/predictions','/systems','/in-play','/players','/player','/my-picks','/stats','/join','/account','/admin')

  return (
    <>
      <header className="app-header">
        <div className="app-header-inner">
          <Link to="/" className="app-logo" aria-label="ratethat.tennis home">
            <img src={rttLogo} alt="ratethat.tennis" className="app-logo-img" />
          </Link>
          <nav className="app-nav">
            <Link to="/" className={`nav-link ${matchesActive ? 'active' : ''}`}>
              Matches
            </Link>
            <Link to="/in-play" className={`nav-link ${is('/in-play') ? 'active' : ''}`}>
              <span className="live-dot" style={{ width: 5, height: 5 }} />
              In play
            </Link>
            <Link to="/predictions" className={`nav-link ${is('/predictions') ? 'active' : ''}`}>
              Predictions
            </Link>
            <Link to="/systems" className={`nav-link ${is('/systems') ? 'active' : ''}`}>
              Systems
            </Link>
            <Link to="/players" className={`nav-link ${is('/players') && !loc.pathname.startsWith('/player/') ? 'active' : ''}`}>
              Players
            </Link>
            <Link to="/stats" className={`nav-link ${is('/stats') ? 'active' : ''}`}>
              Stats
            </Link>
            <Link to="/my-picks" className={`nav-link ${is('/my-picks') ? 'active' : ''}`}
                  style={{ display:'flex', alignItems:'center', gap:5 }}>
              ★ My Picks
            </Link>
          </nav>

          {/* User area */}
          <div style={{ marginLeft:'auto', display:'flex', alignItems:'center' }}>
            {isLoggedIn ? (
              <div style={{ position:'relative' }}>
                <button
                  onClick={() => setShowUserMenu(v => !v)}
                  style={{
                    display:'flex', alignItems:'center', gap:7,
                    padding:'5px 10px', borderRadius:'var(--r)',
                    background:'var(--bg-raised)', fontSize:13, fontWeight:500,
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
                    <Link to="/my-picks" onClick={() => setShowUserMenu(false)}
                      style={{ display:'block', padding:'7px 12px', fontSize:13, fontWeight:500 }}>
                      My Picks
                    </Link>
                    <Link to="/account" onClick={() => setShowUserMenu(false)}
                      style={{ display:'block', padding:'7px 12px', fontSize:13, fontWeight:500 }}>
                      Account &amp; emails
                    </Link>
                    {user?.is_admin && (
                      <Link to="/admin" onClick={() => setShowUserMenu(false)}
                        style={{ display:'block', padding:'7px 12px', fontSize:13, fontWeight:500 }}>
                        Admin
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
              <div style={{ display:'flex', gap:8, alignItems:'center' }}>
                <Link to="/join"
                  style={{
                    padding:'6px 14px', borderRadius:'var(--r)',
                    background:'var(--green)', color:'#000',
                    fontSize:13, fontWeight:700, textDecoration:'none',
                  }}
                >
                  Join free
                </Link>
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
              </div>
            )}
          </div>
        </div>
      </header>

      {showAuth && <AuthModal onClose={() => setShowAuth(false)} />}
    </>
  )
}

// Send a GA4 page_view on every client-side route change. The gtag snippet
// in index.html only fires page_view on the initial document load; React
// Router pushes don't reload the page, so we need to nudge gtag manually
// or analytics will under-count by ~10x for any SPA navigation.
function GaRouteTracker() {
  const loc = useLocation()
  useEffect(() => {
    if (typeof window === 'undefined' || typeof window.gtag !== 'function') return
    const path = loc.pathname + loc.search
    window.gtag('event', 'page_view', {
      page_path:     path,
      page_location: window.location.href,
      page_title:    document.title,
    })
  }, [loc.pathname, loc.search])
  return null
}

function AppRoutes() {
  return (
    <>
      <GaRouteTracker />
      <Header />
      <Routes>
        <Route path="/"                       element={<MatchList />} />
        <Route path="/in-play"                element={<InPlayPage />} />
        <Route path="/match/:id"              element={<MatchDetail />} />
        <Route path="/match/:id/:slug"        element={<MatchDetail />} />
        <Route path="/players"                element={<PlayerDatabase />} />
        <Route path="/player/:id"             element={<PlayerPage />} />
        <Route path="/player/:id/:slug"       element={<PlayerPage />} />
        <Route path="/predictions"            element={<PredictionsResults />} />
        {/* /predictions/today merged into the main page; redirect any old links */}
        <Route path="/predictions/today"      element={<Navigate to="/predictions" replace />} />
        <Route path="/predictions/history"    element={<PredictionsHistory />} />
        <Route path="/systems"                element={<SystemsList />} />
        <Route path="/systems/:code"          element={<SystemDetail />} />
        <Route path="/my-picks"               element={<MyPicks />} />
        <Route path="/stats"                  element={<StatConflicts />} />
        <Route path="/join"                   element={<JoinPage />} />
        <Route path="/account"                element={<AccountPage />} />
        <Route path="/admin"                  element={<AdminPage />} />
      </Routes>
    </>
  )
}

export default function App() {
  return (
    <AuthProvider>
      <AppRoutes />
    </AuthProvider>
  )
}
