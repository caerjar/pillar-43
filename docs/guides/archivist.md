# Archivist's guide: bringing in and describing the archive

For the person who brings the press's documents into Pillar-43, decides who may
see them, and keeps the record honest. You need a working installation
([install.md](install.md)) with the real archive set up as its own installation
("Using your own documents"). Practice first on the invented press.

Most steps here are Terminal commands today. Each section says which. A table at
the end lists what has no screen yet.

## The idea in four lines

- Pillar-43 reads your folder as it is. It never moves, renames or re-files anything. The order you keep is the order it shows.
- Every file becomes an item with a kind (contract, letter...) and a level (private, staff, model).
- A new item starts at the level the press chose for its kind. You change levels only with the contributor's permission ([permissions.md](permissions.md)).
- Everything you do is written to a record that shows if anyone edits it afterwards.

## Before you start

Open Terminal in the Pillar-43 folder and paste the three `export` lines from
install guide Step 5, using the names of the installation you are working on.
In this guide `CLI` stands for the start of every command. Paste the whole line:

```
docker compose -p "$ARCHIVE_PROJECT" exec api python scripts/archive_cli.py
```

## 1. Keep the original order

Arrange nothing for Pillar-43. Point it at the folder the press already has
(install guide, "Using your own documents"). Folders can be messy; names can be
inconsistent. Pillar-43 records each file under its place in that folder.

It decides each file's kind from the folder and file name, trying these in order;
the first that matches wins:

| Kind | A file is this kind if it is... | Starts at |
|---|---|---|
| contract | in a folder named `contracts`, or has "contract" in its name | staff |
| minutes | in a folder named `board`, or has "minutes" in its name | staff |
| email | a `.mbox` or `.eml` file | private |
| letter | in a folder named `letters` or `correspondence` | private |
| recording | `.m4a`, `.wav`, `.mp3`, `.aiff` | private |
| handwritten | in a folder named `handwritten` | private |
| design | in a folder named `design`, or a `.png` or `.svg` | staff |
| book | `.epub`, or in a folder named `books` | private |
| document | in a folder named `manuscripts`, or `.docx`, or `.pdf` | private |
| note | `.md` or `.txt` | staff |
| catalog | in a folder named `catalog`, or `.csv` | model |

The last row matters: a catalog starts open to the AI. Everything else the AI can
read starts closed. The table lives in `api/orgs/press.yaml`; changing it
needs **[the maintainer]** (it needs a rebuild, see [maintenance.md](maintenance.md)).

Because a rule matches on names, a contract saved as `Orchard.pdf` in a folder
called `misc` is a plain "document" (private). Check kinds in step 3.

## 2. Bring the files in (Terminal)

```
CLI intake
```

You should see a block of text ending with the counts, for example
`"contract:staff": 1` and `"new": 1`: one line per kind and level, and how many items are
new or already known. Running it again is safe: items already known keep their
level; only new files are added.

Things you may see:

- `"refused_tombstoned": 1` - a file was withdrawn before and is refused. This is correct.
- a `"mail"` block - an email file was opened. See step 4.

Then make it searchable:

```
CLI index
```

You should see `"embedded": true` and `"errors": []`. This reads each file's text with a
small program on this Mac. No AI summaries are written. It can take minutes for a
large folder. Run it again after every intake.

If `errors` lists a file: that file could not be read (a damaged PDF, for example).
It stays an item but cannot be found by search. Tell **[the maintainer]** the name.

## 3. Check what came in (Terminal)

```
CLI counts
```

You should see a list of kind and level with counts, like
`"contract:staff": 6` or `"email:private": 41`. Compare with what you expect: six
contracts in the folder, six lines of contract. A kind that is too big or missing
means names did not match the table in step 1.

There is no screen that lists items with their levels for staff. The administrator can see files under Files in the web app.
Each writer sees their own on My work.

## 4. Email, tracked changes, recordings, handwriting

**Email.** Put the `.mbox` or `.eml` file in the folder. Every message becomes its
own item and so does every attachment. All are private. Pillar-43 records who sent
and received each message. A message is indexed only with the sender's own words:
quoted lines from other people's earlier messages are left out, so one person
agreeing to open their words never opens someone else's.

To open a person's messages after they agree:

```
CLI consent person:ines@example.org staff --by "Ines Quillfeather, form signed 2026-11-20, recorded by Your Name"
```

