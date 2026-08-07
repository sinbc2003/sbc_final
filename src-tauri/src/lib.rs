//! TeacherFlow Tauri 셸.
//!
//! 프로덕션에서 PyInstaller 엔진(onedir)을 리소스에서 찾아 자식 프로세스로
//! 기동하고, 앱 종료 시 반드시 죽인다(§28: 고아 llama-server 방지는 엔진의
//! shutdown 훅이, 고아 엔진 방지는 여기가 담당). 엔진 포트는
//! initialization_script로 window.__ENGINE_PORT__에 주입한다(src/apiBase.ts).

use std::process::{Child, Command};
use std::sync::Mutex;
use tauri::{Manager, RunEvent};

struct EngineProc(Mutex<Option<Child>>);

/// 8406이 비어 있으면 8406, 점유 중이면 OS가 주는 빈 포트.
fn pick_port() -> u16 {
    use std::net::TcpListener;
    match TcpListener::bind(("127.0.0.1", 8406u16)) {
        Ok(_) => 8406,
        Err(_) => TcpListener::bind(("127.0.0.1", 0u16))
            .and_then(|l| l.local_addr())
            .map(|a| a.port())
            .unwrap_or(8406),
    }
}

fn spawn_engine(app: &tauri::AppHandle, port: u16) {
    // dev에서는 uvicorn을 따로 띄운다(vite proxy 경유) — 프로덕션만 사이드카.
    if cfg!(debug_assertions) {
        return;
    }
    let res_dir = match app.path().resource_dir() {
        Ok(d) => d,
        Err(_) => {
            eprintln!("[TeacherFlow] resource_dir 해석 실패 — 엔진 미기동");
            return;
        }
    };
    let engine_exe = res_dir.join("engine").join("engine.exe");
    if !engine_exe.exists() {
        eprintln!("[TeacherFlow] 엔진 없음: {}", engine_exe.display());
        return;
    }
    let mut cmd = Command::new(&engine_exe);
    cmd.env("ENGINE_PORT", port.to_string())
        .env("TEACHERFLOW_HOME", &res_dir)
        .current_dir(&res_dir);
    #[cfg(windows)]
    {
        use std::os::windows::process::CommandExt;
        const CREATE_NO_WINDOW: u32 = 0x0800_0000;
        cmd.creation_flags(CREATE_NO_WINDOW);
    }
    match cmd.spawn() {
        Ok(child) => {
            *app.state::<EngineProc>().0.lock().unwrap() = Some(child);
        }
        Err(e) => eprintln!("[TeacherFlow] 엔진 기동 실패: {e}"),
    }
}

#[cfg_attr(mobile, tauri::mobile_entry_point)]
pub fn run() {
    let port = pick_port();

    let app = tauri::Builder::default()
        .manage(EngineProc(Mutex::new(None)))
        .setup(move |app| {
            spawn_engine(&app.handle().clone(), port);

            // 창은 코드에서 생성 — initialization_script(포트 주입)는
            // 정적 설정 창에는 붙일 수 없다.
            let win = tauri::WebviewWindowBuilder::new(
                app,
                "main",
                tauri::WebviewUrl::default(),
            )
            .title("TeacherFlow — 교사 업무 자동화")
            .inner_size(1400.0, 900.0)
            .min_inner_size(1000.0, 600.0)
            .center()
            .initialization_script(&format!("window.__ENGINE_PORT__={port};"))
            .build()?;

            #[cfg(debug_assertions)]
            win.open_devtools();
            #[cfg(not(debug_assertions))]
            let _ = win;

            Ok(())
        })
        .build(tauri::generate_context!())
        .expect("TeacherFlow 앱 빌드 실패");

    app.run(|app_handle, event| {
        if let RunEvent::Exit = event {
            if let Some(mut child) = app_handle
                .state::<EngineProc>()
                .0
                .lock()
                .unwrap()
                .take()
            {
                let _ = child.kill();
                let _ = child.wait();
            }
        }
    });
}
