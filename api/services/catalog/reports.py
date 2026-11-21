"""Catalog report generation — load-bearing texts and project status.

Extracted from routes/catalog.py to reduce file size and improve maintainability.
Each function queries the catalog DB and generates a markdown report.
"""

import time

from config import settings

from .constants import MAX_TEXT_EXTRACT_BYTES


def generate_load_bearing_report(conn) -> dict:
    """Find the most-referenced files across the vault by wikilink count.

    Returns:
        dict: {"file_count": int, "output": str (path to generated report)}
    """
    # Count how many times each file is referenced as a wikilink target
    rows = conn.execute(
        """SELECT target_path, COUNT(*) as ref_count
           FROM file_connections
           WHERE kind = 'wikilink'
           GROUP BY target_path
           ORDER BY ref_count DESC
           LIMIT 50"""
    ).fetchall()

    if not rows:
        # Fallback: use files with most topic connections
        rows = conn.execute(
            """SELECT f.rel_path as target_path, COUNT(*) as ref_count
               FROM file_connections fc
               JOIN files f ON fc.file_a_id = f.id OR fc.file_b_id = f.id
               GROUP BY f.rel_path
               ORDER BY ref_count DESC
               LIMIT 50"""
        ).fetchall()

    lines = [
        "# Load-Bearing Texts",
        "",
        f"*Generated: {time.strftime('%Y-%m-%d %H:%M')}*",
        "",
        "Files most frequently referenced across the vault.",
        "",
        "| File | References |",
        "|------|-----------|",
    ]
    for row in rows:
        path = row["target_path"] or "(unknown)"
        count = row["ref_count"]
        fname = path.split("/")[-1]
        lines.append(f"| [{fname}]({path}) | {count} |")

    if not rows:
        lines.append("| — | No wikilink data yet. Run Index first. |")

    lines.extend(["", "---", ""])
    lines.append(f"*{len(rows)} files analyzed.*")

    out_path = settings.generated_path / "load-bearing-texts.md"
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text("\n".join(lines), encoding="utf-8")
    return {"file_count": len(rows), "output": str(out_path)}


def generate_project_status_report(conn) -> dict:
    """Determine status of each thread and write a report.

    Classifies threads as ACTIVE/LATENT/STALLED/UNKNOWN based on:
    - Thread status field
    - File count
    - Last active timestamp

    Returns:
        dict: {"thread_count": int, "output": str (path to generated report)}
    """
    now = time.time()
    rows = conn.execute(
        """SELECT name, label, status, file_count,
                  last_active
           FROM threads
           ORDER BY last_active DESC NULLS LAST"""
    ).fetchall()

    def classify(row) -> str:
        status = row["status"] or "unknown"
        file_count = row["file_count"] or 0
        last_active = row["last_active"]
        if status == "alive" and file_count > 3:
            return "ACTIVE"
        if status == "latent":
            return "LATENT"
        if status == "dormant":
            age_days = (now - last_active) / 86400 if last_active else 9999
            return "STALLED" if age_days > 90 else "LATENT"
        if file_count == 0:
            return "UNKNOWN"
        return "ACTIVE" if status == "alive" else "LATENT"

    def fmt_age(last_active) -> str:
        if not last_active:
            return "never"
        days = int((now - last_active) / 86400)
        if days == 0:
            return "today"
        if days == 1:
            return "yesterday"
        return f"{days}d ago"

    categories: dict[str, list] = {
        "ACTIVE": [],
        "LATENT": [],
        "STALLED": [],
        "UNKNOWN": [],
    }
    for row in rows:
        cat = classify(row)
        categories[cat].append(row)

    lines = [
        "# Project Status",
        "",
        f"*Generated: {time.strftime('%Y-%m-%d %H:%M')}*",
        "",
        f"{len(rows)} threads analyzed.",
        "",
    ]

    for cat, cat_rows in categories.items():
        if not cat_rows:
            continue
        lines.append(f"## {cat} ({len(cat_rows)})")
        lines.append("")
        for row in cat_rows:
            name = row["label"] or row["name"]
            file_count = row["file_count"] or 0
            topic = row["label"] or row["name"] or ""
            age = fmt_age(row["last_active"])
            lines.append(f"- **{name}** — {file_count} files · {age}")
            if topic and topic != name:
                lines.append(f"  *{topic}*")
        lines.append("")

    out_path = settings.generated_path / "project-status.md"
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text("\n".join(lines), encoding="utf-8")
    return {"thread_count": len(rows), "output": str(out_path)}


