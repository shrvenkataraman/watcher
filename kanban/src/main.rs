use kanban::app::{clamp, handle, Command, Key};
use kanban::model::{self, Board};
use kanban::ui::{draw, View};
use ratatui::crossterm::event::{self, Event, KeyCode, KeyEventKind};
use std::process::Command as Proc;
use std::time::{Duration, Instant};

fn opt(a: &[String], name: &str) -> Option<String> {
    a.iter().position(|x| x == name).and_then(|i| a.get(i + 1)).cloned()
}

fn fetch(bin: &str, prd: &str, root: &Option<String>) -> Result<Board, String> {
    let mut c = Proc::new(bin);
    c.args(["status", "--json", "--prd", prd]);
    if let Some(r) = root {
        c.args(["--state-root", r]);
    }
    let out = c.output().map_err(|e| format!("{bin}: {e}"))?;
    if !out.status.success() {
        return Err(String::from_utf8_lossy(&out.stderr).trim().to_string());
    }
    model::parse(&String::from_utf8_lossy(&out.stdout))
}

fn map(code: KeyCode) -> Key {
    match code {
        KeyCode::Left | KeyCode::Char('h') => Key::Left,
        KeyCode::Right | KeyCode::Char('l') => Key::Right,
        KeyCode::Up | KeyCode::Char('k') => Key::Up,
        KeyCode::Down | KeyCode::Char('j') => Key::Down,
        KeyCode::Char('J') => Key::LaneDown,
        KeyCode::Char('K') => Key::LaneUp,
        KeyCode::Char('r') => Key::Retry,
        KeyCode::Char('s') => Key::Skip,
        KeyCode::Char('q') => Key::Quit,
        _ => Key::Other,
    }
}

fn main() {
    let a: Vec<String> = std::env::args().skip(1).collect();
    let Some(prd) = opt(&a, "--prd") else {
        eprintln!("usage: watcher-kanban --prd P [--state-root S] [--watcher BIN]");
        std::process::exit(2);
    };
    let root = opt(&a, "--state-root");
    let bin = opt(&a, "--watcher").unwrap_or_else(|| "watcher".into());

    let mut term = ratatui::init(); // installs a panic hook that restores the terminal
    let mut board = Board { prd: prd.clone(), phase: String::new(), model: String::new(), needs_you: 0, lanes: vec![] };
    let mut view = View { lane: 0, column: 0, row: 0 };
    let mut note = String::new();
    let mut last = Instant::now() - Duration::from_secs(10);
    loop {
        if last.elapsed() >= Duration::from_secs(2) {
            match fetch(&bin, &prd, &root) {
                Ok(b) => {
                    board = b;
                    note.clear();
                }
                Err(e) => note = e,
            }
            last = Instant::now();
        }
        clamp(&board, &mut view);
        let _ = term.draw(|f| draw(f, &board, &view, &note));
        if event::poll(Duration::from_millis(200)).unwrap_or(false) {
            if let Ok(Event::Key(k)) = event::read() {
                if k.kind == KeyEventKind::Press {
                    match handle(&board, &mut view, map(k.code), &prd) {
                        Some(Command::Quit) => break,
                        Some(Command::Watcher(args)) => {
                            let mut c = Proc::new(&bin);
                            c.args(&args);
                            if let Some(r) = &root {
                                c.args(["--state-root", r]);
                            }
                            note = match c.output() {
                                Ok(o) if o.status.success() => String::new(),
                                Ok(o) => String::from_utf8_lossy(&o.stderr).trim().to_string(),
                                Err(e) => format!("{bin}: {e}"),
                            };
                        }
                        None => {}
                    }
                    last = Instant::now() - Duration::from_secs(10);
                }
            }
        }
    }
    ratatui::restore();
}
