# Recording a contributor's permission form

For the staff member who receives a signed form
([../templates/](../templates/README.md)) and records it in Pillar-43. Recording
needs the Terminal for now, apart from what a contributor can do on their own
My work screen. You need an administrator account and the three `export` lines
from [install.md](install.md) Step 5 for the installation you are working on.

As in [archivist.md](archivist.md), `CLI` below stands for the start of every
command. Paste the whole line, then the rest of the command after it:

```
docker compose -p "$ARCHIVE_PROJECT" exec api python scripts/archive_cli.py
```

Every command takes `--by "<your name>"`. It writes your name into the record
next to the change, so always add it.

## 1. Check the form

- It is signed and dated.
- Every item has one level: Private, Staff or Model. A blank level means
  Private. Items the form does not list stay Private.
- The terms are written next to the items they apply to.

If something is unclear, ask the contributor before recording anything. Never
open an item to the AI because it looks harmless.

## 2. Name the items as Pillar-43 does

Pillar-43 names an item by `library/` followed by its place in the press folder.
A contract at `contracts/t_2014_vasconcelo-reis_orchard_RIGHTS+TRANSLATOR.pdf`
in the press folder is

```
library/contracts/t_2014_vasconcelo-reis_orchard_RIGHTS+TRANSLATOR.pdf
```

Put each name in single quotes in the commands below, because file names can
contain spaces and `+`.

## 3. Set each item's level

One command per item:

```
CLI consent 'library/contracts/t_2014_vasconcelo-reis_orchard_RIGHTS+TRANSLATOR.pdf' model --by "Your Name"
```

The level is `private`, `staff` or `model`, in lower case.

You should see: `1 item(s) set to model`.

If you see `0 item(s)`: the name does not match an item. Check it letter by
letter against the press folder, including capitals.

If the form covers every email and letter from one person, use their address
in place of a name. This sets the level of everything that person sent:

```
CLI consent 'person:lucia@example.org' staff --by "Your Name"
```

## 4. Set the terms

The terms on the form have these names in the command:

| On the form | In the command |
|---|---|
| teaching only | `teaching_only` |
| ask the estate | `ask_the_estate` |
| translators of this book only | `translators_only` |
| never for training | `never_for_training` |
| attribution required | `attribution_required` |

List every term for the item in one command. The command replaces the item's
terms, so leave none out:

```
CLI labels 'library/contracts/t_2014_vasconcelo-reis_orchard_RIGHTS+TRANSLATOR.pdf' never_for_training attribution_required --by "Your Name"
```

You should see the item name and the terms in square brackets.

To remove every term from an item, give the command with no terms.

## 5. Make the contributor an account, if they asked for one

The account lets them sign in and use My work: see their items, change a level
or a term, see the dates the AI read each item, and withdraw. Like the
administrator's, the password is typed without showing it, so the Terminal does
not remember it. Choose a first password with the contributor, in person.

```
printf 'Contributor name: '; read WRITER_NAME
printf 'Password (at least 8 characters, not shown): '; read -s WRITER_PW; echo
export WRITER_NAME WRITER_PW
docker compose -p "$ARCHIVE_PROJECT" exec -e WRITER_NAME -e WRITER_PW api sh -c 'python scripts/archive_cli.py account "$WRITER_NAME" writer "$WRITER_PW"'
unset WRITER_PW
```

You should see: `account <name> (writer) created`.

Then link their items to the account. Only linked items appear in their My work,
and they can change only those:

```
CLI owner "Cassia Merrowby" 'library/contracts/contract_merrowby_SaltLedger_2012.pdf' 'library/correspondence/letters/2024-05-06_merrowby_spine-colour.txt'
```

You should see: `Cassia Merrowby: 2 item(s) linked`.

Pillar-43 never links items by matching names in documents; a wrong match would
give someone control of another person's work. Link each item yourself.

## 6. Check it

- Sign in as the contributor in a private browser window, or ask them to. My
  work should list the linked items with the levels and terms from the form.
- Fill in section 5 of the form ("For the press") and file it with the press's
  paper records, not in the folder Pillar-43 reads.

## Withdrawal

A contributor with an account withdraws an item themselves from My work. The
screen asks them to confirm, because withdrawal cannot be undone.

If they ask you instead, in writing:

```
CLI withdraw 'library/correspondence/letters/2024-05-06_merrowby_spine-colour.txt' --by "Your Name"
```

You should see a list of the item names withdrawn. Every copy of the same file
is withdrawn with it, under any name.

What it does: blocks that file from being imported again, removes it from search,
and marks earlier answers that quoted it. What it does not do: delete the
original in the press folder (do that by hand if the contributor asked), or
remove other items that quote it, such as an email that copies the letter.
Those are separate items with their own levels.

Then run `CLI intake` once. `"refused_tombstoned"` should go up by one.

## Changing a decision

A contributor can change their mind at any time. Record the new form or the
written request the same way, from step 3. The record keeps both the old and the
new decision, with the dates and your name.
