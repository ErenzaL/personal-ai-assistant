//! Starts and supervises the local FastAPI backend.
//!
//! The backend is a separate process so the API key and the model calls
//! never live in the desktop app. In the packaged app it is a single
//! executable (`dully-backend`, built with PyInstaller) shipped next to this
//! binary; in development it is the repository's `backend/` run from its
//! virtualenv. At launch this looks for a backend already answering as Dully
//! (a developer's `--reload` server) and otherwise starts one on the first
//! free port from 8000, bound to 127.0.0.1 only, restarts it a few times if
//! it crashes, and stops it again when the app quits. The child also watches
//! this process and shuts itself down if it vanishes, so a crash or force
//! quit cannot leave it running. Nothing here ever stops a backend it did not
//! start.

use std::fs::{self, File};
use std::io::{Read, Write};
use std::net::{SocketAddr, TcpListener, TcpStream};
use std::path::{Path, PathBuf};
use std::process::{Child, Command, Stdio};
use std::sync::atomic::{AtomicU16, Ordering};
use std::sync::{Arc, Mutex, MutexGuard};
use std::thread;
use std::time::{Duration, Instant};

use tauri::{AppHandle, Manager};

const DEFAULT_PORT: u16 = 8000;
/// How many ports above the requested one to try when it is taken.
const PORT_SEARCH: u16 = 20;
/// How long a fresh backend may take to answer `/health` (the packaged one
/// unpacks itself first).
const READY_TIMEOUT: Duration = Duration::from_secs(45);
const START_ATTEMPTS: u32 = 3;
/// How often the supervisor checks whether the child is still alive. A
/// `try_wait` is a single syscall, so this costs nothing noticeable.
const WATCH_INTERVAL: Duration = Duration::from_secs(2);
/// Name of the packaged backend next to the app's own executable.
const SIDECAR: &str = "dully-backend";
/// How often an adopted (external) backend is checked, and how many checks
/// in a row must fail before we start our own: a developer's `--reload`
/// server is briefly down while it restarts, which must not count.
const EXTERNAL_CHECK: Duration = Duration::from_secs(10);
const EXTERNAL_MISSES: u32 = 3;

/// Tauri-managed handle to the backend and the port it answers on.
pub struct Backend {
    child: Arc<Mutex<Option<Child>>>,
    port: Arc<AtomicU16>,
}

enum Launch {
    /// The packaged executable inside the app bundle.
    Sidecar(PathBuf),
    /// The repository's backend, run from its virtualenv.
    Source { python: PathBuf, dir: PathBuf },
}

impl Backend {
    pub fn start(app: AppHandle) -> Self {
        let (port, external) = choose_port(requested_port());
        let child = Arc::new(Mutex::new(None));
        let current = Arc::new(AtomicU16::new(port));
        let slot = Arc::clone(&child);
        let shared_port = Arc::clone(&current);
        thread::Builder::new()
            .name("backend".into())
            .spawn(move || run(app, slot, shared_port, port, external))
            .expect("failed to start the backend supervisor");
        Self { child, port: current }
    }

    pub fn port(&self) -> u16 {
        self.port.load(Ordering::Relaxed)
    }

    /// Stop the backend this app started. Asks nicely first, then insists.
    pub fn stop(&self) {
        let Some(mut child) = self.lock().take() else {
            return;
        };
        let pid = child.id();
        let _ = Command::new("kill").args(["-TERM", &pid.to_string()]).status();
        let deadline = Instant::now() + Duration::from_secs(3);
        while Instant::now() < deadline {
            if matches!(child.try_wait(), Ok(Some(_))) {
                eprintln!("backend: stopped (pid {pid})");
                return;
            }
            thread::sleep(Duration::from_millis(100));
        }
        let _ = child.kill();
        let _ = child.wait();
        eprintln!("backend: killed (pid {pid})");
    }

    fn lock(&self) -> MutexGuard<'_, Option<Child>> {
        self.child.lock().unwrap_or_else(|poisoned| poisoned.into_inner())
    }
}

/// Where the backend answers. The webview asks once at startup, so a move to
/// another port (8000 taken by something else) is invisible to the user.
#[tauri::command]
pub fn backend_url(backend: tauri::State<'_, Backend>) -> String {
    format!("http://127.0.0.1:{}", backend.port())
}

