import { describe, it, expect, vi } from 'vitest'
import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { ConfirmDestructiveProvider, useConfirmDestructive } from './ConfirmDestructive'

function Harness({ onResult }: { onResult: (v: boolean) => void }) {
  const confirm = useConfirmDestructive()
  return (
    <button
      onClick={async () => {
        onResult(await confirm({
          title: 'Erase everything?',
          message: 'There is no undo.',
          removed: ['Every note'],
          kept: ['Your library folder'],
          phrase: 'ERASE',
          confirmLabel: 'Erase everything',
        }))
      }}
    >
      open
    </button>
  )
}

function open() {
  const onResult = vi.fn()
  render(
    <ConfirmDestructiveProvider>
      <Harness onResult={onResult} />
    </ConfirmDestructiveProvider>,
  )
  return { onResult, user: userEvent.setup() }
}

const confirmButton = () => screen.getByRole('button', { name: 'Erase everything' })

describe('ConfirmDestructive', () => {
  it('keeps the action disabled until the exact phrase is typed', async () => {
    const { user } = open()
    await user.click(screen.getByRole('button', { name: 'open' }))

    expect(confirmButton()).toBeDisabled()
    await user.type(screen.getByLabelText(/Type/), 'ERAS')
    expect(confirmButton()).toBeDisabled()
    await user.type(screen.getByLabelText(/Type/), 'E')
    expect(confirmButton()).toBeEnabled()
  })

  it('is case-sensitive', async () => {
    // The whole value of type-to-confirm is that it cannot be satisfied by
    // muscle memory. Lower-casing the comparison would give it away.
    const { user } = open()
    await user.click(screen.getByRole('button', { name: 'open' }))
    await user.type(screen.getByLabelText(/Type/), 'erase')
    expect(confirmButton()).toBeDisabled()
  })

  it('shows what is kept as well as what is destroyed', async () => {
    const { user } = open()
    await user.click(screen.getByRole('button', { name: 'open' }))
    expect(screen.getByText('Every note')).toBeInTheDocument()
    expect(screen.getByText('Your library folder')).toBeInTheDocument()
  })

  it('resolves true only after confirming', async () => {
    const { user, onResult } = open()
    await user.click(screen.getByRole('button', { name: 'open' }))
    await user.type(screen.getByLabelText(/Type/), 'ERASE')
    await user.click(confirmButton())
    await waitFor(() => expect(onResult).toHaveBeenCalledWith(true))
  })

  it('resolves false on cancel', async () => {
    const { user, onResult } = open()
    await user.click(screen.getByRole('button', { name: 'open' }))
    await user.type(screen.getByLabelText(/Type/), 'ERASE')
    await user.click(screen.getByRole('button', { name: 'Cancel' }))
    await waitFor(() => expect(onResult).toHaveBeenCalledWith(false))
  })

  it('resolves false on Escape', async () => {
    const { user, onResult } = open()
    await user.click(screen.getByRole('button', { name: 'open' }))
    await user.keyboard('{Escape}')
    await waitFor(() => expect(onResult).toHaveBeenCalledWith(false))
  })

  it('forgets the typed phrase between openings', async () => {
    // Otherwise the second, possibly different, destructive action arrives
    // pre-armed — one click from done.
    const { user } = open()
    await user.click(screen.getByRole('button', { name: 'open' }))
    await user.type(screen.getByLabelText(/Type/), 'ERASE')
    await user.click(screen.getByRole('button', { name: 'Cancel' }))

    await user.click(screen.getByRole('button', { name: 'open' }))
    expect(screen.getByLabelText(/Type/)).toHaveValue('')
    expect(confirmButton()).toBeDisabled()
  })
})
