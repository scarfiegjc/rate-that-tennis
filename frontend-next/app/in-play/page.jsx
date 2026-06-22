import InPlayClient from '../../components/pages/InPlayClient'

export const metadata = {
  title: 'Live Tennis Scores & In-Play',
  description: 'Live tennis match scores, in-play updates and real-time win probability. ATP, WTA and Challenger matches updated every 20 seconds.',
  alternates: { canonical: 'https://ratethat.tennis/in-play' },
}

export default function InPlayPage() {
  return <InPlayClient />
}
