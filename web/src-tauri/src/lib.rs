// 股票教室 · 桌面外壳
//
// 目标：像成熟商业软件那样启动与驻留。
//   · 启动闪屏  → 主窗口在内核就绪后淡入（不出现白屏等待）
//   · 系统托盘  → 常驻托盘图标，菜单「显示主界面 / 退出」，左键唤起
//   · 单实例    → 再次双击桌面图标只唤起已有窗口，不重复拉起后端
//   · 窗口记忆  → 位置/大小/最大化状态持久化
//   · 开机自启  → 可在设置里开关（写注册表 Run 项）
//   · 系统通知  → 长任务完成/失败时弹 Windows 通知（最小化到托盘也能看到）
//
// 说明：设置（关闭行为等）落盘在 app_config_dir/desktop.json，前端通过 command 读写。
use std::path::PathBuf;
use std::sync::atomic::{AtomicBool, Ordering};
use std::time::Duration;

use serde::{Deserialize, Serialize};
use tauri::{AppHandle, Manager, WebviewWindow};
use tauri_plugin_autostart::ManagerExt as _;

#[cfg(not(debug_assertions))]
use std::process::Command;

/// 桌面行为偏好（落盘）
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct DesktopPrefs {
    /// 点关闭按钮时最小化到托盘（而不是退出）
    pub close_to_tray: bool,
    /// 任务完成/失败时弹系统通知
    pub system_notify: bool,
    /// 数据目录（SC_DATA_DIR）。留空 = 使用后端 exe 同目录下的 data/
    #[serde(default)]
    pub data_dir: Option<String>,
}

impl Default for DesktopPrefs {
    fn default() -> Self {
        Self { close_to_tray: true, system_notify: true, data_dir: None }
    }
}

static QUITTING: AtomicBool = AtomicBool::new(false);

fn prefs_path(app: &AppHandle) -> Option<PathBuf> {
    let dir = app.path().app_config_dir().ok()?;
    let _ = std::fs::create_dir_all(&dir);
    Some(dir.join("desktop.json"))
}

fn load_prefs(app: &AppHandle) -> DesktopPrefs {
    prefs_path(app)
        .and_then(|p| std::fs::read_to_string(p).ok())
        .and_then(|s| serde_json::from_str(&s).ok())
        .unwrap_or_default()
}

fn save_prefs(app: &AppHandle, prefs: &DesktopPrefs) -> Result<(), String> {
    let p = prefs_path(app).ok_or("无法定位配置目录")?;
    let s = serde_json::to_string_pretty(prefs).map_err(|e| e.to_string())?;
    std::fs::write(p, s).map_err(|e| e.to_string())
}

/// 显示并聚焦主窗口（同时关掉闪屏）
fn reveal_main(app: &AppHandle) {
    if let Some(splash) = app.get_webview_window("splash") {
        let _ = splash.close();
    }
    if let Some(main) = app.get_webview_window("main") {
        let _ = main.show();
        let _ = main.unminimize();
        let _ = main.set_focus();
    }
}

// ───────────────────────────── commands ─────────────────────────────

/// 前端就绪（bootstrap 完成）后调用：关闪屏、显示主窗口。
#[tauri::command]
fn app_ready(app: AppHandle) {
    reveal_main(&app);
}

/// 读桌面偏好
#[tauri::command]
fn get_desktop_prefs(app: AppHandle) -> DesktopPrefs {
    load_prefs(&app)
}

/// 写桌面偏好
#[tauri::command]
fn set_desktop_prefs(app: AppHandle, prefs: DesktopPrefs) -> Result<DesktopPrefs, String> {
    save_prefs(&app, &prefs)?;
    Ok(prefs)
}

/// 开机自启状态
#[tauri::command]
fn get_autostart(app: AppHandle) -> bool {
    app.autolaunch().is_enabled().unwrap_or(false)
}

/// 开关开机自启
#[tauri::command]
fn set_autostart(app: AppHandle, enabled: bool) -> Result<bool, String> {
    let mgr = app.autolaunch();
    let r = if enabled { mgr.enable() } else { mgr.disable() };
    r.map_err(|e| e.to_string())?;
    Ok(mgr.is_enabled().unwrap_or(enabled))
}

/// 系统通知（Windows 通知中心）
#[tauri::command]
fn system_notify(app: AppHandle, title: String, body: String) {
    use tauri_plugin_notification::NotificationExt;
    let _ = app
        .notification()
        .builder()
        .title(title)
        .body(body)
        .show();
}

/// 最小化到托盘 / 从托盘恢复（供前端按钮调用）
#[tauri::command]
fn hide_to_tray(app: AppHandle) {
    if let Some(w) = app.get_webview_window("main") {
        let _ = w.hide();
    }
}

