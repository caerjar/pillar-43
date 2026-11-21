// Pillar-43 — native macOS shell.
//
// This process owns three things and deliberately nothing else: the window,
// the backend child process, and the native dialogs the web UI cannot open for
// itself. It does NOT serve the frontend — the backend does that (see the
// StaticFiles mount in api/main.py), which is what makes the page same-origin
// with the API and removes CORS and any runtime base-URL injection from the
// picture entirely.
//
// Startup order matters and is not arbitrary:
//
//   1. pick a free loopback port
//   2. create the vault directories — `settings.validate_startup(strict=True)`
//      refuses to boot when notes/ or generated/ are missing, so a first launch
//      would die at import if we spawned first
//   3. spawn the backend with everything it needs in the environment
//   4. poll /health until it answers
//   5. only then show a window pointing at it
//
// Showing the window before step 4 would mean a blank frame while migrations
// run. Failing step 4 shows the child's stderr in a dialog rather than an empty
// window, because "it opened and nothing happened" is the least debuggable
// possible failure for someone who was sent a .dmg.

#![cfg_attr(not(debug_assertions), windows_subsystem = "windows")]

use std::io::{BufRead, BufReader};
use std::net::TcpListener;
use std::path::PathBuf;
use std::process::{Child, Command, Stdio};
use std::sync::{Arc, Mutex};
use std::time::{Duration, Instant};

use tauri::{Manager, WebviewUrl, WebviewWindowBuilder};

mod menu;
mod paths;
use paths::resolved_paths;

/// How long the backend gets to answer /health before we give up and show the
/// error dialog. Generous: a first launch runs the whole Alembic chain.
const HEALTH_TIMEOUT: Duration = Duration::from_secs(90);

struct Backend(Mutex<Option<Child>>);

/// Ask the OS for a free port by binding to 0, then release it.
///
/// There is a race between releasing and the child binding, but it is the same
/// race every dev server on the machine runs, and the alternative — a fixed
/// port — collides with the Docker stack the developer may also be running.
fn free_port() -> std::io::Result<u16> {
    let listener = TcpListener::bind("127.0.0.1:0")?;
    let port = listener.local_addr()?.port();
    drop(listener);
    Ok(port)
}

fn app_support_dir() -> PathBuf {
    let home = std::env::var("HOME").unwrap_or_else(|_| "/tmp".into());
    PathBuf::from(home)
        .join("Library")
        .join("Application Support")
        .join("Pillar-43")
}



fn is_healthy(port: u16) -> bool {
    // A hand-rolled request rather than a HTTP crate: this is the only network
    // call the shell ever makes, and it is to a socket we just spawned.
    use std::io::{Read, Write};
    use std::net::TcpStream;
    let Ok(mut stream) = TcpStream::connect(("127.0.0.1", port)) else {
        return false;
    };
    let _ = stream.set_read_timeout(Some(Duration::from_secs(3)));
    if stream
        .write_all(b"GET /health HTTP/1.1\r\nHost: 127.0.0.1\r\nConnection: close\r\n\r\n")
        .is_err()
    {
        return false;
    }
    let mut buf = String::new();
    if stream.read_to_string(&mut buf).is_err() {
        return false;
    }
    buf.starts_with("HTTP/1.1 200") || buf.starts_with("HTTP/1.0 200")
}

