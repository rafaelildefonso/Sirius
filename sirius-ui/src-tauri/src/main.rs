#![windows_subsystem = "windows"]

use std::path::PathBuf;
use std::sync::Mutex;
use std::process::{Child, Command, Stdio};
#[cfg(windows)] use std::os::windows::process::CommandExt;
use tauri::{
    Emitter, Manager,
    menu::{MenuBuilder, MenuItemBuilder},
    tray::{TrayIconBuilder, TrayIconEvent},
};
use winreg::enums::*;
use winreg::RegKey;

#[allow(dead_code)]
struct PythonProcess(Mutex<Option<Child>>);

// ── Windows Job Object — ensures backend dies when Tauri exits ─────────────
#[cfg(windows)]
mod job_object {
    use std::os::windows::io::AsRawHandle;

    const JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE: u32 = 0x00002000;

    #[repr(C)]
    struct BasicLimit {
        per_process_time: i64,
        per_job_time: i64,
        limit_flags: u32,
        min_ws: usize,
        max_ws: usize,
        active_process: u32,
        affinity: usize,
        child_rate: u32,
        extended_flags: u16,
    }

    #[repr(C)]
    struct ExtendedLimit {
        basic: BasicLimit,
        io_info: [u8; 24],
        process_memory: usize,
        job_memory: usize,
        peak_process: usize,
        peak_job: usize,
    }

    extern "system" {
        fn CreateJobObjectW(
            attr: *const std::ffi::c_void,
            name: *const u16,
        ) -> *mut std::ffi::c_void;
        fn AssignProcessToJobObject(
            job: *mut std::ffi::c_void,
            process: *mut std::ffi::c_void,
        ) -> i32;
        fn SetInformationJobObject(
            job: *mut std::ffi::c_void,
            info_class: u32,
            info: *const std::ffi::c_void,
            info_len: u32,
        ) -> i32;
    }

    pub fn attach(child: &std::process::Child) {
        unsafe {
            let job = CreateJobObjectW(std::ptr::null(), std::ptr::null());
            if job.is_null() {
                return;
            }
            let mut ext: ExtendedLimit = std::mem::zeroed();
            ext.basic.limit_flags = JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE;
            SetInformationJobObject(
                job,
                9, // JobObjectExtendedLimitInformation
                &ext as *const _ as *const std::ffi::c_void,
                std::mem::size_of::<ExtendedLimit>() as u32,
            );
            AssignProcessToJobObject(job, child.as_raw_handle() as *mut std::ffi::c_void);
        }
    }
}

fn log_msg(msg: &str) {
    eprintln!("{}", msg);
    if let Ok(exe) = std::env::current_exe() {
        if let Some(dir) = exe.parent() {
            if let Ok(mut f) = std::fs::OpenOptions::new()
                .create(true)
                .append(true)
                .open(dir.join("sirius.log"))
            {
                use std::io::Write;
                let _ = writeln!(f, "{}", msg);
            }
        }
    }
}

fn log_startup() {
    log_msg("[Tauri] Application starting");
}

fn find_sidecar(app: &tauri::AppHandle) -> Option<PathBuf> {
    let candidates = [
        // Production: installed alongside the main exe
        std::env::current_exe().ok().map(|p| p.parent().unwrap().to_path_buf()),
        // Tauri resource dir (production bundle)
        app.path().resource_dir().ok().map(|d| d.join("binaries")),
        // exe dir + binaries (legacy layout)
        std::env::current_exe().ok().map(|p| p.parent().unwrap().join("binaries")),
        // current working directory + binaries (dev mode)
        std::env::current_dir().ok().map(|d| d.join("binaries")),
    ];
    for dir in candidates.into_iter().flatten() {
        if !dir.is_dir() { continue; }
        log_msg(&format!("[Tauri] Searching for sidecar in: {}", dir.display()));
        if let Ok(entries) = std::fs::read_dir(&dir) {
            for entry in entries.flatten() {
                let name = entry.file_name().to_string_lossy().to_string();
                if (name.starts_with("sirius-backend-") || name == "sirius-backend.exe")
                    && name.ends_with(".exe")
                {
                    let path = entry.path();
                    if path.metadata().ok()?.len() > 1024 {
                        log_msg(&format!("[Tauri] Found sidecar: {}", path.display()));
                        return Some(path);
                    }
                }
            }
        }
    }
    None
}

