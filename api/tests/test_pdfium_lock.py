"""PDFium is not thread-safe: a page render and a highlight lookup inside it at
the same time segfault the worker. Both must hold the one process-wide lock."""

import threading
import time
from pathlib import Path

import pypdfium2 as pdfium

from services.archive.highlight import locate
from services.vault.pdf import render_pdf_page


def test_render_and_locate_never_overlap_inside_pdfium(monkeypatch):
    inside = 0
    peak = 0
    guard = threading.Lock()

    class Doc:
        def __init__(self, *_a, **_k):
            nonlocal inside, peak
            with guard:
                inside += 1
                peak = max(peak, inside)
            time.sleep(0.05)

        def __len__(self):
            return 0  # render raises, locate returns "none": both leave at once

        def close(self):
            nonlocal inside
            with guard:
                inside -= 1

    monkeypatch.setattr(pdfium, "PdfDocument", Doc)
    p = Path("x.pdf")

    def render():
        try:
            render_pdf_page(p, 1)
        except RuntimeError:
            pass

    threads = [threading.Thread(target=render) for _ in range(3)]
    threads += [
        threading.Thread(target=lambda: locate(p, 1, "some text")) for _ in range(3)
    ]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert peak == 1
