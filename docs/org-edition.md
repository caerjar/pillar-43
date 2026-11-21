# Organization edition ("Local Archive")

First site: a small poetry and translation press.
Point `ORG_CONFIG` at an `org.yaml`. (An earlier profile switch, with a
personal default; P2 removed it and the personal behaviour with it.) On screen the app is
titled "Local Archive".

Code is never deleted for org. Org only hides: the nav entry goes, the route answers 404,
and a test asserts both. Sections 1-8 were written as the plan before the build;
sections 9 and 10 say what is built (2026-11-19) and what is not.

## 1. Who uses it

- **Press staff.** Ask the press a question. Browse what has been opened to staff.
- **Writers** checking their own work. They see only their own items and set consent on them.
- **One admin.** Intake, Settings, Ledger, and the file tree (one click away, admin only).

Open point: the app has no authentication today (the maintainer notes, Security: loopback only).
Staff, writer and admin views need an identity step. That is a product decision for the
first milestone and is not designed here.

## 2. The two gestures

**(a) Ask, then follow the citation.** Staff type a question. Every sentence of the answer
carries a citation. Clicking it opens the source at the place: a PDF at the page with the
passage highlighted, a letter, a set of minutes, a recording playing from that second.
The answer also names what it could not read (see the plinth below). Rights questions quote
the contract clause and never paraphrase it.

**(b) A writer sets what may be done with their work.** Three levels, set per item:

| Level | Meaning |
|---|---|
| private | Held. Not searchable. |
| staff | Searchable and cited to staff. Never sent to the model. |
| model | The model may read it at question time. |

Plus **Withdraw**: the item is tombstoned and cannot be re-imported. Each item shows
"Read by the AI N times", a receipt per question that touched it, listed in the Ledger.

## 3. Data model and vocabulary

Underneath, the record structure follows archival standards so export is lossless:
ArchivesSpace (accessions, resources, digital objects, agents, subjects) and AtoM / ISAD(G)
(fonds, series, file, item). On screen the words are Titles, People, Collections, Intake,
Items. Archivist jargon (fonds, accession, ISAD(G)) never appears in the org UI.

| On screen | Underneath |
|---|---|
| Titles | resources (a book, a manuscript) |
| People | agents (authors, translators, staff) |
| Collections | series / files, in original order |
| Intake | accessions |
| Items | digital objects / items |
| topics | subjects, an index only |

Original order is kept inside a collection. Topics are an index over it, never a re-filing.

## 4. Navigation in org

Ask, Titles, People, Collections, Recordings, Intake, Ledger, Settings.

- File tree: admin only, one click away. No editor as the main view.
- Settings lists local models only. No provider keys, no cloud sources.
- Recordings reuses Transcribe (local faster-whisper). Intake reuses catalog inbox and the
  archivist review. Ask, Titles, People, Collections and Ledger are new views over the
  existing catalog and search routes.

## 5. References and what to take from each

| Reference | Take | Leave |
|---|---|---|
| ArchivesSpace, AtoM | Record structure; the finding aid as the public face. | The vocabulary and the forms. |
| Folio intake review | Folio proposes a reorganisation, shows it, and moves nothing until you approve; reversible, offline, ledgered. Take the plan-you-approve screen for Intake: staff review a proposed description and consent, then accept. | Its re-filing. Here the plan assigns description and consent, never a new location. |
| Ars Electronica plinth | An answer that names what it could not read, every time. Offered / held / sealed as ancestor of staff / private / model: offered is read and cited, sealed is a count and never content, held is not even counted. | Its performance register, theatre, dark palette. |

Consequence of the plinth rule for private items: the Ask view may say "N items could not
be read" only for staff-level items it was not allowed to send to the model. Private items
are not counted at all.

## 6. The never-list

