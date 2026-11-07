//! Turns API responses into report parts. Unknown fields are ignored so that
//! additions on Ollama's side do not break anything, and a malformed timestamp
//! loses only that timestamp.

use serde::Deserialize;
use serde::de::DeserializeOwned;
use time::OffsetDateTime;
use time::format_description::well_known::Rfc3339;

use crate::error::EndpointError;
use crate::report::{
    Credits, IncludedCredits, Metrics, ModelUsage, OtherUsage, Range, Usage, Warning, WarningCode,
    Window, Windows,
};

/// What `/api/balance` contributes to a report.
#[derive(Debug, Clone, PartialEq)]
pub(crate) struct Balance {
    pub(crate) windows: Windows,
    pub(crate) credits: Credits,
    pub(crate) warnings: Vec<Warning>,
}

pub(crate) fn balance(body: &str) -> Result<Balance, EndpointError> {
    let wire: BalanceWire = from_json(body)?;
    let included = wire.included.unwrap_or_default();
    let mut warnings = Vec::new();

    let (monthly, included_credits) = if included.is_monthly() {
        match (included.balance_usd, included.allowance_usd) {
            (Some(balance), Some(allowance)) if allowance > 0.0 => {
                let period = included.period.unwrap_or_default();
                let window = Window {
                    used_pct: round(100.0 * (1.0 - balance / allowance), 4),
                    starts_at: timestamp(period.from.as_deref()),
                    resets_at: timestamp(period.until.as_deref()),
                };
                let credits = IncludedCredits {
                    balance_usd: balance,
                    allowance_usd: allowance,
                    spent_usd: round(allowance - balance, 6),
                };
                (Some(window), Some(credits))
            }
            _ => {
                warnings.push(Warning::new(
                    WarningCode::MonthlyAllowanceMissing,
                    "the monthly period has no included allowance, so no percentage can be computed",
                ));
                (None, None)
            }
        }
    } else {
        (None, None)
    };

    let windows = Windows {
        monthly,
        session: included.session.and_then(LegacyWindowWire::into_window),
        weekly: included.weekly.and_then(LegacyWindowWire::into_window),
    };
    if warnings.is_empty() && windows.iter().next().is_none() {
        warnings.push(Warning::new(
            WarningCode::NoQuotaWindow,
            "/api/balance reported no quota window",
        ));
    }

    Ok(Balance {
        windows,
        credits: Credits {
            included: included_credits,
            purchased_balance_usd: wire.purchased.and_then(|purchased| purchased.balance_usd),
        },
        warnings,
    })
}

pub(crate) fn usage(body: &str, range: Range) -> Result<Usage, EndpointError> {
    let wire: UsageWire = from_json(body)?;
    let totals = wire.totals.metrics.into_metrics();
    let share = Share::of(&totals);

    let models = wire
        .totals
        .groups
        .into_iter()
        .map(|group| {
            let metrics = group.metrics.into_metrics();
            ModelUsage {
                share_pct: share.of_part(&metrics),
                model: group.model,
                metrics,
            }
        })
        .collect();
    let other = wire.totals.remainder.map(|remainder| {
        let metrics = remainder.into_metrics();
        OtherUsage {
            share_pct: share.of_part(&metrics),
            metrics,
        }
    });

    Ok(Usage {
        range,
        from: timestamp(wire.from.as_deref()),
        until: timestamp(wire.until.as_deref()),
        totals,
        models,
        other,
    })
}

/// The plan name from `/api/me`, in lower case. Only the `Plan` field is read.
pub(crate) fn plan(body: &str) -> Result<String, EndpointError> {
    let wire: MeWire = from_json(body)?;
    wire.plan
        .map(|plan| plan.trim().to_lowercase())
        .filter(|plan| !plan.is_empty())
        .ok_or_else(|| EndpointError::Parse("no `Plan` field".to_owned()))
}

fn from_json<T: DeserializeOwned>(body: &str) -> Result<T, EndpointError> {
    serde_json::from_str(body).map_err(|error| EndpointError::Parse(error.to_string()))
}

fn timestamp(text: Option<&str>) -> Option<OffsetDateTime> {
    let parsed = OffsetDateTime::parse(text?, &Rfc3339).ok();
    if parsed.is_none() {
        log::debug!("ignoring malformed timestamp {text:?}");
    }
    parsed
}

/// Rounds away the floating-point noise of a subtraction, e.g.
/// `12.500000000000002`, so reports compare and print cleanly.
fn round(value: f64, decimals: i32) -> f64 {
    let scale = 10_f64.powi(decimals);
    (value * scale).round() / scale
}

/// How a part's share of the total is measured: by cost, or by requests when
/// nothing was billed.
enum Share {
    Cost(f64),
    Requests(u64),
    Nothing,
}