fn spawn_backend(app: &tauri::AppHandle, port: u16) -> Result<(Child, Arc<Mutex<Vec<String>>>), String> {
    let resource_dir = app
        .path()
        .resource_dir()
        .map_err(|e| format!("could not resolve the app's resource directory: {e}"))?;

    // A relocatable CPython running the backend's source, rather than a
    // PyInstaller-frozen binary (2026-08-19). The freeze was abandoned because
    // Avast-engine antivirus quarantines PyInstaller's bootloader as spyware —
    // a proven false positive that still made the app unbuildable. See
    // plans/EMBEDDED_CPYTHON_SIDECAR.md.
    let python = resource_dir.join("python").join("bin").join("python3.12");
    let entry = resource_dir.join("backend").join("app").join("backend_main.py");
    for (what, path) in [("interpreter", &python), ("entry point", &entry)] {
        if !path.is_file() {
            return Err(format!("backend {what} missing at {}", path.display()));
        }
    }
    // An interpreter that lost its executable bit fails at spawn() with a bare
    // "Permission denied" naming no file, which is a poor thing to hand a user.
    #[cfg(unix)]
    {
        use std::os::unix::fs::PermissionsExt;
        let mode = std::fs::metadata(&python)
            .map_err(|e| format!("could not stat the interpreter: {e}"))?
            .permissions()
            .mode();
        if mode & 0o111 == 0 {
            return Err(format!("interpreter is not executable: {}", python.display()));
        }
    }

    let data = app_support_dir();
    // Resolved before the mkdir, not after: a mount the user relocated must be
    // created where they put it, not where it used to be.
    let vault = resolved_paths(&data);
    for dir in vault.all().into_iter().chain(std::iter::once(data.as_path())) {
        std::fs::create_dir_all(dir)
            .map_err(|e| format!("could not create {}: {e}", dir.display()))?;
    }

    // Bundled binaries win over anything on the user's PATH, but the system
    // PATH is kept so a Homebrew ffmpeg still works for people who have one.
    let bin_dir = resource_dir.join("bin");
    let path = match std::env::var("PATH") {
        Ok(p) => format!("{}:{}", bin_dir.display(), p),
        Err(_) => bin_dir.display().to_string(),
    };

    // Spawn the interpreter DIRECTLY — never via `sh -c` or a launcher script.
    // Child::id() is what both shutdown paths SIGTERM, and a wrapper's PID
    // would leave uvicorn running: the FastAPI lifespan never fires, and the
    // batched git commit is lost silently.
    let mut child = Command::new(&python)
        .arg(&entry)
        // PyInstaller's bootloader ignored the ambient environment; a real
        // interpreter does not. This machine, for one, exports a PYTHONPATH
        // pointing at Homebrew's 3.13 site-packages — verified to leak straight
        // into sys.path. Clear both rather than trusting the user's shell.
        .env_remove("PYTHONPATH")
        .env_remove("PYTHONHOME")
        // Belt to the .pyc-only bundle's braces: anything written into a signed
        // .app after signing invalidates its code signature.
        .env("PYTHONDONTWRITEBYTECODE", "1")
        .env("PYTHONNOUSERSITE", "1")
        // backend_main.py resolves `../api` relative to itself and would find
        // this anyway; stating it means the import does not depend on the
        // bundle's directory shape staying as it is.
        .env("PYTHONPATH", resource_dir.join("backend").join("api"))
        .env("PILLAR43_DESKTOP", "1")
        .env("PILLAR43_PORT", port.to_string())
        .env("NOTES_PATH", &vault.notes)
        .env("GENERATED_PATH", &vault.generated)
        .env("LIBRARY_ROOT", &vault.library)
        .env("DATA_PATH", &data)
        .env("LIBRARIES_CONFIG_PATH", data.join("libraries.conf"))
        // Named rather than left to the default so the two processes cannot
        // disagree about the filename. See src/paths.rs.
        .env("PILLAR43_LOCATIONS_PATH", data.join("locations.json"))
        .env("WEB_DIST_PATH", resource_dir.join("web"))
        .env("FASTEMBED_CACHE_PATH", resource_dir.join("models"))
        .env("PILLAR43_HELP_SEED", resource_dir.join("seed").join("help").join("manual.md"))
        .env("PATH", path)
        .stdout(Stdio::piped())
        .stderr(Stdio::piped())
        .spawn()
        .map_err(|e| format!("could not start the backend: {e}"))?;

    // Drain both pipes. Not for logging's sake — a child whose pipes fill up
    // blocks forever on its next write, which would look exactly like a hang.
    let log: Arc<Mutex<Vec<String>>> = Arc::new(Mutex::new(Vec::new()));
    for stream in [
        child.stderr.take().map(|s| Box::new(s) as Box<dyn std::io::Read + Send>),
        child.stdout.take().map(|s| Box::new(s) as Box<dyn std::io::Read + Send>),
    ]
    .into_iter()
    .flatten()
    {
        let log = Arc::clone(&log);
        std::thread::spawn(move || {
            for line in BufReader::new(stream).lines().map_while(Result::ok) {
                eprintln!("[backend] {line}");
                let mut guard = log.lock().unwrap();
                // Keep only the tail; the dialog shows the end, and an
                // unbounded buffer is a slow leak over a long session.
                if guard.len() >= 200 {
                    guard.remove(0);
                }
                guard.push(line);
            }
        });
    }

    Ok((child, log))
}

// NOTE: there is no `pick_vault_folder` command any more. It existed here for
// months with a comment claiming "the wizard calls this" and nothing ever did,
// and it could not have: the window loads a remote loopback origin, and the
// only capability granted `ExecutionContext::Local`, so the command was
// unreachable from the page regardless. The folder picker now goes through the
// dialog plugin's own JS API, granted to that origin by
// capabilities/remote.json — one permission (`dialog:allow-open`) instead of an
// app command that would need its own ACL entry to do the same job.
//
// `vault_path` went with it: the backend already reports the live paths in
// `host_paths` (api/routes/settings.py), so asking the shell was a second
// answer to a question that already had one.

