# Pillar-43 — Local Archive, architecture and status

The organization edition of Pillar-43, first built for a small poetry and translation press.

**Name (2026-11-19):** the product is Pillar-43 and the public repo is
`pillar-43` (renamed 2026-11-20). The org edition's
on-screen title ("Pillar-43 - Local Archive", set in org.yaml), the desktop menu,
the README and the export use it. The video was recorded under an earlier name;
the Mozilla application text uses Pillar-43 (it briefly said Pillar-13). The rename of the package, identifiers, compose project and volumes is done (clean break, no migration). Product and interface: `docs/org-edition.md`.

Status markers: **built** (in the branch, tested), **next** (milestone 2),
**later** (incubator year).

## Decisions

**Base: this app, not caer-stack.** It already has the catalog, local
transcription, handwriting, cited retrieval through one chokepoint, a desktop
app and the Commons. caer-stack is an appliance for a community node; Pillar-43
is the archive a staff member sits at. We copy caer-stack's take-down test, not
its stack.

**One behaviour.** The profile switch was removed in P2 (2026-11-20): the app is
the press archive and reads `ORG_CONFIG` (an org.yaml). Nothing
organization-specific is in code: kinds, the folder globs that classify them,
default consent per kind, roles, rights fields and model names live in
`api/orgs/<org>.yaml`. The example is `api/orgs/press.yaml`. **built**

**Models, all local.** qwen3:8b through Ollama on the host for answers and
extraction; qwen2.5vl:7b for scans (**next**); the in-process fastembed
embedding model Pillar-43 already uses. In the org profile the `config.py`
getters for chat provider, API keys, base URL and transcription provider
short-circuit to local, so no value from `.env`, the saved config or the
Settings UI can select a hosted model; `_whisper_api` refuses as a second lock.
`tests/test_archive_profile.py` sets every hosted option from all three
sources and asserts none takes. **built**. `tests/test_archive_no_egress.py` runs intake and ask with every
non-loopback `connect` refused and recorded; the one allowed host is the
configured `OLLAMA_URL` (`host.docker.internal` in the container). Watched
failing with one injected outbound call. **built**

**Vectors stay in SQLite.** One file holds items, consent, tombstones, chunks
and vectors, so a withdrawal is one transaction. Brute-force numpy search is
single-digit milliseconds at 22k chunks. Revisit at ~200k chunks or when
filtering must happen inside the index; first step then is sqlite-vec (same
file), not a second store. Rationale in `api/services/vector_store.py`.

**Consent lives in a table, not in paths.** Migration `0022_archive_items`:
`item(id, path, sha256, kind, title_isbn, people, consent, consent_by,
consent_at, ledger_seq)` and `tombstone(sha256, withdrawn_by, at)`. Levels:
`private` (held, not searchable), `staff` (searchable and cited to staff, never
sent to the model), `model` (the model may read it at question time). **built**

**Enforced in `fetch_materials`, for every caller.** In the org profile the
chokepoint filters on consent before hydration and before the limit; a caller
that names no audience gets `model`, because every caller that predates the
org profile feeds a model. A file with no item row is treated as private (fails
closed). `fetch_materials_counted` also returns how many matches consent
withheld, as a number only. Guards: `tests/test_archive_ask.py` — removing the
filter fails three of them (watched 2026-11-17). **built**

**Withdrawal** writes a tombstone and calls `catalog/forget.forget_file`;
intake refuses tombstoned hashes (`register_item` already does). **built** (C1: `services/archive/withdraw.py`, CLI `withdraw`, `POST /api/archive/withdraw`; earlier answers are recorded in `answer`/`answer_citation` and flagged by `GET /api/archive/answers/{id}`; the item row stays, forced to `private`, with `withdrawn_at`.)

