import { apiFetch } from '../../../../lib/api'
import PlayerPageClient from '../../../../components/pages/PlayerPageClient'
import { notFound } from 'next/navigation'
import Script from 'next/script'

export const revalidate = 86400

export async function generateMetadata({ params }) {
  const raw = await apiFetch(`/api/v1/players/${params.id}`, { revalidate: 86400 })
  if (!raw) return { title: 'Player | RateThatTennis' }
  const name = raw.player?.full_name || raw.player?.name || 'Player'
  const rtt = raw.ratings?.rtt_score ? ` RTT ${Math.round(raw.ratings.rtt_score)}.` : ''
  const rank = raw.player?.ranking ? ` Ranked #${raw.player.ranking}.` : ''
  const title = `${name} — Tennis Stats, Form & Predictions`
  const description = `${name} tennis stats, RTT player rating, form, H2H record and ML predictions.${rtt}${rank} Free betting intelligence.`
  const canonical = `https://ratethat.tennis/player/${params.id}`
  return {
    title,
    description,
    alternates: { canonical },
    openGraph: { title, description, url: canonical },
  }
}

export default async function PlayerDetailPage({ params }) {
  const player = await apiFetch(`/api/v1/players/${params.id}`, { revalidate: 86400 })
  if (!player) notFound()
  const jsonLd = {
    '@context': 'https://schema.org',
    '@type': 'Person',
    name: player.name || '',
    nationality: player.country || '',
    url: `https://ratethat.tennis/player/${params.id}`,
  }
  return (
    <>
      <Script id="player-jsonld" type="application/ld+json"
        dangerouslySetInnerHTML={{ __html: JSON.stringify(jsonLd) }} />
      <PlayerPageClient initialPlayer={player} playerId={params.id} />
    </>
  )
}