You should see how many items changed (`3 item(s) set to staff`). Attachments are
a different kind (`attachment`), so opening documents does not open them by accident.

**Tracked changes in Word files.** Each insertion, deletion and comment in a
`.docx` is an item of its own, with its author and date. It starts at the same
level as the manuscript. You can set one comment private while the manuscript is open.

**Recordings and handwriting.** They are registered and kept (private), and the
originals are never altered. Pillar-43 does not read what is said or written in
them yet (the project documents list this as still to be built; on the invented
press the three recordings have no searchable text), so they cannot be found by
search and cannot be quoted in an answer.

## 5. Decide levels and terms

Follow [permissions.md](permissions.md), form by form. Do not open an item to the
AI because it seems harmless. The levels:

- private: held, never searched or read.
- staff: found and cited by staff, never sent to the AI.
- model: the AI may read it when staff ask a question.

## 6. Add an annotation (not available to staff yet)

An annotation is a signed, dated note attached to an item or one passage, the
contributor's right of reply. The note is kept apart from the text; the AI never
reads it, and it is returned with the passage in answers. It can be retracted but
never edited.

There is no screen and no archive command for it. Today it is added with one
Terminal command, which you can run on a contributor's behalf if they have given
you the words and signed. Replace the item name, the words and the person:

```
docker compose -p "$ARCHIVE_PROJECT" exec api python -c "from services.archive.annotations import add_annotation; from services.db import get_db; print(add_annotation(get_db(), 'library/contracts/t_2014_vasconcelo-reis_orchard_RIGHTS+TRANSLATOR.pdf', 'The estate confirms this clause was read at the 2026-11-20 meeting.', by='Lucia Vasconcelo-Reis', role='estate'))"
```

You should see a number, the note's number (`1`). If you see `KeyError`, the item
name is wrong. Keep the signed paper. To add a note to one passage and not the
whole item the command needs the passage number (ask **[the maintainer]**).

## 7. Withdraw

When a contributor withdraws an item, follow "Withdrawal" in
[permissions.md](permissions.md). Then run `CLI intake` once: it should show
`"refused_tombstoned"` going up by one, meaning the file is blocked from coming back.

What withdrawing does: blocks the file from being imported again (under any name),
removes it from search, and marks earlier answers that quoted it. What it does
not do: delete the original from the press folder, or remove other items that quote
it (an email that copies a letter is a separate item with its own owner).

## 8. Check the record

```
docker compose -p "$ARCHIVE_PROJECT" exec api python -c "from services.archive.ledger import verify; from services.db import get_db; print(verify(get_db()))"
```

You should see `{'ok': True, 'entries': 75, 'first_bad_seq': None}` (the number of
entries will differ). Run it after a batch of changes and before every report.
`ok: False` with a number after `first_bad_seq` means a line of the record was
changed or removed. Stop and tell **[the maintainer]**.

## 9. Folders for a purpose (Terminal)

Pillar-43 can assemble a folder of the items one title allows, in original order,
with a list of terms and receipts. It never writes new text unless you ask for a
cover note.

```
CLI job editorial-history "The Drowned Orchard"
CLI job teaching-packet "The Drowned Orchard"
CLI job rights-answer "The Drowned Orchard"
```

You should see a path such as
`/generated/archive/jobs/editorial-history-the-drowned-orchard-20261120-170801`.
The folder is on your Mac under `.archive/generated/archive/jobs/` (invented
press) or `.press/generated/archive/jobs/` (yours). Open `manifest.json` in it to
see every item and its terms. Items closed by their writers, or by a term, are
not in it. `CLI stats` and `CLI colophon` write counts and a plain list of models
and levels to `generated/archive` the same way.

## What has no screen yet

| Task | Today |
|---|---|
| List items with their levels | Terminal `counts` (totals only); admin Files screen |
| Intake and index | Terminal |
| Set levels and terms for someone | Terminal |
| Make accounts, link items | Terminal |
| Annotate | one Python command |
| Check the record | one Python command (a check exists in the program; no command or screen) |
| Read the record of who asked what | not available to staff as a screen |
| Handwriting and recordings | kept, not read yet |
| Mistakes in commands | a block of technical text; the last line tells the cause |

What each would need is in the report that came with these guides.
