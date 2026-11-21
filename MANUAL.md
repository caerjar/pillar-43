# Pillar-43 manual

Pillar-43 is a local archive for a small literary press. Staff ask questions of
the press's own documents and get answers that quote and cite them. Writers,
translators and estates see their own items and decide what the archive and the
AI may do with each one. Everything runs on one Mac in the press office. No
question or document goes to a hosted AI service.

This manual describes what the running program does. Where a screen does not
exist yet, it says "not built yet".

Guides for the work around the program:

| Guide | For |
|---|---|
| [docs/guides/install.md](docs/guides/install.md) | setting up the Mac |
| [docs/guides/archivist.md](docs/guides/archivist.md) | bringing documents in, levels, withdrawals |
| [docs/guides/permissions.md](docs/guides/permissions.md) | contributor permission forms |
| [docs/guides/maintenance.md](docs/guides/maintenance.md) | updates, backups, changing the model, problems |
| [docs/guides/workshop.md](docs/guides/workshop.md) | running a workshop with another press |
| [docs/templates/](docs/templates/README.md) | permission forms to print |

For developers: [DEV_MANUAL.md](DEV_MANUAL.md).

## Contents

1. Who sees what
2. Signing in
3. Ask
4. Explore
5. People
6. My work (writers)
7. The three levels
8. Labels
9. Withdrawing an item
10. Citations and "Not in this answer"
11. Files (administrators)
12. Settings
13. Things done in the Terminal
14. Not built yet
15. Troubleshooting

## 1. Who sees what

An account has one of three roles. An administrator makes accounts (section 13).

| Role | Left-hand buttons | Can do |
|---|---|---|
| admin | Ask, Explore, People, Files, Settings | Everything staff can do. Opens the Files view. Sets the level or labels on any item. Makes accounts. |
| staff | Ask, Explore, People, Settings | Asks, explores, reads people records, opens cited documents. Cannot change any level. |
| writer | My work, Settings | Sees only the items an administrator has linked to the writer. Sets the level and labels on those items, and withdraws them. Cannot ask, explore or see people. |

The server enforces this. A button a role does not have is not hidden by the
screen alone; the server refuses that role's request.

Until the first account exists, the archive is open: anyone who can reach the
web address gets in without signing in, and the first account must be an
administrator. Make it before loading any documents ([install.md](docs/guides/install.md),
Step 7). Until then, withdrawing an item or changing its level is refused.

The default install is at http://127.0.0.1:5211. That address works only on the
Mac it runs on.

## 2. Signing in

The sign-in screen has a Name field, a Password field and a Sign in button. A
wrong name or password shows the line "Wrong name or password" and clears the
password. A password is at least 8 characters.

Sign out is the last button of the left-hand column ("Sign out", with your name
as its tooltip). It reloads the page so no answer from your session stays on the
screen.

A writer lands on My work after signing in.

## 3. Ask

For admin and staff. Type a question in the Question field and press Ask (or
Return). Examples the field suggests: a contract, a title, the minutes.

While the model works, the screen shows "Answering..." with the elapsed seconds
and a Stop button. Stop cancels the question; it is not an error and your
question stays in the field. Answers take roughly 10 to 60 seconds on the test
Mac ([install.md](docs/guides/install.md), Step 8).

What you get back:

- **The answer**, set as plain sentences. Each sentence has one or more
  numbered buttons, for example `[2]`. A sentence taken word for word from a
  document says "Quoted from" and names the document. A sentence that
  paraphrases a quotation shows the quotation under it with its source.
- **A source panel.** Click a `[n]` button and a panel opens at the right with
  the document's title, kind, ISBN and heading when it has them, the page with
  the cited clause highlighted (PDFs), and the passage sentence by sentence
  with the cited sentence marked. Close source closes it. Open whole file opens
  the full document (section 11).
- **Not in this answer**, beside the answer (section 10).
- **Past questions**, a list above the answer. Click one to see its answer
  again. The list lasts until the page is reloaded.

When the archive cannot answer, the answer area says so in one of three ways:

- the question is about an item that is closed to the AI, and says why, for
  example "The question is about The Drowned Orchard contract. It is closed by
  its writer, so the AI did not read it.";
