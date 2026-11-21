/**
 * Settings and configuration API client.
 *
 * Covers: app settings, library health, voice profile, notifications.
 *
 * The `appSettings` / `updateSettings` shapes are NOT hand-typed — they
 * import from `./_generated` (produced by `./scripts/codegen-types` from
 * the FastAPI OpenAPI schema). To change the shape: edit the Pydantic
 * model in `api/routes/settings.py:SettingsResponse` / `SettingsUpdate`,
 * then run `npm run codegen`.
 */

import { req } from './_fetch'
import type { components } from './_generated'

type SettingsResponse = components['schemas']['SettingsResponse']
type SettingsUpdateBody = components['schemas']['SettingsUpdate']

/**
 * `/api/library/status`. Hand-typed because the route returns a bare dict
 * rather than a Pydantic model, so codegen leaves it `unknown`.
 *
 * `setup_complete` is the wizard gate. `notes.git_ready` is a different
 * question — "is the workspace initialized" — and the two diverge after a soft
 * reset, which keeps notes/.git.
 */
export interface LibraryStatus {
  setup_complete: boolean
  notes: { exists: boolean; writable: boolean; git_ready: boolean; file_count: number }
  generated: { exists: boolean; writable: boolean; file_count: number }
  library: { exists: boolean; file_count: number }
  extra_libraries: Record<string, { exists: boolean; file_count: number }>
}

export const settingsApi = {
  // ── App Settings ─────────────────────────────────────────────────────────

  appSettings: () => req<SettingsResponse>('/api/settings'),

  updateSettings: (updates: SettingsUpdateBody) =>
    req<SettingsResponse>('/api/settings', {
      method: 'POST',
      body: JSON.stringify(updates),
    }),

  // ── Voice Profile ────────────────────────────────────────────────────────

  rebuildVoiceProfile: () =>
    req<{ path: string; authored_file_count: number; word_count: number }>('/api/catalog/voice-profile', {
      method: 'POST',
    }),

  // ── Library Health ───────────────────────────────────────────────────────

  libraryStatus: () =>
    req<LibraryStatus>('/api/library/status'),

  initLibrary: () =>
    req<LibraryStatus>('/api/library/init', { method: 'POST' }),

  // ── Notifications ────────────────────────────────────────────────────────

  notificationSettings: () =>
    req<{
      notifications_enabled: boolean
      notify_email_to: string
      smtp_host: string
      smtp_port: number
      smtp_user: string
      smtp_from: string
      telegram_bot_token: string   // masked
      telegram_chat_id: string
      smtp_pass_set: boolean
      telegram_token_set: boolean
    }>('/api/notifications'),

  updateNotificationSettings: (updates: {
    notifications_enabled?: boolean
    notify_email_to?: string
    smtp_host?: string
    smtp_port?: number
    smtp_user?: string
    smtp_pass?: string
    smtp_from?: string
    telegram_bot_token?: string
    telegram_chat_id?: string
  }) =>
    req<{
      notifications_enabled: boolean
      notify_email_to: string
      smtp_host: string
      smtp_port: number
      smtp_user: string
      smtp_from: string
      telegram_bot_token: string
      telegram_chat_id: string
      smtp_pass_set: boolean
      telegram_token_set: boolean
    }>('/api/notifications', {
      method: 'POST',
      body: JSON.stringify(updates),
    }),

  testNotification: (channel: 'email' | 'telegram') =>
    req<{ ok: boolean; channel: string; to?: string; chat_id?: string }>('/api/notifications/test', {
      method: 'POST',
      body: JSON.stringify({ channel }),
    }),

  // ── Path Management ──────────────────────────────────────────────────────

  stagePathChange: (mount: string, hostPath: string) =>
    req<{
      status: string
      pending: Record<string, string>
      restart_command: string
    }>('/api/settings/stage-path', {
      method: 'POST',
      body: JSON.stringify({ mount, host_path: hostPath }),
    }),

  /**
   * Point a core mount at a new folder and make it true (native app only).
   *
   * Distinct from `stagePathChange`, which only records an intention. Under
   * Docker this answers 409 — there the path is a bind mount and nothing the
   * app can do changes it. Before the vault is initialised `applied` comes
   * back true and no restart is needed, which is what lets the first-run
   * wizard just work.
   */
  applyPath: (mount: string, hostPath: string) =>
    req<{
      applied: boolean
      restart_required: boolean
      mount: string
      host_path: string
      reindex_required: boolean
      message: string
    }>('/api/settings/apply-path', {
      method: 'POST',
      body: JSON.stringify({ mount, host_path: hostPath }),
    }),

  clearPendingPaths: () =>
    req<{ status: string; pending: Record<string, string> }>('/api/settings/clear-pending-paths', {
      method: 'POST',
    }),

  removeLibrary: (mount: string) =>
    req<{
      status: string
      pending: Record<string, string>
      pending_removals: string[]
      restart_command: string
    }>('/api/settings/remove-library', {
      method: 'POST',
      body: JSON.stringify({ mount, host_path: '' }),
    }),
}
