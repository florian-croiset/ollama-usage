use std::fmt;
use std::str::FromStr;

use serde::{Deserialize, Serialize};
use time::OffsetDateTime;

/// Version of the JSON contract that [`Report`] serializes to. Changes within a
/// major version only add fields.
pub const SCHEMA_VERSION: &str = "1.0";

/// Everything one fetch learned about the account.
#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
#[non_exhaustive]
pub struct Report {
    /// Always [`SCHEMA_VERSION`] for a report built by this version.
    pub schema_version: String,
    /// When the report was built, to the second.
    #[serde(with = "time::serde::rfc3339")]
    pub fetched_at: OffsetDateTime,
    /// Plan name in lower case (`"free"`, `"pro"`…), from the undocumented
    /// `/api/me`. `None` when it could not be read.
    pub plan: Option<String>,
    /// Quota windows. A current plan has `monthly`; a plan subscribed before
    /// Ollama's 2026-08-31 pricing change has `session` and `weekly`.
    pub windows: Windows,
    /// Credit balances. `None` when `/api/balance` failed.
    pub credits: Option<Credits>,
    /// Requests, cost and tokens over [`Usage::range`]. `None` when `/api/usage`
    /// failed.
    pub usage: Option<Usage>,
    /// What went wrong without preventing the report, in the order it happened.
    pub warnings: Vec<Warning>,
}

impl Report {
    /// Whether `/api/balance` or `/api/usage` failed, leaving part of the report
    /// empty. A missing plan name does not count.
    pub fn is_partial(&self) -> bool {
        self.warnings.iter().any(|warning| {
            matches!(
                warning.code,
                WarningCode::BalanceUnavailable | WarningCode::UsageUnavailable
            )
        })
    }
}

/// The quota windows of a plan. Windows that do not apply to the plan are `None`.
#[derive(Debug, Clone, Default, PartialEq, Serialize, Deserialize)]
#[non_exhaustive]
pub struct Windows {
    /// Included monthly usage, on current plans.
    pub monthly: Option<Window>,
    /// Five-hour window, on plans subscribed before the pricing change.
    pub session: Option<Window>,
    /// Weekly window, on plans subscribed before the pricing change.
    pub weekly: Option<Window>,
}

impl Windows {
    /// The windows present, in display order: monthly, session, weekly.
    pub fn iter(&self) -> impl Iterator<Item = (WindowKind, &Window)> {
        [
            (WindowKind::Monthly, self.monthly.as_ref()),
            (WindowKind::Session, self.session.as_ref()),
            (WindowKind::Weekly, self.weekly.as_ref()),
        ]
        .into_iter()
        .filter_map(|(kind, window)| window.map(|window| (kind, window)))
    }
}

/// Which quota window a [`Window`] is.
#[derive(Debug, Clone, Copy, PartialEq, Eq, Hash)]
#[non_exhaustive]
pub enum WindowKind {
    /// See [`Windows::monthly`].
    Monthly,
    /// See [`Windows::session`].
    Session,
    /// See [`Windows::weekly`].
    Weekly,
}

impl WindowKind {
    /// The field name used in the report: `"monthly"`, `"session"` or `"weekly"`.
    pub const fn as_str(self) -> &'static str {
        match self {
            Self::Monthly => "monthly",
            Self::Session => "session",
            Self::Weekly => "weekly",
        }
    }
}

impl fmt::Display for WindowKind {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        f.write_str(self.as_str())
    }
}

/// How much of a quota window is used, and when it resets.
#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
#[non_exhaustive]
pub struct Window {
    /// Share of the window used, from 0 to 100.
    pub used_pct: f64,
    /// Start of the window. Only known for the monthly window.
    #[serde(default, with = "time::serde::rfc3339::option")]
    pub starts_at: Option<OffsetDateTime>,
    /// When the window resets.
    #[serde(default, with = "time::serde::rfc3339::option")]
    pub resets_at: Option<OffsetDateTime>,
}

/// Credit balances, in US dollars.
#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
#[non_exhaustive]
pub struct Credits {
    /// The plan's included credits. `None` on plans subscribed before the pricing
    /// change, which have session and weekly windows instead.
    pub included: Option<IncludedCredits>,
    /// Remaining purchased credits that have not expired.
    pub purchased_balance_usd: Option<f64>,
}

/// The included credits of the current monthly period.
#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
#[non_exhaustive]
pub struct IncludedCredits {
    /// What is left for this period.
    pub balance_usd: f64,
    /// What the plan includes for a whole period.
    pub allowance_usd: f64,
    /// What has been used this period: `allowance_usd - balance_usd`.
    pub spent_usd: f64,
}

/// Requests, cost and tokens over a fixed range, overall and per model.
#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
#[non_exhaustive]
pub struct Usage {
    /// The range covered. It ends now and is not aligned with the quota period.
    pub range: Range,
    /// Start of the range, inclusive.
    #[serde(default, with = "time::serde::rfc3339::option")]
    pub from: Option<OffsetDateTime>,
    /// End of the range, exclusive.
    #[serde(default, with = "time::serde::rfc3339::option")]
    pub until: Option<OffsetDateTime>,
    /// Totals over the range, every model included.
    #[serde(flatten)]
    pub totals: Metrics,
    /// Up to ten models, most expensive first.
    pub models: Vec<ModelUsage>,
    /// The models beyond the first ten, combined. `None` when there are none.
    pub other: Option<OtherUsage>,
}

