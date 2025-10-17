use anyhow::Result;
use crossterm::{
    event::{self, DisableMouseCapture, EnableMouseCapture, Event, KeyCode},
    execute,
    terminal::{disable_raw_mode, enable_raw_mode, EnterAlternateScreen, LeaveAlternateScreen},
};
use ratatui::{
    backend::{Backend, CrosstermBackend},
    layout::{Constraint, Direction, Layout},
    style::{Color, Modifier, Style},
    text::{Line, Span},
    widgets::{Block, Borders, Gauge, List, ListItem},
    Frame, Terminal,
};
use std::collections::VecDeque;
use std::io;
use std::sync::{Arc, Mutex};
use std::time::{Duration, Instant};

/// Progress state for the TUI
#[derive(Clone)]
pub struct ProgressState {
    pub phase: Phase,
    pub records_read: usize,
    pub pairs_written: usize,
    pub filtered: usize,
    pub lines_processed: usize,
    pub unique_cells: usize,
    pub bytes_processed: u64,
    pub total_bytes: u64,
    pub start_time: Instant,
    pub pass1_bytes_read: u64,
    pub pass1_total_bytes: u64,
}

#[derive(Clone, Copy, PartialEq)]
pub enum Phase {
    Pass1,
    Sorting,
    Pass2,
    Complete,
}

impl Phase {
    fn name(&self) -> &str {
        match self {
            Phase::Pass1 => "Pass 1: Extract Pairs",
            Phase::Sorting => "Sorting Pairs File",
            Phase::Pass2 => "Pass 2: Aggregate Data",
            Phase::Complete => "Complete",
        }
    }

    fn progress(&self, state: &ProgressState) -> f64 {
        match self {
            Phase::Pass1 => {
                // Show progress based on compressed bytes read from TAR entry
                if state.pass1_total_bytes > 0 {
                    (state.pass1_bytes_read as f64 / state.pass1_total_bytes as f64).min(1.0)
                } else {
                    0.0
                }
            }
            Phase::Sorting => {
                // No progress available during sort
                0.0
            }
            Phase::Pass2 => {
                if state.total_bytes > 0 {
                    state.bytes_processed as f64 / state.total_bytes as f64
                } else {
                    0.0
                }
            }
            Phase::Complete => 1.0,
        }
    }
}

impl Default for ProgressState {
    fn default() -> Self {
        Self {
            phase: Phase::Pass1,
            records_read: 0,
            pairs_written: 0,
            filtered: 0,
            lines_processed: 0,
            unique_cells: 0,
            bytes_processed: 0,
            total_bytes: 0,
            start_time: Instant::now(),
            pass1_bytes_read: 0,
            pass1_total_bytes: 0,
        }
    }
}

/// TUI application state
pub struct App {
    pub state: Arc<Mutex<ProgressState>>,
    pub logs: Arc<Mutex<VecDeque<String>>>,
    max_logs: usize,
}

impl App {
    pub fn new() -> Self {
        Self {
            state: Arc::new(Mutex::new(ProgressState::default())),
            logs: Arc::new(Mutex::new(VecDeque::new())),
            max_logs: 1000,
        }
    }

    pub fn add_log(&self, message: String) {
        let mut logs = self.logs.lock().unwrap();
        if logs.len() >= self.max_logs {
            logs.pop_front();
        }
        logs.push_back(message);
    }

    pub fn update_state<F>(&self, f: F)
    where
        F: FnOnce(&mut ProgressState),
    {
        let mut state = self.state.lock().unwrap();
        f(&mut *state);
    }

    pub fn get_state(&self) -> ProgressState {
        self.state.lock().unwrap().clone()
    }
}

/// Run the TUI
pub fn run_tui(app: Arc<App>) -> Result<()> {
    // Setup terminal
    enable_raw_mode()?;
    let mut stdout = io::stdout();
    execute!(stdout, EnterAlternateScreen, EnableMouseCapture)?;
    let backend = CrosstermBackend::new(stdout);
    let mut terminal = Terminal::new(backend)?;

    let res = run_app(&mut terminal, app);

    // Restore terminal
    disable_raw_mode()?;
    execute!(
        terminal.backend_mut(),
        LeaveAlternateScreen,
        DisableMouseCapture
    )?;
    terminal.show_cursor()?;

    res
}

