import { useEffect } from 'react'

const DEFAULT_TITLE = 'RateThatTennis - Tennis Predictions, Analytics & Tips - Machine Learning for Tennis. Always free.'
const DEFAULT_DESC  = 'Free ML-powered tennis predictions, player ratings and betting intelligence. Win probabilities, RTT ratings, bookmaker odds and edge for every ATP, WTA and Challenger match.'

/**
 * useSEO — lightweight hook for per-page SEO signals.
 * Sets document.title, meta description, canonical URL, and injects
 * a page-specific JSON-LD <script> that is cleaned up on unmount.
 *
 * @param {Object} opts
 * @param {string}  opts.title       — full page title (include brand suffix)
 * @param {string}  [opts.description]
 * @param {string}  [opts.canonical] — absolute URL
 * @param {Object}  [opts.jsonLd]    — schema.org object to inject
 */
export function useSEO({ title, description, canonical, jsonLd } = {}) {
  useEffect(() => {
    const prevTitle = document.title

    // ── Title ─────────────────────────────────────────────────────────────
    if (title) document.title = title

    // ── Meta description ──────────────────────────────────────────────────
    let descEl = document.querySelector('meta[name="description"]')
    const prevDesc = descEl?.content || ''
    if (description) {
      if (!descEl) {
        descEl = document.createElement('meta')
        descEl.name = 'description'
        document.head.appendChild(descEl)
      }
      descEl.content = description
    }

    // ── OG title / description ────────────────────────────────────────────
    let ogTitle = document.querySelector('meta[property="og:title"]')
    let ogDesc  = document.querySelector('meta[property="og:description"]')
    const prevOgTitle = ogTitle?.content || ''
    const prevOgDesc  = ogDesc?.content  || ''
    if (title && ogTitle)       ogTitle.content = title
    if (description && ogDesc)  ogDesc.content  = description

    // ── Canonical ─────────────────────────────────────────────────────────
    let canonEl = document.querySelector('link[rel="canonical"]')
    const prevCanon = canonEl?.href || ''
    if (canonical) {
      if (!canonEl) {
        canonEl = document.createElement('link')
        canonEl.rel = 'canonical'
        document.head.appendChild(canonEl)
      }
      canonEl.href = canonical
    }

    // ── JSON-LD ───────────────────────────────────────────────────────────
    const ldId = 'rtt-page-jsonld'
    let ldEl = document.getElementById(ldId)
    if (jsonLd) {
      if (!ldEl) {
        ldEl = document.createElement('script')
        ldEl.id   = ldId
        ldEl.type = 'application/ld+json'
        document.head.appendChild(ldEl)
      }
      ldEl.textContent = JSON.stringify(jsonLd)
    }

    // ── Cleanup ───────────────────────────────────────────────────────────
    return () => {
      document.title = prevTitle || DEFAULT_TITLE
      if (descEl && prevDesc)     descEl.content = prevDesc
      if (descEl && !prevDesc)    descEl.content = DEFAULT_DESC
      if (ogTitle && prevOgTitle) ogTitle.content = prevOgTitle
      if (ogDesc  && prevOgDesc)  ogDesc.content  = prevOgDesc
      if (canonEl) canonEl.href = prevCanon || 'https://ratethat.tennis/'
      const ldScript = document.getElementById(ldId)
      if (ldScript) ldScript.remove()
    }
  }, [title, description, canonical, jsonLd])
}
