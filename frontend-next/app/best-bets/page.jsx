import BestBetsClient from '../../components/pages/BestBetsClient'

export const metadata = {
  title: 'Best Bets — Tennis Value Betting Tips',
  description: 'Matches where our ML model identifies positive edge vs bookmaker odds. Free tennis betting tips.',
  alternates: { canonical: 'https://ratethat.tennis/best-bets' },
}

export default function BestBetsPage() {
  return <BestBetsClient />
}
