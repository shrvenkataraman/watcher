//! Argument and prd-list parsing for `watcher-kanban`. Pure functions only.

use serde::Deserialize;

const USAGE: &str = "usage: watcher-kanban (--prd P | --all) [--state-root S] [--watcher BIN]";

#[derive(Debug, PartialEq, Eq)]
pub enum Target {
    One(String),
    All,
}

/// Reads `--prd <value>` and `--all` out of the argument list.
///
/// A `--prd` with no following value counts as missing.
pub fn parse_target(a: &[String]) -> Result<Target, String> {
    let mut prd: Option<String> = None;
    let mut all = false;
    let mut i = 0;

    while i < a.len() {
        match a[i].as_str() {
            "--prd" if i + 1 < a.len() => {
                if prd.is_none() {
                    prd = Some(a[i + 1].clone());
                }
                i += 2;
            }
            "--all" => {
                all = true;
                i += 1;
            }
            _ => i += 1,
        }
    }

    match (prd, all) {
        (Some(_), true) => Err("use --prd or --all, not both".to_string()),
        (Some(p), false) => Ok(Target::One(p)),
        (None, true) => Ok(Target::All),
        (None, false) => Err(USAGE.to_string()),
    }
}

#[derive(Deserialize)]
struct PrdList {
    schema: u64,
    #[serde(default)]
    prds: Vec<String>,
}

/// Reads `{"schema":1,"prds":["a","b"]}` and returns the names in order.
pub fn parse_prds(json: &str) -> Result<Vec<String>, String> {
    let raw: PrdList = serde_json::from_str(json).map_err(|e| format!("invalid json: {e}"))?;
    if raw.schema != 1 {
        return Err(format!("unsupported schema {n}", n = raw.schema));
    }
    Ok(raw.prds)
}