impl Share {
    fn of(totals: &Metrics) -> Self {
        if totals.cost_usd > 0.0 {
            Self::Cost(totals.cost_usd)
        } else if totals.requests > 0 {
            Self::Requests(totals.requests)
        } else {
            Self::Nothing
        }
    }

    #[allow(clippy::cast_precision_loss)]
    fn of_part(&self, part: &Metrics) -> f64 {
        let ratio = match *self {
            Self::Cost(total) => part.cost_usd / total,
            Self::Requests(total) => part.requests as f64 / total as f64,
            Self::Nothing => 0.0,
        };
        round(100.0 * ratio, 2)
    }
}

#[derive(Debug, Deserialize)]
struct BalanceWire {
    included: Option<IncludedWire>,
    purchased: Option<PurchasedWire>,
}

#[derive(Debug, Default, Deserialize)]
struct IncludedWire {
    balance_usd: Option<f64>,
    allowance_usd: Option<f64>,
    period: Option<PeriodWire>,
    session: Option<LegacyWindowWire>,
    weekly: Option<LegacyWindowWire>,
}

impl IncludedWire {
    fn is_monthly(&self) -> bool {
        self.balance_usd.is_some() || self.allowance_usd.is_some() || self.period.is_some()
    }
}

#[derive(Debug, Default, Deserialize)]
struct PeriodWire {
    from: Option<String>,
    until: Option<String>,
}

#[derive(Debug, Deserialize)]
struct LegacyWindowWire {
    remaining_percent: Option<f64>,
    resets_at: Option<String>,
}

impl LegacyWindowWire {
    fn into_window(self) -> Option<Window> {
        Some(Window {
            used_pct: round(100.0 - self.remaining_percent?, 4),
            starts_at: None,
            resets_at: timestamp(self.resets_at.as_deref()),
        })
    }
}

#[derive(Debug, Deserialize)]
struct PurchasedWire {
    balance_usd: Option<f64>,
}

#[derive(Debug, Deserialize)]
struct UsageWire {
    from: Option<String>,
    until: Option<String>,
    totals: TotalsWire,
}

#[derive(Debug, Deserialize)]
struct TotalsWire {
    #[serde(flatten)]
    metrics: MetricsWire,
    #[serde(default)]
    groups: Vec<GroupWire>,
    remainder: Option<MetricsWire>,
}

#[derive(Debug, Deserialize)]
struct GroupWire {
    model: String,
    #[serde(flatten)]
    metrics: MetricsWire,
}

#[derive(Debug, Default, Deserialize)]
#[serde(default)]
struct MetricsWire {
    request_count: u64,
    usage_usd: f64,
    input_tokens: u64,
    cached_input_tokens: u64,
    output_tokens: u64,
}

impl MetricsWire {
    fn into_metrics(self) -> Metrics {
        Metrics {
            requests: self.request_count,
            cost_usd: self.usage_usd,
            input_tokens: self.input_tokens,
            cached_input_tokens: self.cached_input_tokens,
            output_tokens: self.output_tokens,
        }
    }
}

#[derive(Debug, Deserialize)]
struct MeWire {
    #[serde(rename = "Plan")]
    plan: Option<String>,
}

#[cfg(test)]
mod tests {
    use time::macros::datetime;

    use super::*;

    const BALANCE_CURRENT: &str = include_str!("../../../fixtures/api/balance_current.json");
    const BALANCE_LEGACY: &str = include_str!("../../../fixtures/api/balance_legacy.json");
    const USAGE_30D: &str = include_str!("../../../fixtures/api/usage_30d.json");
    const USAGE_EMPTY: &str = include_str!("../../../fixtures/api/usage_empty.json");
    const ME: &str = include_str!("../../../fixtures/api/me.json");

    #[test]
    fn a_current_plan_has_a_monthly_window_from_its_included_credits() {
        let balance = balance(BALANCE_CURRENT).unwrap();
        let monthly = balance.windows.monthly.unwrap();
        assert_eq!(monthly.used_pct, 12.5);
        assert_eq!(monthly.starts_at, Some(datetime!(2026-01-01 00:00 UTC)));
        assert_eq!(monthly.resets_at, Some(datetime!(2026-02-01 00:00 UTC)));
        assert_eq!(balance.windows.session, None);
        assert_eq!(balance.warnings, vec![]);
    }

    #[test]
    fn the_included_spend_is_the_allowance_minus_the_balance() {
        let credits = balance(BALANCE_CURRENT).unwrap().credits;
        let included = credits.included.unwrap();
        assert_eq!(included.spent_usd, 0.625);
        assert_eq!(credits.purchased_balance_usd, Some(0.0));
    }