fn main() {
    tauri::Builder::default()
        .menu(menu::build)
        .on_menu_event(|app, event| menu::dispatch(app, event.id().as_ref()))
        .plugin(tauri_plugin_dialog::init())
        .plugin(tauri_plugin_single_instance::init(|app, _argv, _cwd| {
            // Second launch: focus the window we already have rather than
            // starting a second backend against the same SQLite file.
            if let Some(w) = app.get_webview_window("main") {
                let _ = w.set_focus();
                let _ = w.unminimize();
            }
        }))
        .setup(|app| {
            let handle = app.handle().clone();

            let port = free_port().map_err(|e| format!("no free port: {e}"))?;
            let (child, log) = spawn_backend(&handle, port)?;
            app.manage(Backend(Mutex::new(Some(child))));

            let started = Instant::now();
            let mut up = false;
            while started.elapsed() < HEALTH_TIMEOUT {
                if is_healthy(port) {
                    up = true;
                    break;
                }
                std::thread::sleep(Duration::from_millis(250));
            }

            if !up {
                let tail = log.lock().unwrap().join("\n");
                let tail = tail.chars().rev().take(1500).collect::<String>();
                let tail: String = tail.chars().rev().collect();
                use tauri_plugin_dialog::{DialogExt, MessageDialogKind};
                handle
                    .dialog()
                    .message(format!(
                        "Pillar-43's backend did not start within {}s.\n\n{}",
                        HEALTH_TIMEOUT.as_secs(),
                        if tail.is_empty() { "(no output)".into() } else { tail }
                    ))
                    .kind(MessageDialogKind::Error)
                    .title("Pillar-43 could not start")
                    .blocking_show();
                std::process::exit(1);
            }

            WebviewWindowBuilder::new(
                &handle,
                "main",
                WebviewUrl::External(
                    format!("http://127.0.0.1:{port}")
                        .parse()
                        .expect("loopback URL is well-formed"),
                ),
            )
            .title("Pillar-43")
            .inner_size(1440.0, 900.0)
            .min_inner_size(900.0, 600.0)
            // The window may only ever BE the origin we granted the picker to.
            //
            // capabilities/remote.json grants `dialog:allow-open` to
            // http://127.0.0.1:*, because that is the only way a page served
            // over loopback can open a native folder dialog. A `remote.urls`
            // grant attaches to whatever is loaded in the window, not to our
            // page — and with `withGlobalTauri: true` and `csp: null`, anything
            // that navigated this webview elsewhere on loopback would inherit
            // it. Pinning navigation to the exact port we just spawned is what
            // makes the wildcard in that file mean what its description claims.
            .on_navigation(move |url| {
                url.scheme() == "http"
                    && url.host_str() == Some("127.0.0.1")
                    && url.port() == Some(port)
            })
            .build()?;

            Ok(())
        })
        .on_window_event(|window, event| {
            if let tauri::WindowEvent::Destroyed = event {
                // Terminate rather than kill: SIGTERM lets the FastAPI lifespan
                // shutdown half run, which stops the scheduler and flushes any
                // batched git commits. SIGKILL would drop them.
                if let Some(state) = window.app_handle().try_state::<Backend>() {
                    if let Some(mut child) = state.0.lock().unwrap().take() {
                        unsafe { libc::kill(child.id() as i32, libc::SIGTERM) };
                        let deadline = Instant::now() + Duration::from_secs(5);
                        loop {
                            match child.try_wait() {
                                Ok(Some(_)) => break,
                                _ if Instant::now() > deadline => {
                                    let _ = child.kill();
                                    break;
                                }
                                _ => std::thread::sleep(Duration::from_millis(100)),
                            }
                        }
                    }
                }
            }
        })
        .build(tauri::generate_context!())
        .expect("error while building Pillar-43")
        .run(|app, event| {
            // Belt and braces with the window-destroyed handler above: Exit
            // fires on Cmd-Q and on a dock quit, which do not necessarily go
            // through window destruction. Neither covers a crash — that is
            // what the child's own parent-watch is for (backend_main.py).
            if let tauri::RunEvent::Exit = event {
                if let Some(state) = app.try_state::<Backend>() {
                    if let Some(mut child) = state.0.lock().unwrap().take() {
                        unsafe { libc::kill(child.id() as i32, libc::SIGTERM) };
                        let _ = child.wait();
                    }
                }
            }
        });
}
