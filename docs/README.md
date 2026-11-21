# docs/

Documentation for Pillar-43. Staff guides are written for press staff; the rest
is for whoever builds and maintains the software. For a map of the code, start
at the module READMEs under `api/` and `web/src/`. What ships is recorded in
[`CHANGELOG.md`](../CHANGELOG.md); `NEXT.md` lists what is open.

## For press staff

| Doc | For |
|---|---|
| [`guides/`](guides/README.md) | Install, permissions, archivist work, maintenance (updating, backing up, what to do when something is wrong), workshop. Start at [`guides/install.md`](guides/install.md). |
| [`templates/`](templates/README.md) | Contributor permission forms to print (writer, translator, estate). |

## What Pillar-43 is and does

| Doc | What it holds |
|---|---|
| [`archive.md`](archive.md) | The Local Archive build deployed at Lantern Wharf Editions: what is built, next, later. |
| [`architecture.md`](architecture.md) | The components, what runs where, and where every kind of data lives, each marked built or planned. |
| [`org-edition.md`](org-edition.md) | The organization edition: users, consent, what is hidden, what is built and what is not. |
| [`concept-org.md`](concept-org.md) | The interface concept for the organization edition (the title file, Explore, People). |
| [`pillar-43-gap-analysis.md`](pillar-43-gap-analysis.md) | Each claim made about the software, checked against a running stack. |

## History of the clean-up from the personal app

| Doc | What it holds |
|---|---|
| [`prune-inventory.md`](prune-inventory.md) | Every tracked file, marked keep or remove, from the prune (P1). |
| [`rename-map.md`](rename-map.md) | The map of old names to pillar43 used for the rename (P3). |

## Checks and evidence

| Doc | What it holds |
|---|---|
| [`eval/`](eval/) | The 50-question answer-quality runs (baseline and after changes), with results as `.md` and `.jsonl`. |
| [`audits/`](audits/) | Dated audits (UI, code, docs, features, research). Dated records; not rewritten. |
| [`research/plan.md`](research/plan.md) | How research on Pillar-43 is to be done. A plan; no instruments are built. |
| [`screenshots/`](screenshots/) | Screens used in the documentation. |

## Building and releasing

| Doc | What it holds |
|---|---|
| [`MACOS_CODE_SIGNING.md`](MACOS_CODE_SIGNING.md) | Signing and notarizing the macOS app. |
| [`sequence.md`](sequence.md) | The run order for the interface, video and page work. |
| [`../DEV_MANUAL.md`](../DEV_MANUAL.md) | Developer commands and tooling. |
| [`../DEPLOYMENT_GUIDE.md`](../DEPLOYMENT_GUIDE.md) | Running and resetting an install. |
| [`../RELEASING.md`](../RELEASING.md) | Cutting a tagged release. |