/// Request count, cost and tokens.
#[derive(Debug, Clone, Default, PartialEq, Serialize, Deserialize)]
#[non_exhaustive]
pub struct Metrics {
    /// Number of requests.
    pub requests: u64,
    /// Cost in US dollars, whether covered by the plan or paid with credits.
    pub cost_usd: f64,
    /// Input tokens, cached ones included.
    pub input_tokens: u64,
    /// Input tokens served from the cache, already counted in `input_tokens`.
    pub cached_input_tokens: u64,
    /// Output tokens.
    pub output_tokens: u64,
}

/// The usage of one model.
#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
#[non_exhaustive]
pub struct ModelUsage {
    /// Model name as Ollama reports it.
    pub model: String,
    /// What this model used.
    #[serde(flatten)]
    pub metrics: Metrics,
    /// This model's share of the total cost, from 0 to 100, or its share of the
    /// requests when nothing was billed.
    pub share_pct: f64,
}

/// The combined usage of the models beyond the first ten.
#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
#[non_exhaustive]
pub struct OtherUsage {
    /// What these models used together.
    #[serde(flatten)]
    pub metrics: Metrics,
    /// Their share of the total, computed like [`ModelUsage::share_pct`].
    pub share_pct: f64,
}

/// The ranges `/api/usage` accepts. Each one ends now.
#[derive(Debug, Clone, Copy, Default, PartialEq, Eq, Hash, Serialize, Deserialize)]
pub enum Range {
    /// The last 24 hours.
    #[serde(rename = "24h")]
    Hours24,
    /// The last 7 days.
    #[serde(rename = "7d")]
    Days7,
    /// The last 30 days.
    #[default]
    #[serde(rename = "30d")]
    Days30,
}

impl Range {
    /// Every range, shortest first.
    pub const ALL: [Self; 3] = [Self::Hours24, Self::Days7, Self::Days30];

    /// The spelling the API and the report use: `"24h"`, `"7d"` or `"30d"`.
    pub const fn as_str(self) -> &'static str {
        match self {
            Self::Hours24 => "24h",
            Self::Days7 => "7d",
            Self::Days30 => "30d",
        }
    }
}

impl fmt::Display for Range {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        f.write_str(self.as_str())
    }
}

impl FromStr for Range {
    type Err = ParseRangeError;

    fn from_str(text: &str) -> Result<Self, Self::Err> {
        Self::ALL
            .into_iter()
            .find(|range| range.as_str() == text)
            .ok_or_else(|| ParseRangeError(text.to_owned()))
    }
}

/// A string that is not one of `24h`, `7d` or `30d`.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct ParseRangeError(String);

impl fmt::Display for ParseRangeError {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        write!(f, "unknown range `{}`, expected 24h, 7d or 30d", self.0)
    }
}

impl std::error::Error for ParseRangeError {}

/// Something that went wrong without preventing the report.
#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
#[non_exhaustive]
pub struct Warning {
    /// Stable identifier, safe to match on.
    pub code: WarningCode,
    /// Human-readable explanation. Its wording may change.
    pub message: String,
}

impl Warning {
    pub(crate) fn new(code: WarningCode, message: impl Into<String>) -> Self {
        Self {
            code,
            message: message.into(),
        }
    }
}

/// The kinds of [`Warning`].
#[derive(Debug, Clone, Copy, PartialEq, Eq, Hash, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
#[non_exhaustive]
pub enum WarningCode {
    /// `/api/balance` failed: no windows and no credits.
    BalanceUnavailable,
    /// `/api/usage` failed: no usage.
    UsageUnavailable,
    /// `/api/me` failed or was skipped: no plan name.
    PlanUnavailable,
    /// The monthly period has no usable allowance, so no percentage.
    MonthlyAllowanceMissing,
    /// `/api/balance` answered without any quota window.
    NoQuotaWindow,
    /// A code added by a later version of this library.
    #[serde(other)]
    Unknown,
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn ranges_round_trip_through_their_spelling() {
        for range in Range::ALL {
            assert_eq!(range.as_str().parse::<Range>(), Ok(range));
        }
    }

    #[test]
    fn an_unknown_range_is_rejected_with_the_valid_ones() {
        let error = "1y".parse::<Range>().unwrap_err();
        assert_eq!(
            error.to_string(),
            "unknown range `1y`, expected 24h, 7d or 30d"
        );
    }

    #[test]
    fn the_default_range_is_30_days() {
        assert_eq!(Range::default(), Range::Days30);
    }

    #[test]
    fn windows_are_listed_in_display_order() {
        let window = Window {
            used_pct: 1.0,
            starts_at: None,
            resets_at: None,
        };
        let windows = Windows {
            monthly: None,
            session: Some(window.clone()),
            weekly: Some(window),
        };
        let kinds: Vec<_> = windows.iter().map(|(kind, _)| kind).collect();
        assert_eq!(kinds, [WindowKind::Session, WindowKind::Weekly]);
    }

    #[test]
    fn a_warning_code_from_a_later_version_still_deserializes() {
        let warning: Warning =
            serde_json::from_str(r#"{"code":"something_new","message":"m"}"#).unwrap();
        assert_eq!(warning.code, WarningCode::Unknown);
    }
}
