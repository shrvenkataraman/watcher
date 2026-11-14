use kanban::fetch::{parse_prds, parse_target, Target};
use proptest::prelude::*;

fn args(a: &[&str]) -> Vec<String> {
    a.iter().map(|s| s.to_string()).collect()
}

const USAGE: &str = "usage: watcher-kanban (--prd P | --all) [--state-root S] [--watcher BIN]";

// AC1

#[test]
fn ac1_prd() {
    assert_eq!(parse_target(&args(&["--prd", "p"])), Ok(Target::One("p".into())));
}

// AC2

#[test]
fn ac2_all() {
    assert_eq!(parse_target(&args(&["--all"])), Ok(Target::All));
}

// AC3

#[test]
fn ac3_both() {
    assert_eq!(parse_target(&args(&["--prd", "p", "--all"])), Err("use --prd or --all, not both".into()));
}

// AC4

#[test]
fn ac4_neither() {
    assert_eq!(parse_target(&args(&[])), Err(USAGE.into()));
}

// AC5

#[test]
fn ac5_prd_without_value() {
    assert_eq!(parse_target(&args(&["--prd"])), Err(USAGE.into()));
}

// AC6

#[test]
fn ac6_parse_prds() {
    assert_eq!(parse_prds(r#"{"schema":1,"prds":["a","b"]}"#), Ok(vec!["a".into(), "b".into()]));
    assert_eq!(parse_prds(r#"{"schema":2,"prds":[]}"#), Err("unsupported schema 2".into()));
    assert!(parse_prds("nope").unwrap_err().starts_with("invalid json:"));
}

proptest! {
    // AC6
    #[test]
    fn ac6_property_round_trip(names in proptest::collection::vec("[a-z0-9-]{1,8}", 0..6)) {
        let json = serde_json::json!({"schema": 1, "prds": names}).to_string();
        prop_assert_eq!(parse_prds(&json), Ok(names));
    }
}