- No chatbot persona, avatar, name or greeting, and no "Ask me anything".
- No text written in an author's voice, no "in the style of", no summaries presented as the author's, no generated blurbs or jacket copy.
- No answer sentence without a citation, and no paraphrased contract terms: rights answers quote the clause.
- No hosted model, telemetry, analytics script or remote font. The app works with Wi-Fi off; a test proves it.
- No real press contract, letter, recording or unpublished text in a commit, a fixture, a screenshot or the video, unless the press cleared it.
- No dashboard of charts, engagement metrics or "AI insights" cards; three views, labels that name things.
- No fine-tuning on writers' work in this prototype. The `model` level means "may be read at question time", nothing more.
- No re-filing of the archive by topic. Original order is kept; topics are an index over it.
- No email body, address or attachment leaves the machine, appears in a log line, or reaches the model before staff have reviewed its consent. No reading of a whole mailbox by the model "to summarise it".
- No handwritten note shown only as machine text: the image is always one click away, and the reading is marked as a reading.
- No personal-vault vocabulary in the org profile: no Oracle, Dive, alive / latent / dormant threads, Today, Catch up or Counter-Archive. No archivist jargon on screen either (fonds, accession, ISAD(G)).
- Nothing removed from the personal profile.

## 7. The audit

Status words:

- **keep**: available in org as is (some with a stated restriction).
- **rename**: kept, relabelled or re-pointed for org.
- **hide**: personal-practice feature. Neutral to the never-list; org hides it.
- **remove**: conflicts with the never-list (outside calls, authored text, persona). Org has
  no path to it, the route 404s, and a test asserts the absence. Code stays.

"Where" says what the implementer switches: **nav** (entry hidden), **route** (404 in org),
**both**, or a dash when nothing is hidden. Line references were read on 2026-11-17.

### 7a. Where to switch

The frontend can learn the profile from two existing responses, add one field to each:

- `GET /health` (`api/main.py:285`, `health()`): unauthenticated, cheap, already polled by
  the desktop shell. Add `"profile": "personal" | "org"`. Best for first paint.
- `GET /api/settings` (`api/routes/settings.py:34`, `_settings_response()`): the shape the
  web already reads through `web/src/lib/api/settings.ts`. Add `profile` plus the parsed
  `org.yaml` fields the UI needs (title, nav list).

Backend gate: routers are registered in `api/main.py:234-260`. Wrap the hidden ones in one
dependency, `include_router(x, dependencies=[Depends(personal_only)])`, that returns 404
when the profile is `org`. The `/mcp` mount (`api/main.py:263`) needs the same gate.

Frontend nav files, all of which must read the profile:

- `web/src/components/ActivityBar.tsx`: `RIBBON` (Files, Threads, Tasks), Home button, AI icon.
- `web/src/lib/menu/menuModel.ts`: `DESTINATIONS` (~117-128), `RUNS` (~143), the
  `research.ask` entry (~461), `go.home`. This one model feeds the MenuBar, the command
  palette (`CommandPalette/commands.ts`) and the native macOS menu
  (`desktop/src-tauri/src/menu.rs`), so filtering it once covers all three.
- `web/src/components/MenuBar/MenuBar.tsx`: renders the model.
- `web/src/App.tsx`: the `leftTab ===` switch (~506-516, 532), the Home empty state
  (~666-671 lists Voice and others), and the first-run wizard gate (~699-726).
- `web/src/stores/appStore.ts`: the `LeftTab` type. Org adds `titles`, `people`,
  `collections`, `recordings`, `intake`, `ledger`.
- `web/src/components/Settings/groups.tsx`: `SETTINGS_GROUPS`, the list that drives both
  the Settings nav and its content.

### 7b. Route modules (`api/routes/`)

