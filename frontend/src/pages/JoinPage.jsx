/**
 * JoinPage — "Join For Free" landing page
 */
import { useState } from 'react'
import { Link } from 'react-router-dom'
import { useAuth } from '../contexts/AuthContext.jsx'
import AuthModal from '../components/AuthModal.jsx'
import courtHardImg from '../assets/court-hard.jpg'
import courtClayImg from '../assets/court-clay.jpg'

const GREEN      = '#16A34A'
const GREEN_DARK = '#14532D'
const GOLD       = '#F59E0B'
const WHITE      = '#FFFFFF'

function FreePill() {
  return (
    <span style={{
      display: 'inline-flex', alignItems: 'center', gap: 6,
      background: '#DCFCE7', color: GREEN_DARK,
      padding: '4px 14px', borderRadius: 999,
      fontSize: 13, fontWeight: 800, letterSpacing: 0.3,
      border: '1px solid #86EFAC',
    }}>
      ✓ Completely free — no credit card
    </span>
  )
}

function FeatureIcon({ children }) {
  return (
    <div style={{
      width: 44, height: 44, borderRadius: 12,
      background: '#DCFCE7', color: GREEN_DARK,
      display: 'flex', alignItems: 'center', justifyContent: 'center',
      fontSize: 22, flexShrink: 0,
    }}>
      {children}
    </div>
  )
}

function FeatureRow({ icon, title, desc }) {
  return (
    <div style={{ display: 'flex', gap: 18, alignItems: 'flex-start' }}>
      <FeatureIcon>{icon}</FeatureIcon>
      <div>
        <div style={{ fontWeight: 700, fontSize: 16, marginBottom: 4 }}>{title}</div>
        <div style={{ color: '#6B7280', fontSize: 14, lineHeight: 1.65 }}>{desc}</div>
      </div>
    </div>
  )
}

function MatchCardMockup() {
  return (
    <div style={{
      background: '#fff', border: '1px solid #E5E7EB', borderRadius: 14,
      overflow: 'hidden', boxShadow: '0 4px 24px rgba(0,0,0,0.08)',
      maxWidth: 340, width: '100%',
    }}>
      <div style={{ background: `linear-gradient(135deg, ${GREEN_DARK}, #166534)`, padding: '12px 16px', color: '#fff' }}>
        <div style={{ fontSize: 11, opacity: 0.8, marginBottom: 2 }}>Wimbledon · Grass · Centre Court</div>
        <div style={{ fontSize: 11, opacity: 0.6 }}>Today · 14:00</div>
      </div>
      <div style={{ padding: '16px', display: 'flex', flexDirection: 'column', gap: 12 }}>
        {[
          { name: 'C. Alcaraz', prob: 68, edge: '+6.2%', rtt: 91, dots: ['W','W','W','L','W'], picked: true },
          { name: 'N. Djokovic', prob: 32, rtt: 87, dots: ['W','L','W','W','L'], picked: false },
        ].map((p, i) => (
          <div key={i} style={{
            display: 'flex', alignItems: 'center', justifyContent: 'space-between',
            padding: '10px 12px', borderRadius: 10,
            background: p.picked ? '#F0FDF4' : '#F9FAFB',
            border: `1px solid ${p.picked ? '#86EFAC' : '#F3F4F6'}`,
          }}>
            <div>
              <div style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
                {p.picked && <span style={{ color: GOLD, fontSize: 14 }}>★</span>}
                <span style={{ fontWeight: 700, fontSize: 15 }}>{p.name}</span>
              </div>
              <div style={{ display: 'flex', gap: 3, marginTop: 5 }}>
                {p.dots.map((d, j) => (
                  <span key={j} style={{ width: 8, height: 8, borderRadius: '50%', background: d === 'W' ? '#16A34A' : '#DC2626', display: 'inline-block' }} />
                ))}
              </div>
            </div>
            <div style={{ textAlign: 'right' }}>
              <div style={{ fontSize: 22, fontWeight: 900, color: p.picked ? GREEN : '#9CA3AF' }}>{p.prob}%</div>
              {p.edge && <div style={{ fontSize: 11, fontWeight: 700, color: GREEN, background: '#DCFCE7', padding: '1px 6px', borderRadius: 20 }}>{p.edge} edge</div>}
            </div>
          </div>
        ))}
      </div>
      <div style={{ padding: '10px 16px', borderTop: '1px solid #F3F4F6', display: 'flex', justifyContent: 'space-between', alignItems: 'center', background: '#FAFAFA' }}>
        <div style={{ fontSize: 11, color: '#9CA3AF', fontWeight: 600 }}>RTT Score · Surface · Form</div>
        <div style={{ fontSize: 11, fontWeight: 700, color: WHITE, background: GREEN, padding: '4px 10px', borderRadius: 20 }}>Model edge →</div>
      </div>
    </div>
  )
}

