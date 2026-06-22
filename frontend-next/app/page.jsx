import { apiFetch } from '../lib/api'
import MatchListClient from '../components/pages/MatchListClient'

export const metadata = {
  title: 'Tennis Predictions & Betting Tips Today',
  description: 'ML-powered win probabilities, RTT ratings and bookmaker edge for every ATP, WTA and Challenger match today. Free.',
  alternates: { canonical: 'https://ratethat.tennis/' },
}

export default async function HomePage() {
  const data = await apiFetch('/api/v1/matches/today')
  const matches = Array.isArray(data) ? data : data?.matches || []
  return <MatchListClient initialMatches={matches} />
}