fn spawn_and_forward(cmd: &mut Command) -> Option<Child> {
    let mut child = cmd.spawn().ok()?;
    let pid = child.id();
    let stdout = child.stdout.take();
    let stderr = child.stderr.take();
    std::thread::spawn(move || {
        use std::io::Read;
        if let Some(mut r) = stdout {
            let mut buf = [0u8; 4096];
            while let Ok(n) = r.read(&mut buf) {
                if n == 0 { break; }
                log_msg(&format!("[Python] {}", String::from_utf8_lossy(&buf[..n]).trim_end()));
            }
        }
    });
    std::thread::spawn(move || {
        use std::io::Read;
        if let Some(mut r) = stderr {
            let mut buf = [0u8; 4096];
            while let Ok(n) = r.read(&mut buf) {
                if n == 0 { break; }
                log_msg(&format!("[Python:err] {}", String::from_utf8_lossy(&buf[..n]).trim_end()));
            }
        }
    });
    log_msg(&format!("[Tauri] Backend started (PID: {})", pid));
    Some(child)
}

fn start_python_backend(app: &tauri::AppHandle) -> Option<Child> {
    // 1. Try sidecar binary (production / after build_backend.py)
    if let Some(sidecar_path) = find_sidecar(app) {
        log_msg(&format!("[Tauri] Starting sidecar: {}", sidecar_path.display()));
        let mut cmd = Command::new(&sidecar_path);
        cmd.env("SIRIUS_WS_UI", "1")
            .stdout(Stdio::piped())
            .stderr(Stdio::piped());
        #[cfg(windows)]
        cmd.creation_flags(0x08000000);
        if let Some(child) = spawn_and_forward(&mut cmd) {
            return Some(child);
        }
    }

    // 2. Fallback: python sirius_backend_launcher.py (dev only — no sidecar compiled)
    #[cfg(debug_assertions)]
    {
        let cwd = std::env::current_dir().ok()?;
        let launcher = cwd.join("sirius_backend_launcher.py");
        if launcher.exists() {
            log_msg(&format!("[Tauri] Starting python directly: {}", launcher.display()));
            let mut cmd = Command::new("python");
            cmd.arg(&launcher)
                .current_dir(&cwd)
                .env("SIRIUS_WS_UI", "1")
                .stdout(Stdio::piped())
                .stderr(Stdio::piped());
            #[cfg(windows)]
            cmd.creation_flags(0x08000000);
            if let Some(child) = spawn_and_forward(&mut cmd) {
                return Some(child);
            }
        }
    }

    log_msg("[Tauri] No backend found.");
    None
}

fn kill_process_on_port(port: u16) {
    log_msg(&format!("[Tauri] Killing any process holding port {}...", port));
    let script = format!(
        "Get-NetTCPConnection -LocalPort {} -ErrorAction SilentlyContinue | Select-Object -ExpandProperty OwningProcess -First 1 | ForEach-Object {{ taskkill /F /PID $_ }}",
        port
    );
    let mut cmd = Command::new("powershell");
    cmd.args(["-NoProfile", "-Command", &script])
        .stdout(Stdio::null())
        .stderr(Stdio::null());
    #[cfg(windows)]
    cmd.creation_flags(0x08000000); // CREATE_NO_WINDOW
    let _ = cmd.output();
    std::thread::sleep(std::time::Duration::from_millis(300));
    log_msg(&format!("[Tauri] Port {} released.", port));
}

fn toggle_window(app: &tauri::AppHandle) {
    if let Some(window) = app.get_webview_window("main") {
        if window.is_visible().unwrap_or(false) {
            let _ = window.hide();
            let _ = app.emit("window-hidden", ());
        } else {
            let _ = window.show();
            let _ = window.set_focus();
            let _ = app.emit("window-shown", ());
        }
    }
}

