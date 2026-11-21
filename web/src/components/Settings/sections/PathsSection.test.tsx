/**
 * The pending-paths banner, and which runtime it thinks it is talking to.
 *
 * This branch used to read `restartCommand ? docker : desktop`, which answers
 * "which runtime is this" by accident and got it wrong in a way nobody hit
 * while testing: `restartCommand` is state seeded empty and only filled by a
 * stage call in THIS session, so a Docker user who reopened Settings with a
 * pending change from a previous session was told to quit and reopen the app —
 * advice that does nothing to a container.
 *
 * It now reads `desktop_mode` off the settings payload, which is the backend
 * stating a fact rather than the UI inferring one. These tests pin both
 * directions, because a branch with two plausible-looking outcomes is exactly
 * the kind that silently flips back.
 */
import { describe, it, expect, vi } from 'vitest'
import { render, screen } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { PathsSection } from './PathsSection'

vi.mock('../../../lib/api', () => ({
  api: {
    stagePathChange: vi.fn(),
    clearPendingPaths: vi.fn(),
    removeLibrary: vi.fn(),
  },
}))

type Settings = Parameters<typeof PathsSection>[0]['s']

function settings(over: Partial<Settings> = {}): Settings {
  return {
    paths: {
      library_root: '/library',
      notes_path: '/notes',
      generated_path: '/generated',
    },
    host_paths: { library: '', notes: '', generated: '' },
    extra_libraries: {},
    pending_path_changes: { notes: '/somewhere/new' },
    pending_library_removals: [],
    desktop_mode: false,
    vault_root: '',
    ...over,
  } as unknown as Settings
}

function wrap(s: Settings) {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return render(
    <QueryClientProvider client={qc}>
      <PathsSection s={s} />
    </QueryClientProvider>,
  )
}

describe('PathsSection — pending banner', () => {
  it('tells a desktop user to quit and reopen', () => {
    wrap(settings({ desktop_mode: true }))
    expect(screen.getByText(/quit and reopen the app/i)).toBeInTheDocument()
  })

  it('does not tell a desktop user to clear the message by hand', () => {
    // The startup reconcile drops a staged change the running mounts already
    // satisfy, so the banner clears itself. Telling the user to press
    // "I've restarted" was the old copy, from when it did not.
    wrap(settings({ desktop_mode: true }))
    expect(screen.getByText(/clears itself/i)).toBeInTheDocument()
  })

  it('does not show a docker command in the native app', () => {
    wrap(settings({ desktop_mode: true }))
    expect(screen.queryByText(/docker compose/i)).not.toBeInTheDocument()
  })

  it('keeps the terminal instructions under docker', () => {
    // The regression the old inference caused: this is a pending change from a
    // previous session, so `restartCommand` state is empty. The banner must
    // still say "run this in your terminal", not "quit and reopen".
    wrap(settings({ desktop_mode: false }))
    expect(screen.getByText(/run this command in your terminal/i)).toBeInTheDocument()
    expect(screen.queryByText(/quit and reopen the app/i)).not.toBeInTheDocument()
  })
})
