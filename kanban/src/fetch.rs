//! Red-commit stub. Ticket 05 replaces the bodies.

#[derive(Debug, PartialEq, Eq)]
pub enum Target {
    One(String),
    All,
}

pub fn parse_target(_a: &[String]) -> Result<Target, String> {
    unimplemented!("ticket 05")
}

pub fn parse_prds(_json: &str) -> Result<Vec<String>, String> {
    unimplemented!("ticket 05")
}