fn run_app<B: Backend>(terminal: &mut Terminal<B>, app: Arc<App>) -> Result<()> {
    loop {
        // Try to draw, but catch terminal errors gracefully
        match terminal.draw(|f| ui(f, &app)) {
            Ok(_) => {},
            Err(e) => {
                // Terminal device lost - exit gracefully
                return Err(e.into());
            }
        }

        // Poll for events with timeout
        match event::poll(Duration::from_millis(100)) {
            Ok(true) => {
                if let Ok(Event::Key(key)) = event::read() {
                    if let KeyCode::Char('q') = key.code {
                        return Ok(());
                    }
                }
            }
            Ok(false) => {}, // No event, continue
            Err(_) => {
                // Event polling failed - terminal likely closed
                return Ok(());
            }
        }

        // Check if complete
        let state = app.get_state();
        if state.phase == Phase::Complete {
            // Give a moment to see the final state
            std::thread::sleep(Duration::from_secs(2));
            return Ok(());
        }
    }
}

fn ui(f: &mut Frame, app: &App) {
    let state = app.get_state();

    // Create layout
    let chunks = Layout::default()
        .direction(Direction::Vertical)
        .constraints([
            Constraint::Length(6), // Progress panel
            Constraint::Min(10),   // Logs panel
        ])
        .split(f.area());

    // Progress panel
    render_progress(f, chunks[0], &state);

    // Logs panel
    render_logs(f, chunks[1], app);
}

fn render_progress(f: &mut Frame, area: ratatui::layout::Rect, state: &ProgressState) {
    let progress = state.phase.progress(state);
    let elapsed = state.start_time.elapsed();
    let elapsed_str = format!("{}:{:02}", elapsed.as_secs() / 60, elapsed.as_secs() % 60);

    // Build progress label based on phase
    let label = match state.phase {
        Phase::Pass1 => {
            if state.pass1_total_bytes > 0 {
                format!(
                    "Records: {} | Pairs: {} | Filtered: {} | {:.1}% | {}",
                    format_number(state.records_read),
                    format_number(state.pairs_written),
                    format_number(state.filtered),
                    progress * 100.0,
                    elapsed_str
                )
            } else {
                format!(
                    "Records: {} | Pairs: {} | Filtered: {} | {} (working...)",
                    format_number(state.records_read),
                    format_number(state.pairs_written),
                    format_number(state.filtered),
                    elapsed_str
                )
            }
        }
        Phase::Sorting => format!("Sorting in progress (no progress available) | {} (working...)", elapsed_str),
        Phase::Pass2 => format!(
            "Lines: {} | Cells: {} | {:.1}% | {}",
            format_number(state.lines_processed),
            format_number(state.unique_cells),
            progress * 100.0,
            elapsed_str
        ),
        Phase::Complete => format!("Analysis complete in {}", elapsed_str),
    };

    let gauge = Gauge::default()
        .block(
            Block::default()
                .borders(Borders::ALL)
                .title(state.phase.name()),
        )
        .gauge_style(
            Style::default()
                .fg(Color::Cyan)
                .bg(Color::Black)
                .add_modifier(Modifier::BOLD),
        )
        .percent((progress * 100.0) as u16)
        .label(label);

    f.render_widget(gauge, area);
}

fn render_logs(f: &mut Frame, area: ratatui::layout::Rect, app: &App) {
    let logs = app.logs.lock().unwrap();

    // Take last N logs that fit in the area
    let visible_logs = (area.height as usize).saturating_sub(2); // Account for borders
    let start_idx = logs.len().saturating_sub(visible_logs);

    let items: Vec<ListItem> = logs
        .iter()
        .skip(start_idx)
        .map(|log| {
            let style = if log.contains("[ERROR]") {
                Style::default().fg(Color::Red)
            } else if log.contains("[WARN]") {
                Style::default().fg(Color::Yellow)
            } else if log.contains("[INFO]") {
                Style::default().fg(Color::Green)
            } else {
                Style::default()
            };

            ListItem::new(Line::from(vec![Span::styled(log.clone(), style)]))
        })
        .collect();

    let list = List::new(items).block(
        Block::default()
            .borders(Borders::ALL)
            .title(format!("Logs ({} total)", logs.len())),
    );

    f.render_widget(list, area);
}

fn format_number(n: usize) -> String {
    n.to_string()
        .as_bytes()
        .rchunks(3)
        .rev()
        .map(std::str::from_utf8)
        .collect::<Result<Vec<&str>, _>>()
        .unwrap()
        .join(",")
}
