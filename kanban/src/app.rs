use crate::model::Board;
use crate::ui::View;

pub enum Key {
    Left,
    Right,
    Up,
    Down,
    LaneUp,
    LaneDown,
    Retry,
    Skip,
    Quit,
    Other,
}

pub enum Command {
    Quit,
    Watcher(Vec<String>),
}

fn col_len(board: &Board, view: &View) -> usize {
    board.lanes.get(view.lane).map_or(0, |l| l.columns[view.column.min(5)].len())
}

pub fn clamp(board: &Board, view: &mut View) {
    view.column = view.column.min(5);
    view.lane = view.lane.min(board.lanes.len().saturating_sub(1));
    let len = col_len(board, view);
    view.row = view.row.min(len.saturating_sub(1));
}

pub fn handle(board: &Board, view: &mut View, key: Key, prd: &str) -> Option<Command> {
    match key {
        Key::Left => {
            view.column = view.column.saturating_sub(1);
            clamp(board, view);
        }
        Key::Right => {
            view.column = (view.column + 1).min(5);
            clamp(board, view);
        }
        Key::Up => view.row = view.row.saturating_sub(1),
        Key::Down => {
            view.row = (view.row + 1).min(col_len(board, view).saturating_sub(1));
        }
        Key::LaneUp => {
            view.lane = view.lane.saturating_sub(1);
            clamp(board, view);
        }
        Key::LaneDown => {
            view.lane += 1;
            clamp(board, view);
        }
        Key::Retry | Key::Skip => {
            let t = board.lanes.get(view.lane)?.columns[view.column.min(5)].get(view.row)?;
            let verb = if matches!(key, Key::Retry) { "retry" } else { "skip" };
            return Some(Command::Watcher(vec![verb.into(), t.key.clone(), "--prd".into(), prd.into()]));
        }
        Key::Quit => return Some(Command::Quit),
        Key::Other => {}
    }
    None
}
