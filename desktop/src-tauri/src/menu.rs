//! The native macOS menu.
//!
//! Labels and ids come from `menu_model.json`, generated from
//! `web/src/lib/menu/menuModel.ts` by `scripts/codegen-menu`. Hand-copying them
//! would make this the second source of truth, and the repo already has one
//! scar from exactly that: the wizard and Settings drifted to different default
//! Ollama models (`qwen2.5` vs `llama3`) because two files described the same
//! thing.
//!
//! ## Two things here are load-bearing
//!
//! **1. Every OS affordance is added back by hand, deliberately.**
//! Tauri synthesises a default macOS menu (`enable_macos_default_menu`), and
//! passing `.menu(...)` replaces it — so Cmd-C, Cmd-V, Cmd-Q and Cmd-W vanish
//! unless each is re-added. Nothing errors; the app quietly loses copy and
//! paste, and it gets reported weeks later as something else.
//!
//! The first cut avoided that by starting from `Menu::default(app)?` and
//! *appending*. That kept the predefined items and shipped a menu bar with
//! **two File menus and two Help menus**, because the default already has
//! both — and the Help macOS focuses is its own, so "Help" searched Mac Help
//! rather than Pillar-43's. Appending cannot fix that; the assembly has to be
//! explicit, which is what `build` below does. `PredefinedMenuItem` is what
//! makes it safe: `.copy()`, `.paste()`, `.quit()` and friends carry the real
//! system actions and their accelerators.
//!
//! **2. Dispatch with `eval`, not `emit`.**
//! The window loads `http://127.0.0.1:<port>`, which Tauri classifies as a
//! REMOTE origin. `core:event:default` (which carries `allow-listen`) is part
//! of `core:default`, and `capabilities/default.json` grants that to the local
//! context only — so the page cannot listen for a Tauri event. Making `emit`
//! work would mean widening the wildcard grant in `capabilities/remote.json`,
//! the file whose whole description is about being narrow.
//!
//! `eval` is a host-side API with no capability check: the ACL governs what the
//! *page* may invoke, not what the shell injects. So the shell dispatches a
//! plain `CustomEvent` and the page listens with `addEventListener`. Zero new
//! permissions. See `web/src/lib/desktop.ts:onNativeMenu`.
//!
//! This is the same class of mistake as the old `pick_vault_folder`, which sat
//! here for months being unreachable from a remote origin while its comment
//! claimed the wizard called it.

use serde::Deserialize;
use tauri::menu::{
    AboutMetadata, Menu, MenuBuilder, MenuItemBuilder, PredefinedMenuItem, Submenu,
    SubmenuBuilder,
};
use tauri::{AppHandle, Manager, Runtime};

/// Must match `NATIVE_MENU_EVENT` in `web/src/lib/desktop.ts`.
const MENU_EVENT: &str = "pillar43:menu";

/// Generated — see `scripts/codegen-menu`.
const MODEL_JSON: &str = include_str!("menu_model.json");

fn model_json() -> &'static str {
    MODEL_JSON
}

fn app_title() -> &'static str {
    "Pillar-43"
}

#[derive(Debug, Deserialize)]
struct MenuModel {
    menus: Vec<MenuDef>,
}

#[derive(Debug, Clone, Deserialize)]
struct MenuDef {
    id: String,
    label: String,
    items: Vec<Entry>,
}

