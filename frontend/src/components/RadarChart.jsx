import {
  Chart as ChartJS,
  RadialLinearScale,
  PointElement,
  LineElement,
  Filler,
  Tooltip,
  Legend,
} from 'chart.js'
import { Radar } from 'react-chartjs-2'

ChartJS.register(RadialLinearScale, PointElement, LineElement, Filler, Tooltip, Legend)

const AXES = ['Serve', 'Return', 'Pressure', 'Consistency', 'Surface', 'Big match']

function getRatings(ratings, surface) {
  if (!ratings) return [50, 50, 50, 50, 50, 50]
  const surfKey = `${(surface || 'hard').toLowerCase()}_rating`
  return [
    ratings.serve_rating        || 50,
    ratings.return_rating       || 50,
    ratings.pressure_rating     || 50,
    ratings.consistency_rating  || 50,
    ratings[surfKey]            || 50,
    ratings.big_match_rating    || 50,
  ]
}

export default function RadarChart({ p1Ratings, p2Ratings, p1Name, p2Name, surface }) {
  const data = {
    labels: AXES,
    datasets: [
      {
        label: p1Name || 'Player 1',
        data: getRatings(p1Ratings, surface),
        backgroundColor: 'rgba(0,204,122,0.12)',
        borderColor: 'rgba(0,204,122,0.8)',
        borderWidth: 2,
        pointBackgroundColor: 'rgba(0,204,122,0.8)',
        pointRadius: 3,
      },
      {
        label: p2Name || 'Player 2',
        data: getRatings(p2Ratings, surface),
        backgroundColor: 'rgba(56,139,253,0.1)',
        borderColor: 'rgba(56,139,253,0.7)',
        borderWidth: 2,
        pointBackgroundColor: 'rgba(56,139,253,0.7)',
        pointRadius: 3,
      },
    ],
  }

  const options = {
    responsive: true,
    maintainAspectRatio: true,
    scales: {
      r: {
        min: 40,
        max: 100,
        ticks: {
          stepSize: 20,
          color: '#484f58',
          font: { size: 9 },
          backdropColor: 'transparent',
        },
        grid: { color: '#21262d' },
        angleLines: { color: '#21262d' },
        pointLabels: {
          color: '#8b949e',
          font: { size: 11 },
        },
      },
    },
    plugins: {
      legend: {
        position: 'bottom',
        labels: {
          color: '#8b949e',
          font: { size: 11 },
          boxWidth: 12,
          padding: 12,
        },
      },
      tooltip: {
        backgroundColor: '#161b22',
        borderColor: '#30363d',
        borderWidth: 1,
        titleColor: '#e6edf3',
        bodyColor: '#8b949e',
      },
    },
  }

  return (
    <div className="radar-wrapper">
      <Radar data={data} options={options} />
    </div>
  )
}