def _fmt_size(n: int) -> str:
    """Human-readable size — MB to one decimal for anything ≥ 1 MB, else KB."""
    if n >= 1024 * 1024:
        return f"{n / (1024 * 1024):.1f} MB"
    if n >= 1024:
        return f"{n / 1024:.0f} KB"
    return f"{n} B"


def generate_extraction_skipped_report(skipped: list[dict]) -> dict:
    """Write a markdown report of files NOT indexed this maintain run.

    Two skip categories reported (unchanged-hash skips are intentionally
    excluded — most files most runs, would explode the report):

      - ``over_size``: file exceeded MAX_TEXT_EXTRACT_BYTES before extraction.
      - ``empty_extraction``: extractor ran but produced no usable text
        (binary type without transcript, image-only PDF, parse failure,
        extraction timeout).

    Rewrites ``generated/extraction-skipped.md`` in full each run — matches
    the existing ``generate_*_report`` pattern; current state is what matters.

    Returns ``{"skipped_count": int, "output": str}``.
    """
    cap_label = _fmt_size(MAX_TEXT_EXTRACT_BYTES)

    over_size = [s for s in skipped if s["reason"] == "over_size"]
    empty = [s for s in skipped if s["reason"] == "empty_extraction"]
    # Stable, useful ordering: biggest first for over-size; alpha for empty.
    over_size.sort(key=lambda s: s["size_bytes"], reverse=True)
    empty.sort(key=lambda s: s["rel_path"])

    lines = [
        "# Extraction Skipped",
        "",
        f"*Generated: {time.strftime('%Y-%m-%d %H:%M')}*",
        "",
        (
            "Files not included in the search index by the most recent maintain "
            "run. Re-generated each run — older entries replaced."
        ),
        "",
        f"Current extraction size cap: **{cap_label}**.",
        "",
    ]

    if not skipped:
        lines.extend(
            [
                "_No files skipped. All scanned files produced text for the index._",
                "",
            ]
        )
    else:
        lines.append(f"## Over size limit ({len(over_size)} files)")
        lines.append("")
        if over_size:
            lines.append("| File | Size | Cap | Extension |")
            lines.append("|------|------|-----|-----------|")
            for s in over_size:
                lines.append(
                    f"| {s['rel_path']} | {_fmt_size(s['size_bytes'])} "
                    f"| {cap_label} | {s['ext'] or '(none)'} |"
                )
        else:
            lines.append("_None._")
        lines.append("")

        lines.append(f"## Empty extraction result ({len(empty)} files)")
        lines.append("")
        lines.append(
            "Likely binary, image-only, unsupported format, or parse failure. "
            "Audio/video files without transcripts also land here."
        )
        lines.append("")
        if empty:
            lines.append("| File | Size | Extension |")
            lines.append("|------|------|-----------|")
            for s in empty:
                lines.append(
                    f"| {s['rel_path']} | {_fmt_size(s['size_bytes'])} "
                    f"| {s['ext'] or '(none)'} |"
                )
        else:
            lines.append("_None._")
        lines.append("")

    out_path = settings.generated_path / "extraction-skipped.md"
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text("\n".join(lines), encoding="utf-8")
    return {"skipped_count": len(skipped), "output": str(out_path)}