function PLMockup() {
  const pts = [0, 1.2, 0.8, 2.1, 1.5, 3.3, 2.8, 4.7, 4.1, 6.2, 5.8, 7.4]
  const W = 300, H = 90, PAD = 8
  const min = Math.min(...pts), max = Math.max(...pts)
  const range = max - min || 1
  const svgPts = pts.map((v, i) => [PAD + (i / (pts.length - 1)) * (W - PAD * 2), PAD + ((max - v) / range) * (H - PAD * 2)])
  const d = svgPts.map((p, i) => `${i === 0 ? 'M' : 'L'}${p[0].toFixed(1)},${p[1].toFixed(1)}`).join(' ')
  const fill = `${d} L${svgPts[svgPts.length-1][0]},${H} L${svgPts[0][0]},${H} Z`
  return (
    <div style={{ background: '#fff', border: '1px solid #E5E7EB', borderRadius: 14, overflow: 'hidden', boxShadow: '0 4px 24px rgba(0,0,0,0.08)', maxWidth: 340, width: '100%' }}>
      <div style={{ padding: '16px 20px 8px' }}>
        <div style={{ fontSize: 11, color: '#9CA3AF', fontWeight: 700, textTransform: 'uppercase', letterSpacing: '0.5px' }}>My P&L</div>
        <div style={{ display: 'flex', gap: 16, marginTop: 10 }}>
          {[{ label: 'Picks', value: '34', color: '#111827' }, { label: 'Win rate', value: '62%', color: GREEN }, { label: 'P&L', value: '+£41.20', color: GREEN }].map(s => (
            <div key={s.label} style={{ textAlign: 'center' }}>
              <div style={{ fontSize: 20, fontWeight: 900, color: s.color }}>{s.value}</div>
              <div style={{ fontSize: 10, color: '#9CA3AF', fontWeight: 600, textTransform: 'uppercase' }}>{s.label}</div>
            </div>
          ))}
        </div>
      </div>
      <svg viewBox={`0 0 ${W} ${H}`} style={{ width: '100%', height: 'auto', display: 'block' }}>
        <path d={fill} fill={GREEN} opacity={0.1} />
        <path d={d} fill="none" stroke={GREEN} strokeWidth={2.5} strokeLinejoin="round" strokeLinecap="round" />
        <circle cx={svgPts[svgPts.length-1][0]} cy={svgPts[svgPts.length-1][1]} r={4} fill={GREEN} stroke="#fff" strokeWidth={2} />
      </svg>
    </div>
  )
}

function EdgeMockup() {
  return (
    <div style={{ background: '#fff', border: '1px solid #E5E7EB', borderRadius: 14, padding: '20px', boxShadow: '0 4px 24px rgba(0,0,0,0.08)', maxWidth: 340, width: '100%' }}>
      <div style={{ fontSize: 11, color: '#9CA3AF', fontWeight: 700, textTransform: 'uppercase', letterSpacing: '0.5px', marginBottom: 14 }}>RTT Edge vs Market</div>
      {[{ player: 'C. Alcaraz', rtt: 68, mkt: 58, edge: '+10.0%' }, { player: 'J. Sinner', rtt: 72, mkt: 65, edge: '+7.0%' }, { player: 'H. Hurkacz', rtt: 61, mkt: 56, edge: '+5.0%' }].map((r, i) => (
        <div key={i} style={{ marginBottom: 14 }}>
          <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: 5, alignItems: 'center' }}>
            <span style={{ fontSize: 14, fontWeight: 600 }}>{r.player}</span>
            <span style={{ fontSize: 13, fontWeight: 800, color: GREEN, background: '#DCFCE7', padding: '2px 8px', borderRadius: 20 }}>{r.edge}</span>
          </div>
          {[{ label: 'RTT', val: r.rtt, color: GREEN }, { label: 'Mkt', val: r.mkt, color: '#D1D5DB' }].map(bar => (
            <div key={bar.label} style={{ display: 'flex', gap: 6, alignItems: 'center', marginTop: 3 }}>
              <span style={{ fontSize: 11, color: '#9CA3AF', width: 28, textAlign: 'right' }}>{bar.label}</span>
              <div style={{ flex: 1, height: 6, background: '#F3F4F6', borderRadius: 99 }}>
                <div style={{ width: `${bar.val}%`, height: '100%', background: bar.color, borderRadius: 99 }} />
              </div>
              <span style={{ fontSize: 11, fontWeight: 700, color: bar.color === GREEN ? GREEN : '#9CA3AF', width: 28 }}>{bar.val}%</span>
            </div>
          ))}
        </div>
      ))}
    </div>
  )
}

