use serde::Deserialize;

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum Column {
    Pending,
    Working,
    Review,
    Changes,
    Done,
    NeedsYou,
}

impl Column {
    pub const ALL: [Column; 6] = [
        Column::Pending,
        Column::Working,
        Column::Review,
        Column::Changes,
        Column::Done,
        Column::NeedsYou,
    ];

    pub fn title(self) -> &'static str {
        match self {
            Column::Pending => "Pending",
            Column::Working => "Working",
            Column::Review => "In review",
            Column::Changes => "Changes",
            Column::Done => "Done",
            Column::NeedsYou => "Needs you",
        }
    }

    pub fn of(status: &str) -> Column {
        match status {
            "pending" => Column::Pending,
            "running" => Column::Working,
            "implemented" | "fixed" => Column::Review,
            "changes" => Column::Changes,
            "approved" | "skipped" => Column::Done,
            _ => Column::NeedsYou,
        }
    }

    fn index(self) -> usize {
        Column::ALL.iter().position(|c| *c == self).unwrap()
    }
}

#[derive(Debug, Clone, PartialEq, Eq, Deserialize)]
pub struct Ticket {
    pub key: String,
    pub status: String,
    #[serde(default)]
    pub sha: String,
    #[serde(default)]
    pub title: String,
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct Lane {
    pub repo: String,
    pub pr_status: String,
    pub columns: [Vec<Ticket>; 6],
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct Board {
    pub prd: String,
    pub phase: String,
    pub model: String,
    pub needs_you: usize,
    pub lanes: Vec<Lane>,
}

#[derive(Deserialize)]
struct RawLane {
    repo: String,
    #[serde(default)]
    pr_status: String,
    #[serde(default)]
    tickets: Vec<Ticket>,
}

#[derive(Deserialize)]
struct Raw {
    schema: u64,
    #[serde(default)]
    prd: String,
    #[serde(default)]
    phase: String,
    #[serde(default)]
    model: String,
    #[serde(default)]
    needs_you: Vec<serde_json::Value>,
    #[serde(default)]
    lanes: Vec<RawLane>,
}

pub fn parse(json: &str) -> Result<Board, String> {
    let raw: Raw = serde_json::from_str(json).map_err(|e| format!("invalid json: {e}"))?;
    if raw.schema != 1 {
        return Err(format!("unsupported schema {}", raw.schema));
    }
    let lanes = raw
        .lanes
        .into_iter()
        .map(|l| {
            let mut columns: [Vec<Ticket>; 6] = Default::default();
            for t in l.tickets {
                columns[Column::of(&t.status).index()].push(t);
            }
            Lane { repo: l.repo, pr_status: l.pr_status, columns }
        })
        .collect();
    Ok(Board {
        prd: raw.prd,
        phase: raw.phase,
        model: raw.model,
        needs_you: raw.needs_you.len(),
        lanes,
    })
}

/// Boards in input order. Returns the merged board and, per merged lane, the prd it came from.
pub fn merge(boards: Vec<Board>) -> (Board, Vec<String>) {
    let mut lanes: Vec<Lane> = Vec::new();
    let mut prds: Vec<String> = Vec::new();
    let mut needs_you = 0usize;
    let mut phases: Vec<String> = Vec::new();
    let mut models: Vec<String> = Vec::new();

    for board in boards {
        let Board { prd, phase, model, needs_you: board_needs_you, lanes: board_lanes } = board;
        needs_you += board_needs_you;
        if !phase.is_empty() && !phases.contains(&phase) {
            phases.push(phase);
        }
        if !model.is_empty() && !models.contains(&model) {
            models.push(model);
        }
        for lane in board_lanes {
            lanes.push(Lane {
                repo: format!("{}/{}", lane.repo, prd),
                pr_status: lane.pr_status,
                columns: lane.columns,
            });
            prds.push(prd.clone());
        }
    }

    phases.sort();
    models.sort();

    (
        Board {
            prd: "all".to_string(),
            phase: phases.join(","),
            model: models.join(","),
            needs_you,
            lanes,
        },
        prds,
    )
}