**Ledger**: Folio's append-only hash-chained ledger as the provenance record;
every intake, consent change, withdrawal and model call is a line; `verify`
proves nothing was edited. **built** (C2: table `ledger`, kinds `intake`, `consent`, `withdraw`, `model_call`; line hash = sha256 over seq, time, kind, actor, subject, data and the previous hash; `verify` names the first broken line. Each answer's `receipt_id` is its `model_call` line, which lists every item whose passages were in the prompt; "read by the AI N times" counts those lines per item. An unchanged re-run of intake writes no line.)

**Labels (writers' terms)** are defined in `org.yaml` and stored on
`item.labels` (migration 0025). **built** (C3). Enforced, not displayed: at
retrieval `items.allowed_paths(audience="model", purpose, role)` drops an item
any of whose labels does not permit the purpose (`ask` by default); jobs and
training sets pick items only through `labels.select_for(conn, purpose)`.
Purposes: `ask`, `teaching-packet`, `editorial-history`, `training`,
`export`. Each job has its own purpose, so a label can allow or refuse the
editorial history alone (E1c). "teaching only" = only `teaching-packet` and
`editorial-history`; "ask the estate" = nothing until cleared;
"translators of this book only" = `ask` for role `translator` (tying a role to
a title is C6); "never for training" = deny `training`; "attribution required"
= carried, enforced at display. An unknown label id closes the item (fails
closed). CLI `labels`, `POST /api/archive/items/labels`; each change is a
`labels` ledger line.

**IETF AI-preferences mapping.** Draft recorded: `draft-ietf-aipref-vocab-08`
(14 Sept 2026, expires 18 Mar 2027; read at datatracker.ietf.org/doc/
draft-ietf-aipref-vocab/ on 2026-11-18 through a fetch summary, not the raw
text: **verify against the draft before publishing**; it is a working-group
draft without consensus). Vocabulary used: `train-ai`, `ai-use`, `search`,
values `y`/`n`. Mapping: never for training -> `train-ai=n`; teaching only,
ask the estate, translators only -> `train-ai=n, ai-use=n` (the vocabulary
has no purpose or role, so the local purpose rule is stricter than what the
terms can say); attribution required -> no term. The terms show as `aipref`
on `GET /api/archive/items/reads`. Carrying them on every export, packet and
published item is **next** (jobs, E1). The draft number is `aipref_draft` in
`org.yaml`: track the draft by changing it there.

**Annotations (right of reply)** **built** (C4, migration 0026). A signed, dated
note attached to an item or to one passage (`ordinal`); `POST /api/archive/annotations`,
`GET /api/archive/annotations?path=`, `POST .../{id}/retract`. Append-only: a note
is retracted (hidden, ledger line kept), never edited. `ask` returns each passage
with its `annotations`; the model never reads them (tested against the recorded
prompt). Items staff may not see cannot be annotated.

**Silences** **built** (C5, migration 0027). Every answer carries `silences`:
`closed` (the withheld count), `missing_correspondents`, `empty_years` and a
`line` Ask shows under the answer ("3 items closed by their writers; Ana R.'s
replies are not in the archive; nothing from 2013-2015"), all computed in
`services/archive/silences.py`, none by the model. Logged on the answer row;
`GET /api/archive/gaps` aggregates them across questions (the Gaps view is C7).
Decision (agent, needs maintainer review): a correspondent is named by an item's
`people` entry with role `correspondent`, and counts as missing when no
non-withdrawn letter or email lists them with role `author`; the years in scope
are the years (or ranges like 2012-2014) the question names, a year is empty
when no non-withdrawn item has that `item.year`, whatever its consent (a year
with only closed items is counted under closed instead). `item.year` is read
from the first 19xx/20xx in the path at intake. `people` is not populated by
anything yet (email intake, D1, will), so on real material the correspondent
silence stays empty until then.

**Accounts and roles** **built** (C6, migration 0028). `admin`, `staff`, `writer`;
local only: scrypt-hashed passwords, a random session token in an HttpOnly,
SameSite=Strict cookie (only its SHA-256 is stored), no OAuth. Login and account
routes refuse a non-loopback `Host` (login does not: the web proxy rewrites `Host`, and writers sign in from their own devices). The archive stays open until the first
account exists (which must be an admin); from then on every `/api/archive/*`
route and every other `/api` route needs a session, except `profile` and
`login`. Admin: everything. Staff: ask, ledger, gaps, annotate, read what
consent opens to staff; cannot set consent. Writer: sees and controls only
their own items (`items/reads` lists them, closed ones included;
`items/consent`, `items/labels`, `withdraw`, `annotations` on them); no ask,
no ledger, no gaps, no staff file views. The actor written to the ledger is the
session's account, never the request body. CLI `account`, `owner`; routes
`POST /accounts`, `GET /accounts`, `POST /accounts/{name}/items`, `login`,
`logout`, `me`, `POST /items/consent`.

**Decision (agent, needs maintainer review): how a writer is tied to items.** An
admin links them explicitly (`item_owner`); names in `item.people` are not
matched automatically, because they are free text and a wrong match would hand
someone control of a stranger's work. Also decided: staff cannot change
consent (it is the writer's to give; an admin can act for a writer who asks);
writers never use Ask, because Ask answers from other people's open items; the
open-until-first-account bootstrap; the model-call ledger line's actor is still
`ask`, not the asking account.

## The ask path — consent the model cannot get around

1. Retrieval with `audience="model"`; ≤ 8 passages, each split into numbered
   sentences (clause numbers kept with their clause).
2. A JSON schema built per question and sent as Ollama's `format`: `cites` and
   `quote.passage` are enums of this question's passage numbers; each
   `quote.sentence` is bounded by its passage's sentence count. Ollama compiles
   the schema into a grammar that masks disallowed tokens, so an out-of-set
   cite cannot be emitted. Quotes are pointers; code inserts the words.
3. The validator, for what a grammar cannot see. First probe (2026-11-17): the
   model was told to cite passage 7 and could only emit `cites: [1]` — but it
   wrote "passage [7] … 'rights never revert'" into the free-text sentence,
   set `not_answered: true` alongside an answer, and restated the question as a
   sentence. So the validator drops sentences that name a passage outside the
   set, carry a quotation that is not verbatim in a cited passage, or restate
   the question; and an answer that survives is an answer.

"Cannot write a quotation" therefore holds for the grammar plus validator
together, not for the grammar alone. That is the honest claim.

4. Milestone 1 fixes (A1-A4, 2026-11-18). Each passage header carries the
   item's title and ISBN, and a cite whose passage shares no content terms
   with its sentence is dropped, so a question about one book cites that
   book's contract (A1). A free-text sentence that copies a passage sentence
   (high token overlap) is turned into a quote pointer or dropped, so
   unmarked quotation cannot reach the reader (A2). Retrieved passages are
   extended to sentence edges, so no passage starts mid-sentence (A3, at
   retrieval, no reindex). The prompt has a worked `not_answered` example and
   code checks the question's key terms against the passages, so the archive
   declines when it holds no answer (A4). Headings, letterhead and addresses
   (`ask.is_heading`: short, title case or capitals, no closing punctuation,
   no year or amount) are shown as unnumbered `##` lines, left out of the
   schema's sentence enum, never re-pointed to, and a sentence repeating one
   is dropped (A8).

**Bounded arrays are part of the constraint.** The first run of the test set
hung on question 1: with `cites` unbounded, qwen3:8b at temperature 0 emitted
`[2, 2, 2, …]` until the 300 s timeout, every time. `cites` is now `maxItems`
3 and `answer` `maxItems` 6, enforced by the same grammar, with `num_predict`
1200 as a backstop (a cut-off is reported as `truncated`). That question went
from >300 s to 10 s.

Measurement on 50 questions (`fixtures/press-eval/`, scorer
`scripts/archive_score.py`, scored against the consent in force; a question
may have alternative source sets, A5). qwen3:8b, constrained, on this Mac:

| | baseline 2026-11-18 (rescored) | after A1-A4, 2026-11-19 |
|---|---|---|
| accuracy, all 50 | 0.36 | 0.62 |
| accuracy, 23 answerable now | 16/23 | 13/23 |
| correct declines, 27 not answerable | 0 | 18 |
| misquote rate | 0 | 0 |
| seconds p50 / max | 12.6 / 31.3 | 6.2 / 16.9 |

The gain is declines; answerable accuracy fell by three. Open: headings and
letterhead kept as the answer sentence, declines that are too eager, 9
answers where the archive has none (NEXT A8-A10). Details:
`docs/eval/2026-11-19-clean.md`. Unconstrained comparison: **next**.

Runtime prompt: `services/archive/ask.py:RUNTIME_PROMPT` (`ask-v1`).

## Running it

`make archive` does the setup in one step, as its own compose project (`pillar43`)
on API 8061 and web 5211: bring-up, intake, index, contracts open to the AI. Then
`make archive-ask Q="…"`, `make archive-stop`. Ports and project name can be
overridden (`ARCHIVE_PROJECT`, `ARCHIVE_API_PORT`, `ARCHIVE_WEB_PORT`).

By hand:

```
docker compose -p archive --env-file .env.archive \
  -f docker-compose.yml -f docker-compose.archive.yml up --build -d
docker exec archive-api-1 python scripts/archive_cli.py intake
docker exec archive-api-1 python scripts/archive_cli.py counts
docker exec archive-api-1 python scripts/archive_cli.py consent kind:contract model --by "<staff name>"
docker exec archive-api-1 python scripts/archive_cli.py ask "When can the estate get the rights back?"
```

API on 127.0.0.1:8041, web on 127.0.0.1:5191. `LIBRARY_ROOT` in `.env.archive`
is the synthetic press (`fixtures/synthetic-press`, fully invented; rebuild with
`python3 fixtures/make_synthetic_press.py`). On the maintainer's machine it is changed to
a press's real folder; only `stats.json` and counts come back.

**Native menu and phone title (2026-11-18).** The macOS app builds its menu in
Rust from generated JSON; `scripts/codegen-menu` now also emits
`menu_model_org.json` (the model through `orgProfile.ts`: Pillar-43 and Go) and
`menu.rs` picked it under the org profile (P2 final: the profile switch and
that second model are gone; the one model is the archive menu). At 600px and below the top bar
drops the in-app menu and the search label so the title fits. Guards:
`orgProfile.test.ts`, the codegen drift check, a Rust test. Compiled
2026-11-19 (cargo build; `cargo test` 21 passed, including the org menu test,
watched failing with the full model). Launching the app under the org profile
is a maintainer hand check. **built**

**Audit 2026-11-18 (`main...archive`).** Fixed: profile `nav` advertised six
views that do not exist (nothing in the frontend reads it); the transcription
lock re-implemented the org check inline. (The profile switch itself was removed in P2 final.)

**Email (stage 2b), built.** `services/archive/mail.py`. An .mbox/.eml is
registered as its file item plus one item per message and one per attachment,
using the existing columns: `path` is the mailbox path plus
`#<thread>/<message>[/<n>-<file>]` (a child's path starts with its parent's),
`sha256` is the message's raw bytes (so a withdrawn message stays out on
re-intake), `people` holds sender and recipients as `correspondent`. Everything
is private; attachments are kind `attachment`, so `consent kind:document` cannot
open them by accident. The catalog indexes decoded text (From/To/Date/Subject
and body). Each message has its own catalog row and chunks, so ask cites it
singly under its own consent, and a correspondent's recorded consent
(`consent person:ADDRESS`) carries to every message they sent (D1b). A message
is indexed by its sender's own words only: quoted `>` lines, the "On ...
wrote:" line above them, and an Outlook "Original Message" tail are left out
(`mail.own_words`, D1c), so a consenting sender never makes a non-consenting
correspondent's words citable. Those words are citable only through the
correspondent's own message, under their consent.

**Tracked changes (stage 2d), built.** `services/archive/docx_changes.py`
reads `w:ins`, `w:del` and `comments.xml` (author, date, words). Each
insertion, deletion and comment is an item of its own
(`<file>#change/<kind>-<key>`) recording its paragraph index and the
paragraph's final text, indexed as one sentence saying who, what and when
("Wren Tallowfield deleted "1 June" on 2026-06-02."), so a quotation of it
carries the attribution (D2b). It starts at the manuscript's consent and can be
set alone, so a private editor's comment stays out while the manuscript is
open; a re-intake keeps the level set. In the org profile the manuscript's own
text no longer carries the history.

**Offline index, built** (B1b). The embedding model (bge-small-en-v1.5,
~65 MB) is baked into the api image and loaded with `local_files_only` under
the org profile, so indexing never reaches Hugging Face;
`test_archive_no_egress` covers index as well as intake and ask.

**Jobs, built** (E1, E1b, E1c). `services/archive/jobs.py`, CLI
`archive_cli.py job editorial-history|teaching-packet|rights-answer "<title or
ISBN>" [--cover-note]`. A job is a folder under `generated/archive/jobs/`
assembled by code: the items in original (path) order, `manifest.json` with
each item's labels, aipref string and ledger receipt, the job's text, and one
`job` ledger line. Items enter only through `labels.select_for`, so private,
withdrawn and label-denied items are not in the folder and not counted. Each
job has its own purpose (`ask` for the rights answer, `teaching-packet`,
`editorial-history`), so a label can allow or refuse one job alone. Without a
cover note no model reads anything, so a job takes staff-level items; with
`--cover-note` (the one model call, at most three cited sentences) the whole
job is built from model-level items. The rights answer quotes the title's
contract clauses verbatim; the editorial history is the .docx tracked changes
plus the letters and email about the title. `stats` and `colophon` write
`generated/archive/stats.json` and `COLOPHON.md` (models, consent counts,
withheld counts, the ledger head and whether the chain holds) by code.

**Open test archive, built** (E3). `scripts/package-test-archive.sh <dir>`
packages the synthetic press, the 50 questions, the answer keys and a scorer
that needs only Python 3.10 (`run_score.py`), with the archive under CC BY 4.0,
so another archive tool can be scored on the same questions.

## Training a local model (decided, not built)

Decided 2026-11-19 (F1): one fused model per collection, rebuilt on demand.
LoRA on the host with mlx-lm, `mlx fuse --dequantize`, then `ollama create
<collection> FROM` the safetensors with `-q int8`. Ollama 0.40 refuses
Modelfile `ADAPTER`, so separate adapters loaded per question are out. Only
items at `model` level whose labels permit `training` go in. Adding or removing
an item never edits the model: the collection shows "changed, model not
rebuilt" until a full retrain from the base model (no continued training, so a
removal is real), and a removal counts as done only when the old model is
`ollama rm`'d. Tiny run measured on Llama-3.2-1B: 42 s, 2.0 GB peak, fused
model 1.6 GB. An 8B model is about 5 GB per collection. Next: the host runner
and a Train screen (F2).

## Incubator-year plan (not built)

Export to an
ArchivesSpace/AtoM-compatible format; a writer's view from a phone on the
office network; backups a non-technical admin can restore.
