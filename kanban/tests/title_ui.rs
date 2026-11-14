use kanban::model::{Board, Lane, Ticket};
use kanban::ui::{draw, View};
use ratatui::{backend::TestBackend, Terminal};

fn screen(title: &str, sha: &str) -> String {
    let t = Ticket { key: "r/03".into(), status: "pending".into(), sha: sha.into(), title: title.into() };
    let mut columns: [Vec<Ticket>; 6] = Default::default();
    columns[0] = vec![t];
    let board = Board { prd: "p".into(), phase: String::new(), model: String::new(), needs_you: 0,
        lanes: vec![Lane { repo: "r/p".into(), pr_status: "none".into(), columns }] };
    let mut term = Terminal::new(TestBackend::new(300, 20)).unwrap();
    term.draw(|f| draw(f, &board, &View { lane: 0, column: 0, row: 0 }, "")).unwrap();
    let buf = term.backend().buffer().clone();
    (0..buf.area.height)
        .map(|y| (0..buf.area.width).map(|x| buf[(x, y)].symbol().to_string()).collect::<String>())
        .collect::<Vec<_>>()
        .join("\n")
}

// AC1
#[test]
fn ac1_card_shows_number_and_title() {
    assert!(screen("prds-command", "").contains("03 prds-command"));
}

// AC2
#[test]
fn ac2_card_without_title_shows_number_only() {
    let s = screen("", "");
    let bytes = s.as_bytes();
    let i = s.find("03").expect("card number");
    assert!(bytes.get(i + 2).map_or(true, |c| *c == b' '), "{s}");
    assert!(bytes.get(i + 3).map_or(true, |c| *c == b' '), "{s}");
}

// AC3
#[test]
fn ac3_card_with_title_and_sha() {
    assert!(screen("prds-command", "abcdef123").contains("03 prds-command abcdef1"));
}

// AC1
#[test]
fn ac1_property_any_short_title_is_shown() {
    for t in ["a", "ab-cd", "title_with_underscores", "x y z"] {
        assert!(screen(t, "").contains(&format!("03 {t}")), "{t}");
    }
}
