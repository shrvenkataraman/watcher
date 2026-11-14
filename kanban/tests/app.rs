use kanban::app::{clamp, handle, Command, Key};
use kanban::model::{Board, Lane, Ticket};
use kanban::ui::View;
use proptest::prelude::*;

fn t(key: &str, status: &str) -> Ticket {
    Ticket { key: key.into(), status: status.into(), sha: String::new() }
}

fn lane(repo: &str, cols: [Vec<Ticket>; 6]) -> Lane {
    Lane { repo: repo.into(), pr_status: String::new(), columns: cols }
}

/// Lane 0: Pending 3 cards, Working 1 card, rest empty. Lane 1: Pending 1 card, rest empty.
fn board() -> Board {
    let l0 = lane(
        "R",
        [
            vec![t("R/01", "pending"), t("R/02", "pending"), t("R/03", "pending")],
            vec![t("R/04", "running")],
            vec![],
            vec![],
            vec![],
            vec![],
        ],
    );
    let l1 = lane("S", [vec![t("S/01", "pending")], vec![], vec![], vec![], vec![], vec![]]);
    Board { prd: "p".into(), phase: String::new(), model: String::new(), needs_you: 0, lanes: vec![l0, l1] }
}

fn v(lane: usize, column: usize, row: usize) -> View {
    View { lane, column, row }
}

fn pos(view: &View) -> (usize, usize, usize) {
    (view.lane, view.column, view.row)
}

fn args(c: Option<Command>) -> Option<Vec<String>> {
    match c {
        Some(Command::Watcher(a)) => Some(a),
        _ => None,
    }
}

fn s(a: &[&str]) -> Vec<String> {
    a.iter().map(|x| x.to_string()).collect()
}

#[test]
fn ac1_moves_and_clamps_at_edges() {
    // AC1
    let b = board();
    let mut w = v(0, 0, 0);
    handle(&b, &mut w, Key::Up, "p");
    assert_eq!(pos(&w), (0, 0, 0), "up clamps at row 0");
    handle(&b, &mut w, Key::Left, "p");
    assert_eq!(pos(&w), (0, 0, 0), "left clamps at column 0");
    handle(&b, &mut w, Key::LaneUp, "p");
    assert_eq!(pos(&w), (0, 0, 0), "lane up clamps at 0");
    handle(&b, &mut w, Key::Down, "p");
    handle(&b, &mut w, Key::Down, "p");
    assert_eq!(pos(&w), (0, 0, 2));
    handle(&b, &mut w, Key::Down, "p");
    assert_eq!(pos(&w), (0, 0, 2), "down clamps at last card");
    handle(&b, &mut w, Key::Up, "p");
    assert_eq!(pos(&w), (0, 0, 1));
    // Right into the shorter Working column resets row to 0.
    let mut w = v(0, 0, 2);
    handle(&b, &mut w, Key::Right, "p");
    assert_eq!(pos(&w), (0, 1, 0), "row resets when new column is shorter");
    // Right keeps the row when the new column is long enough.
    let mut w = v(0, 0, 0);
    handle(&b, &mut w, Key::Right, "p");
    assert_eq!(pos(&w), (0, 1, 0));
    for _ in 0..10 {
        handle(&b, &mut w, Key::Right, "p");
    }
    assert_eq!(w.column, 5, "right clamps at column 5");
    handle(&b, &mut w, Key::Down, "p");
    assert_eq!(pos(&w), (0, 5, 0), "down on empty column stays at 0");
    handle(&b, &mut w, Key::Left, "p");
    assert_eq!(pos(&w), (0, 4, 0));
    // Lanes.
    let mut w = v(0, 0, 0);
    handle(&b, &mut w, Key::LaneDown, "p");
    assert_eq!(w.lane, 1);
    handle(&b, &mut w, Key::LaneDown, "p");
    assert_eq!(w.lane, 1, "lane down clamps at last lane");
    handle(&b, &mut w, Key::LaneUp, "p");
    assert_eq!(w.lane, 0);
    // Lane change into a shorter column keeps the selection valid.
    let mut w = v(0, 0, 2);
    handle(&b, &mut w, Key::LaneDown, "p");
    assert_eq!(w.lane, 1);
    assert_eq!(w.row, 0, "row is valid in the shorter lane");
    // Other does nothing and returns None.
    let mut w = v(0, 1, 0);
    assert!(handle(&b, &mut w, Key::Other, "p").is_none());
    assert_eq!(pos(&w), (0, 1, 0));
}

