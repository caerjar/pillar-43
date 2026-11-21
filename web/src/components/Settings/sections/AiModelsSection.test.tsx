/**
 * Ollama is the only model provider. These pin what the section writes.
 */
import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { AiModelsSection } from './AiModelsSection'

const { apiMock } = vi.hoisted(() => ({
  apiMock: {
    localModels: vi.fn(),
    updateSettings: vi.fn(),
    appSettings: vi.fn(),
  },
}))
vi.mock('../../../lib/api', () => ({ api: apiMock }))

type Settings = Parameters<typeof AiModelsSection>[0]['s']

function settings(over: Record<string, unknown> = {}): Settings {
  return {
    ollama_base_url: 'http://127.0.0.1:11434/v1',
    ollama_model: 'llama3',
    embedding_model: 'bge-small',
    available_embedding_models: ['bge-small', 'bge-base'],
    ...over,
  } as unknown as Settings
}

const update = vi.fn()

function renderSection(over: Record<string, unknown> = {}) {
  render(<AiModelsSection s={settings(over)} update={update} />)
}

beforeEach(() => {
  vi.clearAllMocks()
  apiMock.localModels.mockResolvedValue({ models: [], error: null })
})

describe('AiModelsSection', () => {
  it('offers no hosted provider', () => {
    renderSection()
    expect(screen.queryByRole('combobox', { name: /primary provider/i })).not.toBeInTheDocument()
    expect(screen.queryByText(/anthropic|openai|api key/i)).not.toBeInTheDocument()
  })

  it('shows the Ollama address as read-only: the install sets it', async () => {
    renderSection()
    const input = screen.getByDisplayValue('http://127.0.0.1:11434/v1') as HTMLInputElement
    expect(input.readOnly).toBe(true)
    await userEvent.type(input, 'x')
    await userEvent.tab()
    expect(update).not.toHaveBeenCalledWith(expect.objectContaining({ ollama_base_url: expect.anything() }))
  })

  it('discovering adopts the first model', async () => {
    apiMock.localModels.mockResolvedValue({ models: ['qwen3', 'llama3'], error: null })
    renderSection()
    await userEvent.click(screen.getByRole('button', { name: /discover/i }))
    await waitFor(() => expect(update).toHaveBeenCalledWith({ ollama_model: 'qwen3' }))
    expect(await screen.findByText(/2 models found/i)).toBeInTheDocument()
  })

  it('shows fixed copy rather than the backend error text', async () => {
    apiMock.localModels.mockResolvedValue({ models: [], error: 'connection refused to 127.0.0.1:11434' })
    renderSection()
    await userEvent.click(screen.getByRole('button', { name: /discover/i }))
    expect(await screen.findByText(/could not reach endpoint/i)).toBeInTheDocument()
    expect(screen.queryByText(/connection refused/i)).not.toBeInTheDocument()
  })

  it('warns that a changed embedding model needs a re-index', async () => {
    renderSection()
    await userEvent.selectOptions(screen.getByDisplayValue('bge-small'), 'bge-base')
    expect(update).toHaveBeenCalledWith({ embedding_model: 'bge-base' })
    expect(screen.getByText(/embedding model changed/i)).toBeInTheDocument()
  })
})
