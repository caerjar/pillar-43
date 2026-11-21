# Workshop: map a collection, set permissions, test the system

A facilitator's script for a half-day with staff or writers from another press.
It uses only the invented press (Lantern Wharf Editions). **No real contract,
letter, recording or unpublished text may be in the room**, on a screen, or on the
machine that runs the workshop.

Times below are suggestions. This workshop has not yet been run with a group.

## Before the day (facilitator)

1. Install Pillar-43 on one Mac with the invented press, following [install.md](install.md) Steps 1 to 8. Use the default names. The check in Step 8 must work.
2. Make one staff account for the room, so participants do not use the administrator:

```
printf 'Staff name: '; read STAFF_NAME
printf 'Password (at least 8 characters, not shown): '; read -s STAFF_PW; echo
export STAFF_NAME STAFF_PW
docker compose -p "$ARCHIVE_PROJECT" exec -e STAFF_NAME -e STAFF_PW api sh -c 'python scripts/archive_cli.py account "$STAFF_NAME" staff "$STAFF_PW"'
unset STAFF_PW
```

You should see `account <name> (staff) created`. Signing in with it shows Ask, Explore and People; it cannot change levels.

3. Make a backup ([maintenance.md](maintenance.md), "Make a backup"). Between sessions, restore it so every group starts from the same state.
4. Print: the kinds table (part 1), a writer permission form from [../templates/](../templates/README.md) per participant, and the test sheet (part 3).

## Part 1. Map a collection (60 minutes)

Aim: each participant can sort their own shelf into the kinds Pillar-43 uses, and
say what level each kind starts at.

1. (10 min) Show the kinds table from [archivist.md](archivist.md) step 1: contract, minutes, email, letter, recording, handwritten, design, book, document, note, catalog, with the level each starts at.
2. (20 min) On paper, each participant lists 10 things from their own press's shelf or drive (names only, no content) and writes the kind next to each. The rule: folder and file names decide the kind. Where a thing fits nowhere, write "document".
3. (15 min) Compare with the invented press. Show the folders in Finder (`fixtures/synthetic-press`) and then the result:

```
docker compose -p "$ARCHIVE_PROJECT" exec api python scripts/archive_cli.py counts
```

You should see a list such as `"contract:model": 6`, `"email:private": 41`, `"letter:private": 11`.
Ask: which of these kinds does your press have that the list lacks? Which names would land in the wrong kind?
Examples from the invented press: `contracts/ferriday_fieldguide_agreement_2019-10-21.pdf` is a contract; `board/Minutes April 14 2026 (final).docx` is minutes; `design/yellow-spine-brief_2019-03-12.md` is a design file; `manuscripts/merrowby_slack-water_draft3.docx` is a document (private).
4. (15 min) Discuss: the folders are kept as they are; nothing is filed by topic. What would a participant need to rename or move before intake? (Answer: nothing; but a contract kept in a folder called `misc` would be a plain document.)

## Part 2. Set permissions (75 minutes)

Aim: each participant fills a permission form and sees the effect.

1. (15 min) Walk through the form ([permission-form-writer.md](../templates/permission-form-writer.md)): the three levels, the five terms, the right to withdraw, the right to see who read. Use Cassia Merrowby as the writer.
2. (20 min) Each participant fills the form as Cassia Merrowby for two invented items: the contract `library/contracts/contract_merrowby_SaltLedger_2012.pdf` and the letter `library/correspondence/letters/2024-05-06_merrowby_spine-colour.txt`. They choose a level and terms and sign with an invented name.
3. (25 min) The facilitator records one form live, following [permissions.md](permissions.md) steps 2 to 4 (set level, set terms, make Cassia an account, link the two items). Show the participants: sign in as Cassia on a second browser window, open My work, see the two items, their levels, the terms and "Not read by the AI."
4. (15 min) Withdraw the letter as Cassia (the button asks "The archive forgets it and cannot take it back"). Back in Terminal run `counts` and the record check from [archivist.md](archivist.md) step 8. You should see `'ok': True`.

Discuss: what did the writer decide that the press would not have? What would the press do about contracts the writer did not sign?

## Part 3. Test the system (60 minutes)

Aim: participants learn to check an answer against its source and see that a closed
item stays closed.

Give each pair this sheet. Sign in as the staff account.

| # | Do | You should see | Tick |
|---|---|---|---|
| 1 | Ask: "How long is the cure period before rights revert on The Drowned Orchard?" | A quoted sentence with "nine (9) months", with `[2]` or a similar source button | |
| 2 | Click the source button | The contract opens at clause 7, Reversion, with the sentence highlighted | |
| 3 | Read "Not in this answer" under the answer | A number of items closed by their writers, and staff items it did not read | |
| 4 | Facilitator: close the contract (`consent "library/contracts/t_2014_vasconcelo-reis_orchard_RIGHTS+TRANSLATOR.pdf" staff --by "Workshop"`) | `1 item(s) set to staff` | |
| 5 | Ask the question from 1 again | The nine-months sentence must not appear. (On the test installation the answer was an unrelated sentence about a cover, not a clear "I cannot answer". Note exactly what yours says.) | |
| 6 | Facilitator: reopen it (the same command with `model`) and ask again | The nine-months sentence is back | |
| 7 | Ask: "In which territory may the Press publish Lanterns for the Second Winter?" Then open the source and read it. The right answer is "the United States and its territories" (contract, clause 2) | Compare. The answer may be wrong or may quote another clause. A wrong answer with a visible source is how you catch it | |
| 8 | Ask a question the press cannot answer, such as "What is the printer's phone number?" | No answer sentence (the archive declines). If a sentence appears, open its source: it must contain the number | |

Discuss: the model gets some questions wrong. The project's own 50-question check
(`docs/eval/2026-11-19-clean.md`) scored 0.62 on all 50 questions. What does your
press need before it trusts an answer? (Our rule: open the citation every time.)

Close the day by running the record check once more and restoring the backup.

## What this workshop does not cover

Real documents, handwriting, recordings, backups beyond the basic procedure,
and anything that needs the Terminal beyond the commands printed above.
