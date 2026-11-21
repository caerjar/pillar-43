/// <reference types="vite/client" />

// Build-time stamps injected via vite.config.ts `define`.
declare const __PILLAR43_SHA__: string
declare const __PILLAR43_BUILT_AT__: string

interface Window {
  __PILLAR43_BUILD__?: { sha: string; builtAt: string }
}
