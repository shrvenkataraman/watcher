use kanban::model::{parse, Board, Column, Lane, Ticket};
use kanban::ui::{draw, View};
use ratatui::{backend::TestBackend, buffer::Buffer, style::Modifier, Terminal};

const FIXTURE: &str = include_str!("fixtures/status.json");
const HELP: &str = "h/l column  j/k card  J/K lane  r retry  s skip  q quit";
// Oracle: column titles from the ticket text, independent of the code under test.
const TITLES: [&str; 6] = ["Pending", "Working", "In review", "Changes", "Done", "Needs you"];

fn render(board: &Board, view: &View, note: &str) -> Buffer {
    let mut term = Terminal::new(TestBackend::new(120, 30)).unwrap();
    term.draw(|f| draw(f, board, view, note)).unwrap();
    term.backend().buffer().clone()
}

fn line(buf: &Buffer, y: u16) -> String {
    (0..buf.area.width).map(|x| buf[(x, y)].symbol().to_string()).collect()
}

fn lines(buf: &Buffer) -> Vec<String> {
    (0..buf.area.height).map(|y| line(buf, y)).collect()
}

/// (x, y) of the first cell of `needle` on a row (cells are one char wide in ASCII).
fn find(buf: &Buffer, needle: &str) -> Option<(u16, u16)> {
    for (y, l) in lines(buf).iter().enumerate() {
        if let Some(i) = l.find(needle) {
            return Some((l[..i].chars().count() as u16, y as u16));
        }
    }
    None
}

fn ticket(key: &str, status: &str, sha: &str) -> Ticket {
    Ticket { key: key.into(), status: status.into(), sha: sha.into() }
}

fn board_of(prd: &str, tickets: &[Ticket]) -> Board {
    let mut columns: [Vec<Ticket>; 6] = Default::default();
    for t in tickets {
        let i = Column::ALL.iter().position(|c| *c == Column::of(&t.status)).unwrap();
        columns[i].push(t.clone());
    }
    Board {
        prd: prd.into(),
        phase: "build".into(),
        model: "m1".into(),
        needs_you: 0,
        lanes: vec![Lane { repo: "repo1".into(), pr_status: "open".into(), columns }],
    }
}

fn view0() -> View {
    View { lane: 0, column: 0, row: 0 }
}

#[test]
fn ac1_header_line_for_fixture() {
    // AC1
    let board = parse(FIXTURE).unwrap();
    let buf = render(&board, &view0(), "");
    assert!(line(&buf, 0).starts_with("prd-demo  phase=review  model=qwen3.8-27b-w8a8  needs you=1"));
}

#[test]
fn ac2_column_titles_with_counts() {
    // AC2: fixture counts by hand: alpha 1/1/1/0/1/0, beta 0/0/1/1/1/1 (fixed->In review, skipped->Done)
    let board = parse(FIXTURE).unwrap();
    let all = lines(&render(&board, &view0(), "")).join("\n");
    for t in ["Pending (1)", "Working (1)", "In review (1)", "Changes (0)", "Done (1)", "Needs you (0)",
              "Pending (0)", "Working (0)", "In review (1)", "Changes (1)", "Done (1)", "Needs you (1)"] {
        assert!(all.contains(t), "missing title {t}");
    }
    assert!(all.contains("alpha  pr=none"));
    assert!(all.contains("beta  pr=open"));
}

#[test]
fn ac2_property_title_counts_sum_to_ticket_count() {
    // AC2 property: deterministic sweep over many generated boards (no proptest dependency available).
    let statuses = ["pending", "running", "implemented", "fixed", "changes", "approved", "skipped", "needs_you"];
    let mut seed: u32 = 12345;
    for _ in 0..40 {
        let mut ts = vec![];
        seed = seed.wrapping_mul(1664525).wrapping_add(1013904223);
        let n = (seed >> 24) as usize % 13;
        for i in 0..n {
            seed = seed.wrapping_mul(1664525).wrapping_add(1013904223);
            ts.push(ticket(&format!("p/{i:02}"), statuses[(seed >> 24) as usize % 8], ""));
        }
        let buf = render(&board_of("p", &ts), &view0(), "");
        let first_title_row = lines(&buf).into_iter().find(|l| l.contains("Pending (")).unwrap();
        let mut sum = 0usize;
        for t in TITLES {
            let pat = format!("{t} (");
            let i = first_title_row.find(&pat).unwrap_or_else(|| panic!("no title {t}"));
            let rest = &first_title_row[i + pat.len()..];
            sum += rest[..rest.find(')').unwrap()].parse::<usize>().unwrap();
        }
        assert_eq!(sum, n);
    }
}

#[test]
fn ac3_card_inside_done_column_area() {
    // AC3
    let b = board_of("p", &[ticket("p/01", "approved", "abc1234def"), ticket("p/02", "pending", "")]);
    let buf = render(&b, &view0(), "");
    let (tx, ty) = find(&buf, "Done (1)").expect("done title");
    let (cx, cy) = find(&buf, "01 abc1234").expect("card text");
    assert!(cy > ty, "card below title");
    assert!(cx >= tx.saturating_sub(1) && cx < tx + 20, "card x {cx} outside Done column at {tx}");
    assert!(!line(&buf, cy).contains("abc1234d"), "sha must be cut to 7 chars");
    // card without sha shows only the key part
    assert!(find(&buf, "02").is_some());
}

#[test]
fn ac4_selected_card_reversed_others_not() {
    // AC4
    let b = board_of("p", &[ticket("p/01", "pending", "1111111"), ticket("p/02", "pending", "2222222")]);
    let buf = render(&b, &View { lane: 0, column: 0, row: 1 }, "");
    let (x1, y1) = find(&buf, "01 1111111").unwrap();
    let (x2, y2) = find(&buf, "02 2222222").unwrap();
    for i in 0..10 {
        assert!(buf[(x2 + i, y2)].modifier.contains(Modifier::REVERSED), "selected cell {i}");
        assert!(!buf[(x1 + i, y1)].modifier.contains(Modifier::REVERSED), "other cell {i}");
    }
    // moving the selection moves the reversal
    let buf = render(&b, &view0(), "");
    assert!(buf[(x1, y1)].modifier.contains(Modifier::REVERSED));
    assert!(!buf[(x2, y2)].modifier.contains(Modifier::REVERSED));
}

#[test]
fn ac5_empty_note_shows_help() {
    // AC5
    let board = parse(FIXTURE).unwrap();
    let buf = render(&board, &view0(), "");
    assert!(line(&buf, 29).trim_end().starts_with(HELP));
}

#[test]
fn ac5_note_replaces_help() {
    // AC5 (non-empty branch)
    let board = parse(FIXTURE).unwrap();
    let buf = render(&board, &view0(), "retry queued");
    let last = line(&buf, 29);
    assert!(last.trim_end().starts_with("retry queued"));
    assert!(!last.contains("h/l column"));
}