| Module | Status | Where | Reason |
|---|---|---|---|
| `__init__.py` | keep | - | Empty package marker. |
| `_sse_worker.py` | keep | - | Shared SSE scaffold for transcription and handwriting. Not a router. |
| `ai_helpers.py` | keep | - | Shared helpers for `ai/`. Not a router. |
| `files.py` read side: `/tree`, `/file`, `/file/raw`, `/file/pdf-page`, `/file/pdf-info`, `/file/text`, `/file/find`, `/file/cataloged` | keep | - | File serving, preview, PDF rendering: the citation target. |
| `files.py` write side: `/file` POST, `/file/new`, `/folder*`, `/file/move`, `/file/trash`, `/file/rename`, `/file/duplicate`, `/trash*`, `/file/restore`, DELETE `/file` | rename | - | Admin only; becomes Intake and file-tree actions. Never available to staff or writers. |
| `files.py` `/file/backlinks`, `/file/annotation-path`, `/file/git-tracked`, `/files/recent-changes` | hide | route | Note-editor features; Recent and git are personal. |
| `vault.py` | keep | - | `library/status` is the first-run gate; org reads `org.yaml` instead of the wizard copy. |
| `setup.py` | rename | - | First-run and reset; org replaces the wizard steps with the `org.yaml` load. `/setup/reset` admin only. |
| `settings.py` | rename | - | Same endpoint; org response lists local models only and omits cloud-provider keys. Adds `profile`. |
| `settings_paths.py` | keep | - | Path staging for mounts; admin only. |
| `search.py` | keep | - | ripgrep full text. Org filters results by consent level server-side. |
| `jobs.py` | keep | - | Background job list and cancel; feeds Intake progress. |
| `links.py` | keep | - | Reference queries; basis for "mentioned in" on People and Titles. |
| `handwriting.py` | keep | - | Local vision model only; reading is marked as a reading, image one click away. Cloud path blocked. |
| `transcription.py` | keep | - | Local faster-whisper only. The hosted Whisper API upload path is blocked in org. |
| `commons.py` | keep | - | Milestone 3 only; `COMMONS_ENABLED` stays off until then. |
| `archivist.py` | rename | - | Duplicate review becomes the Intake review screen; detritus review hidden. |
| `ai/__init__.py` | keep | - | Router shell and the `routes.ai.X` test-patch shim. |
| `ai/_provider.py` (`/ai/ping`, `/ai/local-models`) | keep | - | Local model discovery. `ping` of a non-local base URL is refused in org. |
| `ai/_chat.py` (`/ai/chat`) | rename | - | Becomes Ask: org prompt, retrieval limited to staff/model items, citation required per sentence, no persona. |
| `ai/_classify.py` (`/ai/classify`) | hide | route | Personal note classification; Intake proposes description instead. |
| `ai/_inline.py` (`/ai/inline`) | remove | route | Writes text into the editor; org has no editor and no authored text. |
| `ai/_folder_generate.py` (`/ai/folder/generate`) | remove | route | Generated folder summaries are summaries presented as the archive's own. |
| the persona-agent route module | remove | route | The Pillar-43 Agent: a named persona with reflect, patterns and interests. |
| `catalog/__init__.py`, `catalog/_helpers.py` | keep | - | Router and SSE plumbing. |
| `catalog/run.py` (`/catalog/run`, `/force-stop`) | keep | - | The index run; Intake triggers it. |
| `catalog/read.py` `/stats`, `/breakdown`, `/status`, `/estimate`, `/` | rename | - | Feeds Intake and admin counts. Counts shown as plain lists, no chart panels. |
| `catalog/read.py` `/threads`, `/orphans`, `/figures`, `/gaps` | hide | route | Thread and figure views of the personal vault. |
| `catalog/read.py` `/detritus`, `/ghosts` | hide | route | Counter-Archive remnants and personal cleanup. |
| `catalog/passes/__init__.py` | keep | - | Registers the passes. |
| `catalog/passes/inbox.py` (`/inbox`, `/inbox/delete`, `/inbox/move`) | rename | - | Becomes Intake. Move must propose, not file by topic (never-list: re-filing). |
| `catalog/passes/reindex.py`, `reextract.py` | keep | - | Index maintenance after intake or model change. |
| `catalog/passes/dedup.py` | keep | - | Duplicate detection for Intake review. |
| `catalog/passes/admin.py` (`DELETE /catalog/reset`) | keep | - | Admin only, behind the destructive-operations confirm. |
| `catalog/passes/connections.py` (`/connections`, `/load-bearing`) | hide | route | Interest-map edges; org uses linked mentions only. |
| `catalog/passes/tasks.py` (`/tasks`) | hide | route | Task mining for the personal Kanban. |
| `catalog/passes/dispatch.py` (`/dispatch`) | hide | route | Generator for the daily dispatch. |
| `catalog/passes/review.py` (`/periodic-review`) | hide | route | Personal note review cadence. |
| `catalog/passes/voice_profile.py` (`/voice-profile`) | remove | route | Learns the user's writing voice; org forbids text in an author's voice. |
| `connections.py` | hide | route | Suggested note-to-note edges. |
| `graph.py` | hide | both | Whole-vault graph; Graph tab and `/graph/local`. |
| `history.py` | hide | both | Git history of `notes/`; History tab. |
| `threads.py` | hide | both | Alive / latent / dormant threads; Threads tab. |
| `analyze.py` (`/analyze/dormant-threads`) | hide | route | Dormant threads, named in the never-list. |
| `tasks.py` | hide | both | Mined `[ ]` tasks; Tasks tab. |
| `reading_queue.py` | hide | route | Personal reading queue markdown file. |
| `recap.py` | hide | route | Daily and range recaps from the git log. |
| `dispatch.py` | hide | both | Daily dispatch read endpoint; Home cards. |
| `saved_searches.py` | hide | route | Personal saved queries; may return for staff later. |
| `scheduled_jobs.py` | hide | route | Settings panel for cron and watcher; admin sees Jobs instead. |
| `notifications.py` | remove | route | Email and Telegram send; nothing leaves the machine. |
| `sources.py` | remove | both | Google Drive, Dropbox OAuth and Apple Notes import; cloud ingest. Intake takes local files. |
| `/mcp` mount (`main.py:263`, `mcp_server.py`) | remove | route | Exposes the vault to outside agents; bypasses consent checks. |
| `/health` (`main.py:285`) | rename | - | Gains `profile`. |

