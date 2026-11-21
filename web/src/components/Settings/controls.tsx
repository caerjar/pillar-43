import { useState } from 'react'

// ── Reusable controls ─────────────────────────────────────────────────────────

export function Section({ title, restartRequired }: { title: string; restartRequired?: boolean }) {
  return (
    <div className="sp-section">
      {title}
      {restartRequired && (
        <span className="sp-restart-badge">
          ↺ restart required
        </span>
      )}
    </div>
  )
}

export function RestartBadge() {
  return (
    <span className="sp-restart-badge">
      ↺ restart required
    </span>
  )
}

export function Row({ label, description, restartRequired, children }: {
  label: string
  description?: string
  restartRequired?: boolean
  children: React.ReactNode
}) {
  return (
    <div className="sp-row">
      <div className="sp-row__label-group">
        <div className="sp-row__label-line">
          <span className="sp-row__label">{label}</span>
          {restartRequired && <RestartBadge />}
        </div>
        {description && (
          <div className="sp-row__description">{description}</div>
        )}
      </div>
      <div className="sp-row__control">{children}</div>
    </div>
  )
}

/**
 * On/off switch.
 *
 * `role="switch"` + `aria-checked` because the rendered element is a bare
 * `<button>` whose only content is a styled thumb — without them a screen
 * reader announces "button" and gives no way to tell on from off. Free to add
 * and it fixes every existing caller at once.
 *
 * `label` sets the accessible name. It is optional only because the other
 * callers predate it; a Toggle without one is announced as an unnamed switch,
 * which is better than before and still not good. Pass it on new rows.
 */
export function Toggle({
  checked,
  onChange,
  disabled,
  label,
}: {
  checked: boolean
  onChange: (v: boolean) => void
  disabled?: boolean
  label?: string
}) {
  return (
    <button
      type="button"
      role="switch"
      aria-checked={checked}
      aria-label={label}
      onClick={() => { if (!disabled) onChange(!checked) }}
      disabled={disabled}
      className={`sp-toggle${checked ? ' sp-toggle--on' : ' sp-toggle--off'}${disabled ? ' sp-toggle--disabled' : ''}`}
    >
      <span className="sp-toggle__thumb" />
    </button>
  )
}

export function SelectField({ value, options, onChange, label }: {
  value: string
  options: { value: string; label: string }[]
  onChange: (v: string) => void
  /**
   * Accessible name. `Row` renders the visible label as a sibling, not a
   * `<label for>`, so without this the select has no accessible name at all —
   * screen readers announce it as an unlabelled combobox, and tests can only
   * reach it by index into `getAllByRole('combobox')`, which silently retargets
   * whenever a row is added above it.
   */
  label?: string
}) {
  return (
    <select
      value={value}
      onChange={(e) => onChange(e.target.value)}
      className="sp-select"
      aria-label={label}
    >
      {options.map((o) => <option key={o.value} value={o.value}>{o.label}</option>)}
    </select>
  )
}

export function PathDisplay({ label, value }: { label: string; value: string }) {
  const [copied, setCopied] = useState(false)
  function copy() {
    navigator.clipboard.writeText(value).then(() => {
      setCopied(true)
      setTimeout(() => setCopied(false), 1500)
    })
  }
  return (
    <Row label={label} restartRequired description={`Set during install — restart the app to change it`}>
      <div className="sp-path-display">
        <span className="sp-path-value" title={value}>
          {value}
        </span>
        <button
          onClick={copy}
          title="Copy path"
          className={`sp-path-copy${copied ? ' sp-path-copy--copied' : ''}`}
        >
          {copied ? '✓' : '⎘'}
        </button>
      </div>
    </Row>
  )
}

export function PasswordInput({ placeholder, onSave }: { placeholder?: string; onSave: (v: string) => void }) {
  const [value, setValue] = useState('')
  const [show, setShow] = useState(false)
  return (
    <div className="sp-password-wrap">
      <div className="sp-password-inner">
        <input
          type={show ? 'text' : 'password'}
          value={value}
          onChange={(e) => setValue(e.target.value)}
          onBlur={() => { if (value) onSave(value); setValue('') }}
          onKeyDown={(e) => { if (e.key === 'Enter' && value) { onSave(value); setValue('') } }}
          placeholder={placeholder}
          className="sp-password-input"
        />
        <button
          onClick={() => setShow((s) => !s)}
          className="sp-password-reveal"
        >
          {show ? '◻' : '◼'}
        </button>
      </div>
    </div>
  )
}

export function SendTestButton({ label, loading, onClick }: { label: string; loading: boolean; onClick: () => void }) {
  return (
    <button
      onClick={onClick}
      disabled={loading}
      className={`sp-btn-test${loading ? ' sp-btn-test--loading' : ' sp-btn-test--idle'}`}
    >
      {loading ? '…' : label}
    </button>
  )
}