fn focus_window(app: &tauri::AppHandle) {
    if let Some(window) = app.get_webview_window("main") {
        let _ = window.show();
        let _ = window.set_focus();
        let _ = window.unminimize();
        let _ = app.emit("window-shown", ());
    }
}

fn create_tray(app: &tauri::App) -> Result<(), Box<dyn std::error::Error>> {
    let show_hide = MenuItemBuilder::with_id("toggle", "Mostrar / Ocultar")
        .build(app)?;
    let mute_item = MenuItemBuilder::with_id("mute", "Mutar")
        .build(app)?;
    let quit = MenuItemBuilder::with_id("quit", "Sair")
        .build(app)?;
    let menu = MenuBuilder::new(app)
        .item(&show_hide)
        .separator()
        .item(&mute_item)
        .separator()
        .item(&quit)
        .build()?;

    TrayIconBuilder::with_id("sirius-tray")
        .icon(app.default_window_icon().unwrap().clone())
        .tooltip("SIRIUS — AI Assistant")
        .menu(&menu)
        .on_menu_event(|app, event| {
            match event.id().as_ref() {
                "toggle" => toggle_window(app),
                "mute" => {
                    let _ = app.emit("toggle-mute", ());
                }
                "quit" => {
                    // ------------------------------------------------
                    // 8️⃣ Quit selected – log and kill backend explicitly
                    // ------------------------------------------------
                    log_msg("[Tauri] Quit menu selected – terminating backend.");
                    let state = app.state::<PythonProcess>();
                    if let Ok(mut guard) = state.0.lock() {
                        if let Some(mut child) = guard.take() {
                            let pid = child.id();
                            let _ = child.kill();
                            let _ = child.wait();
                            log_msg(&format!("[Tauri] Backend process (PID: {}) terminated via kill().", pid));
                            // Fallback: ensure full tree termination
                            let _ = std::process::Command::new("taskkill")
                                .args(&["/F", "/T", "/PID", &pid.to_string()])
                                .output();
                        }
                    }
                    // Release the WS port in case the backend held it
                    kill_process_on_port(8765);
                    std::process::exit(0);
                }
                _ => {}
            }
        })
        .on_tray_icon_event(|tray, event| {
            if let TrayIconEvent::DoubleClick { .. } = event {
                toggle_window(tray.app_handle());
            }
        })
        .build(app)?;

    Ok(())
}

    #[tauri::command]
    fn exit_app(app: tauri::AppHandle) {
        // ------------------------------------------------
        // 9️⃣ Explicit exit command (called from UI) – same logic as quit menu
        // ------------------------------------------------
        log_msg("[Tauri] exit_app called — terminating backend...");
        let state = app.state::<PythonProcess>();
        if let Ok(mut guard) = state.0.lock() {
            if let Some(mut child) = guard.take() {
                let pid = child.id();
                let _ = child.kill();
                let _ = child.wait();
                log_msg(&format!("[Tauri] Backend process (PID: {}) terminated via exit_app.", pid));
                let _ = std::process::Command::new("taskkill")
                    .args(&["/F", "/T", "/PID", &pid.to_string()])
                    .output();
            }
        }
        kill_process_on_port(8765);
        std::process::exit(0);
    }

#[tauri::command]
fn update_tray_tooltip(app: tauri::AppHandle, text: String) {
    if let Some(tray) = app.tray_by_id("sirius-tray") {
        let _ = tray.set_tooltip(Some(text));
    }
}

const AUTOSTART_KEY: &str = r"Software\Microsoft\Windows\CurrentVersion\Run";
const AUTOSTART_FLAG: &str = "--autostart";

fn is_autostart_launch() -> bool {
    std::env::args().any(|a| a == AUTOSTART_FLAG)
}

fn get_autostart_key(for_write: bool) -> Result<RegKey, String> {
    let hkcu = RegKey::predef(HKEY_CURRENT_USER);
    let flags = if for_write { KEY_SET_VALUE } else { KEY_READ };
    hkcu.open_subkey_with_flags(AUTOSTART_KEY, flags)
        .map_err(|e| format!("Failed to open registry: {}", e))
}