### 7c. Web components (`web/src/components/`)

| Item | Status | Where | Reason |
|---|---|---|---|
| `ActivityBar.tsx` | rename | nav | Org rail: Ask, Titles, People, Collections, Recordings, Intake, Ledger. Settings in the window. |
| ActivityBar: Home | remove | nav | Greeting and dispatch Home; the vocabulary in the never-list ("Today"). |
| ActivityBar: Files | rename | nav | File tree, admin only. |
| ActivityBar: Threads | hide | nav | Thread map. |
| ActivityBar: Tasks | hide | nav | Kanban of mined tasks. |
| ActivityBar: AI toggle | rename | nav | Becomes the Ask view, not a sidebar toggle. |
| `MenuBar/` | rename | nav | Reads the filtered `menuModel`; org items only. |
| Go menu: Recent | hide | nav | `RecentPanel`. |
| Go menu: Graph | hide | nav | `GraphView`. |
| Go menu: Commons | keep | nav | Milestone 3; hidden until `COMMONS_ENABLED`. |
| Go menu: Voice | rename | nav | Relabel Recordings; local transcription only. |
| Go menu: History | hide | nav | Git history. |
| Go menu: Maintain | hide | nav | Personal indexing and dispatch panel. |
| `RUNS` (Run Index / Task Rollup / Connections / Daily Dispatch / Inbox Processor) | hide | nav | Index and Inbox move to Intake; the rest are personal. |
| `AISidebar/AISidebar.tsx` | rename | nav | Skill buttons and persona chat removed; reused only for streaming rendering in Ask. |
| `AISidebar/MarkdownMessage.tsx` | keep | - | Renders answers; needs a citation-link renderer. |
| `AISidebar/RelatedPanel.tsx` | hide | nav | Related-note suggestions from embeddings. |
| `CommandPalette/` | rename | nav | Reads the model; org command set only. |
| `Search/SearchPalette.tsx` | keep | - | Full-text and semantic search; consent filter applied server-side. |
| `Search/sections/SavedSearchesSection.tsx` | hide | nav | Saved searches. |
| `Search/sections/FileResults.tsx` | keep | - | Result list. |
| `FileTree/` | rename | nav | Admin only. Original order is its native structure. |
| `Editor/Editor.tsx` | hide | both | CodeMirror editing; no editor as main view. Read-only viewer remains. |
| `Editor/PDFViewer.tsx` | keep | - | The citation target: page and highlight. |
| `Editor/InlineAI.tsx`, `useInlineAI.ts` | remove | both | Writes text in place. |
| `Editor/LinkSuggestions.tsx`, `useLinkSuggestions.ts` | hide | nav | Wikilink suggestions. |
| `Editor/BacklinkGraph.tsx` | hide | nav | Graph of backlinks. |
| `Editor/NoteProperties.tsx` | hide | nav | Frontmatter editor. |
| `Editor/FileActionsMenu.tsx` | rename | nav | Admin file actions only. |
| `Editor/FileActivityPill.tsx` | hide | nav | Personal activity chip. |
| `FolderArtifact/` | remove | nav | Folder-level generated summaries. |
| `Dispatch/` | hide | both | Daily dispatch cards. |
| `Today/HomePanel.tsx` | remove | both | "Today" Home; greeting is also a banned greeting. |
| `Graph/` | hide | both | Whole-vault and local graph. |
| `History/` | hide | both | Git history. |
| `Recent/` | hide | both | Last-opened files. |
| `ThreadMap/` | hide | both | Alive / latent / dormant clusters. |
| `TaskBoard/` | hide | both | Kanban. |
| `Maintain/` | hide | both | Do not decompose (its the maintainer notes). Contains "Catch up" and Dive. |
| `Transcribe/` | rename | nav | Recordings. Audio plays from the cited second. |
| `Commons/` | keep | - | Milestone 3 only. |
| `Setup/` | rename | - | First-run wizard replaced by `org.yaml` load for org. |
| `ui/` | keep | - | Primitives; no profile logic. |
| `Settings/SettingsWindow.tsx`, `groups.tsx`, `controls.tsx`, `PathRow.tsx` | keep | - | Window and group list; groups filtered by profile. |
| `Settings/ProviderCard.tsx` | hide | nav | Cloud provider cards. |
| Settings group: Identity | rename | - | Press name and roles from `org.yaml`. |
| Settings group: AI & Models | rename | - | Local models only (Ollama, llama.cpp, LM Studio). |
| `sections/AiModelsSection.tsx`, `detectProvider.ts` | rename | nav | Groq, Gemini, Anthropic, OpenAI cards hidden. |
| `sections/TaskModelRoutingSection.tsx` | hide | nav | Per-task cloud routing. |
| `sections/MultimediaSection.tsx` | rename | nav | Local faster-whisper only; Whisper API upload hidden. |
| `sections/VoiceStyleSection.tsx` | remove | nav | Writing-voice and style settings. |
| Settings group: persona agent (`AgentPolicySection`, `ResearchInterestsSection`) | remove | nav | Persona, policy and interests. |
| `sections/SourcesSection.tsx`, `GoogleDriveSource.tsx`, `DropboxSource.tsx`, `useSourceSync.ts` | remove | nav | Cloud sources. |
| `sections/CommonsSection.tsx` | keep | - | Milestone 3 only. |
| `sections/BackgroundJobsSection.tsx` | hide | nav | Cron and watcher panel. |
| `sections/NotificationsSection.tsx` | remove | nav | Email and Telegram. |
| `sections/PathsSection.tsx`, `LibrarySection.tsx`, `ExcludedTypesSection.tsx`, `VaultHealthSection.tsx` | keep | - | Mounts, intake filters, health; admin. |
| `sections/NotesSection.tsx`, `MovesSection.tsx` | hide | nav | New-note format and move-confirm are note-app settings. |
| `sections/DangerZoneSection.tsx` | keep | - | Admin; destructive confirm. |