function FeatureSection({ title, sub, children, mockup, flip = false, accent = false }) {
  return (
    <section style={{ padding: '64px 24px', background: accent ? '#F0FDF4' : '#fff', borderTop: '1px solid #F3F4F6' }}>
      <div style={{ maxWidth: 1100, margin: '0 auto', display: 'flex', gap: 56, alignItems: 'center', flexWrap: 'wrap', flexDirection: flip ? 'row-reverse' : 'row' }}>
        <div style={{ flex: '1 1 320px', minWidth: 280 }}>
          <h2 style={{ fontSize: 28, fontWeight: 900, margin: '0 0 10px', letterSpacing: '-0.6px', lineHeight: 1.2, color: accent ? GREEN_DARK : '#111827' }}>{title}</h2>
          <p style={{ fontSize: 16, color: '#6B7280', margin: '0 0 28px', lineHeight: 1.7 }}>{sub}</p>
          <div style={{ display: 'flex', flexDirection: 'column', gap: 20 }}>{children}</div>
        </div>
        <div style={{ flex: '1 1 300px', display: 'flex', justifyContent: 'center' }}>{mockup}</div>
      </div>
    </section>
  )
}

export default function JoinPage() {
  const { isLoggedIn } = useAuth()
  const [showAuth, setShowAuth] = useState(false)

  function handleCTA() {
    if (isLoggedIn) { window.location.href = '/' } else { setShowAuth(true) }
  }

  return (
    <div style={{ fontFamily: "'DM Sans', system-ui, -apple-system, sans-serif" }}>

      {/* HERO */}
      <section style={{ position: 'relative', overflow: 'hidden', background: GREEN_DARK, paddingBottom: 0 }}>
        <div style={{ position: 'absolute', inset: 0, backgroundImage: `url(${courtHardImg})`, backgroundSize: 'cover', backgroundPosition: 'center 40%', opacity: 0.18 }} />
        <div style={{ position: 'absolute', bottom: -1, left: 0, right: 0, height: 80, background: '#fff', clipPath: 'polygon(0 100%, 100% 0, 100% 100%)', zIndex: 1 }} />
        <div style={{ position: 'relative', zIndex: 2, maxWidth: 900, margin: '0 auto', padding: '80px 24px 100px', textAlign: 'center' }}>
          <div style={{ marginBottom: 20 }}><FreePill /></div>
          <h1 style={{ fontSize: 'clamp(36px, 7vw, 62px)', fontWeight: 900, color: WHITE, margin: '0 0 20px', letterSpacing: '-1.5px', lineHeight: 1.05 }}>
            Smarter tennis betting,<br /><span style={{ color: '#86EFAC' }}>completely free</span>
          </h1>
          <p style={{ fontSize: 18, color: 'rgba(255,255,255,0.82)', maxWidth: 580, margin: '0 auto 36px', lineHeight: 1.7 }}>
            ratethat.tennis uses machine learning to find value bets before the bookmakers do. Daily predictions, your own picks tracker, P&L analysis, and the RTT edge — all free, forever.
          </p>
          <div style={{ display: 'flex', gap: 16, justifyContent: 'center', flexWrap: 'wrap', marginBottom: 40 }}>
            {[{ v: '66.5%', l: 'Prediction accuracy' }, { v: '+5pp', l: 'Edge over market' }, { v: '56', l: 'ML features per match' }, { v: '£0', l: 'Cost to join' }].map(s => (
              <div key={s.l} style={{ background: 'rgba(255,255,255,0.1)', border: '1px solid rgba(255,255,255,0.15)', borderRadius: 10, padding: '12px 20px', textAlign: 'center' }}>
                <div style={{ fontSize: 24, fontWeight: 900, color: '#86EFAC', fontVariantNumeric: 'tabular-nums' }}>{s.v}</div>
                <div style={{ fontSize: 11, color: 'rgba(255,255,255,0.6)', fontWeight: 600, textTransform: 'uppercase', letterSpacing: '0.4px', marginTop: 2 }}>{s.l}</div>
              </div>
            ))}
          </div>
          <div style={{ display: 'flex', gap: 12, justifyContent: 'center', flexWrap: 'wrap' }}>
            <button onClick={handleCTA} style={{ padding: '15px 36px', borderRadius: 10, background: '#16A34A', color: WHITE, fontSize: 17, fontWeight: 800, boxShadow: '0 4px 20px rgba(22,163,74,0.4)' }}>
              {isLoggedIn ? 'Go to matches →' : 'Join for free →'}
            </button>
            <Link to="/" style={{ padding: '15px 28px', borderRadius: 10, background: 'rgba(255,255,255,0.12)', border: '1px solid rgba(255,255,255,0.2)', color: WHITE, fontSize: 15, fontWeight: 600, textDecoration: 'none' }}>
              See today's matches
            </Link>
          </div>
          <p style={{ color: 'rgba(255,255,255,0.5)', fontSize: 13, marginTop: 16 }}>No credit card. No subscription. Just better tennis bets.</p>
        </div>
      </section>

      <FeatureSection title="Predictions in your inbox, every day" sub="Our ML model runs every morning and surfaces the day's best value opportunities. Get them delivered straight to your email — or browse the full card on site." mockup={<MatchCardMockup />}>
        <FeatureRow icon="📧" title="Daily predictions email" desc="Wake up to RTT's top picks with win probabilities, edge over market, and recommended odds — all calculated overnight." />
        <FeatureRow icon="📊" title="Win probability for every match" desc="Every match on the ATP & WTA Tour gets a machine-learning win probability updated daily based on 56 features." />
        <FeatureRow icon="🎾" title="Surface-specific analysis" desc="Clay-court Alcaraz and hard-court Alcaraz are completely different bets. Our model treats them that way." />
      </FeatureSection>

      <FeatureSection title="Track your picks & your P&L" sub="Star any player on any match to add them to My Picks. We track results automatically, calculate your cumulative P&L, and show you exactly where you're winning and losing." mockup={<PLMockup />} flip accent>
        <FeatureRow icon="★" title="One-tap pick tracking" desc="Hit the star icon next to any player and they're saved to your My Picks board instantly." />
        <FeatureRow icon="💰" title="Automatic P&L calculation" desc="Using a £1 × confidence stars staking model, we track your running profit and loss as results come in." />
        <FeatureRow icon="📈" title="Know where you're strongest" desc="Breakdown by surface, tournament level, and confidence rating — so you can focus on the bets you're actually good at." />
      </FeatureSection>

      {/* RTT Edge section */}
      <section style={{ padding: '72px 24px', background: GREEN_DARK, position: 'relative', overflow: 'hidden' }}>
        <div style={{ position: 'absolute', top: -1, left: 0, right: 0, height: 80, background: '#F0FDF4', clipPath: 'polygon(0 0, 100% 100%, 0 100%)', zIndex: 1 }} />
        <div style={{ position: 'absolute', bottom: -1, left: 0, right: 0, height: 80, background: '#fff', clipPath: 'polygon(0 100%, 100% 0, 100% 100%)', zIndex: 1 }} />
        <div style={{ position: 'absolute', inset: 0, backgroundImage: `url(${courtClayImg})`, backgroundSize: 'cover', backgroundPosition: 'center', opacity: 0.1 }} />
        <div style={{ position: 'relative', zIndex: 2, maxWidth: 1100, margin: '0 auto', display: 'flex', gap: 56, alignItems: 'center', flexWrap: 'wrap', paddingTop: 40, paddingBottom: 40 }}>
          <div style={{ flex: '1 1 320px', color: WHITE }}>
            <div style={{ display: 'inline-block', background: '#86EFAC', color: GREEN_DARK, padding: '4px 12px', borderRadius: 20, fontSize: 12, fontWeight: 800, marginBottom: 16, letterSpacing: 0.5 }}>THE RTT EDGE</div>
            <h2 style={{ fontSize: 32, fontWeight: 900, margin: '0 0 16px', letterSpacing: '-0.7px', lineHeight: 1.2, color: WHITE }}>See exactly where the bookmakers are wrong</h2>
            <p style={{ fontSize: 16, color: 'rgba(255,255,255,0.8)', margin: '0 0 28px', lineHeight: 1.7 }}>The RTT Edge shows you the gap between our model's win probability and the bookmaker's implied probability. When our number is higher, you've found a value bet the market has missed.</p>
            <div style={{ display: 'flex', flexDirection: 'column', gap: 16 }}>
              {[
                { icon: '🎯', t: 'Model-first, not data-dump', d: 'Every competitor shows stats and leaves the conclusion to you. We answer "is there value here?" upfront.' },
                { icon: '🔬', t: 'XGBoost + LightGBM ensemble', d: '66.5% prediction accuracy and +5pp edge over market Elo in 10-year walk-forward backtests.' },
                { icon: '⚡', t: 'Updated daily', d: "Odds and predictions refresh automatically every morning so you're always working with the freshest numbers." },
              ].map(f => (
                <div key={f.t} style={{ display: 'flex', gap: 14, alignItems: 'flex-start' }}>
                  <div style={{ width: 38, height: 38, borderRadius: 10, background: 'rgba(134,239,172,0.15)', border: '1px solid rgba(134,239,172,0.3)', display: 'flex', alignItems: 'center', justifyContent: 'center', fontSize: 18, flexShrink: 0 }}>{f.icon}</div>
                  <div>
                    <div style={{ fontWeight: 700, fontSize: 15, color: WHITE, marginBottom: 2 }}>{f.t}</div>
                    <div style={{ fontSize: 13, color: 'rgba(255,255,255,0.65)', lineHeight: 1.6 }}>{f.d}</div>
                  </div>
                </div>
              ))}
            </div>
          </div>
          <div style={{ flex: '1 1 300px', display: 'flex', justifyContent: 'center' }}><EdgeMockup /></div>
        </div>
      </section>

      {/* Free callout */}
      <section style={{ padding: '72px 24px', background: '#F9FAFB', borderTop: '1px solid #F3F4F6', textAlign: 'center' }}>
        <div style={{ maxWidth: 620, margin: '0 auto' }}>
          <div style={{ display: 'inline-block', background: '#DCFCE7', color: GREEN_DARK, padding: '6px 18px', borderRadius: 999, fontSize: 14, fontWeight: 800, marginBottom: 20, letterSpacing: 0.3 }}>100% FREE — ALWAYS</div>
          <h2 style={{ fontSize: 32, fontWeight: 900, margin: '0 0 16px', letterSpacing: '-0.7px' }}>Everything is free.<br />No catches.</h2>
          <p style={{ fontSize: 16, color: '#6B7280', margin: '0 auto 36px', lineHeight: 1.7, maxWidth: 520 }}>
            ratethat.tennis will always be free to use. We believe the edge should be available to everyone, not just those who can afford expensive subscriptions.
          </p>
          <div style={{ display: 'flex', gap: 12, justifyContent: 'center', flexWrap: 'wrap', marginBottom: 32 }}>
            {['✓  Daily predictions', '✓  RTT Edge vs market', '✓  My Picks tracker', '✓  P&L analytics', '✓  Player ratings', '✓  Email digests'].map(f => (
              <span key={f} style={{ background: '#fff', border: '1px solid #E5E7EB', borderRadius: 8, padding: '8px 14px', fontSize: 14, fontWeight: 600, color: '#374151' }}>{f}</span>
            ))}
          </div>
          <button onClick={handleCTA} style={{ padding: '16px 44px', borderRadius: 10, background: GREEN, color: WHITE, fontSize: 17, fontWeight: 800, boxShadow: '0 4px 20px rgba(22,163,74,0.35)' }}>
            {isLoggedIn ? 'Go to matches →' : 'Create your free account →'}
          </button>
          <p style={{ color: '#9CA3AF', fontSize: 13, marginTop: 12 }}>Takes 30 seconds. No credit card needed.</p>
        </div>
      </section>

      <footer style={{ background: GREEN_DARK, color: 'rgba(255,255,255,0.6)', padding: '32px 24px', textAlign: 'center', fontSize: 13 }}>
        <Link to="/" style={{ color: WHITE, fontWeight: 700, fontSize: 16, textDecoration: 'none' }}>ratethat.tennis</Link>
        <p style={{ margin: '8px 0 0' }}>ML-powered tennis predictions & betting intelligence.<br />Free forever · No ads · No subscription</p>
      </footer>

      {showAuth && <AuthModal onClose={() => setShowAuth(false)} />}
    </div>
  )
}
