import { describe, expect, it } from 'vitest'

import {
  HANDWRITING_EXTS,
  IMAGE_EXTS,
  IMAGE_VIEWER_EXTS,
} from './multimediaExts'

describe('HANDWRITING_EXTS', () => {
  it('includes every plain image format the menu action accepts', () => {
    for (const ext of IMAGE_EXTS) {
      expect(HANDWRITING_EXTS).toContain(ext)
    }
  })

  it('adds .heic on top of the base image set', () => {
    expect(HANDWRITING_EXTS).toContain('.heic')
  })

  it('accepts PDFs (the route renders each page server-side)', () => {
    expect(HANDWRITING_EXTS).toContain('.pdf')
  })

  it('rejects audio/video/text and other non-handwriting file types', () => {
    for (const ext of ['.mp3', '.mp4', '.mov', '.md', '.txt', '.json']) {
      expect(HANDWRITING_EXTS).not.toContain(ext)
    }
  })

  it('keeps HEIC out of IMAGE_VIEWER_EXTS — browsers cannot render HEIC inline', () => {
    expect(IMAGE_VIEWER_EXTS).not.toContain('.heic')
  })
})
