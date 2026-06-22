import { apiFetch } from '../../../../lib/api'
import MatchDetailClient from '../../../../components/pages/MatchDetailClient'
import { notFound } from 'next/navigation'
import Script from 'next/script'

export async function generateMetadata({ params }) {
  const match = await apiFetch(`/api/v1/matches/${params.id}`)
  if (!match) return { title: 'Match | RateThatTennis' }
  const p1 = match.first_player?.name || match.players?.first?.name || 'Player 1'
  const p2 = match.second_player?.name || match.players?.second?.name || 'Player 2'
  const tournament = match.tournament || ''
  const date = match.event_date
    ? new Date(match.event_date + 'T12:00:00Z').toLocaleDateString('en-GB', { day: 'numeric', month: 'short', year: 'numeric' })
    : ''
  const title = `${p1} vs ${p2} — ${tournament}${date ? ` ${date}` : ''}`
  const description = `ML prediction, RTT ratings and bookmaker odds for ${p1} vs ${p2} at ${tournament}. Free tennis betting intelligence.`
  const canonical = `https://ratethat.tennis/match/${params.id}`
  return {
    title,
    description,
    alternates: { canonical },
    openGraph: { title, description, url: canonical, type: 'article' },
  }
}

export default async function MatchDetailPage({ params }) {
  const raw = await apiFetch(`/api/v1/matches/${params.id}`)
  if (!raw) notFound()

  // Normalise into the shape MatchDetailClient expects
  const p1 = raw.players?.first || raw.first_player || {}
  const p2 = raw.players?.second || raw.second_player || {}
  const pred = raw.prediction || {}
  const mkt = raw.market || {}
  const edge = raw.edge || {}

  const match = {
    ...raw.match,
    ...raw,
    first_player: { ...p1, player_id: p1.id, logo_url: p1.logo_url || null },
    second_player: { ...p2, player_id: p2.id, logo_url: p2.logo_url || null },
    prediction: { ...pred, edge_first: edge.p1, edge_second: edge.p2 },
    market: {
      odds_first_player: mkt.p1?.decimal_odds,
      odds_second_player: mkt.p2?.decimal_odds,
      bookmaker: mkt.p1?.bookmaker || mkt.p2?.bookmaker,
      all_bookmakers: mkt.all_bookmakers || [],
      bresbet_link: mkt.bresbet_link || null,
      cloudbet_link: mkt.cloudbet_link || null,
      cloudbet_markets: mkt.cloudbet_markets || null,
    },
    edge,
  }

  const jsonLd = {
    '@context': 'https://schema.org',
    '@type': 'SportsEvent',
    name: `${p1.name || 'Player 1'} vs ${p2.name || 'Player 2'}`,
    startDate: match.event_date,
    location: { '@type': 'Place', name: match.tournament || '' },
    sport: 'Tennis',
    competitor: [
      { '@type': 'Person', name: p1.name || '' },
      { '@type': 'Person', name: p2.name || '' },
    ],
    url: `https://ratethat.tennis/match/${params.id}`,
  }

  return (
    <>
      <Script id="match-jsonld" type="application/ld+json"
        dangerouslySetInnerHTML={{ __html: JSON.stringify(jsonLd) }} />
      <MatchDetailClient initialMatch={match} matchId={params.id} />
    </>
  )
}
