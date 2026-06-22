import InPlayClient from '../../components/pages/InPlayClient'

export const metadata = {
  title: 'Live Tennis Scores — In-Play Matches',
  description: 'Live tennis scores with in-play win probabilities, serve stats and match intelligence. Updated every 30 seconds.',
  alternates: { canonical: 'https://ratethat.tennis/in-play' },
}

export default function InPlayPage() {
  return <InPlayClient />
}
