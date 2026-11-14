use kanban::model::{merge, Board, Lane, Ticket};
use proptest::prelude::*;

fn t(key: &str) -> Ticket {
    Ticket { key: key.into(), status: "pending".into(), sha: String::new() }
}

fn lane(repo: &str, tickets: Vec<Ticket>) -> Lane {
    let mut columns: [Vec<Ticket>; 6] = Default::default();
    columns[0] = tickets;
    Lane { repo: repo.into(), pr_status: "open".into(), columns }
}

fn board(prd: &str, phase: &str, needs: usize, lanes: Vec<Lane>) -> Board {
    Board { prd: prd.into(), phase: phase.into(), model: String::new(), needs_you: needs, lanes }
}

#[test]
fn ac1_lane_repos_and_prds() {
    let a = board("p1", "", 0, vec![lane("r1", vec![])]);
    let b = board("p2", "", 0, vec![lane("r2", vec![]), lane("r3", vec![])]);
    let (m, prds) = merge(vec![a, b]);
    let repos: Vec<_> = m.lanes.iter().map(|l| l.repo.as_str()).collect();
    assert_eq!(repos, ["p1/r1", "p2/r2", "p2/r3"]);
    assert_eq!(prds, ["p1", "p2", "p2"]);
    assert_eq!(m.prd, "all");
}

#[test]
fn ac2_needs_you_sums() {
    let (m, _) = merge(vec![board("a", "", 2, vec![]), board("b", "", 3, vec![])]);
    assert_eq!(m.needs_you, 5);
}

#[test]
fn ac3_phase_joined_sorted_distinct() {
    let (m, _) = merge(vec![board("a", "review", 0, vec![]), board("b", "flash", 0, vec![])]);
    assert_eq!(m.phase, "flash,review");
    let (m, _) = merge(vec![board("a", "pr", 0, vec![]), board("b", "pr", 0, vec![])]);
    assert_eq!(m.phase, "pr");
}

#[test]
fn ac4_empty_input() {
    let (m, prds) = merge(vec![]);
    assert_eq!((m.prd.as_str(), m.lanes.len(), prds.len()), ("all", 0, 0));
}

#[test]
fn ac5_columns_preserved() {
    let src = lane("r", vec![t("r/01"), t("r/02")]);
    let want = src.columns.clone();
    let (m, _) = merge(vec![board("p", "", 0, vec![src])]);
    assert_eq!(m.lanes[0].columns, want);
    assert_eq!(m.lanes[0].pr_status, "open");
}

proptest! {
    #[test]
    fn ac1_property_lengths_match(counts in proptest::collection::vec(0usize..4, 0..5)) {
        let boards: Vec<Board> = counts.iter().enumerate().map(|(i, n)| {
            board(&format!("p{i}"), "", 0, (0..*n).map(|j| lane(&format!("r{j}"), vec![])).collect())
        }).collect();
        let total: usize = counts.iter().sum();
        let (m, prds) = merge(boards);
        prop_assert_eq!(m.lanes.len(), total);
        prop_assert_eq!(prds.len(), total);
    }
}
