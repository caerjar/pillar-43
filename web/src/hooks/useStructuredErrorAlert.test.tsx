/**
 * Tests for useStructuredErrorAlert — toast routing for classified backend
 * error_codes (billing_exhausted, authentication_error, rate_limit_error,
 * model_not_found_error, provider_connection_error).
 *
 * Previously named useBillingAlert.test.tsx — kept the billing assertions
 * verbatim, added rows for the new codes shipped in Triage Sprint Theme A.
 */
import { describe, it, expect, beforeEach } from 'vitest'
import { act, render, screen, fireEvent } from '@testing-library/react'
import { useAppStore } from '../stores/appStore'
import { useStructuredErrorAlert } from './useStructuredErrorAlert'
import { ToastProvider } from '../components/ui/Toast'

// Reset store between tests so lastError leakage can't mask bugs.
beforeEach(() => {
  useAppStore.setState({
    leftTab: 'files',
    lastError: null,
  })
})

// Render-only wrapper component that mounts the hook.
function Host() {
  useStructuredErrorAlert()
  return null
}

function renderWithProvider() {
  return render(
    <ToastProvider>
      <Host />
    </ToastProvider>,
  )
}

describe('useStructuredErrorAlert', () => {
  it('shows a sticky toast when lastError.code === "billing_exhausted"', () => {
    renderWithProvider()
    expect(screen.queryByText(/credit balance/i)).toBeNull()

    act(() => {
      useAppStore.getState().setLastError({
        code: 'billing_exhausted',
        message: 'Model provider credit balance exhausted. Update billing or change model in Settings, then restart this action manually.',
      })
    })

    expect(screen.getByText(/credit balance exhausted/i)).toBeInTheDocument()
    expect(screen.getByRole('button', { name: /open settings/i })).toBeInTheDocument()
  })

  it('does not show a toast for unrecognised error codes', () => {
    renderWithProvider()
    act(() => {
      useAppStore.getState().setLastError({ code: 'some_unknown_code', message: 'slow down' })
    })
    expect(screen.queryByText(/slow down/)).toBeNull()
  })

  it('"Open Settings" opens the Preferences window on the AI group and clears lastError', () => {
    renderWithProvider()
    act(() => {
      useAppStore.getState().setLastError({
        code: 'billing_exhausted',
        message: 'Top up your account.',
      })
    })

    const btn = screen.getByRole('button', { name: /open settings/i })
    act(() => {
      fireEvent.click(btn)
    })

    // Settings is a window since 2026-08-30, not a left tab. All three codes
    // this hook handles are AI-provider problems, so the CTA lands on that
    // group rather than at the top of Preferences.
    expect(useAppStore.getState().settingsOpen).toBe(true)
    expect(useAppStore.getState().settingsSection).toBe('ai')
    expect(useAppStore.getState().lastError).toBeNull()
  })

  it('does not re-fire the toast if the same billing error is re-set', () => {
    renderWithProvider()
    act(() => {
      useAppStore.getState().setLastError({
        code: 'billing_exhausted',
        message: 'Same message.',
      })
    })
    // Force a second setState with the same code+message — the hook should
    // de-dupe by ref so the existing sticky toast isn't duplicated.
    act(() => {
      useAppStore.getState().setLastError({
        code: 'billing_exhausted',
        message: 'Same message.',
      })
    })
    const toasts = screen.getAllByText(/Same message/i)
    expect(toasts).toHaveLength(1)
  })

  it('authentication_error shows a sticky toast with Open Settings CTA', () => {
    renderWithProvider()
    act(() => {
      useAppStore.getState().setLastError({
        code: 'authentication_error',
        message: 'Authentication failed — check your API key in Settings.',
      })
    })
    expect(screen.getByText(/authentication failed/i)).toBeInTheDocument()
    expect(screen.getByRole('button', { name: /open settings/i })).toBeInTheDocument()
  })

  it('model_not_found_error shows a sticky toast with Open Settings CTA', () => {
    renderWithProvider()
    act(() => {
      useAppStore.getState().setLastError({
        code: 'model_not_found_error',
        message: 'Model not found — check the model name in Settings.',
      })
    })
    expect(screen.getByText(/model not found/i)).toBeInTheDocument()
    expect(screen.getByRole('button', { name: /open settings/i })).toBeInTheDocument()
  })

  it('rate_limit_error shows a warning toast without CTA (auto-retry context)', () => {
    renderWithProvider()
    act(() => {
      useAppStore.getState().setLastError({
        code: 'rate_limit_error',
        message: 'Rate limit reached — your request was stopped.',
      })
    })
    expect(screen.getByText(/rate limit reached/i)).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: /open settings/i })).toBeNull()
  })

  it('provider_connection_error shows a sticky error toast without CTA', () => {
    renderWithProvider()
    act(() => {
      useAppStore.getState().setLastError({
        code: 'provider_connection_error',
        message: 'Could not connect to Ollama — is it running.',
      })
    })
    expect(screen.getByText(/could not connect/i)).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: /open settings/i })).toBeNull()
  })
})
