//! The text report. Styles are always emitted; anstream strips them when the
//! output is not a terminal or colours are disabled.

use std::fmt::Write;

use ollama_usage::{Credits, Metrics, Range, Report, Usage, Window, WindowKind};
use owo_colors::{OwoColorize, Style};
use time::OffsetDateTime;

const LABEL_WIDTH: usize = 9;
const BAR_WIDTH: usize = 20;
const DETAIL_INDENT: usize = LABEL_WIDTH + 2;

pub(crate) fn text(report: &Report, now: OffsetDateTime) -> String {
    let mut out = String::new();
    if let Some(plan) = &report.plan {
        line(&mut out, "Plan", plan);
    }
    for (kind, window) in report.windows.iter() {
        line(&mut out, label(kind), &window_summary(window, now));
    }
    if let Some(credits) = report.credits.as_ref().and_then(credits_summary) {
        line(&mut out, "Credits", &credits);
    }
    if let Some(usage) = &report.usage {
        usage_lines(&mut out, usage);
    }
    out
}

fn line(out: &mut String, label: &str, value: &str) {
    let _ = writeln!(out, "{label:<LABEL_WIDTH$}{value}");
}

fn label(kind: WindowKind) -> &'static str {
    match kind {
        WindowKind::Session => "Session",
        WindowKind::Weekly => "Weekly",
        _ => "Monthly",
    }
}

#[allow(
    clippy::cast_possible_truncation,
    clippy::cast_sign_loss,
    clippy::cast_precision_loss
)]
fn window_summary(window: &Window, now: OffsetDateTime) -> String {
    let filled = ((window.used_pct / 100.0 * BAR_WIDTH as f64).round() as usize).min(BAR_WIDTH);
    let bar = format!("{}{}", "█".repeat(filled), "░".repeat(BAR_WIDTH - filled));
    let pct = format!("{:>7}", format!("{:.1}%", window.used_pct));
    let style = severity(window.used_pct);
    let mut summary = format!("[{}] {}", bar.style(style), pct.style(style));
    if let Some(resets_at) = window.resets_at {
        let _ = write!(summary, "   resets {}", until(now, resets_at));
    }
    summary
}

fn severity(used_pct: f64) -> Style {
    if used_pct >= 80.0 {
        Style::new().red()
    } else if used_pct >= 50.0 {
        Style::new().yellow()
    } else {
        Style::new().green()
    }
}

fn until(now: OffsetDateTime, at: OffsetDateTime) -> String {
    let seconds = (at - now).whole_seconds();
    if seconds <= 0 {
        return "now".to_owned();
    }
    let (days, hours, minutes) = (
        seconds / 86_400,
        seconds % 86_400 / 3_600,
        seconds % 3_600 / 60,
    );
    if days > 0 {
        format!("in {days}d {hours}h")
    } else if hours > 0 {
        format!("in {hours}h {minutes}m")
    } else if minutes > 0 {
        format!("in {minutes}m")
    } else {
        "in less than a minute".to_owned()
    }
}

fn credits_summary(credits: &Credits) -> Option<String> {
    let included = credits.included.as_ref().map(|included| {
        format!(
            "included {} / {}",
            money(included.balance_usd),
            money(included.allowance_usd)
        )
    });
    let purchased = credits
        .purchased_balance_usd
        .map(|balance| format!("purchased {}", money(balance)));
    match (included, purchased) {
        (Some(included), Some(purchased)) => Some(format!("{included}  ·  {purchased}")),
        (one, other) => one.or(other),
    }
}

fn usage_lines(out: &mut String, usage: &Usage) {
    let period = match usage.range {
        Range::Hours24 => "last 24 hours",
        Range::Days7 => "last 7 days",
        Range::Days30 => "last 30 days",
    };
    if usage.totals.requests == 0 {
        line(out, "Usage", &format!("{period}  ·  no requests"));
        return;
    }
    line(
        out,
        "Usage",
        &format!(
            "{period}  ·  {} req  ·  {}",
            usage.totals.requests,
            money(usage.totals.cost_usd)
        ),
    );

    let rows: Vec<(&str, &Metrics, f64)> = usage
        .models
        .iter()
        .map(|model| (model.model.as_str(), &model.metrics, model.share_pct))
        .chain(
            usage
                .other
                .iter()
                .map(|other| ("other models", &other.metrics, other.share_pct)),
        )
        .collect();
    let costs: Vec<String> = rows
        .iter()
        .map(|(_, metrics, _)| money(metrics.cost_usd))
        .collect();
    let name_width = rows
        .iter()
        .map(|(name, ..)| name.chars().count())
        .max()
        .unwrap_or(0);
    let requests_width = rows
        .iter()
        .map(|(_, metrics, _)| metrics.requests.to_string().len())
        .max()
        .unwrap_or(0);
    let cost_width = costs.iter().map(String::len).max().unwrap_or(0);

    for ((name, metrics, share), cost) in rows.iter().zip(&costs) {
        let _ = writeln!(
            out,
            "{:DETAIL_INDENT$}{name:<name_width$}  {:>requests_width$} req  {cost:>cost_width$}  {:>6}",
            "",
            metrics.requests,
            format!("{share:.1}%"),
        );
    }
}

