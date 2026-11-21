/**
 * The only file in `web/` that knows Tauri exists.
 *
 * Everything else asks these two questions and gets a plain answer, so the
 * Docker build — which has no Tauri anywhere — never imports a thing that
 * cannot resolve. There is deliberately **no npm dependency**: the shell sets
 * `withGlobalTauri: true`, which injects the plugin APIs onto `window.__TAURI__`,
 * so this is a feature detect rather than a bundled module. A missing symbol
 * means "not the desktop app", which is exactly the answer we want in a browser.
 *
 * The grant that makes `open` reachable at all is
 * `desktop/src-tauri/capabilities/remote.json` — the page is served from a
 * loopback origin, which Tauri classifies as remote, and a capability with no
 * `remote.urls` never matches it. That was why the shell's own
 * `pick_vault_folder` command sat unreachable for months.
 */

interface TauriDialog {
  open?: (options: {
    directory?: boolean
    multiple?: boolean
    title?: string
  }) => Promise<string | string[] | null>
}

declare global {
  interface Window {
    __TAURI__?: { dialog?: TauriDialog }
  }
}

/**
 * Can this page open a native folder dialog?
 *
 * Note what this does NOT answer: "am I the desktop app". That question is
 * answered by the API (`desktop_mode` on `GET /api/settings`), because it is
 * the backend that knows which runtime it is. Gate a picker button on both —
 * `desktop_mode && hasNativePicker()` — so that a desktop build where the ACL
 * is somehow wrong degrades to the text input instead of a dead end.
 */
export function hasNativePicker(): boolean {
  try {
    return typeof window !== 'undefined' && typeof window.__TAURI__?.dialog?.open === 'function'
  } catch {
    return false
  }
}

/**
 * Open the native folder picker. Resolves to an absolute path, or `null` when
 * the user cancels or no picker is available.
 *
 * Never throws: a caller has a text input to fall back to, and an exception
 * here would take out the wizard step it was called from.
 */
export async function pickFolder(title?: string): Promise<string | null> {
  const open = window.__TAURI__?.dialog?.open
  if (typeof open !== 'function') return null
  try {
    const picked = await open({ directory: true, multiple: false, title })
    if (typeof picked === 'string') return picked
    // `multiple: false` should never yield an array, but the plugin's type
    // allows one and a silent [0] beats a crash if that ever changes.
    if (Array.isArray(picked)) return picked[0] ?? null
    return null
  } catch {
    return null
  }
}

/**
 * Menu-item ids dispatched by the native macOS menu.
 *
 * The shell does NOT use Tauri's event system for this. The page is a remote
 * origin (`http://127.0.0.1:<port>`), and `core:event:default` — which carries
 * `allow-listen` — lives inside `core:default`, granted to the *local* context
 * only. Listening would mean widening the wildcard grant in
 * `capabilities/remote.json`, which exists to be narrow.
 *
 * So the shell calls `webview.eval` and dispatches a plain `CustomEvent`
 * instead. `eval` is a host-side API with no capability check — the ACL
 * governs what the page may invoke, not what the shell injects into it. Zero
 * new permissions, and in the Docker build the event simply never fires.
 *
 * Returns an unsubscribe function.
 */
export function onNativeMenu(handler: (id: string) => void): () => void {
  function listener(e: Event) {
    const id = (e as CustomEvent<string>).detail
    if (typeof id === 'string') handler(id)
  }
  window.addEventListener(NATIVE_MENU_EVENT, listener)
  return () => window.removeEventListener(NATIVE_MENU_EVENT, listener)
}

/** Kept in one place because Rust spells it too — see desktop/src-tauri/src/menu.rs. */
export const NATIVE_MENU_EVENT = 'pillar43:menu'
