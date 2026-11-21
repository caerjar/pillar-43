# Concept: the Pillar-43 org interface

The pick, 2026-11-19: **form C, the title file**, with two
scopes added by the maintainer: a whole-archive topic timeline (Explore) and a People view.
Forms A (the apparatus) and B (the facing page) were shown as static mockups and not
chosen. No graft was recorded; nothing from A or B is carried over except where noted
below.

## The form

A press keeps one file per title. The backlist is the way in.

- **Titles**: every book is a dated strip, contract to drafts, translation, print and
  reissue. The rights term is drawn as a band over time: where the grant ends, where a
  reversion window opens. Years with no records stay blank. They are not compressed or
  filled.
- **Ask, inside a title**: asking from a title's strip scopes the question to that title.
  This is also how the interface keeps answers from crossing titles.
- **Explore (whole archive)**: a topic, e.g. "yellow", across the whole press. One row per
  title plus a **Press** row for documents tied to no title. Each matching document is a
  dot at its date. Years without matches stay blank. A dot opens its passage, highlighted
  at its page. Below the rows is a short dated summary whose lines cite the dots. Beside it
  is the count of matching items not open to the AI, with the reasons.
- **People**: an authority record on the AtoM model, with name, relationship to the press
  and titles, over the same timeline. Each dot says how the document connects to the
  person: signed, wrote, received or mentioned.
- **The writer's screen**: a table of the writer's own items only, with columns for item,
  level (private / staff / model, each with a one-line meaning), labels, the dates the AI
  read it, and withdraw. Withdraw confirms in place.

## The AI-only move

**Every answer also shows what the archive could not say and why.** This is set in the same
layout as the answer, not as an error. A finding aid lists what is there. Pillar-43 reads
everything open to it at question time and answers with quoted clauses. It then names, in
plain lines with counts, what it was not allowed to read and for what reason: "3 letters
closed by their writer", "1 contract at staff level". In Explore, those items appear only as
a count with reasons and are never drawn as dots. The same consent filter that governs ask
runs before any cut, so the silence is exact.

The second move is the full consent-filtered search behind Explore and People. It returns
every matching passage, not a top-k sample, and the model writes only a short dated summary
whose every line cites one of those passages. The dots come from the search, never from the
model.

## References: what to take, what to leave

| Reference | Take | Leave |
|---|---|---|
| A publisher's title file | One file per title as the spine; dated order; contract first | The filing-cabinet look |
| Darwin Correspondence Project calendar | Dated, one-line-per-document listing; gaps visible as gaps | Scholarly abbreviations |
| AtoM authority record (ISAAR(CPF)) | Name, dates, relationship to the press, linked titles and records | The ISAAR field names on screen |
| Local Contexts labels | A label notice shown on the item it governs, in words | Treating labels as a hidden filter |
| Plinth legend (art/plinth, ~line 560) | Each kind of absence in one plain line with its count | Floor plan, palette, ritual voice |
| Folio review screen | (Intake, later) proposed consent per item, nothing applied until approved | |

## Furniture allowed, and why

- **Org ribbon** (Ask, Titles, Explore, People, and later the other views): a press learns
  one navigation. Files is admin-only, one click away.
- **Question field**: the primary gesture. It is a field, not a chat box.
- **Source panel**: following the citation to the highlighted clause at its page is the
  reason staff come back.
- **Elapsed seconds and a Stop button** while the model works: the wait is honest and can
  be cancelled.
- **The timeline rows**: the form itself. No zoom or pan controls. The years are the axis.
- **In-place confirm** for withdraw: an irreversible act on one's own work needs one more
  click, without a browser dialog.

Nothing else: no cards, no sidebars of suggestions, no settings on the first screen.

## Architecture (decided)

- No new frontend framework, component library or remote fonts. Tokens come from
  `web/src/design-tokens.css` and are extended there.
- Org views live under `web/src/components/Archive/<View>/`, reached from ORG_RIBBON and
  `web/src/lib/menu/menuModel.ts`.
- The role decides what renders, and the backend decides what is returned. Writers get only
  their own items. Any field a view needs is added to the Pydantic `response_model` and
  regenerated with `./scripts/codegen-types`. Nothing is derived client-side from a wider
  response.
- `ask.py` and RUNTIME_PROMPT stay at ask-v5. Explore's summary is a new route with its own
  call. It is not a change to ask.

## Never-list

From the brief (`pillar-43-interface-prompt.md`, NEVER-LIST):
- No chat bubbles, typing dots, assistant avatar, sparkle "AI" icons or "Ask me anything".
  An answer is a set text with its sources, not a message.
- No dashboard of cards and charts on the first screen. Gaps and usage are lists and tables
  whose every number links to its items.
- No padlock or traffic-light icons for consent. The level is written out with a one-line
  meaning, and label notices sit on the item they govern.
- No summaries of items, no generated blurbs, no "related items you might like" rail.
  (Explore's dated summary is a cited answer to the asked topic, not an item summary.)
- No archivist jargon on screen (fonds, accession, ISAD(G), siglum unexplained) and no
  personal-Pillar-43 vocabulary (Oracle, Today, threads, dispatch).
- No skeleton shimmer while the model works: elapsed seconds and a Stop button.
- No drag-only control, no hover-only information, no browser alert/confirm dialogs.
- No real press material, names or screenshots: the synthetic press only.
- Silences are never shown as an error or in a warning colour.

`docs/org-edition.md` §6 applies in full on top of these.
