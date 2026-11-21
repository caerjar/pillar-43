# Keeping Pillar-43 running

For press staff. Updating, backing up, changing the answer model, and what to do
when something is wrong. Every command here was run on a test installation; where
something does not exist yet, this guide says so.

Open Terminal in the Pillar-43 folder and paste the three `export` lines from
[install.md](install.md) Step 5 first (use the names of the installation you are working on).

## Everyday

| To do this | Paste | You should see |
|---|---|---|
| See if it is running | `make archive-status` | `api` and `web` both `Up`, then a list of counts |
| Read the last messages | `docker compose -p "$ARCHIVE_PROJECT" logs --tail 50 api` | lines of text ending with the latest activity |
| Stop (nothing deleted) | `docker compose -p "$ARCHIVE_PROJECT" stop` | `Stopped` for `web` and `api` |
| Start again | `docker compose -p "$ARCHIVE_PROJECT" start` | `Started` for `api` and `web`; reload the page after half a minute |
| Check the program answers | `curl -s http://127.0.0.1:$ARCHIVE_API_PORT/health` | text containing `"status":"ok"` and `"profile":"org"` |

Do not use `make archive` for restarting. It runs intake again and opens every
contract and "yellow" document to the AI, undoing decisions made by hand.

## Update

There is no tagged release yet, so **[the maintainer]** tells you when to update.

1. Back up first (next section).
2. Get the new files. If you received a new folder, copy `.env.press` and the `.press` folder from the old one into it. If you use git:

```
git pull
```

You should see `Already up to date.` or a list of changed files.

3. Rebuild and start. This keeps your documents, decisions and accounts. Paste all of it as one line. `ARCHIVE_ENV` is `.env.press` for your press and `.env.archive` for the invented one (set it the way install.md does):

```
API_PORT=$ARCHIVE_API_PORT WEB_PORT=$ARCHIVE_WEB_PORT docker compose -p "$ARCHIVE_PROJECT" --env-file "$ARCHIVE_ENV" -f docker-compose.yml -f docker-compose.archive.yml up --build -d
```

You should see `Built`, then `Started` for `api` and `web`. A rebuild takes
seconds when little changed and minutes when much did.

4. Check it came back:

```
curl -s http://127.0.0.1:$ARCHIVE_API_PORT/health
```

You should see `"status":"ok"`. Open the web address and sign in. Check that
`make archive-status` shows the counts you had.

If the page does not come back: see the table below, then restore the backup.

## Backups

**The records have a backup command; the folders around them do not.** One command saves the
levels, withdrawals, accounts and the ledger to a single file and checks it. The manual steps
below copy everything else (and the whole data volume). Do both before every update and every Friday.

The quick one, with Pillar-43 running (use `make archive-backup` if that is how you start it):

```
./pillar43 backup /Volumes/YourBackupDrive/pillar-43/
```

It prints `Backup written and verified: <file> (<N> ledger line(s))`. If it prints anything
else, there is no backup. To put it back: `./pillar43 restore <file>`. It refuses if the
archive has recorded more since (that would lose those changes) and tells you; adding
`--force` replaces them. `make clean` and `./pillar43 reset` will not delete the records
until a backup in `backups/` covers them. Details in `DEPLOYMENT_GUIDE.md`, "Backups".

The manual procedure (everything, including the search index), run on a test installation:

What to save:

- The records: levels, accounts, the ledger, the search index. They live in a Docker storage area, not in a folder you can see.
- The folder `.press` (or `.archive`) beside the program: generated folders and saved settings.
- The settings file `.env.press` (or `.env.archive`).
- Your original documents (the press folder). Pillar-43 never changes them; back them up the way the press already does. They are not part of this procedure.

Make a backup:

1. Stop Pillar-43, so the records are not changing:

```
docker compose -p "$ARCHIVE_PROJECT" stop
```

2. Make a dated folder on a drive that is not this Mac's own disk. Replace the path with your drive. This line stores it in `BACKUP`:

```
BACKUP="/Volumes/YourBackupDrive/pillar-43-$(date +%F)"; mkdir -p "$BACKUP"
```

3. Copy the records (one line):

```
docker run --rm -v "${ARCHIVE_PROJECT}_pillar43_data":/data -v "$BACKUP":/backup alpine tar czf /backup/data.tar.gz -C /data .
```

4. Copy the folder and the settings file (use `.archive` and `.env.archive` for the invented press):

```
cp -R .press "$BACKUP/press"
cp "$ARCHIVE_ENV" "$BACKUP/"
```

5. Start Pillar-43 again:

```
docker compose -p "$ARCHIVE_PROJECT" start
```

You should see in the backup folder: `data.tar.gz` (the records; for the invented press
about 0.4 MB), `press` and the settings file. If `data.tar.gz` is missing or has size 0,
the backup did not work; do not trust it.

