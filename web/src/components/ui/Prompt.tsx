/**
 * Promise-based text prompt. The sibling of `Confirm.tsx`, and deliberately
 * the same shape — provider + hook + `window.prompt` fallback — so the two
 * read alike at a call site and neither needs its own explanation.
 *
 * It exists because the File menu needs to ask for a name. New Folder,
 * Duplicate and Rename all wanted the same three-line dialog, and the file
 * tree had been doing it with inline `useState` per row (`TreeNodeRow.tsx`),
 * which a menu action running outside any row cannot reuse.
 */
import { ReactNode, useState, useCallback, createContext, useContext } from 'react'
import { Modal } from './Modal'
import { Button } from './Button'
import { Input } from './Input'

interface PromptOptions {
  title?: ReactNode
  message?: ReactNode
  /** Pre-filled value — callers usually seed this with a sensible default. */
  initialValue?: string
  placeholder?: string
  confirmLabel?: string
  cancelLabel?: string
}

/** Resolves to the entered string, or `null` when cancelled. */
type PromptFn = (opts: PromptOptions) => Promise<string | null>

const PromptContext = createContext<PromptFn | null>(null)

interface State extends PromptOptions {
  open: boolean
  value: string
  resolver?: (v: string | null) => void
}

/**
 * Provide usePrompt() throughout the app.
 *
 * Wrap the App once, beside ConfirmProvider:
 *   <ConfirmProvider><PromptProvider><App/></PromptProvider></ConfirmProvider>
 */
export function PromptProvider({ children }: { children: ReactNode }) {
  const [state, setState] = useState<State>({ open: false, value: '' })

  const prompt = useCallback<PromptFn>(
    (opts) =>
      new Promise<string | null>((resolve) => {
        setState({ ...opts, open: true, value: opts.initialValue ?? '', resolver: resolve })
      }),
    [],
  )

  const close = (result: string | null) => {
    state.resolver?.(result)
    setState((s) => ({ ...s, open: false, resolver: undefined }))
  }

  // Empty is a cancel, not a rename to "". Every caller would otherwise have
  // to re-check, and one of them would forget.
  const submit = () => {
    const v = state.value.trim()
    close(v ? v : null)
  }

  return (
    <PromptContext.Provider value={prompt}>
      {children}
      <Modal
        open={state.open}
        onClose={() => close(null)}
        title={state.title ?? 'Enter a name'}
        width={420}
      >
        {state.message && (
          <div style={{ marginBottom: 12, fontSize: 13, lineHeight: 1.5 }}>{state.message}</div>
        )}
        <Input
          autoFocus
          value={state.value}
          placeholder={state.placeholder}
          ariaLabel={typeof state.title === 'string' ? state.title : 'Name'}
          onChange={(v) => setState((s) => ({ ...s, value: v }))}
          // Enter submits, Escape cancels. Modal binds Escape at the overlay
          // level too; stopPropagation keeps the keystroke off whatever is
          // behind the dialog (the global chord engine, mainly).
          onKeyDown={(e) => {
            if (e.key === 'Enter') {
              e.preventDefault()
              submit()
            } else if (e.key === 'Escape') {
              e.preventDefault()
              close(null)
            }
            e.stopPropagation()
          }}
          style={{ width: '100%', marginBottom: 16 }}
        />
        <div style={{ display: 'flex', justifyContent: 'flex-end', gap: 8 }}>
          <Button variant="subtle" onClick={() => close(null)}>
            {state.cancelLabel ?? 'Cancel'}
          </Button>
          <Button variant="primary" onClick={submit} disabled={!state.value.trim()}>
            {state.confirmLabel ?? 'OK'}
          </Button>
        </div>
      </Modal>
    </PromptContext.Provider>
  )
}

/**
 * Promise-based prompt. Replaces window.prompt().
 *
 *   const prompt = usePrompt()
 *   const name = await prompt({ title: 'Rename', initialValue: 'note.md' })
 *   if (name) await api.renameFile(path, name)
 *
 * Falls back to window.prompt() when no <PromptProvider> is mounted, so tests
 * and any stray call site keep working — same escape hatch as `useConfirm`.
 */
/** Module-level for reference stability — see the note in `Confirm.tsx`. */
const windowPromptFallback: PromptFn = async (opts) => {
  const text = typeof opts.title === 'string' ? opts.title : 'Enter a value'
  const v = window.prompt(text, opts.initialValue ?? '')
  const trimmed = v?.trim()
  return Promise.resolve(trimmed ? trimmed : null)
}

export function usePrompt(): PromptFn {
  return useContext(PromptContext) ?? windowPromptFallback
}
