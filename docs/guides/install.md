# Install Pillar-43 on your own Mac

For press staff. You will type about ten lines into the Terminal app. Each step
says what you should see afterwards and what to do if you do not.

Pillar-43 runs on one Mac in your office. The questions you ask, the documents
and the answers stay on that Mac. This guide installs it with the invented press
(Lantern Wharf Editions) so you can check it works before any real document goes
in.

## What you need

| Item | What |
|---|---|
| Mac | Apple silicon (M1 or newer), macOS 14 or newer. |
| Memory | Tested on a MacBook Pro with an M3 Max and 48 GB of memory. The grant application names a workstation with 128 GB for the full archive (200 titles, 5,000 records, handwriting and recordings). Nothing smaller than 48 GB has been tried. A Mac with 16 GB is expected to be slow or to fail when the model loads; this has not been tested. |
| Disk | At least 15 GB free. The software images are about 1.7 GB and the answer model 5.2 GB; Docker needs room to build. Your own documents are extra. |
| Internet | Needed once, for the downloads in steps 1 to 4 and the first build. After that Pillar-43 does not need it. |
| Time | Allow an hour the first time, most of it waiting for downloads. On the test Mac, with the software parts already downloaded, Step 6 took 20 seconds; a Mac that has never built it has not been timed. |

## What never leaves your Mac

- The answer model (Qwen3 8B) runs in Ollama on your Mac. No question or document is sent to any hosted AI service. In the press edition a hosted service cannot be switched on, not even in Settings.
- Search uses a small model that is already built into the software, so indexing does not use the internet.
- There is no usage tracking, no analytics and no web font loaded from elsewhere.
- Documents marked private are not searched or read, by staff or by the model. Ask shows only a number of items closed by their writers, never what they are. Documents marked staff are shown to signed-in staff but never sent to the model. Only documents marked model can be read by the model, and only at the moment a question is asked.
- Internet is used for: downloading Docker Desktop, Ollama, the model and the software images during install and updates. Nothing else.

A test in the software refuses every outbound connection except the one to Ollama
on your own Mac, and passes. It has not been run with Wi-Fi switched off by hand.

## Step 1. Install Docker Desktop

1. Download Docker Desktop for Mac (Apple silicon) from docker.com/products/docker-desktop and drag it into Applications.
2. Open Docker Desktop. Accept the terms. Wait until the whale icon in the menu bar stops moving.

You should see: the Docker Desktop window shows the engine as running (a green indicator at the bottom left).

If you do not: quit Docker Desktop and open it again. If it asks for your Mac password, give it.

## Step 2. Install Ollama and the answer model

1. Download Ollama from ollama.com and drag it into Applications. Open it once. A llama icon appears in the menu bar.
2. Open Terminal (press Command + Space, type Terminal, press Return).
3. Paste this line and press Return. It downloads 5.2 GB.

```
ollama pull qwen3:8b
```

You should see: a progress bar, then the word "success".

Check it: paste `ollama list` and press Return. You should see a line starting with `qwen3:8b`.

If you do not: make sure the llama icon is in the menu bar (open Ollama again), then repeat.

## Step 3. Install the Apple command line tools

These give you the `make` and `git` commands.

```
xcode-select --install
```

A window opens. Click Install and wait. If a message says the tools are already
installed, go on.

Check it: paste `make --version` and press Return. You should see "GNU Make".

## Step 4. Get Pillar-43 and open its folder

1. Get the Pillar-43 folder from **[the maintainer: the public download address, or the way the folder is handed to press staff]**. Put it in your home folder.
2. In Terminal, go into it. If the folder is called `pillar-43`:

```
cd ~/pillar-43
```

Check it: paste `ls Makefile` and press Return. You should see `Makefile`.

If you see "No such file or directory": the folder has another name or place. Type `cd ` (with a space), drag the folder from Finder into the Terminal window, and press Return.

## Step 5. Name this installation

Paste these four lines, one at a time, pressing Return after each. They give your
installation a name, two door numbers (ports) on your Mac, and the settings file it uses.

```
export ARCHIVE_PROJECT=pillar43
export ARCHIVE_API_PORT=8061
export ARCHIVE_WEB_PORT=5211
export ARCHIVE_ENV=.env.archive
```

Nothing is printed. If you close the Terminal window, paste the four lines again
in the new window before using any command in this guide. Always use the same
`ARCHIVE_PROJECT` name: your documents' record is stored under it.

If a later step says a port is already in use, pick other numbers (for example
8062 and 5212) and keep them.

## Step 6. Build and start Pillar-43

```
make archive-up
```

This builds the software and starts it. It does not read any documents yet. The
first time on a new Mac it downloads and builds for a while (not timed; plan on 10 minutes or more). Lines scroll by.
Do not close the window.

You should see: a line `Waiting for the API on :8061 .....`, and then the prompt returns.

If it stops with "API did not come up": run `make archive-logs`, press Control + C
after a few lines, and send those lines to **[the maintainer]**. If Docker says it cannot
connect, open Docker Desktop (Step 1) and run `make archive-up` again; it is safe to
repeat.

Check it: paste `make archive-status` and press Return. You should see two
services, `api` and `web`, both "Up".

## Step 7. Make the first administrator account, then load the invented press

Until the first account exists, anyone who can reach the web address can open the
archive without signing in. Withdrawing an item and changing its level are
refused until the account exists, so make it before you load any documents.

The account command needs a password. Do not type the password into the command
itself, because Terminal remembers commands. Use this instead. It asks for the name and the
password and does not show the password on screen or save it.

