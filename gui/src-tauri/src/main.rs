#![cfg_attr(
  all(not(debug_assertions), target_os = "windows"),
  windows_subsystem = "windows"
)]

use once_cell::sync::Lazy;
use serde::Serialize;
use std::io::{BufRead, BufReader};
use std::process::{Child, Command, Stdio};
use std::sync::Mutex;
use tauri::{AppHandle, Manager};

static PYTHON_PROCESS: Lazy<Mutex<Option<Child>>> = Lazy::new(|| Mutex::new(None));

#[derive(Serialize, Clone)]
struct LogPayload {
    message: String,
}

#[derive(Serialize)]
struct Metrics {
    total_evaluated: i64,
    total_followed: i64,
    total_starred: i64,
    purge_queue_size: i64,
}

fn get_project_root() -> std::path::PathBuf {
    // Traverse up parent directories from the current working directory to find main.py
    let mut path = std::env::current_dir().unwrap_or_else(|_| std::path::PathBuf::from("."));
    for _ in 0..5 {
        if path.join("main.py").exists() {
            return path;
        }
        if let Some(parent) = path.parent() {
            path = parent.to_path_buf();
        } else {
            break;
        }
    }
    // Fallback to relative parent path
    std::path::PathBuf::from("..")
}

fn get_db_path() -> std::path::PathBuf {
    get_project_root().join("data").join("followme.sqlite")
}

#[tauri::command]
fn start_bot(app_handle: AppHandle) -> Result<String, String> {
    let mut process_guard = PYTHON_PROCESS.lock().unwrap();
    if process_guard.is_some() {
        return Err("Bot is already running".into());
    }

    let project_root = get_project_root();
    
    // Explicitly set the CWD (current working directory) of the Python process
    // so it resolves .env and database locations relative to the workspace root.
    let mut child = Command::new("python")
        .current_dir(&project_root)
        .arg("main.py")
        .arg("-i") // Infinite loop
        .stdout(Stdio::piped())
        .stderr(Stdio::piped())
        .spawn()
        .map_err(|e| format!("Failed to spawn Python bot process: {}", e))?;

    let stdout = child.stdout.take().ok_or("Failed to open stdout")?;
    let stderr = child.stderr.take().ok_or("Failed to open stderr")?;

    *process_guard = Some(child);

    // Thread for stdout
    let app_handle_clone1 = app_handle.clone();
    std::thread::spawn(move || {
        let reader = BufReader::new(stdout);
        for line in reader.lines() {
            if let Ok(l) = line {
                let _ = app_handle_clone1.emit_all("bot-log", LogPayload { message: l });
            }
        }
    });

    // Thread for stderr
    let app_handle_clone2 = app_handle.clone();
    std::thread::spawn(move || {
        let reader = BufReader::new(stderr);
        for line in reader.lines() {
            if let Ok(l) = line {
                let _ = app_handle_clone2.emit_all("bot-log", LogPayload { message: format!("[ERROR] {}", l) });
            }
        }
    });

    Ok("Bot started successfully".into())
}

#[tauri::command]
fn stop_bot() -> Result<String, String> {
    let mut process_guard = PYTHON_PROCESS.lock().unwrap();
    if let Some(mut child) = process_guard.take() {
        let _ = child.kill();
        let _ = child.wait();
        Ok("Bot stopped successfully".into())
    } else {
        Err("Bot is not running".into())
    }
}

#[tauri::command]
fn get_metrics() -> Result<Metrics, String> {
    let db_path = get_db_path();
    let conn = rusqlite::Connection::open(&db_path)
        .map_err(|e| format!("Failed to open database at {:?}: {}", db_path, e))?;

    let total_evaluated: i64 = conn
        .query_row(
            "SELECT COUNT(*) FROM entries WHERE idea IS NOT NULL",
            [],
            |row| row.get(0),
        )
        .unwrap_or(0);

    let total_followed: i64 = conn
        .query_row(
            "SELECT COUNT(DISTINCT profile) FROM entries WHERE followed = 1",
            [],
            |row| row.get(0),
        )
        .unwrap_or(0);

    let total_starred: i64 = conn
        .query_row(
            "SELECT COUNT(*) FROM entries WHERE starred = 1",
            [],
            |row| row.get(0),
        )
        .unwrap_or(0);

    let purge_queue_size: i64 = conn
        .query_row(
            "SELECT COUNT(*) FROM inbound_followers WHERE unfollowed = 1",
            [],
            |row| row.get(0),
        )
        .unwrap_or(0);

    Ok(Metrics {
        total_evaluated,
        total_followed,
        total_starred,
        purge_queue_size,
    })
}

#[tauri::command]
fn read_env() -> Result<String, String> {
    let path = get_project_root().join(".env");
    std::fs::read_to_string(&path)
        .map_err(|e| format!("Failed to read .env file: {}", e))
}

#[tauri::command]
fn save_env(content: String) -> Result<String, String> {
    let path = get_project_root().join(".env");
    std::fs::write(&path, content)
        .map_err(|e| format!("Failed to write .env file: {}", e))?;
    Ok("Saved .env successfully".into())
}

#[tauri::command]
fn read_whitelist() -> Result<String, String> {
    let path = get_project_root().join("whitelist.txt");
    if !path.exists() {
        return Ok("".into());
    }
    std::fs::read_to_string(&path)
        .map_err(|e| format!("Failed to read whitelist.txt: {}", e))
}

#[tauri::command]
fn save_whitelist(content: String) -> Result<String, String> {
    let path = get_project_root().join("whitelist.txt");
    std::fs::write(&path, content)
        .map_err(|e| format!("Failed to write whitelist.txt: {}", e))?;
    Ok("Saved whitelist.txt successfully".into())
}

fn main() {
  tauri::Builder::default()
    .invoke_handler(tauri::generate_handler![
      start_bot,
      stop_bot,
      get_metrics,
      read_env,
      save_env,
      read_whitelist,
      save_whitelist
    ])
    .on_window_event(|event| {
        if let tauri::WindowEvent::Destroyed = event.event() {
            let mut process_guard = PYTHON_PROCESS.lock().unwrap();
            if let Some(mut child) = process_guard.take() {
                let _ = child.kill();
            }
        }
    })
    .run(tauri::generate_context!())
    .expect("error while running tauri application");
}
