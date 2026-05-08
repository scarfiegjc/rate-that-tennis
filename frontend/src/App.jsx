import { useState } from 'react'
import { Routes, Route, Link, useLocation } from 'react-router-dom'
import { AuthProvider, useAuth } from './contexts/AuthContext.jsx'
import AuthModal from './components/AuthModal.jsx'
import MatchList from './pages/MatchList.jsx'
import MatchDetail from './pages/MatchDetail.jsx'
import PlayerPage from './pages/PlayerPage.jsx'
import InPlayPage from './pages/InPlayPage.jsx'
import PredictionsToday from './pages/PredictionsToday.jsx'
import PredictionsHistory from './pages/PredictionsHistory.jsx'
import SystemsList from './pages/SystemsList.jsx'
import SystemDetail from './pages/SystemDetail.jsx'
import PlayerDatabase from './pages/PlayerDatabase.jsx'
import MyPicks from './pages/MyPicks.jsx'
import rttLogo from './assets/rtt_logo.png'

function Header() {
  const loc = useLocation()
  const { isLoggedIn, user, logout } = useAuth()
  const [showAuth, setShowAuth]      = useState(false)
  const [showUserMenu, setShowUserMenu] = useState(false)

  const is = (...prefixes) => prefixes.some(p =>
    p === '/' ? loc.pathname === '/' : loc.pathname.startsWith(p)
  )

  return (
    <>
      <header className="app-header">
        <div className="app-header-inner">
          <Link to="/" className="app-logo" aria-label="ratethat.tennis home">
            <img src={rttLogo} alt="ratethat.tennis" className="app-logo-img" />
          </Link>
          <nav className="app-nav">
            <Link to="/" className={`nav-link ${is('/') && !is('/predictions','/systems','/in-play','/players','/player','/my-picks') ? 'active' : ''}`}>
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

function AppRoutes() {
  return (
    <>
      <Header />
      <Routes>
        <Route path="/"                       element={<MatchList />} />
        <Route path="/in-play"                element={<InPlayPage />} />
        <Route path="/match/:id"              element={<MatchDetail />} />
        <Route path="/players"                element={<PlayerDatabase />} />
        <Route path="/player/:id"             element={<PlayerPage />} />
        <Route path="/predictions"            element={<PredictionsToday />} />
        <Route path="/predictions/history"    element={<PredictionsHistory />} />
        <Route path="/systems"                element={<SystemsList />} />
        <Route path="/systems/:code"          element={<SystemDetail />} />
        <Route path="/my-picks"               element={<MyPicks />} />
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
