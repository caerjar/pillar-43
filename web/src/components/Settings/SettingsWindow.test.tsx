import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { SettingsWindow } from './SettingsWindow'
import { SETTINGS_GROUPS } from './groups'
import { useAppStore } from '../../stores/appStore'

// vi.mock is hoisted before variable declarations — all mock data must be inlined.
vi.mock('../../lib/api', () => ({
  api: {
    appSettings: vi.fn().mockResolvedValue({
      library_readonly: false,
      move_confirm: 'confirm',
      ollama_base_url: 'http://127.0.0.1:11434/v1',
      ollama_model: 'llama3',
      embedding_model: 'BAAI/bge-small-en-v1.5',
      translation_language: '',
      voice_language: '',
      available_embedding_models: [
        'BAAI/bge-small-en-v1.5',
        'BAAI/bge-base-en-v1.5',
        'Alibaba-NLP/gte-base-en-v1.5',
      ],
      paths: { library_root: '/library', notes_path: '/notes', generated_path: '/generated' },
      host_paths: { library: '', notes: '', generated: '' },
    }),
    updateSettings: vi.fn().mockResolvedValue({
      library_readonly: false,
      move_confirm: 'confirm',
      ollama_base_url: 'http://127.0.0.1:11434/v1',
      ollama_model: 'llama3',
      embedding_model: 'BAAI/bge-base-en-v1.5',
      translation_language: '',
      voice_language: '',
      available_embedding_models: [
        'BAAI/bge-small-en-v1.5',
        'BAAI/bge-base-en-v1.5',
        'Alibaba-NLP/gte-base-en-v1.5',
      ],
      paths: { library_root: '/library', notes_path: '/notes', generated_path: '/generated' },
      host_paths: { library: '', notes: '', generated: '' },
    }),
    skills: vi.fn().mockResolvedValue({ skills: [] }),
    notificationSettings: vi.fn().mockResolvedValue({
      notifications_enabled: false,
      notify_email_to: '',
      smtp_host: '',
      smtp_port: 587,
      smtp_user: '',
      smtp_from: '',
      smtp_pass_set: false,
      telegram_token_set: false,
      telegram_bot_token: '',
      telegram_chat_id: '',
    }),
    libraryStatus: vi.fn().mockResolvedValue({
      notes: { exists: true, writable: true, git_ready: true, file_count: 10 },
      generated: { exists: true, writable: true, file_count: 5 },
      library: { exists: false, file_count: 0 },
      extra_libraries: {},
    }),
    commonsSettings: vi.fn().mockResolvedValue({
      commons_enabled: false,
      mattermost_url: '',
      mattermost_team: '',
      pillar43_peer_slug: 'self',
      mattermost_token_masked: '',
      mattermost_token_set: false,
    }),
  },
}))

vi.mock('framer-motion', () => ({
  motion: {
    div: ({ children, ...props }: React.HTMLAttributes<HTMLDivElement>) =>
      <div {...props}>{children}</div>,
  },
  AnimatePresence: ({ children }: { children: React.ReactNode }) => <>{children}</>,
}))

function wrap(ui: React.ReactElement) {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return render(<QueryClientProvider client={qc}>{ui}</QueryClientProvider>)
}

/** Open the Preferences window on a given group before rendering. */
function openOn(section: string) {
  useAppStore.setState({ settingsOpen: true, settingsSection: section })
}

describe('SettingsWindow — the window itself', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    useAppStore.setState({ settingsOpen: false, settingsSection: null })
  })

  it('renders nothing until it is opened', () => {
    wrap(<SettingsWindow />)
    expect(screen.queryByRole('dialog')).toBeNull()
  })

  it('lists every group in the nav, and each one renders content', async () => {
    // The nav and the content pane read the SAME list (groups.tsx). This is the
    // guard for that: split them into two arrays and one of these entries
    // navigates to an empty pane.
    const user = userEvent.setup()
    openOn('local-models')
    wrap(<SettingsWindow />)
    await waitFor(() => screen.getAllByText(/Ollama/))

    for (const g of SETTINGS_GROUPS) {
      const navItem = screen.getByRole('button', { name: g.title })
      await user.click(navItem)
      // The heading above the content pane, not the nav button.
      await waitFor(() =>
        expect(screen.getByRole('heading', { name: g.title })).toBeInTheDocument()
      )
      const body = document.querySelector('.sp-group__body')
      expect(body, `${g.title} rendered no body`).not.toBeNull()
      expect(body!.childElementCount, `${g.title} rendered empty`).toBeGreaterThan(0)
    }
  })

  it('falls back to the first group when asked for one that does not exist', async () => {
    openOn('a-group-that-was-deleted')
    wrap(<SettingsWindow />)
    await waitFor(() =>
      expect(screen.getByRole('heading', { name: SETTINGS_GROUPS[0].title })).toBeInTheDocument()
    )
  })

  it('keeps Tab inside the dialog', async () => {
    // Modal's docstring claimed a focus trap from the start and implemented
    // none — Tab walked straight out into the app behind an aria-modal dialog.
    // Watched failing against that version.
    const user = userEvent.setup()
    const outside = document.createElement('button')
    outside.textContent = 'outside'
    document.body.appendChild(outside)

    openOn('local-models')
    wrap(<SettingsWindow />)
    await waitFor(() => screen.getAllByText(/Ollama/))

    const dialog = screen.getByRole('dialog')
    for (let i = 0; i < 40; i++) {
      await user.tab()
      expect(
        dialog.contains(document.activeElement),
        `focus escaped the dialog after ${i + 1} tabs (landed on ${document.activeElement?.textContent})`,
      ).toBe(true)
    }

    outside.remove()
  })
})