#[test]
fn ac1_quit_returns_quit() {
    // AC1
    let b = board();
    let mut w = v(0, 0, 0);
    assert!(matches!(handle(&b, &mut w, Key::Quit, "p"), Some(Command::Quit)));
}

#[test]
fn ac2_retry_and_skip_commands() {
    // AC2
    let b = board();
    let mut w = v(0, 0, 1);
    assert_eq!(args(handle(&b, &mut w, Key::Retry, "p")), Some(s(&["retry", "R/02", "--prd", "p"])));
    assert_eq!(args(handle(&b, &mut w, Key::Skip, "p")), Some(s(&["skip", "R/02", "--prd", "p"])));
    let mut w = v(1, 0, 0);
    assert_eq!(args(handle(&b, &mut w, Key::Retry, "q")), Some(s(&["retry", "S/01", "--prd", "q"])));
}

#[test]
fn ac2_empty_column_gives_none() {
    // AC2
    let b = board();
    let mut w = v(0, 3, 0);
    assert!(handle(&b, &mut w, Key::Retry, "p").is_none());
    assert!(handle(&b, &mut w, Key::Skip, "p").is_none());
}

#[test]
fn ac3_clamp_after_shorter_column() {
    // AC3
    let b = board();
    let mut w = v(0, 1, 5);
    clamp(&b, &mut w);
    assert_eq!(pos(&w), (0, 1, 0), "Working has 1 card: last index is 0");
    let mut w = v(0, 0, 9);
    clamp(&b, &mut w);
    assert_eq!(pos(&w), (0, 0, 2), "Pending has 3 cards: last index is 2");
    let mut w = v(0, 3, 4);
    clamp(&b, &mut w);
    assert_eq!(pos(&w), (0, 3, 0), "empty column gives row 0");
    let mut w = v(0, 0, 1);
    clamp(&b, &mut w);
    assert_eq!(pos(&w), (0, 0, 1), "valid selection is unchanged");
}

#[test]
fn ac3_clamp_fixes_lane_and_column() {
    // AC3
    let b = board();
    let mut w = v(7, 9, 3);
    clamp(&b, &mut w);
    assert_eq!(w.lane, 1);
    assert_eq!(w.column, 5);
    assert_eq!(w.row, 0);
    let empty = Board { prd: "p".into(), phase: String::new(), model: String::new(), needs_you: 0, lanes: vec![] };
    let mut w = v(3, 2, 4);
    clamp(&empty, &mut w);
    assert_eq!(pos(&w), (0, 2, 0), "no lanes: lane 0, row 0");
}

#[test]
fn ac4_binary_is_built() {
    // AC4: cargo defines this variable only when the watcher-kanban bin target exists.
    let path = env!("CARGO_BIN_EXE_watcher-kanban");
    assert!(std::path::Path::new(path).exists(), "binary missing at {path}");
}

fn key_of(i: u8) -> Key {
    match i % 10 {
        0 => Key::Left,
        1 => Key::Right,
        2 => Key::Up,
        3 => Key::Down,
        4 => Key::LaneUp,
        5 => Key::LaneDown,
        6 => Key::Retry,
        7 => Key::Skip,
        8 => Key::Quit,
        _ => Key::Other,
    }
}

proptest! {
    #[test]
    fn ac1_selection_always_valid(keys in proptest::collection::vec(0u8..10, 0..200)) {
        // AC1
        let b = board();
        let mut w = v(0, 0, 0);
        for k in keys {
            handle(&b, &mut w, key_of(k), "p");
            prop_assert!(w.column < 6);
            prop_assert!(w.lane < b.lanes.len());
            let len = b.lanes[w.lane].columns[w.column].len();
            prop_assert!(w.row == 0 || w.row < len);
        }
    }
}
