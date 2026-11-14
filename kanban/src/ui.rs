use ratatui::{
    layout::{Constraint, Layout},
    style::{Modifier, Style},
    text::Line,
    widgets::{Block, Borders, Paragraph},
    Frame,
};

use crate::model::{Board, Column, Ticket};

const HELP: &str = "h/l column  j/k card  J/K lane  r retry  s skip  q quit";

pub struct View {
    pub lane: usize,
    pub column: usize,
    pub row: usize,
}

fn card_text(t: &Ticket) -> String {
    let short = t.key.split_once('/').map_or(t.key.as_str(), |(_, k)| k);
    if t.sha.is_empty() {
        short.to_string()
    } else {
        let sha: String = t.sha.chars().take(7).collect();
        format!("{short} {sha}")
    }
}

pub fn draw(frame: &mut Frame, board: &Board, view: &View, note: &str) {
    let [header, body, footer] = Layout::vertical([
        Constraint::Length(1),
        Constraint::Min(0),
        Constraint::Length(1),
    ])
    .areas(frame.area());

    frame.render_widget(
        Line::from(format!(
            "{}  phase={}  model={}  needs you={}",
            board.prd, board.phase, board.model, board.needs_you
        )),
        header,
    );

    let lane_areas = Layout::vertical(vec![Constraint::Fill(1); board.lanes.len()]).split(body);
    for (li, (lane, area)) in board.lanes.iter().zip(lane_areas.iter()).enumerate() {
        let block = Block::default()
            .borders(Borders::ALL)
            .title(format!("{}  pr={}", lane.repo, lane.pr_status));
        let inner = block.inner(*area);
        frame.render_widget(block, *area);
        let col_areas = Layout::horizontal(vec![Constraint::Fill(1); 6]).split(inner);
        for (ci, (col, carea)) in Column::ALL.iter().zip(col_areas.iter()).enumerate() {
            let tickets = &lane.columns[ci];
            let cblock = Block::default()
                .borders(Borders::ALL)
                .title(format!("{} ({})", col.title(), tickets.len()));
            let cinner = cblock.inner(*carea);
            frame.render_widget(cblock, *carea);
            let lines: Vec<Line> = tickets
                .iter()
                .enumerate()
                .map(|(ri, t)| {
                    let text = card_text(t);
                    if li == view.lane && ci == view.column && ri == view.row {
                        Line::styled(text, Style::default().add_modifier(Modifier::REVERSED))
                    } else {
                        Line::from(text)
                    }
                })
                .collect();
            frame.render_widget(Paragraph::new(lines), cinner);
        }
    }

    let text = if note.is_empty() { HELP } else { note };
    frame.render_widget(Line::from(text), footer);
}
