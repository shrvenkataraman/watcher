use kanban::model::{parse, Board, Column};

const FIXTURE: &str = include_str!("fixtures/status.json");

// Mapping table (ticket 21), Python status -> column. Independent of the code under test.
const TABLE: [(&str, Column); 8] = [
    ("pending", Column::Pending),
    ("running", Column::Working),
    ("implemented", Column::Review),
    ("fixed", Column::Review),
    ("changes", Column::Changes),
    ("approved", Column::Done),
    ("skipped", Column::Done),
    ("needs_you", Column::NeedsYou),
];

fn expected(status: &str) -> Column {
    TABLE.iter().find(|(s, _)| *s == status).map(|(_, c)| *c).unwrap_or(Column::NeedsYou)
}

fn idx(c: Column) -> usize {
    Column::ALL.iter().position(|x| *x == c).unwrap()
}

fn board() -> Board {
    parse(FIXTURE).expect("fixture parses")
}

#[test]
fn ac1_every_ticket_in_expected_column() {
    // AC1
    let raw: serde_json::Value = serde_json::from_str(FIXTURE).unwrap();
    let b = board();
    let lanes = raw["lanes"].as_array().unwrap();
    assert_eq!(b.lanes.len(), lanes.len());
    for (lane, jl) in b.lanes.iter().zip(lanes) {
        assert_eq!(lane.repo, jl["repo"].as_str().unwrap());
        assert_eq!(lane.pr_status, jl["pr_status"].as_str().unwrap());
        let tickets = jl["tickets"].as_array().unwrap();
        for (ci, col) in lane.columns.iter().enumerate() {
            let want: Vec<&str> = tickets
                .iter()
                .filter(|t| idx(expected(t["status"].as_str().unwrap())) == ci)
                .map(|t| t["key"].as_str().unwrap())
                .collect();
            let got: Vec<&str> = col.iter().map(|t| t.key.as_str()).collect();
            assert_eq!(got, want, "lane {} column {}", lane.repo, ci);
        }
    }
}

#[test]
fn ac1_property_ticket_count_preserved() {
    // AC1 property: no ticket lost or duplicated.
    let raw: serde_json::Value = serde_json::from_str(FIXTURE).unwrap();
    let want: usize = raw["lanes"].as_array().unwrap().iter()
        .map(|l| l["tickets"].as_array().unwrap().len()).sum();
    let got: usize = board().lanes.iter().flat_map(|l| l.columns.iter()).map(|c| c.len()).sum();
    assert_eq!(want, 8);
    assert_eq!(got, want);
}

#[test]
fn ac2_column_of_maps_all_statuses() {
    // AC2
    for (s, c) in TABLE {
        assert_eq!(Column::of(s), c, "status {s}");
    }
    assert_eq!(Column::of("bogus"), Column::NeedsYou);
    assert_eq!(Column::of(""), Column::NeedsYou);
    let titles: Vec<&str> = Column::ALL.iter().map(|c| c.title()).collect();
    assert_eq!(titles, ["Pending", "Working", "In review", "Changes", "Done", "Needs you"]);
}

#[test]
fn ac3_bad_schema_or_json_is_err() {
    // AC3
    let schema2 = FIXTURE.replacen("\"schema\": 1", "\"schema\": 2", 1);
    assert_ne!(schema2, FIXTURE);
    let e = parse(&schema2).unwrap_err().to_lowercase();
    assert!(e.contains("schema") || e.contains("json"), "{e}");
    let e = parse("{not json").unwrap_err().to_lowercase();
    assert!(e.contains("schema") || e.contains("json"), "{e}");
}

#[test]
fn ac4_header_fields_match_fixture() {
    // AC4
    let raw: serde_json::Value = serde_json::from_str(FIXTURE).unwrap();
    let b = board();
    assert_eq!(b.prd, raw["prd"].as_str().unwrap());
    assert_eq!(b.phase, "review");
    assert_eq!(b.model, raw["model"].as_str().unwrap());
    assert_eq!(b.needs_you, raw["needs_you"].as_array().unwrap().len());
    assert_eq!(b.needs_you, 1);
}