- there is no such document for that title ("There is no contract for X in the
  archive");
- otherwise "The archive does not answer this." and, when available, what would
  answer it.

The empty Ask screen shows "Open to the AI: N items" with a count per kind
(contract, letter and so on). Those are the items the model may read for a
question: level model, and every label on the item allows asking.

If the local model is not running, Ask says "The local model is not running."
Open Ollama and ask again.

Ask answers from the documents open to the AI. It does not write in an author's
voice, and it gives no answer sentence without a citation.

## 4. Explore

For admin and staff. Explore takes a topic (a word, a phrase, a colour, a clause,
a name) and finds every document open to the AI that matches it, across the
whole press, laid out in time.

1. Type a topic in the Topic field and press Explore. The screen says
   "Searching..." and then draws the documents.
2. **The timeline.** One row for each title the documents belong to, plus a row
   named Press for documents tied to no title. Years run along the bottom; each
   matching document is a dot at its date. Years with no matching document
   stay blank. There is no zoom or pan.
3. **Click a dot.** A passage panel opens at the right with the document name,
   kind, date, page, titles, how it matched ("matched the phrase ..." or
   "matched the words ..."), and the passage with the matched words marked. A
   PDF shows its page with the passage highlighted. Open whole file opens the
   document.
4. **The summary.** After the dots appear, the model writes a short dated
   summary. Each line ends with `[n]` buttons that select the matching dot.
   While it is written you see "Writing the summary..." with elapsed seconds
   and a Stop button. If you stop it, or the model does not answer, the
   documents stay and the screen says there is no summary. If no summary line
   can be tied to a document, it says so.
5. **Not open to the AI: N**, with one line per reason, counts the matching
   items that were left out and why. Those items are never drawn as dots.

The dots come from the search, not from the model. The result stays on screen if
you open a file and come back.

## 5. People

For admin and staff. The list shows each person the catalog credits, with their
relationship to the press and how many documents open to the AI connect to
them and the span of their dates ("No documents open to the AI" when none).

Click a name to open the person's record:

- name, relationship to the press, the span of the dates of their documents;
- their titles, each with the person's role and publication year;
- a count by connection: signed, wrote, received, mentioned;
- the same timeline as Explore, one dot per document; the dot's description says
  how the document connects to the person;
- a passage panel on a dot, with the person's name marked in the text;
- Not open to the AI: N, with reasons.

## 6. My work (writers)

For writers. A table of your own items only. If none have been linked to your
account it says "No items are linked to your account yet." An administrator
links items (section 13).

| Column | What it shows and does |
|---|---|
| Item | The title and kind. "Withdrawn on DATE" once withdrawn. |
| Level | Three radio buttons: Private, Staff, Model, each with its meaning (section 7). Choosing one saves at once. |
| Labels | The labels on the item, each with its meaning in words and, when it has one, its AI preference. Remove takes a label off. Add buttons put on any label the press offers (section 8). |
| Read by the AI | "Not read by the AI." or "Read N times" with a dated list: the date, the purpose, and the answer receipt number of each time the AI read the item. The question text is never shown. |
| Withdraw | A Withdraw button. See section 9. |

On a narrow screen the table becomes one block per item, with the column name
above each part.

A withdrawn item's level and labels can no longer be changed.

## 7. The three levels

Every item has one level. Items start at the level the press set for their kind
when they came in: contracts and minutes at staff; letters, email, recordings,
handwriting, books and most documents at private; the catalog at model
(`api/orgs/press.yaml`).

| Level | Meaning |
|---|---|
| Private | Held in the archive. Nobody searches it, and the AI never reads it. |
| Staff | Staff can search and cite it. The AI never reads it. |
| Model | The AI may read it to answer staff questions. |

Who can change a level: the writer the item is linked to, and an administrator.
Staff cannot, because the level is the writer's to give.

Reading by the model happens only at the moment a question is asked. Model does
not mean the AI is trained on the item; Pillar-43 does not train on anything.

## 8. Labels

A label is a writer's term of use, set on one item. It is enforced, not just
shown: the AI refuses any purpose the label rules out. The press's labels are
defined in `api/orgs/press.yaml`. Its five:

| Label | Effect |
|---|---|
| teaching only | Only teaching packets and editorial history may use the item. |
| ask the estate | No purpose is allowed until the estate is asked. |
| translators of this book only | Only questions, and only from a translator. |
| never for training | The item may not be used for training. |
| attribution required | Marks that the item must be credited. |

Each label also has an AI preference written in the IETF AI-preferences
vocabulary, for example `train-ai=n, ai-use=n`. My work shows it.

A label can close an item that is at level Model: Ask only reads an item that is
at Model and whose labels all allow asking.

## 9. Withdrawing an item

In My work, press Withdraw on the item. The row then asks, in place: "Withdraw
ITEM? The archive forgets it and cannot take it back." with Yes, withdraw and
Keep it. There is no browser dialog.

After Yes, withdraw:

- the item's level becomes Private and cannot be changed again;
- search and the AI forget it (its text, passages and search entries are
  removed);
- the item's file contents are recorded as withdrawn, so bringing the same file
  in again, under any name or folder, is refused;
- any other item with identical contents is withdrawn with it;
- earlier answers that cited it are flagged when they are opened;
- the ledger records the step.

The original file in the press's folder is not changed. An administrator can
also withdraw from the Terminal (section 13).

## 10. Citations and "Not in this answer"

**Citations.** Each Ask answer sentence carries `[n]` buttons. They open the
source panel at that document and, for a PDF, at the page with the clause
highlighted. Rights questions quote the contract clause rather than paraphrase
it.

**Not in this answer.** Under or beside every answer, the screen lists what the
archive could not say, in the same type as the answer and never in a warning
colour. It is computed by code from the database, not written by the model.
One line for each kind that applies:

- "N items closed by their writers", "N items closed by default (no one has
  opened them to the AI)", "N items closed by staff or an administrator". These
  are counts; what the items are is never shown.
- Named closed items, when the question is about one: its title and the reason.
- "There is no KIND for TITLE in the archive."
- "NAME's replies are not in the archive", for a correspondent whose own letters
  are absent.