#[tauri::command]
fn set_autostart(enabled: bool) -> Result<(), String> {
    let key = get_autostart_key(true)?;
    if enabled {
        let exe = std::env::current_exe().map_err(|e| format!("Failed to get exe path: {}", e))?;
        let value = format!("\"{}\" {}", exe.to_string_lossy(), AUTOSTART_FLAG);
        key.set_value("SIRIUS", &value)
            .map_err(|e| format!("Failed to set registry: {}", e))?;
    } else {
        let _ = key.delete_value("SIRIUS");
    }
    Ok(())
}

#[tauri::command]
fn is_autostart_enabled() -> Result<bool, String> {
    match get_autostart_key(false) {
        Ok(key) => Ok(key.get_value::<String, _>("SIRIUS").is_ok()),
        Err(_) => Ok(false),
    }
}

#[cfg(windows)]
fn set_app_user_model_id() {
    extern "system" {
        fn SetCurrentProcessExplicitAppUserModelID(app_id: *const u16) -> i32;
    }
    let wide: Vec<u16> = "com.rafaelildefonso.sirius\0".encode_utf16().collect();
    unsafe {
        SetCurrentProcessExplicitAppUserModelID(wide.as_ptr());
    }
}

fn main() {
    #[cfg(windows)]
    set_app_user_model_id();

    tauri::Builder::default()
        .plugin(tauri_plugin_shell::init())
        .plugin(tauri_plugin_single_instance::init(|app, _args, _cwd| {
            focus_window(app);
        }))
        .invoke_handler(tauri::generate_handler![exit_app, update_tray_tooltip, set_autostart, is_autostart_enabled])
        .setup(|app| {
            // ------------------------------------------------
            // 1️⃣ Log start of the Tauri process
            // ------------------------------------------------
            log_startup();

            // ------------------------------------------------
            // 2️⃣ Kill any stray process on the WS port (8765)
            // ------------------------------------------------
            kill_process_on_port(8765);
            let child = start_python_backend(app.handle());

            // ------------------------------------------------
            // 3️⃣ Attach to Windows Job Object (ensures backend dies with UI)
            // ------------------------------------------------
            #[cfg(windows)]
            if let Some(ref c) = child {
                job_object::attach(c);
                log_msg("[Tauri] Backend attached to Job Object (KILL_ON_JOB_CLOSE).");
            }

            // ------------------------------------------------
            // 4️⃣ Store the child in shared state for later cleanup
            // ------------------------------------------------
            app.manage(PythonProcess(Mutex::new(child)));

            // ------------------------------------------------
            // 5️⃣ UI window config (autostart flag handling)
            // ------------------------------------------------
            if let Some(window) = app.get_webview_window("main") {
                let _ = window.set_title("SIRIUS");
                if is_autostart_launch() {
                    log_msg("[Tauri] Autostart launch — starting minimized to tray.");
                    let _ = window.hide();
                    let _ = window.emit("window-hidden", ());
                }
            }

            // ------------------------------------------------
            // 6️⃣ Tray creation (log success / failure)
            // ------------------------------------------------
            if app.tray_by_id("sirius-tray").is_none() {
                if let Err(e) = create_tray(app) {
                    log_msg(&format!("[Tauri] Failed to create tray: {}", e));
                }
            }

            // ------------------------------------------------
            // 7️⃣ Immediate tooltip update (loading state)
            // ------------------------------------------------
            if let Some(tray) = app.tray_by_id("sirius-tray") {
                let _ = tray.set_tooltip(Some("SIRIUS — Iniciando..."));
            }

            Ok(())
        })
        .on_window_event(|window, event| {
            if let tauri::WindowEvent::CloseRequested { api, .. } = event {
                // ------------------------------------------------
                // 10️⃣ Quando o usuário fecha a janela (X) – manter em tray
                // ------------------------------------------------
                api.prevent_close();
                let _ = window.hide();
                let _ = window.emit("window-hidden", ());
                log_msg("[Tauri] Window close requested – hiding to tray.");
            }
        })
        .run(tauri::generate_context!())
        .expect("error while running SIRIUS");
}
