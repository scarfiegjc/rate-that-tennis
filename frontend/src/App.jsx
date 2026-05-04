import { Routes, Route, Link, useLocation } from 'react-router-dom'
import MatchList from './pages/MatchList.jsx'
import MatchDetail from './pages/MatchDetail.jsx'
import PlayerPage from './pages/PlayerPage.jsx'
import LivePage from './pages/LivePage.jsx'
import PredictionsToday from './pages/PredictionsToday.jsx'
import PredictionsHistory from './pages/PredictionsHistory.jsx'
import SystemsList from './pages/SystemsList.jsx'
import SystemDetail from './pages/SystemDetail.jsx'

function Header() {
  const loc = useLocation()
  const is = (...prefixes) => prefixes.some(p =>
    p === '/' ? loc.pathname === '/' : loc.pathname.startsWith(p)
  )
  return (
    <header className="app-header">
      <Link to="/" className="app-logo">
        ratethat<span className="app-logo-dot">.</span>tennis
      </Link>
      <nav className="app-nav">
        <Link to="/" className={`nav-link ${is('/') && !is('/predictions','/systems','/live') ? 'active' : ''}`}>
          Matches
        </Link>
        <Link to="/live" className={`nav-link ${is('/live') ? 'active' : ''}`}>
          <span className="live-dot" style={{ width: 5, height: 5 }} />
          Live
        </Link>
        <Link to="/predictions" className={`nav-link ${is('/predictions') ? 'active' : ''}`}>
          Predictions
        </Link>
        <Link to="/systems" className={`nav-link ${is('/systems') ? 'active' : ''}`}>
          Systems
        </Link>
      </nav>
    </header>
  )
}

export default function App() {
  return (
    <>
      <Header />
      <Routes>
        <Route path="/"                       element={<MatchList />} />
        <Route path="/live"                   element={<LivePage />} />
        <Route path="/match/:id"              element={<MatchDetail />} />
        <Route path="/player/:id"             element={<PlayerPage />} />
        <Route path="/predictions"            element={<PredictionsToday />} />
        <Route path="/predictions/history"    element={<PredictionsHistory />} />
        <Route path="/systems"                element={<SystemsList />} />
        <Route path="/systems/:code"          element={<SystemDetail />} />
      </Routes>
    </>
  )
}
