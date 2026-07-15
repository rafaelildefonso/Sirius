#![cfg_attr(not(debug_assertions), windows_subsystem = "windows")]

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

    // 2. Fallback: python sirius_backend_launcher.py (dev without build)
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

    log_msg("[Tauri] No backend found! Tried sidecar and python.");
    None
}

fn kill_process_on_port(port: u16) {
    log_msg(&format!("[Tauri] Killing any process holding port {}...", port));
    let script = format!(
        "Get-NetTCPConnection -LocalPort {} -ErrorAction SilentlyContinue | Select-Object -ExpandProperty OwningProcess -First 1 | ForEach-Object {{ taskkill /F /PID $_ }}",
        port
    );
    let _ = Command::new("powershell")
        .args(["-NoProfile", "-Command", &script])
        .output();
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
fn exit_app() {
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

fn main() {
    tauri::Builder::default()
        .plugin(tauri_plugin_shell::init())
        .plugin(tauri_plugin_single_instance::init(|app, _args, _cwd| {
            focus_window(app);
        }))
        .invoke_handler(tauri::generate_handler![exit_app, update_tray_tooltip, set_autostart, is_autostart_enabled])
        .setup(|app| {
            // Kill any process holding port 8765 (ghost from previous crash)
            kill_process_on_port(8765);
            let child = start_python_backend(app.handle());
            app.manage(PythonProcess(Mutex::new(child)));

            if let Some(window) = app.get_webview_window("main") {
                let _ = window.set_title("SIRIUS");
                // If launched via autostart (--autostart flag), start minimized to tray
                if is_autostart_launch() {
                    log_msg("[Tauri] Autostart launch — starting minimized to tray.");
                    let _ = window.hide();
                    let _ = window.emit("window-hidden", ());
                }
            }

            if app.tray_by_id("sirius-tray").is_none() {
                if let Err(e) = create_tray(app) {
                    log_msg(&format!("[Tauri] Failed to create tray: {}", e));
                }
            }

            // Update tray tooltip immediately to show loading state
            if let Some(tray) = app.tray_by_id("sirius-tray") {
                let _ = tray.set_tooltip(Some("SIRIUS — Iniciando..."));
            }

            Ok(())
        })
        .on_window_event(|window, event| {
            if let tauri::WindowEvent::CloseRequested { api, .. } = event {
                api.prevent_close();
                let _ = window.hide();
                let _ = window.emit("window-hidden", ());
            }
        })
        .run(tauri::generate_context!())
        .expect("error while running SIRIUS");
}