Restore a backup. This replaces everything in the records with the backup: anything done since
is lost. On the test installation a change made after the backup was gone after the
restore, as intended.

1. Stop it: `docker compose -p "$ARCHIVE_PROJECT" stop`
2. Put the path of the backup folder in `BACKUP`:

```
BACKUP="/Volumes/YourBackupDrive/pillar-43-2026-11-20"
```

3. Replace the records (one line):

```
docker run --rm -v "${ARCHIVE_PROJECT}_pillar43_data":/data -v "$BACKUP":/backup alpine sh -c 'rm -rf /data/* /data/.[!.]* ; tar xzf /backup/data.tar.gz -C /data'
```

4. Start it: `docker compose -p "$ARCHIVE_PROJECT" start`
5. Check it: wait half a minute, then run the record check in [archivist.md](archivist.md) step 8 and `make archive-status`. The counts should match the day of the backup.

Not tested: restoring onto a different Mac, or into a new empty installation.
Folders under `.press/generated` are restored by copying them back from `press`.

**Disk encryption.** The application describes encrypted storage. That is done by
the Mac, not by Pillar-43: turn on FileVault (System Settings, Privacy & Security,
FileVault) and use an encrypted drive for backups (in Finder, right-click the drive,
Encrypt). This was not checked on the test Mac.

## Change the answer model

Pillar-43 answers with Qwen3 8B. To use another model Ollama has:

1. Download it: `ollama pull MODELNAME`, then `ollama list` shows it.
2. Open `api/orgs/press.yaml` in a plain-text editor and change the line under `models:` that says `answer: qwen3:8b` to `answer: MODELNAME`. Save.
3. Rebuild with the command in "Update", step 3.
4. Ask a question in the web app.

On the test installation, changing the line to `llama3.2:1b`, rebuilding and asking
loaded that model in Ollama (check with `ollama ps`) and produced an answer. A
model name Ollama does not have (`ollama list` shows what it has) produced
`HTTP Error 404: Not Found` in Terminal; in the web app the same fault is
expected to read "The local model is not running." (from the program's code; not
seen on screen). Only a model Ollama has will work. Smaller models answer worse; the
50-question check in `docs/eval` was run with Qwen3 8B only. Models for handwriting and
recordings are not used yet.

## When something is wrong

| What you see | What it means | What to do |
|---|---|---|
| The web address will not open | Pillar-43 or Docker Desktop is stopped | Open Docker Desktop. Run `make archive-status`. If `api` and `web` are not both `Up`, run `docker compose -p "$ARCHIVE_PROJECT" start`. |
| At startup: `driver failed programming external connectivity` | Another program uses the port | `lsof -i :$ARCHIVE_API_PORT` shows who (a line starting `com.docke` means another Docker installation, maybe your other Pillar-43). Choose other numbers (`export ARCHIVE_API_PORT=8063`, `export ARCHIVE_WEB_PORT=5213`) and start again. Do not remove the other program's data. |
| Ask says "The local model is not running." | Ollama is off, or the model named in `archive.yaml` is not downloaded | Open Ollama (llama icon in the menu bar). Run `ollama list`; it must show the model named in `api/orgs/press.yaml`. |
| Ask is blank, or says the archive does not hold an answer | No open item contains the answer, or the item is closed | Run `make archive-status` and look at the counts: are the contracts `model`? Closed items are not read. Ask again once. |
| Ask answers with an unrelated sentence | A known weakness: with the relevant item closed, it can quote something else | Do not rely on an answer without opening its citation. Send the question to **[the maintainer]**. |
| Sign-in says "Wrong name or password" | Wrong name or password | Names are exact, including capitals. There is no reset screen yet; ask **[the maintainer]**. |
| Someone can open the app without signing in | No account has been made on this installation | Do Step 7 of [install.md](install.md) now. |
| `make archive` ends with "API did not come up" | It started too slowly or failed | `docker compose -p "$ARCHIVE_PROJECT" logs --tail 50 api`, send the lines to **[the maintainer]**. |
| Counts of open items rose after `make archive` | `make archive` reopens contracts and yellow documents | Set them back as your forms say ([permissions.md](permissions.md)). Use `start`, not `make archive`, from now on. |
| The record check shows `'ok': False` | A line of the record was changed or removed | Stop. Do not change anything. Send the number after `first_bad_seq` to **[the maintainer]**. Restore the last backup only if told to. |
| Everything is slow | The Mac is short of memory; the model is large | Quit other large programs. `ollama ps` shows what is loaded. |

## Who to contact

**[the maintainer: name, phone, email, hours]**

When you write, include: what you did, what you saw, the output of
`make archive-status`, and the last lines of
`docker compose -p "$ARCHIVE_PROJECT" logs --tail 50 api`. Never send documents.