/// 当前窗口是否可见
#[tauri::command]
fn is_main_visible(app: AppHandle) -> bool {
    app.get_webview_window("main")
        .and_then(|w| w.is_visible().ok())
        .unwrap_or(false)
}

/// 退出应用（走正常退出路径，避免被关闭拦截）
#[tauri::command]
fn quit_app(app: AppHandle) {
    QUITTING.store(true, Ordering::SeqCst);
    app.exit(0);
}

// ───────────────────────────── 托盘 ─────────────────────────────

fn setup_tray(app: &AppHandle) -> tauri::Result<()> {
    use tauri::menu::{Menu, MenuItem, PredefinedMenuItem};
    use tauri::tray::{MouseButton, MouseButtonState, TrayIconEvent};

    let show = MenuItem::with_id(app, "show", "显示主界面", true, None::<&str>)?;
    let hide = MenuItem::with_id(app, "hide", "最小化到托盘", true, None::<&str>)?;
    let sep = PredefinedMenuItem::separator(app)?;
    let quit = MenuItem::with_id(app, "quit", "退出股票教室", true, None::<&str>)?;
    let menu = Menu::with_items(app, &[&show, &hide, &sep, &quit])?;

    let _tray = tauri::tray::TrayIconBuilder::with_id("main-tray")
        .tooltip("股票教室")
        .icon(app.default_window_icon().cloned().unwrap_or_else(|| {
            tauri::image::Image::new_owned(vec![0, 0, 0, 0], 1, 1)
        }))
        .menu(&menu)
        .show_menu_on_left_click(false)
        .on_menu_event(|app, event| match event.id().as_ref() {
            "show" => reveal_main(app),
            "hide" => {
                if let Some(w) = app.get_webview_window("main") {
                    let _ = w.hide();
                }
            }
            "quit" => {
                QUITTING.store(true, Ordering::SeqCst);
                app.exit(0);
            }
            _ => {}
        })
        .on_tray_icon_event(|tray, event| {
            if let TrayIconEvent::Click { button: MouseButton::Left, button_state: MouseButtonState::Up, .. } = event {
                let app = tray.app_handle();
                match app.get_webview_window("main") {
                    Some(w) if w.is_visible().unwrap_or(false) => {
                        let _ = w.hide();     // 已在前台 → 收起（像微信那样点图标切换）
                    }
                    _ => reveal_main(app),
                }
            }
        })
        .build(app)?;
    Ok(())
}

// ───────────────────────────── 启动 ─────────────────────────────

#[cfg_attr(mobile, tauri::mobile_entry_point)]
pub fn run() {
    let mut builder = tauri::Builder::default();

    // 单实例必须最先注册：第二次启动时回调里唤起已有窗口并退出新进程
    #[cfg(not(any(target_os = "android", target_os = "ios")))]
    {
        builder = builder.plugin(tauri_plugin_single_instance::init(|app, _argv, _cwd| {
            reveal_main(app);
        }));
    }

    builder
        // 只记忆位置/大小/最大化等，**不记忆可见性** —— 否则会跳过启动闪屏直接显示主窗口
        .plugin(
            tauri_plugin_window_state::Builder::default()
                .with_state_flags(
                    tauri_plugin_window_state::StateFlags::POSITION
                        | tauri_plugin_window_state::StateFlags::SIZE
                        | tauri_plugin_window_state::StateFlags::MAXIMIZED
                        | tauri_plugin_window_state::StateFlags::FULLSCREEN,
                )
                .build(),
        )
        .plugin(tauri_plugin_autostart::init(
            tauri_plugin_autostart::MacosLauncher::LaunchAgent,
            None,
        ))
        .plugin(tauri_plugin_notification::init())
        .invoke_handler(tauri::generate_handler![
            app_ready,
            get_desktop_prefs,
            set_desktop_prefs,
            get_autostart,
            set_autostart,
            system_notify,
            hide_to_tray,
            is_main_visible,
            quit_app
        ])
        .setup(|app| {
            #[cfg(not(debug_assertions))]
            spawn_backend(app);

            let handle = app.handle().clone();
            if let Err(e) = setup_tray(&handle) {
                eprintln!("[stock-classroom] 托盘初始化失败: {e}");
            }

            // 闪屏兜底：前端 25 秒内没报到就强开主窗口，避免卡在启动页
            let h2 = handle.clone();
            std::thread::spawn(move || {
                for _ in 0..50 {
                    std::thread::sleep(Duration::from_millis(500));
                    if QUITTING.load(Ordering::SeqCst) {
                        return;
                    }
                    let main_visible = h2
                        .get_webview_window("main")
                        .and_then(|w| w.is_visible().ok())
                        .unwrap_or(false);
                    if main_visible {
                        return;
                    }
                    let splash_alive = h2.get_webview_window("splash").is_some();
                    if !splash_alive {
                        return;
                    }
                }
                eprintln!("[stock-classroom] 前端未在 25s 内就绪，强制显示主窗口");
                reveal_main(&h2);
            });

            Ok(())
        })
        .on_window_event(|window, event| {
            if window.label() != "main" {
                return;
            }
            if let tauri::WindowEvent::CloseRequested { api, .. } = event {
                let app = window.app_handle();
                let prefs = load_prefs(app);
                if prefs.close_to_tray && !QUITTING.load(Ordering::SeqCst) {
                    // 像微信一样：关闭 = 收进托盘，后端与任务继续跑
                    api.prevent_close();
                    let _ = window.hide();
                } else {
                    QUITTING.store(true, Ordering::SeqCst);
                }
            }
        })
        .run(tauri::generate_context!())
        .expect("failed to run tauri application");
}