/// The port to use, and whether a backend of ours is already answering on it.
fn choose_port(requested: u16) -> (u16, bool) {
    if healthy(requested) {
        return (requested, true);
    }
    if port_free(requested) {
        return (requested, false);
    }
    for candidate in requested + 1..=requested.saturating_add(PORT_SEARCH) {
        if port_free(candidate) {
            eprintln!("backend: port {requested} is taken by another program; using {candidate}");
            return (candidate, false);
        }
    }
    eprintln!("backend: no free port near {requested}; trying it anyway");
    (requested, false)
}

/// Use an already-running backend while it lasts, then run our own. An
/// adopted backend that goes away (the developer closed the terminal it ran
/// in) hands over to ours on the same port if it is free by then.
fn run(app: AppHandle, slot: Arc<Mutex<Option<Child>>>, current: Arc<AtomicU16>, port: u16, external: bool) {
    let (mut port, mut external) = (port, external);
    loop {
        current.store(port, Ordering::Relaxed);
        if !external {
            supervise(app, slot, port);
            return;
        }
        eprintln!("backend: already running on 127.0.0.1:{port}; using it");
        let mut misses = 0;
        while misses < EXTERNAL_MISSES {
            thread::sleep(EXTERNAL_CHECK);
            misses = if healthy(port) { 0 } else { misses + 1 };
        }
        eprintln!("backend: the backend on 127.0.0.1:{port} stopped answering; starting our own");
        (port, external) = choose_port(requested_port());
    }
}

fn supervise(app: AppHandle, slot: Arc<Mutex<Option<Child>>>, port: u16) {
    let Some(plan) = launch_plan(&app) else {
        eprintln!(
            "backend: nothing to start. The packaged app ships it; in development set \
             DULLY_BACKEND_DIR or write the backend folder's path into backend-path.txt \
             in the app data folder."
        );
        return;
    };
    match &plan {
        Launch::Sidecar(path) => eprintln!("backend: starting packaged {}", path.display()),
        Launch::Source { dir, .. } => eprintln!("backend: starting from source in {}", dir.display()),
    }
    let data_dir = app.path().app_data_dir().ok();
    if let Some(dir) = &data_dir {
        let _ = fs::create_dir_all(dir);
    }
    let log_path = data_dir.as_ref().map(|d| d.join("backend.log"));

    for attempt in 1..=START_ATTEMPTS {
        let child = match spawn(&plan, port, data_dir.as_deref(), log_path.as_deref()) {
            Ok(child) => child,
            Err(err) => {
                eprintln!("backend: could not start: {err}");
                return;
            }
        };
        let pid = child.id();
        *slot.lock().unwrap_or_else(|p| p.into_inner()) = Some(child);
        if wait_ready(port) {
            eprintln!("backend: ready on 127.0.0.1:{port} (pid {pid})");
        } else {
            eprintln!("backend: no answer after {}s; see backend.log", READY_TIMEOUT.as_secs());
        }

        // Watch it cheaply. A crash gets a restart; our own stop() ends this.
        loop {
            thread::sleep(WATCH_INTERVAL);
            let mut guard = slot.lock().unwrap_or_else(|p| p.into_inner());
            match guard.as_mut() {
                None => return,
                Some(child) => match child.try_wait() {
                    Ok(Some(status)) => {
                        eprintln!("backend: exited ({status})");
                        *guard = None;
                        break;
                    }
                    Ok(None) => {}
                    Err(err) => {
                        eprintln!("backend: lost track of it: {err}");
                        *guard = None;
                        break;
                    }
                },
            }
        }
        if attempt == START_ATTEMPTS {
            eprintln!("backend: giving up after {attempt} attempts; see backend.log");
            return;
        }
        thread::sleep(Duration::from_secs(3));
    }
}

/// The packaged sidecar next to this executable, else the development source.
fn launch_plan(app: &AppHandle) -> Option<Launch> {
    if let Ok(exe) = std::env::current_exe() {
        if let Some(dir) = exe.parent() {
            let sidecar = dir.join(SIDECAR);
            if sidecar.is_file() {
                return Some(Launch::Sidecar(sidecar));
            }
        }
    }
    let dir = locate_source(app)?;
    let python = dir.join(".venv").join("bin").join("python");
    if !python.is_file() {
        eprintln!("backend: {} has no .venv; follow backend/README.md", dir.display());
        return None;
    }
    Some(Launch::Source { python, dir })
}

