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

const FORBIDDEN = /Anthropic|OpenAI|Gemini|Groq|Pillar-43|Claude/i
const ORG_TITLES = ['Local models', 'Storage']

describe('SettingsWindow content', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    useAppStore.setState({ settingsOpen: true, settingsSection: 'ai' })
  })

  it('offers only the local and storage groups', () => {
    expect(SETTINGS_GROUPS.map((g) => g.title)).toEqual(ORG_TITLES)
  })

  it('shows no cloud provider or Pillar-43 text in any group', async () => {
    const user = userEvent.setup()
    wrap(<SettingsWindow />)
    await waitFor(() => screen.getByRole('heading', { name: 'Local models' }))
    for (const title of ORG_TITLES) {
      await user.click(screen.getByRole('button', { name: title }))
      await waitFor(() => screen.getByRole('heading', { name: title }))
      const dialog = screen.getByRole('dialog')
      expect(dialog.textContent).not.toMatch(FORBIDDEN)
      const fields = Array.from(dialog.querySelectorAll('input, select, option')).map(
        (e) => (e as HTMLInputElement).placeholder + ' ' + (e as HTMLOptionElement).label,
      )
      expect(fields.join(' ')).not.toMatch(FORBIDDEN)
    }
  })

  it('keeps the Ollama card and the paths', async () => {
    const user = userEvent.setup()
    wrap(<SettingsWindow />)
    await waitFor(() => screen.getAllByText(/Ollama/))
    await user.click(screen.getByRole('button', { name: 'Storage' }))
    await waitFor(() => screen.getByText('Paths'))
  })

  it('the footer is one plain sentence and "Ollama / local server" is not repeated', async () => {
    const user = userEvent.setup()
    wrap(<SettingsWindow />)
    await waitFor(() => screen.getAllByText(/Ollama/))
    expect(screen.getByText('Settings are saved on this machine.')).toBeDefined()
    expect(screen.queryByText(/environment variables/)).toBeNull()
    expect(screen.queryByText('the settings file')).toBeNull()
    expect(screen.queryByText('Ollama / local server')).toBeNull()
    void user
  })
})