### 7d. Counts

| | keep | rename | hide | remove | rows |
|---|---|---|---|---|---|
| 7b Routes | 20 | 8 | 19 | 7 | 54 |
| 7c Components | 11 | 15 | 25 | 8 | 59 |
| Total | 31 | 23 | 44 | 15 | 113 |

Rows group files that share a fate; one row can cover several routes or files.

Not in the table because they are personal-vault vocabulary only in skills outside the app:
`/oracle` and `/dive` are maintainer tools, not app code. In the app, "Dive" survives only
in a comment in `hooks/useJob.ts` and "Catch up" in `Maintain/features.ts`; both go with
`Maintain/`.

## 8. Incubator-year plan (not built now)

1. **Export, no lock-in.** Write Titles, People, Collections, Items to ArchivesSpace and
   AtoM-compatible files (EAD XML and CSV import templates). Consent and tombstones export
   as fields; withdrawn items export as a stub with no content.
2. **A writer's own view from their phone** on the office network. Read-only plus the consent
   control. Needs the identity decision from section 1 and an explicit non-loopback bind.
3. **Backups a non-technical admin can restore.** One button writes a dated bundle (items,
   index, consent, ledger) to a chosen drive; one button restores it and reports what it
   restored. Tested by restoring onto an empty machine.