#[derive(Debug, Clone, Deserialize)]
#[serde(untagged)]
enum Entry {
    /// The literal string "separator". The payload is never read — serde needs
    /// a field here to match a bare JSON string in an untagged enum, and the
    /// variant itself is the whole signal.
    Separator(#[allow(dead_code)] String),
    Item {
        id: String,
        label: String,
        #[serde(default)]
        accelerator: Option<String>,
    },
}

/// Assemble the whole menu bar, in macOS order.
///
/// Pillar-43 · Edit · Go · Window. The model supplies the application menu's
/// extras and Go; the rest is the OS's.
///
/// Window is built entirely from `PredefinedMenuItem` and never appears in the
/// model. Edit is predefined too, with one exception the model owns: Find,
/// which macOS does not supply and whose behaviour is the editor's. See
/// `edit_menu`.
pub fn build<R: Runtime>(app: &AppHandle<R>) -> tauri::Result<Menu<R>> {
    let model: MenuModel = match serde_json::from_str(model_json()) {
        Ok(m) => m,
        Err(e) => {
            // A malformed model must still leave a usable menu bar — copy,
            // paste and quit are not ours to lose. Same rule as paths.rs: a
            // bad generated file is not a reason to be unusable.
            eprintln!("[pillar43] menu model unreadable, OS menus only: {e}");
            return MenuBuilder::new(app)
                .item(&os_app_menu(app, app_title(), &[])?)
                .item(&edit_menu(app, &[])?)
                .item(&window_menu(app)?)
                .build();
        }
    };

    let find = |id: &str| model.menus.iter().find(|m| m.id == id).cloned();
    let mut bar = MenuBuilder::new(app);

    let app_items = find("app").map(|m| m.items).unwrap_or_default();
    let title = find("app")
        .map(|m| m.label)
        .unwrap_or_else(|| app_title().into());
    bar = bar.item(&os_app_menu(app, &title, &app_items)?);

    // Edit is predefined + exactly one model item (Find). See `edit_menu`.
    let edit_items = find("edit").map(|m| m.items).unwrap_or_default();
    bar = bar.item(&edit_menu(app, &edit_items)?);

    // The model defines the application menu and Go; every other menu is the
    // OS's own, built from predefined items.
    if let Some(def) = find("go") {
        bar = bar.item(&build_submenu(app, &def)?);
    }

    bar = bar.item(&window_menu(app)?);

    bar.build()
}

/// The application menu. macOS titles this with the app name whatever we pass.
fn os_app_menu<R: Runtime>(
    app: &AppHandle<R>,
    title: &str,
    extra: &[Entry],
) -> tauri::Result<Submenu<R>> {
    let mut b = SubmenuBuilder::new(app, title).about(Some(AboutMetadata::default()));
    if !extra.is_empty() {
        b = add_entries(app, b.separator(), extra)?;
    }
    b.separator()
        .services()
        .separator()
        .hide()
        .hide_others()
        .show_all()
        .separator()
        .quit()
        .build()
}

/// Predefined items, so the system accelerators keep working — this submenu is
/// the whole reason to be careful with `.menu(...)` — plus whatever the model
/// puts in `edit`, appended after a separator.
///
/// `extra` is the one exception to "Edit comes entirely from the OS", and it
/// is narrow on purpose: macOS publishes no predefined Find, and Find's
/// behaviour is the editor's, not the system's. Anything the OS *does* supply
/// belongs above, not in the model — see `the_model_defines_no_os_menu`, which
/// still forbids a whole model-defined Edit or Window menu.
fn edit_menu<R: Runtime>(app: &AppHandle<R>, extra: &[Entry]) -> tauri::Result<Submenu<R>> {
    let b = SubmenuBuilder::new(app, "Edit")
        .undo()
        .redo()
        .separator()
        .cut()
        .copy()
        .paste()
        .select_all();
    if extra.is_empty() {
        return b.build();
    }
    add_entries(app, b.separator(), extra)?.build()
}

fn window_menu<R: Runtime>(app: &AppHandle<R>) -> tauri::Result<Submenu<R>> {
    // Tauri 2 exposes no `bring_all_to_front`, so that HIG staple is simply
    // unavailable rather than omitted on purpose.
    // Enter Full Screen lives here again. It sat at the bottom of View, which
    // is where Safari, Mail and Notes put it — but View is gone, and Window is
    // both Tauri's default placement and the only remaining home. Losing the
    // item entirely was the alternative; it is a PredefinedMenuItem, so the
    // model cannot carry it.
    SubmenuBuilder::new(app, "Window")
        .minimize()
        .maximize()
        .separator()
        .fullscreen()
        .build()
}

fn build_submenu<R: Runtime>(app: &AppHandle<R>, def: &MenuDef) -> tauri::Result<Submenu<R>> {
    let builder = add_entries(app, SubmenuBuilder::new(app, &def.label), &def.items)?;
    builder.build()
}

fn add_entries<'m, R: Runtime>(
    app: &'m AppHandle<R>,
    mut builder: SubmenuBuilder<'m, R, AppHandle<R>>,
    entries: &[Entry],
) -> tauri::Result<SubmenuBuilder<'m, R, AppHandle<R>>> {
    for entry in entries {
        match entry {
            Entry::Separator(_) => {
                builder = builder.item(&PredefinedMenuItem::separator(app)?);
            }
            Entry::Item {
                id,
                label,
                accelerator,
            } => {
                let mut item = MenuItemBuilder::with_id(id.clone(), label);
                if let Some(acc) = accelerator {
                    item = item.accelerator(acc);
                }
                builder = builder.item(&item.build(app)?);
            }
        }
    }
    Ok(builder)
}

