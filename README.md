# Pillar-43

Pillar-43 is an archive for small independent literary publishers. It runs on
one computer at the press, with a small open-weight model, and answers questions
about the press's own manuscripts, correspondence, contracts and translations
with citations to the documents it read. Writers, translators and estates decide
which of their documents staff may read and which the model may read, and can
withdraw them.

It is being built with Lantern Wharf Editions and Parallax Press. Why, and the
principles behind every decision: [PROJECT.md](PROJECT.md).

## What it does now

Each line cites the row of [docs/pillar-43-gap-analysis.md](docs/pillar-43-gap-analysis.md)
that checks it against the code.

- **Runs locally.** Answers come from Qwen3 8B in Ollama on the same computer;
  search uses an embedder built into the image. The press edition has no hosted
  AI provider to switch on. (P01, P02, P04)
- **Ask, with sources.** Every answer quotes the passages it used; each citation
  opens the document at the quoted sentence. (P08, P12, P13, P47)
- **Three levels per item: private, staff, model.** Private items are read by no
  one. Staff items are shown to signed-in staff and never sent to the model.
  Only model items reach the model, and the check runs before retrieval, not
  after. (P21, P28, P30)
- **Writers' terms.** Labels such as "teaching only", "ask the estate" and
  "never for training", mapped to the IETF AI-preferences vocabulary. (P29, P40, P41)
- **My work.** A writer sees their own items, each item's level and terms, and
  the dates the AI read it, and can withdraw an item there: its bytes are
  tombstoned, it leaves search, and earlier answers that used it are marked.
  (P31, P32 partial)
- **Silences.** Under each answer, "Not in this answer" counts the items writers
  closed and lists staff items the model did not read. (P38, partial)
- **Accounts.** Admin, staff and writer roles, signed in with a password stored
  as an scrypt hash. (P20, partial)
- **A test archive.** An invented press, Lantern Wharf Editions, with 50 checked
  questions, so the system can be tried and measured without real documents. (P48, P49 partial)

Not built yet, among others: backups (P25), translation and line alignment
(P15, P43), sharing between presses (P33, P61). The gap analysis lists all of them.

## Install

Press staff: follow [docs/guides/install.md](docs/guides/install.md). It needs a
Mac with Apple silicon, Docker Desktop, Ollama and about 15 GB of disk, and says
what you should see after each step.

The short form, for someone who already has Docker Desktop, Ollama and `make`:

```
ollama pull qwen3:8b
git clone https://github.com/caerjar/pillar-43
cd pillar-43
make archive-up
```

`make archive-up` builds and starts the stack without loading any documents. Make
the first administrator account before loading them. Until one exists, anyone who
can reach the port can read the archive, and withdrawing items or changing their
level is refused. The password is read without echo, so it is not saved in shell history:

```
printf 'Administrator name: '; read ADMIN_NAME
printf 'Password (at least 8 characters, not shown): '; read -s ADMIN_PW; echo
export ADMIN_NAME ADMIN_PW
docker compose -p pillar43 exec -e ADMIN_NAME -e ADMIN_PW api sh -c 'python scripts/archive_cli.py account "$ADMIN_NAME" admin "$ADMIN_PW"'
unset ADMIN_PW
make archive
```

`make archive` loads the invented press, indexes it, and prints
`Pillar-43: http://127.0.0.1:5211`. Open http://127.0.0.1:5211, sign in, and ask:

> How long is the cure period before rights revert on The Drowned Orchard?

The answer quotes clause 7 of the contract ("within nine (9) months after the
Publisher's receipt of that written request ...") with a citation that opens it.

Stop and start: `make archive-stop`, and see [docs/guides/maintenance.md](docs/guides/maintenance.md)
for starting again without re-running intake.

## Documentation

| For | Read |
|---|---|
| Press staff, writers, researchers | [MANUAL.md](MANUAL.md), [docs/guides/](docs/guides/README.md), [docs/templates/](docs/templates/README.md) (permission forms) |
| Whoever runs the computer | [DEPLOYMENT_GUIDE.md](DEPLOYMENT_GUIDE.md), [SECURITY.md](SECURITY.md) |
| Developers | [DEV_MANUAL.md](DEV_MANUAL.md), [CONTRIBUTING.md](CONTRIBUTING.md), [RELEASING.md](RELEASING.md), [docs/README.md](docs/README.md) |
| How the press edition works | [docs/org-edition.md](docs/org-edition.md), [docs/archive.md](docs/archive.md) |

## Licence

Apache License 2.0. See [LICENSE-APACHE](LICENSE-APACHE).

Unless you state otherwise, any contribution you submit for inclusion is
licensed under the Apache License 2.0, without additional terms or conditions.
