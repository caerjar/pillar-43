import { useState } from 'react'
import { api } from '../../../lib/api'
import { Row, SelectField } from '../controls'

type AppSettings = Awaited<ReturnType<typeof api.appSettings>>

/** Local models: Ollama is the only provider, plus the embedding model. */
export function AiModelsSection({
  s,
  update,
}: {
  s: AppSettings
  update: (u: Parameters<typeof api.updateSettings>[0]) => void
}) {
  const [embeddingChanged, setEmbeddingChanged] = useState(false)
  const [discoverState, setDiscoverState] = useState<'idle' | 'loading' | 'error'>('idle')
  const [discoveredModels, setDiscoveredModels] = useState<string[]>([])

  async function discoverModels() {
    setDiscoverState('loading')
    try {
      const result = await api.localModels()
      if (result.error) {
        setDiscoverState('error')
        setDiscoveredModels([])
      } else {
        setDiscoveredModels(result.models)
        setDiscoverState('idle')
        if (result.models.length > 0) update({ ollama_model: result.models[0] })
      }
    } catch {
      setDiscoverState('error')
    }
  }

  function onEmbeddingModelChange(model: string) {
    setEmbeddingChanged(model !== s.embedding_model)
    update({ embedding_model: model })
  }

  const embeddingOptions = (s.available_embedding_models ?? []).map((m) => ({ value: m, label: m }))

  return (
    <div>
      <div className="sp-ai-notice sp-ai-notice--info" style={{ marginBottom: 12 }}>
        <strong>Ollama</strong> runs the models on this computer. Nothing leaves it.
      </div>
      <Row label="Base URL" description="Set by the install (OLLAMA_URL); restart the app to change it">
        <input type="text" value={s.ollama_base_url} readOnly className="sp-input" />
      </Row>
      <Row label="Model" description="e.g. llama3, qwen2.5:7b, mistral">
        <div style={{ display: 'flex', gap: 'var(--space-2)', alignItems: 'center' }}>
          <input
            type="text"
            defaultValue={s.ollama_model}
            onBlur={(e) => update({ ollama_model: e.target.value.trim() })}
            placeholder="llama3"
            list="sp-discovered-models"
            className="sp-input"
            style={{ flex: 1 }}
          />
          <datalist id="sp-discovered-models">
            {discoveredModels.map((m) => (
              <option key={m} value={m} />
            ))}
          </datalist>
          <button
            onClick={discoverModels}
            disabled={discoverState === 'loading'}
            className="sp-btn-test sp-btn-test--idle"
            title="Query the configured endpoint for available models"
            style={{ whiteSpace: 'nowrap' }}
          >
            {discoverState === 'loading' ? '…' : 'Discover'}
          </button>
        </div>
        {discoverState === 'error' && (
          <span className="sp-ping-error" style={{ fontSize: 'var(--text-xs)', marginTop: 4 }}>
            Could not reach endpoint
          </span>
        )}
        {discoverState === 'idle' && discoveredModels.length > 0 && (
          <span style={{ fontSize: 'var(--text-xs)', color: 'var(--text-muted)', marginTop: 4 }}>
            {discoveredModels.length} model{discoveredModels.length !== 1 ? 's' : ''} found
          </span>
        )}
      </Row>

      <Row label="Embedding model" description="Used for semantic search. Changing requires full re-index.">
        <SelectField
          value={s.embedding_model ?? 'BAAI/bge-small-en-v1.5'}
          options={embeddingOptions}
          onChange={onEmbeddingModelChange}
        />
      </Row>

      {embeddingChanged && (
        <div className="sp-ai-notice sp-ai-notice--warn">
          Embedding model changed. Re-index the archive to rebuild the semantic search index.
        </div>
      )}
    </div>
  )
}
