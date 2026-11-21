/**
 * Tests for the interaction-heavy ui primitives: Modal, Toast, Confirm.
 *
 * These had zero coverage despite being the shared substrate the whole app
 * renders through (2026-07-30 audit: ui/ was 18 files, 0 tests). The behaviours
 * pinned here are the ones other components silently depend on — the
 * no-provider fallbacks especially, since most existing test files render
 * components *without* wrapping them in ToastProvider/ConfirmProvider and rely
 * on those paths not throwing.
 */
import { describe, it, expect, vi } from 'vitest'
import { render, screen, waitFor, act } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { Modal } from './Modal'
import { ToastProvider, useToast } from './Toast'
import { ConfirmProvider, useConfirm } from './Confirm'

describe('Modal', () => {
  it('renders nothing while closed', () => {
    render(<Modal open={false} onClose={() => {}} title="Nope">body</Modal>)
    expect(screen.queryByRole('dialog')).not.toBeInTheDocument()
  })

  it('portals into document.body with dialog semantics', () => {
    render(<Modal open onClose={() => {}} title="Delete file">body text</Modal>)
    const dialog = screen.getByRole('dialog')
    expect(dialog).toHaveAttribute('aria-modal', 'true')
    expect(dialog).toHaveAttribute('aria-label', 'Delete file')
    // Portal target — not nested under the React tree's container.
    expect(dialog.closest('body')).toBe(document.body)
  })

  it('closes on Escape, and does not when closeOnEscape is false', async () => {
    const onClose = vi.fn()
    const { rerender } = render(<Modal open onClose={onClose}>b</Modal>)
    await userEvent.keyboard('{Escape}')
    expect(onClose).toHaveBeenCalledTimes(1)

    rerender(<Modal open onClose={onClose} closeOnEscape={false}>b</Modal>)
    await userEvent.keyboard('{Escape}')
    expect(onClose).toHaveBeenCalledTimes(1) // unchanged
  })

  it('closes on backdrop click but not on clicks inside the dialog', async () => {
    const onClose = vi.fn()
    render(<Modal open onClose={onClose} title="T"><button>inside</button></Modal>)

    await userEvent.click(screen.getByText('inside'))
    expect(onClose).not.toHaveBeenCalled()

    await userEvent.click(screen.getByRole('presentation'))
    expect(onClose).toHaveBeenCalledTimes(1)
  })

  it('honours closeOnBackdrop={false}', async () => {
    const onClose = vi.fn()
    render(<Modal open onClose={onClose} closeOnBackdrop={false}>b</Modal>)
    await userEvent.click(screen.getByRole('presentation'))
    expect(onClose).not.toHaveBeenCalled()
  })

  it('moves focus to the dialog on open so Escape reaches it', async () => {
    render(<Modal open onClose={() => {}}>b</Modal>)
    await waitFor(() => expect(screen.getByRole('dialog')).toHaveFocus())
  })
})

describe('Toast', () => {
  function Harness({ onReady }: { onReady?: (api: ReturnType<typeof useToast>) => void }) {
    const api = useToast()
    return (
      <div>
        <button onClick={() => api.toast('plain string')}>str</button>
        <button onClick={() => api.error('it broke')}>err</button>
        <button onClick={() => api.toast({ message: 'sticky', duration: 0 })}>sticky</button>
        <button onClick={() => onReady?.(api)}>probe</button>
      </div>
    )
  }

  it('renders a toast with a live-region role and dismisses it manually', async () => {
    render(<ToastProvider><Harness /></ToastProvider>)
    await userEvent.click(screen.getByText('str'))

    const toast = await screen.findByRole('status')
    expect(toast).toHaveTextContent('plain string')

    await userEvent.click(screen.getByLabelText('Dismiss'))
    await waitFor(() => expect(screen.queryByRole('status')).not.toBeInTheDocument())
  })

  it('auto-dismisses after the default duration', async () => {
    vi.useFakeTimers()
    try {
      render(<ToastProvider><Harness /></ToastProvider>)
      // userEvent needs the real clock; drive the click directly instead.
      act(() => { screen.getByText('str').click() })
      expect(screen.getByRole('status')).toBeInTheDocument()

      act(() => { vi.advanceTimersByTime(60_000) })
      expect(screen.queryByRole('status')).not.toBeInTheDocument()
    } finally {
      vi.useRealTimers()
    }
  })

  it('treats duration 0 as persistent — the manual-dismiss-only case', async () => {
    vi.useFakeTimers()
    try {
      render(<ToastProvider><Harness /></ToastProvider>)
      act(() => { screen.getByText('sticky').click() })
      act(() => { vi.advanceTimersByTime(60_000) })
      expect(screen.getByRole('status')).toHaveTextContent('sticky')
    } finally {
      vi.useRealTimers()
    }
  })

  it('stacks multiple toasts rather than replacing', async () => {
    render(<ToastProvider><Harness /></ToastProvider>)
    await userEvent.click(screen.getByText('str'))
    await userEvent.click(screen.getByText('err'))
    expect(await screen.findAllByRole('status')).toHaveLength(2)
  })

  it('falls back to console logging with no provider mounted', async () => {
    // Load-bearing: most component tests render without ToastProvider. If this
    // path threw, every one of them would fail on the first error toast.
    const spy = vi.spyOn(console, 'error').mockImplementation(() => {})
    try {
      render(<Harness />)
      await userEvent.click(screen.getByText('err'))
      expect(spy).toHaveBeenCalledWith('[error]', 'it broke')
      expect(screen.queryByRole('status')).not.toBeInTheDocument()
    } finally {
      spy.mockRestore()
    }
  })
})

describe('Confirm', () => {
  function Harness({ onResult }: { onResult: (v: boolean) => void }) {
    const confirm = useConfirm()
    return (
      <button onClick={async () => onResult(await confirm({ message: 'Delete this file?', destructive: true }))}>
        go
      </button>
    )
  }

  it('resolves true when confirmed and false when cancelled', async () => {
    const onResult = vi.fn()
    render(<ConfirmProvider><Harness onResult={onResult} /></ConfirmProvider>)

    await userEvent.click(screen.getByText('go'))
    expect(await screen.findByText('Delete this file?')).toBeInTheDocument()
    await userEvent.click(screen.getByRole('button', { name: 'OK' }))
    await waitFor(() => expect(onResult).toHaveBeenCalledWith(true))

    await userEvent.click(screen.getByText('go'))
    await userEvent.click(await screen.findByRole('button', { name: 'Cancel' }))
    await waitFor(() => expect(onResult).toHaveBeenLastCalledWith(false))
  })

  it('resolves false when dismissed via Escape — a dropped promise would hang the caller', async () => {
    const onResult = vi.fn()
    render(<ConfirmProvider><Harness onResult={onResult} /></ConfirmProvider>)
    await userEvent.click(screen.getByText('go'))
    await screen.findByRole('dialog')
    await userEvent.keyboard('{Escape}')
    await waitFor(() => expect(onResult).toHaveBeenCalledWith(false))
  })

  it('falls back to window.confirm with no provider mounted', async () => {
    const spy = vi.spyOn(window, 'confirm').mockReturnValue(true)
    const onResult = vi.fn()
    try {
      render(<Harness onResult={onResult} />)
      await userEvent.click(screen.getByText('go'))
      await waitFor(() => expect(onResult).toHaveBeenCalledWith(true))
      expect(spy).toHaveBeenCalledWith('Delete this file?')
    } finally {
      spy.mockRestore()
    }
  })
})
