import {
  Chart as ChartJS,
  CategoryScale,
  LinearScale,
  PointElement,
  LineElement,
  Tooltip,
  Legend,
  Filler,
} from 'chart.js'
import { Line } from 'react-chartjs-2'

ChartJS.register(CategoryScale, LinearScale, PointElement, LineElement, Tooltip, Legend, Filler)

export default function FormChart({ p1Form, p2Form, p1Name, p2Name }) {
  const p1 = p1Form?.matches || []
  const p2 = p2Form?.matches || []

  // Build a common label set (indices)
  const maxLen = Math.max(p1.length, p2.length, 1)
  const labels = Array.from({ length: maxLen }, (_, i) => `M${i + 1}`)

  const data = {
    labels,
    datasets: [
      {
        label: p1Name || 'Player 1',
        data: p1.map(m => m.performance_index),
        borderColor: 'rgba(0,204,122,0.8)',
        backgroundColor: 'rgba(0,204,122,0.06)',
        borderWidth: 2,
        pointRadius: 4,
        pointBackgroundColor: p1.map(m =>
          m.won ? 'rgba(0,204,122,0.9)' : 'rgba(248,81,73,0.7)'
        ),
        tension: 0.3,
        fill: false,
      },
      {
        label: p2Name || 'Player 2',
        data: p2.map(m => m.performance_index),
        borderColor: 'rgba(56,139,253,0.7)',
        backgroundColor: 'rgba(56,139,253,0.05)',
        borderWidth: 2,
        pointRadius: 4,
        pointBackgroundColor: p2.map(m =>
          m.won ? 'rgba(56,139,253,0.9)' : 'rgba(248,81,73,0.7)'
        ),
        tension: 0.3,
        fill: false,
      },
    ],
  }

  const options = {
    responsive: true,
    maintainAspectRatio: false,
    scales: {
      x: {
        grid: { color: '#21262d' },
        ticks: { color: '#484f58', font: { size: 10 } },
      },
      y: {
        min: 0,
        max: 100,
        grid: { color: '#21262d' },
        ticks: { color: '#484f58', font: { size: 10 } },
      },
    },
    plugins: {
      legend: {
        position: 'bottom',
        labels: { color: '#8b949e', font: { size: 11 }, boxWidth: 12, padding: 12 },
      },
      tooltip: {
        backgroundColor: '#161b22',
        borderColor: '#30363d',
        borderWidth: 1,
        titleColor: '#e6edf3',
        bodyColor: '#8b949e',
        callbacks: {
          title: ([item]) => {
            const arr = item.datasetIndex === 0 ? p1 : p2
            const m = arr[item.dataIndex]
            return m ? `${m.opponent_name || ''} · ${m.surface || ''}` : `Match ${item.dataIndex + 1}`
          },
          label: (item) => {
            const arr = item.datasetIndex === 0 ? p1 : p2
            const m = arr[item.dataIndex]
            return `Performance: ${item.raw?.toFixed(1)} (${m?.won ? 'W' : 'L'})`
          },
        },
      },
    },
  }

  if (p1.length === 0 && p2.length === 0) {
    return <div className="loading">No form data available</div>
  }

  return (
    <div style={{ height: 260 }}>
      <Line data={data} options={options} />
    </div>
  )
}
