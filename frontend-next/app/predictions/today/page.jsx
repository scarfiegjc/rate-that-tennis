import PredictionsTodayClient from '../../../components/pages/PredictionsTodayClient'

export const metadata = {
  title: "Today's Predictions",
  description: "Today's ML tennis predictions with win probabilities and edge vs market.",
}

export default function PredictionsTodayPage() {
  return <PredictionsTodayClient />
}
