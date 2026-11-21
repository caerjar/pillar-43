//! Where the vault lives.
//!
//! The shell must know which folders to hand the backend *before* it can spawn
//! the backend, so it cannot ask over HTTP. `locations.json` is the handoff:
//! the backend writes it (`Settings.write_locations`), this module reads it.
//!
//! Schema, versioned so a future shape change is detectable rather than
//! silently misread:
//!
//! ```json
//! { "version": 1, "vault": "/Users/me/Pillar-43",
//!   "notes": null, "generated": null, "library": null }
//! ```
//!
//! A `null` or absent mount means `<vault>/<mount>`. A non-null value is an
//! absolute path anywhere on disk. That single file is what makes "one folder
//! by default, each mount relocatable" one concept rather than two.
//!
//! **Extra libraries are not here.** They live in `libraries.conf`, which the
//! running backend re-reads per call. This file only carries the three mounts
//! the shell needs before boot.
//!
//! A malformed file must fall through to the defaults and never panic — the
//! Python side has the same rule (`Settings.read_locations`), and if the two
//! disagreed the app would launch with the shell and the backend pointing at
//! different folders, which is worse than either failure alone.

use std::path::{Path, PathBuf};

use serde::Deserialize;

/// The three mounts the backend needs in its environment at spawn time.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct Paths {
    pub notes: PathBuf,
    pub generated: PathBuf,
    pub library: PathBuf,
}

impl Paths {
    /// Every directory that must exist before the backend starts.
    ///
    /// `Settings.validate_startup(strict=True)` refuses to boot when notes or
    /// generated are missing, so this is not tidiness — a first launch dies at
    /// import without it.
    pub fn all(&self) -> [&Path; 3] {
        [&self.notes, &self.generated, &self.library]
    }
}

#[derive(Debug, Default, Deserialize)]
struct Locations {
    vault: Option<String>,
    notes: Option<String>,
    generated: Option<String>,
    library: Option<String>,
}

fn read_locations(path: &Path) -> Locations {
    let Ok(text) = std::fs::read_to_string(path) else {
        return Locations::default();
    };
    match serde_json::from_str::<Locations>(&text) {
        Ok(l) => l,
        Err(e) => {
            // Log and carry on. An unparseable file is a reason to use the
            // defaults, never a reason to be unlaunchable.
            eprintln!("[pillar43] ignoring malformed {}: {e}", path.display());
            Locations::default()
        }
    }
}

/// Read an env var, treating blank as unset.
///
/// `PILLAR43_VAULT=` in a launchd plist or a shell profile is a common way to
/// *unset* something; taking it literally would point the vault at "".
fn env_path(key: &str) -> Option<PathBuf> {
    std::env::var(key).ok().and_then(|v| {
        let v = v.trim();
        (!v.is_empty()).then(|| PathBuf::from(v))
    })
}

fn home() -> PathBuf {
    std::env::var("HOME")
        .map(PathBuf::from)
        .unwrap_or_else(|_| PathBuf::from("/tmp"))
}

