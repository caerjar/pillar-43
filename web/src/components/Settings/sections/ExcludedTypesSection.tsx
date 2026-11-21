import { useState } from 'react'
import { api } from '../../../lib/api'

type AppSettings = Awaited<ReturnType<typeof api.appSettings>>

export function ExcludedTypesSection({
  s,
  update,
}: {
  s: AppSettings
  update: (u: Parameters<typeof api.updateSettings>[0]) => void
}) {
  // Local input state — not shared with any other section.
  const [newExt, setNewExt] = useState('')
  const [newTreeExt, setNewTreeExt] = useState('')

  return (
    <>
      <div className="sp-ext-block">
        <div className="sp-ext-block__label">Files to skip when indexing</div>
        <div className="sp-ext-block__desc">Files with these extensions are skipped during indexing and hidden from the file tree. To keep them visible (greyed out) instead of hidden, also add them to the dim list below.</div>
        <div className="sp-ext-chips">
          {(s.excluded_extensions ?? []).map((ext) => (
            <span key={ext} className="sp-ext-chip">
              {ext}
              <button
                className="sp-ext-chip__remove"
                onClick={() => {
                  const next = (s.excluded_extensions ?? []).filter((e) => e !== ext)
                  update({ excluded_extensions: next })
                }}
              >×</button>
            </span>
          ))}
          <input
            className="sp-ext-input"
            value={newExt}
            onChange={(e) => setNewExt(e.target.value)}
            placeholder=".ext"
            onKeyDown={(e) => {
              if (e.key === 'Enter') {
                e.preventDefault()
                const val = newExt.trim().toLowerCase()
                if (!val) return
                const normalized = val.startsWith('.') ? val : `.${val}`
                const current = s.excluded_extensions ?? []
                if (!current.includes(normalized)) {
                  update({ excluded_extensions: [...current, normalized] })
                }
                setNewExt('')
              }
            }}
          />
        </div>
      </div>

      <div className="sp-ext-block">
        <div className="sp-ext-block__label">Dim in file tree</div>
        <div className="sp-ext-block__desc">Files with these extensions are greyed out in the file tree but remain clickable. Extensions from the skip list above must also appear here to stay visible.</div>
        <div className="sp-ext-chips">
          {(s.tree_dim_extensions ?? []).map((ext) => (
            <span key={ext} className="sp-ext-chip">
              {ext}
              <button
                className="sp-ext-chip__remove"
                onClick={() => {
                  const next = (s.tree_dim_extensions ?? []).filter((e) => e !== ext)
                  update({ tree_dim_extensions: next })
                }}
              >×</button>
            </span>
          ))}
          <input
            className="sp-ext-input"
            value={newTreeExt}
            onChange={(e) => setNewTreeExt(e.target.value)}
            placeholder=".ext"
            onKeyDown={(e) => {
              if (e.key === 'Enter') {
                e.preventDefault()
                const val = newTreeExt.trim().toLowerCase()
                if (!val) return
                const normalized = val.startsWith('.') ? val : `.${val}`
                const current = s.tree_dim_extensions ?? []
                if (!current.includes(normalized)) {
                  update({ tree_dim_extensions: [...current, normalized] })
                }
                setNewTreeExt('')
              }
            }}
          />
        </div>
      </div>
    </>
  )
}
