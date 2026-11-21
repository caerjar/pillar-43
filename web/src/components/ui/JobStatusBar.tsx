import { useEffect } from 'react'
import { useAppStore, type Job } from '../../stores/appStore'
import { Spinner } from './Spinner'

function JobPill({ job }: { job: Job }) {
  const isRunning = job.status === 'running'
  const isError = job.status === 'error'
  const isCancelled = job.status === 'cancelled'

  return (
    <div
      style={{
        display: 'inline-flex',
        alignItems: 'center',
        gap: 'var(--space-2)',
        padding: '3px 10px',
        background: isError ? 'var(--error-dim)' : isCancelled ? 'var(--warning-dim, rgba(240,180,40,0.1))' : 'var(--bg-surface)',
        border: `1px solid ${isError ? 'var(--error)' : isCancelled ? 'var(--warning, #c8991a)' : isRunning ? 'var(--border-strong)' : 'var(--border)'}`,
        borderRadius: 'var(--radius-lg)',
        fontSize: 'var(--text-xs)',
        color: isError ? 'var(--error)' : isCancelled ? 'var(--warning, #c8991a)' : isRunning ? 'var(--text-secondary)' : 'var(--text-muted)',
        whiteSpace: 'nowrap',
        animation: 'fadeIn 0.15s ease',
      }}
    >
      {isRunning && <Spinner size="sm" />}
      {!isRunning && !isError && !isCancelled && (
        <span aria-hidden="true" style={{ color: 'var(--success)', fontSize: 10 }}>✓</span>
      )}
      {isError && (
        <span aria-hidden="true" style={{ fontSize: 10 }}>!</span>
      )}
      {isCancelled && (
        <span aria-hidden="true" style={{ fontSize: 10 }}>⏹</span>
      )}
      <span>{job.label}</span>
      {job.progress && (
        <span style={{ color: 'inherit', opacity: 0.75, maxWidth: 200, overflow: 'hidden', textOverflow: 'ellipsis' }}>
          — {job.progress}
        </span>
      )}
    </div>
  )
}

/** Thin persistent bar at the bottom of the app showing active and recently finished jobs. */
export function JobStatusBar() {
  const jobs = useAppStore((s) => s.jobs)
  const clearFinishedJobs = useAppStore((s) => s.clearFinishedJobs)

  // Auto-clear finished jobs after 4 seconds
  useEffect(() => {
    const finished = jobs.filter((j) => j.status !== 'running')
    if (finished.length === 0) return
    const timer = setTimeout(clearFinishedJobs, 4000)
    return () => clearTimeout(timer)
  }, [jobs, clearFinishedJobs])

  if (jobs.length === 0) return null

  return (
    <div
      role="status"
      aria-live="polite"
      style={{
        display: 'flex',
        alignItems: 'center',
        gap: 'var(--space-2)',
        padding: '0 var(--space-4)',
        height: 30,
        borderTop: '1px solid var(--border-subtle)',
        background: 'var(--bg-panel)',
        flexShrink: 0,
        overflow: 'hidden',
      }}
    >
      {jobs.map((job) => (
        <JobPill key={job.id} job={job} />
      ))}
    </div>
  )
}
