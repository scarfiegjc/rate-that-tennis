import PlayerDatabaseClient from '../../components/pages/PlayerDatabaseClient'

export const metadata = {
  title: 'Player Database — ATP & WTA Tennis Player Ratings',
  description: 'Browse RTT ratings for all active ATP and WTA tennis players. Filter by country, surface and ranking.',
  alternates: { canonical: 'https://ratethat.tennis/players' },
}

export default function PlayersPage() {
  return <PlayerDatabaseClient />
}
