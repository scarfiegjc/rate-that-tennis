import './globals.css'
import Script from 'next/script'
import { AuthProvider } from '../contexts/AuthContext'
import Header from '../components/Header'

export const metadata = {
  title: {
    default: 'RateThatTennis — Free ML Tennis Predictions & Analytics',
    template: '%s | RateThatTennis',
  },
  description: 'Free ML-powered tennis predictions, player ratings and betting intelligence. Win probabilities, RTT ratings, bookmaker odds and edge for every ATP, WTA and Challenger match.',
  metadataBase: new URL('https://ratethat.tennis'),
  openGraph: {
    siteName: 'RateThatTennis',
    type: 'website',
    images: [{ url: '/og-image.png', width: 1200, height: 630 }],
  },
  twitter: {
    card: 'summary_large_image',
    site: '@ratethattennis',
  },
  robots: {
    index: true,
    follow: true,
    googleBot: { index: true, follow: true, 'max-snippet': -1, 'max-image-preview': 'large' },
  },
}

export default function RootLayout({ children }) {
  return (
    <html lang="en">
      <body>
        <Script src="https://www.googletagmanager.com/gtag/js?id=G-W2J9P0XWH7" strategy="afterInteractive" />
        <Script id="gtag-init" strategy="afterInteractive">{`
          window.dataLayer = window.dataLayer || [];
          function gtag(){dataLayer.push(arguments);}
          gtag('js', new Date());
          gtag('config', 'G-W2J9P0XWH7');
        `}</Script>
        <AuthProvider>
          <Header />
          <main>{children}</main>
        </AuthProvider>
      </body>
    </html>
  )
}
