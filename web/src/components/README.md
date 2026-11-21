# components/ — entry-point map

One line per panel. Use this to find the right component fast instead of `ls`-ing every dir.

## Top-level (eager) — imported directly in `App.tsx`
- `ActivityBar.tsx` — the left ribbon, one name written under each icon: Ask, Explore, People,
  Files (admin only). A writer's ribbon is "My work" alone. Settings is the gear at the bottom and
  opens the Preferences window (⌘,).
- `MenuBar/MenuBar.tsx` — Pillar-43 / Go, for the browser and Docker builds.
  The macOS app renders the same model as a native menu instead (`desktop/src-tauri/src/menu.rs`),
  and this returns `null` there. Both read `web/src/lib/menu/menuModel.ts`.

(`PanelHeader.tsx` was listed here for a long time and does not exist.)

## Panels (lazy-loaded by route/tab)

| Panel | Entry file | What it does |
|---|---|---|
| Ask | `Archive/Ask/AskPage.tsx` | Ask a question; answer with cited passages, page highlights and the silences (what the archive does not hold). `OpenToAi.tsx` sets whether an item is open to the model |
| Explore | `Archive/Explore/ExploreView.tsx` | Every open passage on a query, as rows and a timeline |
| People | `Archive/People/PeopleView.tsx` | Names found in the archive: signed, wrote, received, mentioned |
| My work | `Archive/Terms/TermsView.tsx` | A writer's own items and the terms on them |
| Sign in | `Archive/SignIn/SignIn.tsx` | Sign-in screen for the organization edition |
| Command Palette | `CommandPalette/CommandPalette.tsx` | ⌘P / ⌘O — commands, files, threads, recents. Reads the menu model, so it cannot drift from the menus |
| Editor | `Editor/Editor.tsx` | File viewer (PDF, image, audio, text) with CodeMirror editing and autosave |
| File Tree | `FileTree/FileTree.tsx` | Left panel: vault navigator |
| Search | `Search/SearchPalette.tsx` | ⌘K (or `/`) — full-text + semantic search |
| Settings | `Settings/SettingsWindow.tsx` | Preferences **window** (⌘,), not a pane. Groups are data in `Settings/groups.tsx` — one list read by both the nav and the content pane, so an entry cannot navigate to nothing. One group renders at a time. Row primitives in `Settings/controls.tsx` |
| Transcribe | `Transcribe/Transcribe.tsx` | Audio/video → text |

## `ui/` — reusable primitives
- `Confirm.tsx` — `<ConfirmProvider>` + `useConfirm()` for confirm dialogs
- `Toast.tsx` — `<ToastProvider>` + `useToast()` for transient messages
- `JobStatusBar.tsx` — global progress bar with Stop button
- `ResizeHandle.tsx` — drag-to-resize splitter
- `Badge.tsx`, plus other small primitives

When adding a new panel: create `components/<Name>/<Name>.tsx`, export the main component,
lazy-import from `App.tsx`, add a row to this table — and add a `DESTINATIONS` entry in
`web/src/lib/menu/menuModel.ts`. That one entry gives it a Go-menu item, a command-palette
command, a `g`-chord and a place in the native macOS menu; without it the panel is reachable
only by whatever you wire by hand.