/// Resolve the three mount paths, highest precedence first:
///
/// 1. `$NOTES_PATH` / `$GENERATED_PATH` / `$LIBRARY_ROOT` — per-mount escape
///    hatch, and the same names the backend itself reads
/// 2. `locations.json` per-mount value, when non-null — the user relocated
///    this one mount
/// 3. `$PILLAR43_VAULT` — the pre-existing tester override for the base,
///    deliberately preserved
/// 4. `locations.json` `vault` — what the wizard recorded
/// 5. `$HOME/Pillar-43` — unchanged for anyone who never opens the step
///
/// 3 sits above 4 so that an env override still wins over a stored choice,
/// which is what makes it useful for pointing a build at a test vault.
pub fn resolved_paths(data_dir: &Path) -> Paths {
    let file = env_path("PILLAR43_LOCATIONS_PATH")
        .unwrap_or_else(|| data_dir.join("locations.json"));
    let stored = read_locations(&file);

    let base = env_path("PILLAR43_VAULT")
        .or_else(|| stored.vault.as_ref().map(PathBuf::from))
        .unwrap_or_else(|| home().join("Pillar-43"));

    let resolve = |env_key: &str, stored: &Option<String>, name: &str| -> PathBuf {
        env_path(env_key)
            .or_else(|| stored.as_ref().map(PathBuf::from))
            .unwrap_or_else(|| base.join(name))
    };

    Paths {
        notes: resolve("NOTES_PATH", &stored.notes, "notes"),
        generated: resolve("GENERATED_PATH", &stored.generated, "generated"),
        library: resolve("LIBRARY_ROOT", &stored.library, "library"),
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use std::sync::{Mutex, MutexGuard};

    // Environment is process-global, so these cannot run concurrently.
    static ENV_LOCK: Mutex<()> = Mutex::new(());

    struct Env(#[allow(dead_code)] MutexGuard<'static, ()>);

    impl Env {
        fn new() -> Self {
            let guard = ENV_LOCK.lock().unwrap_or_else(|e| e.into_inner());
            for k in [
                "PILLAR43_VAULT",
                "PILLAR43_LOCATIONS_PATH",
                "NOTES_PATH",
                "GENERATED_PATH",
                "LIBRARY_ROOT",
            ] {
                std::env::remove_var(k);
            }
            std::env::set_var("HOME", "/home/tester");
            Env(guard)
        }
        fn set(&self, k: &str, v: &str) {
            std::env::set_var(k, v);
        }
    }

    fn write(dir: &Path, body: &str) -> PathBuf {
        let p = dir.join("locations.json");
        std::fs::write(&p, body).unwrap();
        p
    }

    fn tmpdir(name: &str) -> PathBuf {
        let d = std::env::temp_dir().join(format!("pillar43-paths-{name}"));
        let _ = std::fs::remove_dir_all(&d);
        std::fs::create_dir_all(&d).unwrap();
        d
    }

    #[test]
    fn rank5_defaults_to_home_pillar43() {
        let env = Env::new();
        let d = tmpdir("rank5");
        let p = resolved_paths(&d);
        assert_eq!(p.notes, PathBuf::from("/home/tester/Pillar-43/notes"));
        assert_eq!(p.generated, PathBuf::from("/home/tester/Pillar-43/generated"));
        assert_eq!(p.library, PathBuf::from("/home/tester/Pillar-43/library"));
        drop(env);
    }

    #[test]
    fn rank4_stored_vault_moves_all_three() {
        let env = Env::new();
        let d = tmpdir("rank4");
        write(&d, r#"{"version":1,"vault":"/Volumes/Work/Vault"}"#);
        let p = resolved_paths(&d);
        assert_eq!(p.notes, PathBuf::from("/Volumes/Work/Vault/notes"));
        assert_eq!(p.library, PathBuf::from("/Volumes/Work/Vault/library"));
        drop(env);
    }

    #[test]
    fn rank3_env_vault_beats_the_stored_one() {
        // The tester override has to keep working, or pointing a signed build
        // at a scratch vault means editing a JSON file inside Application
        // Support.
        let env = Env::new();
        let d = tmpdir("rank3");
        write(&d, r#"{"version":1,"vault":"/stored"}"#);
        env.set("PILLAR43_VAULT", "/from-env");
        let p = resolved_paths(&d);
        assert_eq!(p.notes, PathBuf::from("/from-env/notes"));
        drop(env);
    }

    #[test]
    fn rank2_a_single_mount_can_live_outside_the_vault() {
        let env = Env::new();
        let d = tmpdir("rank2");
        write(
            &d,
            r#"{"version":1,"vault":"/vault","notes":"/Users/me/Documents/Notes"}"#,
        );
        let p = resolved_paths(&d);
        assert_eq!(p.notes, PathBuf::from("/Users/me/Documents/Notes"));
        // The others stay inside the vault — this is the whole point.
        assert_eq!(p.generated, PathBuf::from("/vault/generated"));
        assert_eq!(p.library, PathBuf::from("/vault/library"));
        drop(env);
    }

    #[test]
    fn rank1_per_mount_env_wins_over_everything() {
        let env = Env::new();
        let d = tmpdir("rank1");
        write(&d, r#"{"version":1,"vault":"/vault","notes":"/stored-notes"}"#);
        env.set("PILLAR43_VAULT", "/env-vault");
        env.set("NOTES_PATH", "/env-notes");
        let p = resolved_paths(&d);
        assert_eq!(p.notes, PathBuf::from("/env-notes"));
        assert_eq!(p.generated, PathBuf::from("/env-vault/generated"));
        drop(env);
    }

    #[test]
    fn a_null_mount_means_inside_the_vault() {
        let env = Env::new();
        let d = tmpdir("nullmount");
        write(&d, r#"{"version":1,"vault":"/vault","notes":null}"#);
        assert_eq!(resolved_paths(&d).notes, PathBuf::from("/vault/notes"));
        drop(env);
    }

    #[test]
    fn a_malformed_file_falls_through_and_does_not_panic() {
        // The rule this pins: unlaunchable is never an acceptable response to a
        // bad config file. Python's read_locations() agrees, and if the two
        // disagreed the shell and backend would point at different folders.
        let env = Env::new();
        let d = tmpdir("malformed");
        write(&d, "{ this is not json");
        assert_eq!(
            resolved_paths(&d).notes,
            PathBuf::from("/home/tester/Pillar-43/notes")
        );
        drop(env);
    }

    #[test]
    fn a_missing_file_is_not_an_error() {
        let env = Env::new();
        let d = tmpdir("missing");
        assert_eq!(
            resolved_paths(&d).notes,
            PathBuf::from("/home/tester/Pillar-43/notes")
        );
        drop(env);
    }

    #[test]
    fn a_blank_env_override_is_treated_as_unset() {
        // `PILLAR43_VAULT=` is how people unset things in a plist or profile.
        // Taken literally it would point the vault at "".
        let env = Env::new();
        let d = tmpdir("blank");
        env.set("PILLAR43_VAULT", "   ");
        assert_eq!(
            resolved_paths(&d).notes,
            PathBuf::from("/home/tester/Pillar-43/notes")
        );
        drop(env);
    }

    #[test]
    fn an_explicit_locations_path_is_honoured() {
        // The shell passes PILLAR43_LOCATIONS_PATH to the backend so the two
        // cannot disagree about the filename; it must read the same one.
        let env = Env::new();
        let d = tmpdir("explicit");
        let elsewhere = tmpdir("explicit-other");
        let f = write(&elsewhere, r#"{"version":1,"vault":"/from-explicit"}"#);
        env.set("PILLAR43_LOCATIONS_PATH", f.to_str().unwrap());
        assert_eq!(
            resolved_paths(&d).notes,
            PathBuf::from("/from-explicit/notes")
        );
        drop(env);
    }
}
