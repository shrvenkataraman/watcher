use kanban::app::{clamp, handle, Command, Key};
use kanban::fetch::{self, Target};
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

fn fetch_all(bin: &str, root: &Option<String>) -> Result<(Board, Vec<String>, String), String> {
    let mut c = Proc::new(bin);
    c.args(["prds"]);
    if let Some(r) = root {
        c.args(["--state-root", r]);
    }
    let out = c.output().map_err(|e| format!("{bin}: {e}"))?;
    if !out.status.success() {
        return Err(String::from_utf8_lossy(&out.stderr).trim().to_string());
    }
    let prds = fetch::parse_prds(&String::from_utf8_lossy(&out.stdout))?;

    let mut boards = Vec::new();
    let mut note = String::new();
    for prd in &prds {
        match fetch(bin, prd, root) {
            Ok(b) => boards.push(b),
            Err(e) => {
                if !note.is_empty() {
                    note.push_str("; ");
                }
                note.push_str(&format!("prd {prd}: {e}"));
            }
        }
    }
    let (board, lane_prds) = model::merge(boards);
    Ok((board, lane_prds, note))
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
    let target = match fetch::parse_target(&a) {
        Ok(t) => t,
        Err(m) => {
            eprintln!("{m}");
            std::process::exit(2);
        }
    };
    let root = opt(&a, "--state-root");
    let bin = opt(&a, "--watcher").unwrap_or_else(|| "watcher".into());

    let prd = match &target {
        Target::One(p) => p.clone(),
        Target::All => String::new(),
    };

    let mut term = ratatui::init(); // installs a panic hook that restores the terminal
    let mut board = Board { prd: prd.clone(), phase: String::new(), model: String::new(), needs_you: 0, lanes: vec![] };
    let mut view = View { lane: 0, column: 0, row: 0 };
    let mut note = String::new();
    let mut lane_prds: Vec<String> = vec![];
    let mut last = Instant::now() - Duration::from_secs(10);
    loop {
        if last.elapsed() >= Duration::from_secs(2) {
            match &target {
                Target::One(p) => match fetch(&bin, p, &root) {
                    Ok(b) => {
                        board = b;
                        note.clear();
                    }
                    Err(e) => note = e,
                },
                Target::All => match fetch_all(&bin, &root) {
                    Ok((b, p, n)) => {
                        board = b;
                        lane_prds = p;
                        note = n;
                    }
                    Err(e) => note = e,
                },
            }
            last = Instant::now();
        }
        clamp(&board, &mut view);
        let _ = term.draw(|f| draw(f, &board, &view, &note));
        if event::poll(Duration::from_millis(200)).unwrap_or(false) {
            if let Ok(Event::Key(k)) = event::read() {
                if k.kind == KeyEventKind::Press {
                    let key_prd = match &target {
                        Target::One(p) => p.clone(),
                        Target::All => {
                            if lane_prds.is_empty() {
                                String::new()
                            } else {
                                lane_prds[view.lane.min(lane_prds.len().saturating_sub(1))].clone()
                            }
                        }
                    };
                    match handle(&board, &mut view, map(k.code), &key_prd) {
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
