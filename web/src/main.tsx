// Inter, bundled rather than fetched from fonts.googleapis.com. The package
// was already a dependency but never imported, so every load went to Google —
// which fails outright with no network and is a needless third-party request
// for a local-first app. Must be imported before App so the @font-face rules
// precede the component styles that use them.
import '@fontsource-variable/inter'

import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import App from './App.tsx'

// Build stamp — inspect from DevTools as `__PILLAR43_BUILD__`.
const build = { sha: __PILLAR43_SHA__, builtAt: __PILLAR43_BUILT_AT__ }
window.__PILLAR43_BUILD__ = build
console.info(`[pillar43] web build ${build.sha} (${build.builtAt})`)

createRoot(document.getElementById('root')!).render(
  <StrictMode>
    <App />
  </StrictMode>,
)