/// Dollars with cents, or with up to five decimals for amounts below a cent so
/// that a single cheap request does not read as free.
fn money(usd: f64) -> String {
    if usd.abs() >= 0.01 || usd.abs() < 1e-9 {
        return format!("${usd:.2}");
    }
    let digits = format!("{usd:.5}");
    format!("${}", digits.trim_end_matches('0'))
}

#[cfg(test)]
mod tests {
    use time::macros::datetime;

    use super::*;

    const CURRENT: &str = include_str!("../../../fixtures/reports/current.json");
    const LEGACY: &str = include_str!("../../../fixtures/reports/legacy.json");
    const NOW: OffsetDateTime = datetime!(2026-01-10 12:00 UTC);

    fn render(golden: &str) -> String {
        let report: Report = serde_json::from_str(golden).unwrap();
        plain(&text(&report, NOW))
    }

    fn plain(styled: &str) -> String {
        anstream::adapter::strip_str(styled).to_string()
    }

    #[test]
    fn a_current_plan() {
        assert_eq!(
            render(CURRENT),
            "\
Plan     free
Monthly  [███░░░░░░░░░░░░░░░░░]   12.5%   resets in 21d 12h
Credits  included $4.38 / $5.00  ·  purchased $0.00
Usage    last 30 days  ·  120 req  ·  $0.80
           model-a       60 req  $0.40   50.0%
           model-b       40 req  $0.30   37.5%
           other models  20 req  $0.10   12.5%
"
        );
    }

    #[test]
    fn a_legacy_plan() {
        let rendered = render(LEGACY);
        let head: Vec<_> = rendered.lines().take(4).collect();
        assert_eq!(
            head,
            [
                "Plan     pro",
                "Session  [███░░░░░░░░░░░░░░░░░]   12.5%   resets in 3h 0m",
                "Weekly   [████████░░░░░░░░░░░░]   40.0%   resets in 1d 12h",
                "Credits  purchased $2.50",
            ]
        );
    }

    #[test]
    fn missing_parts_are_left_out() {
        let mut report: Report = serde_json::from_str(CURRENT).unwrap();
        report.plan = None;
        report.usage = None;
        report.credits = None;
        assert_eq!(
            plain(&text(&report, NOW)),
            "Monthly  [███░░░░░░░░░░░░░░░░░]   12.5%   resets in 21d 12h\n"
        );
    }

    #[test]
    fn an_idle_range_says_so() {
        let mut report: Report = serde_json::from_str(CURRENT).unwrap();
        let usage = report.usage.as_mut().unwrap();
        usage.totals.requests = 0;
        usage.models.clear();
        usage.other = None;
        assert!(plain(&text(&report, NOW)).ends_with("Usage    last 30 days  ·  no requests\n"));
    }

    #[test]
    fn usage_is_coloured_by_severity() {
        assert_eq!(severity(49.9), Style::new().green());
        assert_eq!(severity(50.0), Style::new().yellow());
        assert_eq!(severity(79.9), Style::new().yellow());
        assert_eq!(severity(80.0), Style::new().red());
    }

    #[test]
    fn reset_times_are_relative() {
        assert_eq!(until(NOW, datetime!(2026-01-12 15:30 UTC)), "in 2d 3h");
        assert_eq!(until(NOW, datetime!(2026-01-10 14:05 UTC)), "in 2h 5m");
        assert_eq!(until(NOW, datetime!(2026-01-10 12:07 UTC)), "in 7m");
        assert_eq!(
            until(NOW, datetime!(2026-01-10 12:00:30 UTC)),
            "in less than a minute"
        );
        assert_eq!(until(NOW, datetime!(2026-01-10 11:00 UTC)), "now");
    }

    #[test]
    fn money_keeps_sub_cent_amounts_visible() {
        assert_eq!(money(0.0), "$0.00");
        assert_eq!(money(4.375), "$4.38");
        assert_eq!(money(0.00042), "$0.00042");
        assert_eq!(money(0.0015), "$0.0015");
    }

    #[test]
    fn a_full_window_fills_the_bar_and_no_more() {
        let window: Window = serde_json::from_str(r#"{"used_pct":104}"#).unwrap();
        assert!(plain(&window_summary(&window, NOW)).starts_with(&format!("[{}]", "█".repeat(20))));
    }
}
