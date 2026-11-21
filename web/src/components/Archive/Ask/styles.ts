import type { CSSProperties } from 'react'
import type { AskPassage } from '../../../lib/api/archive'

import { muted, target } from '../styles'

export { muted, target }

export const plainButton: CSSProperties = {
  ...target, background: 'none', border: 'none', padding: '2px 0', cursor: 'pointer',
  fontFamily: 'inherit', fontSize: 'var(--text-sm)', textAlign: 'left',
}

/** A passage is named by its item and the work it is about (title and ISBN
 *  when the text carries them), never by its file name. */
export function passageHeading(p: Pick<AskPassage, 'title' | 'work_title'>): string {
  return p.work_title ? `${p.title}: ${p.work_title}` : p.title
}
