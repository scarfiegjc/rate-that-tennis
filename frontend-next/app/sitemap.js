export default function sitemap() {
  const base = 'https://ratethat.tennis'
  return [
    { url: base, changeFrequency: 'hourly', priority: 1.0, lastModified: new Date() },
    { url: `${base}/players`, changeFrequency: 'daily', priority: 0.8, lastModified: new Date() },
    { url: `${base}/best-bets`, changeFrequency: 'hourly', priority: 0.9, lastModified: new Date() },
    { url: `${base}/predictions`, changeFrequency: 'daily', priority: 0.7, lastModified: new Date() },
    { url: `${base}/in-play`, changeFrequency: 'always', priority: 0.8, lastModified: new Date() },
  ]
}