fn spawn(plan: &Launch, port: u16, data_dir: Option<&Path>, log: Option<&Path>) -> std::io::Result<Child> {
    let port_text = port.to_string();
    // Our own pid: the backend exits when this process is gone, whatever the
    // reason. (Its immediate parent is not us in the packaged build.)
    let parent = std::process::id().to_string();
    let mut command = match plan {
        Launch::Sidecar(path) => {
            let mut command = Command::new(path);
            command.args(["--port", &port_text, "--quiet", "--parent-pid", &parent]);
            if let Some(dir) = data_dir {
                command.current_dir(dir);
            }
            command
        }
        Launch::Source { python, dir } => {
            let mut command = Command::new(python);
            command
                .arg("run_backend.py")
                .args(["--port", &port_text, "--parent-pid", &parent])
                .current_dir(dir);
            command
        }
    };
    command.stdin(Stdio::null());
    // One log per launch, overwritten each time, so it cannot grow forever.
    let file = log.and_then(|path| File::create(path).ok());
    match file {
        Some(file) => {
            let errors = file.try_clone()?;
            command.stdout(Stdio::from(file)).stderr(Stdio::from(errors));
        }
        None => {
            command.stdout(Stdio::null()).stderr(Stdio::null());
        }
    }
    command.spawn()
}

/// Development only: an explicit env var, a note in the app data folder, or
/// the repository the binary sits in.
fn locate_source(app: &AppHandle) -> Option<PathBuf> {
    if let Ok(dir) = std::env::var("DULLY_BACKEND_DIR") {
        if let Some(found) = valid_source(PathBuf::from(dir.trim())) {
            return Some(found);
        }
    }
    if let Ok(data) = app.path().app_data_dir() {
        if let Ok(text) = fs::read_to_string(data.join("backend-path.txt")) {
            if let Some(found) = valid_source(PathBuf::from(text.trim())) {
                return Some(found);
            }
        }
    }
    if let Ok(exe) = std::env::current_exe() {
        for ancestor in exe.ancestors().take(10) {
            if let Some(found) = valid_source(ancestor.join("backend")) {
                return Some(found);
            }
        }
    }
    None
}

fn valid_source(dir: PathBuf) -> Option<PathBuf> {
    dir.join("run_backend.py").is_file().then_some(dir)
}

fn requested_port() -> u16 {
    std::env::var("DULLY_BACKEND_PORT")
        .ok()
        .and_then(|v| v.trim().parse().ok())
        .filter(|p: &u16| *p >= 1024)
        .unwrap_or(DEFAULT_PORT)
}

fn port_free(port: u16) -> bool {
    TcpListener::bind(SocketAddr::from(([127, 0, 0, 1], port))).is_ok()
}

/// One plain GET /health over a fresh connection; true only when Dully's own
/// backend answers, so a stranger on the port is never mistaken for it.
fn healthy(port: u16) -> bool {
    let addr = SocketAddr::from(([127, 0, 0, 1], port));
    let Ok(mut stream) = TcpStream::connect_timeout(&addr, Duration::from_millis(500)) else {
        return false;
    };
    let _ = stream.set_read_timeout(Some(Duration::from_secs(2)));
    if stream
        .write_all(b"GET /health HTTP/1.1\r\nHost: 127.0.0.1\r\nConnection: close\r\n\r\n")
        .is_err()
    {
        return false;
    }
    let mut body = Vec::new();
    let _ = stream.read_to_end(&mut body);
    let text = String::from_utf8_lossy(&body);
    (text.starts_with("HTTP/1.1 200") || text.starts_with("HTTP/1.0 200")) && text.contains("\"dully\"")
}

fn wait_ready(port: u16) -> bool {
    let deadline = Instant::now() + READY_TIMEOUT;
    while Instant::now() < deadline {
        if healthy(port) {
            return true;
        }
        thread::sleep(Duration::from_millis(500));
    }
    false
}
