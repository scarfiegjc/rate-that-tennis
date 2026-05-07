import { Routes, Route, Link, useLocation } from 'react-router-dom'
import MatchList from './pages/MatchList.jsx'
import MatchDetail from './pages/MatchDetail.jsx'
import PlayerPage from './pages/PlayerPage.jsx'
import InPlayPage from './pages/InPlayPage.jsx'
import PredictionsToday from './pages/PredictionsToday.jsx'
import PredictionsHistory from './pages/PredictionsHistory.jsx'
import SystemsList from './pages/SystemsList.jsx'
import SystemDetail from './pages/SystemDetail.jsx'
import PlayerDatabase from './pages/PlayerDatabase.jsx'

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
        <Link to="/" className={`nav-link ${is('/') && !is('/predictions','/systems','/in-play','/players','/player') ? 'active' : ''}`}>
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
        <Route path="/in-play"                element={<InPlayPage />} />
        <Route path="/match/:id"              element={<MatchDetail />} />
        <Route path="/players"                element={<PlayerDatabase />} />
        <Route path="/player/:id"             element={<PlayerPage />} />
        <Route path="/predictions"            element={<PredictionsToday />} />
        <Route path="/predictions/history"    element={<PredictionsHistory />} />
        <Route path="/systems"                element={<SystemsList />} />
        <Route path="/systems/:code"          element={<SystemDetail />} />
      </Routes>
    </>
  )
}
