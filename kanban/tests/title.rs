use kanban::model::{merge, parse, Board, Lane};
use proptest::prelude::*;

fn json_with(title: Option<&str>) -> String {
    let mut t = serde_json::json!({"key": "r/03", "status": "pending", "sha": ""});
    if let Some(x) = title {
        t["title"] = serde_json::json!(x);
    }
    serde_json::json!({"schema": 1, "prd": "p", "phase": "", "model": "", "needs_you": [],
        "lanes": [{"repo": "r", "pr_status": "none", "tickets": [t]}]}).to_string()
}

fn title_of(json: &str) -> String {
    parse(json).unwrap().lanes[0].columns[0][0].title.clone()
}

// AC1
#[test]
fn ac1_title_is_parsed() {
    assert_eq!(title_of(&json_with(Some("prds-command"))), "prds-command");
}

// AC2
#[test]
fn ac2_missing_title_is_empty() {
    assert_eq!(title_of(&json_with(None)), "");
}

// AC3
#[test]
fn ac3_merged_lane_is_repo_slash_project() {
    let lane = |r: &str| Lane { repo: r.into(), pr_status: String::new(), columns: Default::default() };
    let b = |p: &str, r: &str| Board { prd: p.into(), phase: String::new(), model: String::new(), needs_you: 0, lanes: vec![lane(r)] };
    let (m, _) = merge(vec![b("p1", "r1"), b("p2", "r2")]);
    let repos: Vec<_> = m.lanes.iter().map(|l| l.repo.as_str()).collect();
    assert_eq!(repos, ["r1/p1", "r2/p2"]);
}

proptest! {
    // AC1
    #[test]
    fn ac1_property_title_round_trip(t in "[a-z0-9 _-]{0,20}") {
        prop_assert_eq!(title_of(&json_with(Some(&t))), t);
    }
}
