import { describe, it, expect } from 'vitest'
import { errorMessage, isStructuredError } from './errors'
import { ApiStructuredError } from './api/_fetch'

describe('errorMessage', () => {
  it('reads .message from an Error', () => {
    expect(errorMessage(new Error('disk full'))).toBe('disk full')
  })

  it('reads .message from an Error subclass', () => {
    expect(errorMessage(new ApiStructuredError(402, 'billing_exhausted', 'Out of credit')))
      .toBe('Out of credit')
  })

  it('returns a thrown string as-is', () => {
    // `throw 'nope'` is legal JS and (e as Error).message would be undefined.
    expect(errorMessage('nope')).toBe('nope')
  })

  it('reads .message off a plain object', () => {
    // Some libraries reject with a non-Error carrying a message.
    expect(errorMessage({ message: 'from a library' })).toBe('from a library')
  })

  for (const [label, value] of [
    ['null', null],
    ['undefined', undefined],
    ['a number', 42],
    ['an object with no message', { code: 500 }],
    ['an Error with an empty message', new Error('')],
    ['an empty string', ''],
  ] as const) {
    it(`falls back for ${label} rather than surfacing "undefined"`, () => {
      const out = errorMessage(value)
      expect(out).toBe('Something went wrong')
      // The regression this replaces: `(e as Error).message` yielded the
      // literal string "undefined" in a toast, which reads as an app bug
      // rather than a failure.
      expect(out).not.toContain('undefined')
      expect(out.length).toBeGreaterThan(0)
    })
  }

  it('honours a caller-supplied fallback', () => {
    expect(errorMessage(null, "Couldn't save")).toBe("Couldn't save")
  })

  it('never returns an empty string', () => {
    // An empty toast is indistinguishable from a broken one.
    for (const v of [null, undefined, '', {}, new Error('')]) {
      expect(errorMessage(v).length).toBeGreaterThan(0)
    }
  })
})

describe('isStructuredError', () => {
  it('identifies ApiStructuredError and keeps its fields', () => {
    const e = new ApiStructuredError(402, 'billing_exhausted', 'Out of credit')
    expect(isStructuredError(e)).toBe(true)
    if (isStructuredError(e)) {
      // Narrowing works, so callers can dispatch on `code` rather than
      // string-matching a user-facing message that will get reworded.
      expect(e.code).toBe('billing_exhausted')
      expect(e.status).toBe(402)
    }
  })

  it('rejects a plain Error and non-errors', () => {
    expect(isStructuredError(new Error('nope'))).toBe(false)
    expect(isStructuredError('nope')).toBe(false)
    expect(isStructuredError(null)).toBe(false)
  })
})