```
printf 'Administrator name: '; read ADMIN_NAME
printf 'Password (at least 8 characters, not shown): '; read -s ADMIN_PW; echo
export ADMIN_NAME ADMIN_PW
```

Then paste:

```
docker compose -p "$ARCHIVE_PROJECT" exec -e ADMIN_NAME -e ADMIN_PW api sh -c 'python scripts/archive_cli.py account "$ADMIN_NAME" admin "$ADMIN_PW"'
unset ADMIN_PW
```

You should see: `account <your name> (admin) created`.

If the last line says `ValueError: password must be at least 8 characters`: run the three `read` lines again with a longer password. (A block of technical text above that line is normal for any mistake in this command.)
If you see "no such service" or "no configuration file": you are not in the Pillar-43 folder (Step 4) or the names from Step 5 are missing.

Write the password down where the press keeps its passwords. There is no reset
screen yet: **[the maintainer]** can set a new one.

Now load the invented press:

```
make archive
```

This reads every file of the invented press (intake), makes it searchable
(index), and opens the contracts and four "yellow" documents to the model. Lines
scroll by.

You should see some JSON that ends with counts, and finally

```
Pillar-43: http://127.0.0.1:5211
```

Check it: paste `make archive-status` and press Return. You should see a list of
counts such as `contract:model`.

## Step 8. Sign in and ask one question

1. Open http://127.0.0.1:5211 in Safari or Chrome.
2. You should see a sign-in screen. Type the name and password from Step 7.
3. You should see the Ask screen. Type this question and press Return:

   How long is the cure period before rights revert on The Drowned Orchard?

You should see: within about 10 to 60 seconds an answer that quotes the contract
("within nine (9) months after the Publisher's receipt of that written request ...")
with a small `[2]` button and the line "Quoted from ... The Drowned Orchard". Click `[2]`:
the contract opens beside the answer at clause 7, Reversion, with the quoted
sentence highlighted. Under the answer, "Not in this answer" says how many items
the writers closed to the AI and lists staff items it did not read.

If it says "The local model is not running": open Ollama (Step 2) and ask again.
If the answer has no citation, or says the archive does not hold an answer: ask
again once. If it happens twice, send the question and what you saw to **[the maintainer]**.

You have a working installation.

## Step 9. Stop it and start it again

Stop for the night, or before a backup (nothing is deleted):

```
docker compose -p "$ARCHIVE_PROJECT" stop
```

Start it again:

```
docker compose -p "$ARCHIVE_PROJECT" start
```

You should see `Started` for `api` and `web`. Wait half a minute, then reload the
web address. Documents, decisions and accounts are as you left them.

Do not use `make archive` for this. It runs intake again and opens every contract
and every "yellow" document to the model, which undoes any decision made by hand.
On a restart of your own archive, use the two commands above.

(`make archive-stop` also works. It removes the running parts but keeps the stored
data. After it, the bring-up command in [maintenance.md](maintenance.md), "Update",
starts it again without touching decisions.)

## Using your own documents

Do not put real documents into the invented press. Make a second installation with
its own name, so its records are kept apart. This needs the check above to have
passed first. Nothing in this section opens any real document to the AI: new items
start at the level the press set for their kind (contracts and minutes: staff;
letters, email, recordings, handwriting and manuscripts: private).

1. Give the second installation its own name and ports:

```
export ARCHIVE_PROJECT=pillar43-press
export ARCHIVE_API_PORT=8062
export ARCHIVE_WEB_PORT=5212
export ARCHIVE_ENV=.env.press
```

2. Make a copy of the settings file for it, and open the copy in a plain-text editor (TextEdit set to "Make Plain Text", or BBEdit; not Word):

```
cp .env.archive "$ARCHIVE_ENV"
open -t "$ARCHIVE_ENV"
```

3. Change four lines and save. The first is the full path of your press folder (type `ls /Users/you/...` or drag the folder into the Terminal window to see its path):

```
LIBRARY_ROOT=/Users/your-name/PressArchive
NOTES_PATH=./.press/notes
GENERATED_PATH=./.press/generated
PILLAR43_ENV_FILE=.env.press
```

The last line tells the program which settings file to load. The copy still says `.env.archive`; left like that, your installation would load the invented press's settings.

4. Start it. This is one long line; paste all of it:

```
API_PORT=$ARCHIVE_API_PORT WEB_PORT=$ARCHIVE_WEB_PORT docker compose -p "$ARCHIVE_PROJECT" --env-file "$ARCHIVE_ENV" -f docker-compose.yml -f docker-compose.archive.yml up --build -d
```

You should see `Started` for `api` and `web`. Open http://127.0.0.1:5212. It is open
without a sign-in until you do Step 7 again. Do Step 7 now, in this window, so that
`ARCHIVE_PROJECT` is `pillar43-press`.

5. Continue in [archivist.md](archivist.md).

Your press folder is only read by Pillar-43. It is never changed or moved.

## Where things are

| What | Where |
|---|---|
| Documents you ingest | the folder named `LIBRARY_ROOT` in the settings file (`.env.archive` for the invented press, `.env.press` for yours). Pillar-43 only reads it. |
| Records, consent decisions, accounts, the ledger | a Docker storage area named after `ARCHIVE_PROJECT`. It survives `make archive-stop`. |
| Job outputs and generated files | the `.archive` folder (invented press) or `.press` folder (yours) inside the Pillar-43 folder. |

Backups, updates, changing the model and fixing problems:
[maintenance.md](maintenance.md).
