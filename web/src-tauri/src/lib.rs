#[cfg(target_os = "windows")]
use tauri::Manager;

#[cfg_attr(mobile, tauri::mobile_entry_point)]
pub fn run() {
    tauri::Builder::default()
        .setup(|app| {
            #[cfg(not(debug_assertions))]
            spawn_backend(app);
            Ok(())
        })
        .run(tauri::generate_context!())
        .expect("failed to run tauri application");
}

/// 启动打包的 Flask 后端子进程(stock-api.exe), 端口 5000。
/// 优先在资源目录(打包后), 其次 exe 同目录(便携方式)。返回的进程句柄随 App 存活。
/// 开发模式(debug build)不启动 —— 由 run_web.py / vite dev 手动管理。
#[cfg(not(debug_assertions))]
fn spawn_backend(app: &tauri::App) {
    use std::process::Command;
    let mut sidecar = None;
    if let Ok(dir) = app.path().resource_dir() {
        let p = dir.join("stock-api.exe");
        if p.exists() {
            sidecar = Some(p);
        }
    }
    if sidecar.is_none() {
        if let Ok(exe) = std::env::current_exe() {
            if let Some(dir) = exe.parent() {
                let p = dir.join("stock-api.exe");
                if p.exists() {
                    sidecar = Some(p);
                }
            }
        }
    }
    if let Some(sidecar_path) = sidecar {
        let dir = sidecar_path.parent().unwrap_or_else(|| std::path::Path::new(".")).to_path_buf();
        match Command::new(&sidecar_path)
            .arg("--port")
            .arg("5000")
            .current_dir(&dir)
            .spawn()
        {
            Ok(_) => eprintln!("[stock-classroom] 后端已启动: {}", sidecar_path.display()),
            Err(e) => eprintln!("[stock-classroom] 无法启动后端: {e}"),
        }
    } else {
        eprintln!("[stock-classroom] 未找到 stock-api.exe, 后端需手动启动");
    }
}

#[cfg(debug_assertions)]
fn spawn_backend(_app: &tauri::App) {}