4. **Consent-scoped LoRA adapters per collection**, trained only on `model`-level items,
   deleted and retrained on withdrawal. Start from `code/infra/models/local` (it has `lora/`,
   `evals/`, `leakcheck.py`, `restart.sh`). This is the only place training is allowed, and
   only after the prototype's never-list line on fine-tuning is lifted by the press in
   writing.

## 9. Archival practice, and the feature that carries each

The design follows community and radical archives, not corporate records management.

| Principle | Where it comes from | What carries it | Built? |
|---|---|---|---|
| Access by relationship, not only by file | Mukurtu CMS (cultural protocols) | Labels in `org.yaml` say which purposes and roles an item serves (`services/archive/labels.py`, enforced in retrieval and in training selection); roles admin / staff / writer, and a writer controls only their own items (`services/archive/accounts.py`) | Yes (C3, C6) |
| Terms travel with the item | Local Contexts TK and BC Labels | Each label maps to the IETF AI-preferences vocabulary (`draft-ietf-aipref-vocab-08`, checked against the raw text 2026-11-19) and the items API returns the `train-ai=n, ai-use=n` string | Partly: answers, packets and exports do not yet carry the labels of what they contain (needs E1) |
| Care for the people in the records | Caswell and Cifor, radical empathy | Email intake makes every message and attachment private (`services/archive/mail.py`); anyone can attach a signed, dated reply to an item or a passage, shown beside it in every answer and never sent to a model (`services/archive/annotations.py`) | Yes (D1, C4); consent per correspondent is D1b |
| Post-custodial where the writer wants it | Post-custodial archival practice | Withdraw: the bytes' hash is tombstoned so intake refuses them under any path, the item is forgotten by search, and earlier answers that cited it are flagged (`services/archive/withdraw.py`); every step is a line in the hash-chained ledger with a receipt (`services/archive/ledger.py`) | Yes (C1, C2) |
| Original order is kept; description is authored | Respect des fonds | Items keep their place in their collection; the file tree filter keeps order (`services/archive/access.py`) and nothing re-files by topic | Partly: no AI-drafted description exists yet, so the "AI-drafted, unreviewed" label has nothing to mark |
| The archive is for use | Interference Archive, Lesbian Herstory Archives | Ask, and the jobs below: each is a folder built from consent- and label-filtered items in original order, with a manifest and receipts | Ask yes; jobs not yet (E1) |

## 10. Uses

What a small press uses its archive for. Study comes first; the operational jobs follow.
"Runs" means it runs in this build today.

1. **Editorial history** (7): why a line was cut, from tracked changes and the letters
   around them. Tracked changes and comments are kept and citable (D2); the job is E1.
2. **Translator handover** (6): earlier translators' correspondence on the same author,
   under "translators of this book only". The label is enforced (C3); the job is not built.
3. **Teaching packets** (4): for an adopted book, what the author opened under "teaching
   only". The label is enforced (C3); the job is E1.
4. **Programming from the archive** (8): a reading or exhibition built from recordings and
   letters, listing every item used and its terms. Needs recordings (D3).
5. **Rights and reversion** (1): who holds which rights, when they revert. Runs: Ask quotes
   the contract clause and cites it.
6. **Permissions** (2): "may we reprint X in Y", from the contract plus the author's labels.
   Ask answers from the contract; joining it with labels is not built.
7. **Grant writing and reporting** (3): counts computed by code (`stats.json`, E1).
8. **Reissues and anniversaries** (5), 9. **Institutional memory** (9), 10. **Estate
   handover** (10), 11. **Placing papers with a library** (11, EAD finding aid),
   12. **Authenticity** (12, from the ledger): not built.

