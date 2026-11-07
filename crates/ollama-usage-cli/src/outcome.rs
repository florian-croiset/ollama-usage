use ollama_usage::{Error, Report};

/// The exit codes, listed in `--help`.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
#[repr(u8)]
pub(crate) enum Outcome {
    Ok = 0,
    AlertReached = 1,
    Partial = 2,
    Failed = 3,
    NoUsableKey = 4,
    Usage = 64,
}

impl Outcome {
    /// An alert outranks a partial report: it answers the question the caller
    /// asked.
    pub(crate) fn of(report: &Report, alert: Option<f64>) -> Self {
        let reached = alert.is_some_and(|threshold| {
            report
                .windows
                .iter()
                .any(|(_, window)| window.used_pct >= threshold)
        });
        if reached {
            Self::AlertReached
        } else if report.is_partial() {
            Self::Partial
        } else {
            Self::Ok
        }
    }

    pub(crate) fn of_error(error: &Error) -> Self {
        match error {
            Error::Auth(_) => Self::NoUsableKey,
            _ => Self::Failed,
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    const CURRENT: &str = include_str!("../../../fixtures/reports/current.json");

    fn report() -> Report {
        serde_json::from_str(CURRENT).unwrap()
    }

    #[test]
    fn a_complete_report_is_ok() {
        assert_eq!(Outcome::of(&report(), None), Outcome::Ok);
    }

    #[test]
    fn the_alert_fires_at_the_threshold() {
        assert_eq!(Outcome::of(&report(), Some(12.5)), Outcome::AlertReached);
        assert_eq!(Outcome::of(&report(), Some(12.6)), Outcome::Ok);
    }

    #[test]
    fn a_partial_report_is_reported_unless_the_alert_fired() {
        let mut partial = report();
        partial.warnings = serde_json::from_str(
            r#"[{"code":"usage_unavailable","message":"/api/usage: HTTP 503"}]"#,
        )
        .unwrap();
        assert_eq!(Outcome::of(&partial, None), Outcome::Partial);
        assert_eq!(Outcome::of(&partial, Some(10.0)), Outcome::AlertReached);
    }

    #[test]
    fn a_rejected_key_and_other_failures_have_their_own_codes() {
        assert_eq!(
            Outcome::of_error(&Error::Auth(String::new())),
            Outcome::NoUsableKey
        );
        assert_eq!(
            Outcome::of_error(&Error::RateLimited { retry_after: None }),
            Outcome::Failed
        );
    }
}