- "Nothing from YEARS", for years the question names in which the archive holds
  no item at all.
- "N items at staff level, not read by the AI", each as a button that opens the
  item. Staff can read these themselves.

If nothing applies it says so. Items at level Private that the question does not
concern are not listed individually.

Explore and People have the matching line, "Not open to the AI: N", with reasons.

## 11. Files (administrators)

Only an administrator has the Files button. It shows the archive folders as a
tree; clicking a document opens it in a viewer (PDFs with the cited page and
highlight). Original order is kept: the tree shows where each item is filed and
nothing re-files it by topic.

Staff and writers have no Files button. When staff press Open whole file from
Ask, Explore or People, the document opens in the same viewer with a "Back to
Ask" (or Explore, People) button above it that returns to the view with its
result still on screen.

## 12. Settings

The Settings button is at the bottom of the left-hand column (shortcut Command
and comma). It opens a window with two groups.

- **Local models.** The answer model (Ollama only; no hosted provider can be
  chosen), a button to find the models Ollama has, and the search (embedding)
  model.
- **Storage.** The archive's folders, workspace health, and the file types
  intake skips.

There is no screen for accounts yet (section 14). Changing the answer model is
described in [maintenance.md](docs/guides/maintenance.md).

## 13. Things done in the Terminal

These have no screen yet. Each runs inside the running program with
`python scripts/archive_cli.py`; the guides give the exact lines to paste
([install.md](docs/guides/install.md), [archivist.md](docs/guides/archivist.md)).

| Command | What it does |
|---|---|
| `intake` | Reads the press folder and registers every file as an item at its kind's starting level. Safe to repeat; existing items keep their level. |
| `index` | Makes items searchable. |
| `consent TARGET LEVEL` | Sets private, staff or model on one item, on all items of a kind (`kind:contract`), or on a pattern (`glob:*yellow*`). |
| `labels PATH [LABEL ...]` | Sets an item's labels (ids from `archive.yaml`). |
| `withdraw PATH` | Withdraws an item (section 9). |
| `account NAME ROLE PASSWORD` | Makes an account: admin, staff or writer. The first must be admin. Use the lines in install.md Step 7 (or permissions.md step 5), which keep the password out of the Terminal's memory. |
| `owner NAME PATH ...` | Links items to a writer's account. A writer controls only linked items. |
| `ask "QUESTION"` | Asks from the Terminal (`make archive-ask Q="..."`). |
| `job` | Builds a folder for a purpose: `editorial-history`, `teaching-packet` or `rights-answer`, for a title. It holds only items whose level and labels allow that purpose, in original order, with a manifest. |
| `stats`, `colophon` | Writes counts, and `COLOPHON.md`, a document of the models, consent decisions and withholdings. |
| `counts` | Prints the number of items by kind and level. |

Make targets: `make archive-up` (build and start, no documents), `make archive` (first load, after the admin account; do not use to restart, it reopens
contracts and "yellow" documents to the model), `make archive-status`,
`make archive-logs`, `make archive-stop`.

## 14. Not built yet

Found in the plans (`docs/concept-org.md`, `docs/org-edition.md`) but not in the
running screens:

- A Titles view (a dated strip per title with the rights term drawn as a band).
  Explore and People draw title rows; there is no view of one title, and no
  asking scoped to a title.
- Collections, Recordings, Intake and Ledger views. Intake, the ledger and
  recordings work from the Terminal or the server only.
- A screen for accounts and for linking items to a writer. Settings has none,
  though the in-app help text mentions accounts.
- Setting consent or labels from a screen for an administrator or staff. Only a
  writer's My work has those controls; administrators use the Terminal.
- Annotations (a signed, dated reply attached to an item or passage). The
  server can store and return them; no screen adds or shows them.
- The ledger, earlier answers and "gaps" are served to staff and administrators
  by the server; no screen shows them.
- A password reset. Ask the person who installed it.
- Export to archive-description formats and writer access from a phone.

## 15. Troubleshooting

More in [maintenance.md](docs/guides/maintenance.md), "When something is wrong".

| What you see | Do |
|---|---|
| The page does not load at http://127.0.0.1:5211 | Run `make archive-status`. If `api` and `web` are not both Up, open Docker Desktop and start them again as in install.md, Step 9. |
| The address is in use when starting | Another program holds port 5211 (web) or 8061 (api). To see which: `lsof -i :5211` and `lsof -i :8061`. Choose other ports as in install.md, Step 5. |
| "The local model is not running." | Open Ollama (the llama icon in the menu bar) and ask again. |
| Ask finds nothing you expect | Check the item's level and labels. Only items at Model whose labels allow asking are read. "Not in this answer" says how many were closed. |
| An item is missing from Explore | It is at Private or Staff, has a label that refuses it, or was withdrawn. "Not open to the AI" counts it. |
| "Wrong name or password" | Check the name's capitals. A password cannot be shown or reset from a screen. |
| A writer sees "No items are linked to your account yet." | An administrator must link the writer's items with `owner` (section 13). |
| A button the person expects is missing | Their role does not have it (section 1). |