/// 启动打包的 Flask 后端子进程(stock-api.exe), 端口 5000。
/// 优先在资源目录(打包后), 其次 exe 同目录(便携方式)。返回的进程句柄随 App 存活。
/// 开发模式(debug build)不启动 —— 由 run_web.py / vite dev 手动管理。
#[cfg(not(debug_assertions))]
fn spawn_backend(app: &tauri::App) {
    use std::fs::OpenOptions;

    let mut sidecar = None;
    // 打包后资源目录；便携版则与主程序同目录
    if let Ok(dir) = app.path().resource_dir() {
        for cand in [dir.join("stock-api").join("stock-api.exe"), dir.join("stock-api.exe")] {
            if cand.exists() {
                sidecar = Some(cand);
                break;
            }
        }
    }
    if sidecar.is_none() {
        if let Ok(exe) = std::env::current_exe() {
            if let Some(dir) = exe.parent() {
                for cand in [dir.join("stock-api").join("stock-api.exe"), dir.join("stock-api.exe")] {
                    if cand.exists() {
                        sidecar = Some(cand);
                        break;
                    }
                }
            }
        }
    }
    let Some(sidecar_path) = sidecar else {
        eprintln!("[stock-classroom] 未找到 stock-api.exe, 后端需手动启动");
        return;
    };

    let dir = sidecar_path
        .parent()
        .unwrap_or_else(|| std::path::Path::new("."))
        .to_path_buf();

    // 端口探测：若 127.0.0.1:5000 已有后端在服务（异常退出残留的实例），直接复用，
    // 否则会出现"多个 stock-api 同时监听同一端口"（Werkzeug 默认允许），
    // 请求被随机分到旧实例，表现为改了后端却"没生效"。
    if std::net::TcpStream::connect_timeout(
        &"127.0.0.1:5000".parse().expect("addr"),
        std::time::Duration::from_millis(400),
    )
    .is_ok()
    {
        eprintln!("[stock-classroom] 检测到已有后端在 127.0.0.1:5000，复用该实例");
        return;
    }

    let prefs = load_prefs(&app.handle().clone());
    let mut cmd = Command::new(&sidecar_path);
    cmd.arg("--port").arg("5000").current_dir(&dir);
    // 数据目录：设置里指定优先，否则后端默认用 exe 同目录 data/
    if let Some(dd) = prefs.data_dir.as_deref().map(str::trim).filter(|s| !s.is_empty()) {
        eprintln!("[stock-classroom] 数据目录: {dd}");
        cmd.env("SC_DATA_DIR", dd);
    }
    // 后端日志落盘：app_log_dir/stock-api.log（出问题时可回看 Flask 访问日志与异常）
    if let Ok(log_dir) = app.path().app_log_dir() {
        let _ = std::fs::create_dir_all(&log_dir);
        let log_path = log_dir.join("stock-api.log");
        if let Ok(f) = OpenOptions::new().create(true).append(true).open(&log_path) {
            if let Ok(f2) = f.try_clone() {
                eprintln!("[stock-classroom] 后端日志: {}", log_path.display());
                cmd.stdout(std::process::Stdio::from(f));
                cmd.stderr(std::process::Stdio::from(f2));
            }
        }
    }

    match cmd.spawn() {
        Ok(_) => eprintln!("[stock-classroom] 后端已启动: {}", sidecar_path.display()),
        Err(e) => eprintln!("[stock-classroom] 无法启动后端: {e}"),
    }
}

/// 开发模式下的空实现（后端由 vite dev / run_web.py 管理）
#[cfg(debug_assertions)]
#[allow(dead_code)]
fn spawn_backend(_app: &tauri::App) {}

/// 供未来扩展：显式按标签取窗口
#[allow(dead_code)]
fn window_by_label(app: &AppHandle, label: &str) -> Option<WebviewWindow> {
    app.get_webview_window(label)
}