    #[test]
    fn a_legacy_plan_has_session_and_weekly_windows() {
        let balance = balance(BALANCE_LEGACY).unwrap();
        let session = balance.windows.session.unwrap();
        assert_eq!(session.used_pct, 12.5);
        assert_eq!(session.resets_at, Some(datetime!(2026-01-10 15:00 UTC)));
        assert_eq!(session.starts_at, None);
        assert_eq!(balance.windows.weekly.unwrap().used_pct, 40.0);
        assert_eq!(balance.windows.monthly, None);
        assert_eq!(balance.credits.included, None);
        assert_eq!(balance.credits.purchased_balance_usd, Some(2.5));
    }

    #[test]
    fn a_zero_allowance_gives_no_percentage_and_says_why() {
        let body =
            r#"{"included":{"balance_usd":0,"allowance_usd":0},"purchased":{"balance_usd":1}}"#;
        let balance = balance(body).unwrap();
        assert_eq!(balance.windows.monthly, None);
        assert_eq!(balance.credits.included, None);
        assert_eq!(
            balance.warnings[0].code,
            WarningCode::MonthlyAllowanceMissing
        );
    }

    #[test]
    fn a_balance_without_any_window_is_flagged() {
        let balance = balance(r#"{"purchased":{"balance_usd":1}}"#).unwrap();
        assert_eq!(balance.windows, Windows::default());
        assert_eq!(balance.warnings[0].code, WarningCode::NoQuotaWindow);
    }

    #[test]
    fn a_malformed_timestamp_loses_only_that_timestamp() {
        let body = r#"{"included":{"balance_usd":1,"allowance_usd":2,
            "period":{"from":"yesterday","until":"2026-02-01T00:00:00Z"}}}"#;
        let monthly = balance(body).unwrap().windows.monthly.unwrap();
        assert_eq!(monthly.starts_at, None);
        assert_eq!(monthly.resets_at, Some(datetime!(2026-02-01 00:00 UTC)));
    }

    #[test]
    fn unknown_fields_are_ignored() {
        let body =
            r#"{"included":{"balance_usd":1,"allowance_usd":2,"new_field":true},"extra":[]}"#;
        assert_eq!(
            balance(body).unwrap().windows.monthly.unwrap().used_pct,
            50.0
        );
    }

    #[test]
    fn a_balance_that_is_not_json_is_a_parse_error() {
        assert!(matches!(balance("<html>"), Err(EndpointError::Parse(_))));
    }

    #[test]
    fn usage_keeps_totals_models_and_the_remainder() {
        let usage = usage(USAGE_30D, Range::Days30).unwrap();
        assert_eq!(usage.range, Range::Days30);
        assert_eq!(usage.totals.requests, 120);
        assert_eq!(usage.totals.cached_input_tokens, 10_000);
        assert_eq!(usage.from, Some(datetime!(2025-12-11 00:00 UTC)));
        let names: Vec<_> = usage.models.iter().map(|m| m.model.as_str()).collect();
        assert_eq!(names, ["model-a", "model-b"]);
        assert_eq!(usage.other.unwrap().metrics.requests, 20);
    }

    #[test]
    fn shares_are_a_share_of_the_total_cost() {
        let usage = usage(USAGE_30D, Range::Days30).unwrap();
        let shares: Vec<_> = usage.models.iter().map(|m| m.share_pct).collect();
        assert_eq!(shares, [50.0, 37.5]);
        assert_eq!(usage.other.unwrap().share_pct, 12.5);
    }

    #[test]
    fn shares_fall_back_to_requests_when_nothing_was_billed() {
        let body = r#"{"totals":{"request_count":4,"usage_usd":0,
            "groups":[{"model":"m","request_count":1,"usage_usd":0}]}}"#;
        assert_eq!(usage(body, Range::Days7).unwrap().models[0].share_pct, 25.0);
    }

    #[test]
    fn an_idle_range_has_no_models() {
        let usage = usage(USAGE_EMPTY, Range::Days7).unwrap();
        assert_eq!(usage.totals, Metrics::default());
        assert_eq!(usage.models, vec![]);
        assert_eq!(usage.other, None);
    }

    #[test]
    fn usage_without_totals_is_a_parse_error() {
        let error = usage(r#"{"range":"30d","buckets":[]}"#, Range::Days30).unwrap_err();
        assert!(matches!(error, EndpointError::Parse(message) if message.contains("totals")));
    }

    #[test]
    fn the_plan_is_read_in_lower_case() {
        assert_eq!(plan(ME).unwrap(), "free");
    }

    #[test]
    fn a_missing_or_empty_plan_is_an_error() {
        assert!(plan(r#"{"ID":"usr_example"}"#).is_err());
        assert!(plan(r#"{"Plan":"  "}"#).is_err());
    }
}
