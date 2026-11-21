import { ReactNode, useState, useCallback, createContext, useContext } from 'react'
import { Modal } from './Modal'
import { Button } from './Button'

interface ConfirmOptions {
  title?: ReactNode
  message: ReactNode
  confirmLabel?: string
  cancelLabel?: string
  destructive?: boolean
}

type ConfirmFn = (opts: ConfirmOptions) => Promise<boolean>

const ConfirmContext = createContext<ConfirmFn | null>(null)

interface State extends ConfirmOptions {
  open: boolean
  resolver?: (v: boolean) => void
}

/**
 * Provide useConfirm() throughout the app.
 *
 * Wrap the App once:
 *   <ConfirmProvider><App/></ConfirmProvider>
 */
export function ConfirmProvider({ children }: { children: ReactNode }) {
  const [state, setState] = useState<State>({
    open: false,
    message: '',
  })

  const confirm = useCallback<ConfirmFn>(
    (opts) =>
      new Promise<boolean>((resolve) => {
        setState({ ...opts, open: true, resolver: resolve })
      }),
    [],
  )

  const close = (result: boolean) => {
    state.resolver?.(result)
    setState((s) => ({ ...s, open: false, resolver: undefined }))
  }

  return (
    <ConfirmContext.Provider value={confirm}>
      {children}
      <Modal
        open={state.open}
        onClose={() => close(false)}
        title={state.title ?? 'Confirm'}
        width={420}
      >
        <div style={{ marginBottom: 16, fontSize: 13, lineHeight: 1.5 }}>
          {state.message}
        </div>
        <div style={{ display: 'flex', justifyContent: 'flex-end', gap: 8 }}>
          <Button variant="subtle" onClick={() => close(false)}>
            {state.cancelLabel ?? 'Cancel'}
          </Button>
          <Button
            variant={state.destructive ? 'destructive' : 'primary'}
            onClick={() => close(true)}
            autoFocus
          >
            {state.confirmLabel ?? 'OK'}
          </Button>
        </div>
      </Modal>
    </ConfirmContext.Provider>
  )
}

/**
 * Promise-based confirm. Replaces window.confirm().
 *
 *   const confirm = useConfirm()
 *   if (await confirm({ message: 'Delete this file?', destructive: true })) {
 *     await api.deleteFile(path)
 *   }
 *
 * Falls back to window.confirm() if no <ConfirmProvider> is mounted (test contexts).
 */
/**
 * Module-level so the reference is stable across renders.
 *
 * It used to be an inline arrow, which returned a new function on every render
 * whenever no provider was mounted. `useCommandCtx` memoises on this value and
 * feeds the result to `useGlobalKeyboard`, whose effect resets the pending
 * chord on re-registration — an unstable fallback would re-register every
 * render and swallow the second key of a chord.
 */
const windowConfirmFallback: ConfirmFn = async (opts) => {
  const text = typeof opts.message === 'string' ? opts.message : 'Are you sure?'
  return Promise.resolve(window.confirm(text))
}

export function useConfirm(): ConfirmFn {
  return useContext(ConfirmContext) ?? windowConfirmFallback
}
