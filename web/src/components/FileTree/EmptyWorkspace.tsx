/**
 * Shown when the archive has no files yet.
 */

export function EmptyWorkspace() {
  return (
    <div
      style={{
        padding: '32px 20px 24px',
        display: 'flex',
        flexDirection: 'column',
        gap: 14,
        fontSize: 13,
      }}
    >
      <div style={{ fontWeight: 600, fontSize: 16, color: 'var(--text-primary)' }}>
        No files yet
      </div>
      <div style={{ lineHeight: 1.6, color: 'var(--text-secondary)' }}>
        The archive folder is empty. Documents added to it appear here once the
        archive has read them.
      </div>
    </div>
  )
}