/// Forward the chosen item id to the page.
pub fn dispatch<R: Runtime>(app: &AppHandle<R>, id: &str) {
    let Some(webview) = app.get_webview_window("main") else {
        return;
    };
    // The ids are ours (generated, `[a-z.-]`), but a menu id reaching `eval`
    // unescaped would still be a string-injection seam. Refuse anything that
    // is not the shape we generate rather than trusting the generator.
    if !id
        .chars()
        .all(|c| c.is_ascii_alphanumeric() || c == '.' || c == '-' || c == '_')
    {
        eprintln!("[pillar43] refusing to dispatch odd menu id: {id:?}");
        return;
    }
    let script = format!(
        "window.dispatchEvent(new CustomEvent('{MENU_EVENT}', {{ detail: '{id}' }}))"
    );
    if let Err(e) = webview.eval(&script) {
        eprintln!("[pillar43] could not dispatch menu event {id}: {e}");
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    fn model() -> MenuModel {
        serde_json::from_str(MODEL_JSON).expect("generated menu model must parse")
    }

    #[test]
    fn the_model_is_the_app_menu_and_go_only() {
        let m = model();
        let ids: Vec<&str> = m.menus.iter().map(|d| d.id.as_str()).collect();
        assert_eq!(ids, ["app", "go"]);
        assert_eq!(m.menus[0].label, "Pillar-43");
        // No removed-feature entries in what is left.
        for def in &m.menus {
            for entry in &def.items {
                if let Entry::Item { id, .. } = entry {
                    assert!(
                        !id.starts_with("file.")
                            && !id.starts_with("research.")
                            && !id.starts_with("help."),
                        "removed entry {id} in the menu"
                    );
                }
            }
        }
    }

    #[test]
    fn the_generated_model_parses() {
        assert!(!model().menus.is_empty());
    }

    #[test]
    fn every_item_carries_an_id() {
        for def in model().menus {
            for entry in def.items {
                if let Entry::Item { id, label, .. } = entry {
                    assert!(!id.is_empty(), "empty id in {}", def.label);
                    assert!(!label.is_empty(), "empty label in {}", def.label);
                }
            }
        }
    }

    #[test]
    fn no_menu_is_named_twice() {
        // The bug this replaced: appending to Menu::default gave the shipped
        // app two File menus and two Help menus, and macOS focused its own
        // Help — so "Help" searched Mac Help, not Pillar-43's.
        let m = model();
        let mut labels: Vec<&str> = m.menus.iter().map(|d| d.label.as_str()).collect();
        labels.sort_unstable();
        let before = labels.len();
        labels.dedup();
        assert_eq!(before, labels.len(), "duplicate menu label: {labels:?}");
    }

    #[test]
    fn the_model_defines_no_os_menu() {
        // Window is built entirely from PredefinedMenuItem. A model entry for
        // it would produce a second Window beside the real one — the "two File
        // menus, two Help menus" bug in this module's header, which is what
        // this test exists to prevent.
        let m = model();
        assert!(
            !m.menus.iter().any(|d| d.label == "Window"),
            "Window must come from PredefinedMenuItem, not the model"
        );

        // Edit used to be on that list too. It is now allowed to carry model
        // items, because `edit_menu` APPENDS them to the predefined ones
        // rather than replacing them — so there is still exactly one Edit
        // menu, and the OS items in it are still the OS's.
        //
        // Narrowed rather than deleted (2026-08-28, for Find): what must not
        // happen is the model redefining something the OS already supplies,
        // which would show the item twice with only one of them working.
        const OS_SUPPLIED: [&str; 6] = ["Undo", "Redo", "Cut", "Copy", "Paste", "Select All"];
        let Some(edit) = m.menus.iter().find(|d| d.label == "Edit") else {
            return;
        };
        for entry in &edit.items {
            let Entry::Item { label, .. } = entry else { continue };
            assert!(
                !OS_SUPPLIED.iter().any(|o| o.eq_ignore_ascii_case(label)),
                "{label} is a PredefinedMenuItem — remove it from the model, \
                 or Edit shows it twice with one copy inert"
            );
        }
    }

    #[test]
    fn the_go_menu_survived_generation() {
        // A generator that silently emitted an empty Go menu would look fine
        // until someone tried to reach Ask or Files.
        let m = model();
        let go = m
            .menus
            .iter()
            .find(|d| d.label == "Go")
            .expect("Go menu must exist");
        let ids: Vec<&str> = go
            .items
            .iter()
            .filter_map(|e| match e {
                Entry::Item { id, .. } => Some(id.as_str()),
                Entry::Separator(_) => None,
            })
            .collect();
        for id in ["go.ask", "go.files"] {
            assert!(ids.contains(&id), "Go menu is missing {id}");
        }
    }

    #[test]
    fn navigation_lives_in_go_and_view_is_gone() {
        // The reorganisation itself, asserted from the Rust side because this
        // is the file that builds the bar a user actually sees. Back/Forward
        // and the palettes belong in Go (Finder's placement).
        //
        // Without this, a revert of menuModel.ts would leave every other
        // assertion here passing — they all count entries rather than locate
        // them.
        //
        // The View half now pins its ABSENCE. It held only Focus Mode and
        // Light / Dark, both of which have a permanent top-bar button, so the
        // menu was removed rather than kept as a duplicate of two visible
        // controls. If it comes back, `⌘⇧F` is bound twice — once here via the
        // model and once explicitly in App.tsx — so this assertion is what
        // stops that landing quietly.
        let m = model();
        let ids = |label: &str| -> Vec<String> {
            m.menus
                .iter()
                .find(|d| d.label == label)
                .unwrap_or_else(|| panic!("{label} menu must exist"))
                .items
                .iter()
                .filter_map(|e| match e {
                    Entry::Item { id, .. } => Some(id.clone()),
                    Entry::Separator(_) => None,
                })
                .collect()
        };

        let go = ids("Go");
        for id in ["go.back", "go.forward", "go.search", "go.command-palette"] {
            assert!(go.iter().any(|g| g == id), "Go menu is missing {id}");
        }

        assert!(
            m.menus.iter().all(|d| d.label != "View" && d.id != "view"),
            "the View menu is back; see App.tsx's explicit mod+shift+f binding"
        );
    }

    #[test]
    fn destructive_and_editor_bound_keys_are_left_alone() {
        // ⌘D is CodeMirror's selectNextOccurrence and ⌘⌫ is "delete to
        // beginning of line". A native accelerator is an NSMenu key
        // equivalent, dispatched by AppKit before the webview sees it, so
        // claiming either would silently break editing in the desktop build
        // only. Duplicate and Move to Trash therefore ship with no
        // accelerator, on purpose — this pins that against a well-meaning
        // "the menu should have shortcuts" change.
        let m = model();
        for entry in m.menus.iter().flat_map(|d| d.items.iter()) {
            let Entry::Item { id, accelerator, .. } = entry else { continue };
            let Some(accel) = accelerator else { continue };
            let a = accel.replace(' ', "").to_lowercase();
            assert_ne!(a, "cmdorctrl+d", "{id} claims ⌘D, which CodeMirror binds");
            assert!(
                !a.ends_with("+backspace") && !a.ends_with("+delete"),
                "{id} claims a delete accelerator ({accel}) that is live in the editor"
            );
        }
    }

    #[test]
    fn no_item_is_filed_under_another_menus_prefix() {
        // `file.settings` sat in the application menu for months while its id
        // said `file.`. Harmless to the dispatcher — ids are resolved by
        // lookup, not by prefix — but it is how a reader learns the wrong
        // thing about where an item lives.
        //
        // Deliberately narrow: it fires only when an id claims a prefix that
        // is *some other menu's* id. The `run.*` items under Research are
        // fine, because no menu is called `run`.
        let m = model();
        let menu_ids: Vec<&str> = m.menus.iter().map(|d| d.id.as_str()).collect();
        for menu in &m.menus {
            for entry in &menu.items {
                let Entry::Item { id, .. } = entry else { continue };
                let Some((prefix, _)) = id.split_once('.') else { continue };
                if prefix == menu.id {
                    continue;
                }
                assert!(
                    !menu_ids.contains(&prefix),
                    "{id} lives in the {} menu but claims the {prefix} menu's prefix",
                    menu.id
                );
            }
        }
    }
}
