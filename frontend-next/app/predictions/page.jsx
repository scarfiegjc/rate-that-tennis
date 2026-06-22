import PredictionsResultsClient from '../../components/pages/PredictionsResultsClient'

export const metadata = {
  title: 'Predictions Results & Tracker',
  description: 'Track RTT model prediction accuracy, win rates and P&L over time.',
  alternates: { canonical: 'https://ratethat.tennis/predictions' },
}

export default function PredictionsPage() {
  return <PredictionsResultsClient />
}
