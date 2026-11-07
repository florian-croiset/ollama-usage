use std::fmt;
use std::sync::{Mutex, PoisonError};
use std::time::{Duration, Instant};

use time::OffsetDateTime;

use crate::error::{EndpointError, Error};
use crate::http::{Method, Response, Transport, UreqTransport};
use crate::parse;
use crate::report::{Range, Report, SCHEMA_VERSION, Warning, WarningCode, Windows};

const BASE_URL: &str = "https://ollama.com";

/// Timeout applied to each request by [`Client::new`].
pub const DEFAULT_TIMEOUT: Duration = Duration::from_secs(10);

/// How long a plan name read from `/api/me` is reused.
const PLAN_TTL: Duration = Duration::from_hours(24);
/// How long to wait before asking `/api/me` again after it failed.
const PLAN_RETRY_AFTER: Duration = Duration::from_hours(1);

/// A client for one API key.
///
/// Building one does no I/O. Each [`fetch`](Self::fetch) makes two requests, plus
/// a third to `/api/me` the first time and then once a day, so reuse the client
/// when polling: the API allows 10 requests per minute per user.
pub struct Client {
    api_key: String,
    transport: Box<dyn Transport>,
    plan: Mutex<PlanCache>,
}

impl Client {
    /// A client for `api_key`, with the [`DEFAULT_TIMEOUT`].
    ///
    /// Keys are created at <https://ollama.com/settings/keys>.
    pub fn new(api_key: impl Into<String>) -> Self {
        Self::with_timeout(api_key, DEFAULT_TIMEOUT)
    }

    /// A client for `api_key` whose requests each give up after `timeout`.
    pub fn with_timeout(api_key: impl Into<String>, timeout: Duration) -> Self {
        Self::with_transport(api_key, Box::new(UreqTransport::new(timeout)))
    }

    pub(crate) fn with_transport(
        api_key: impl Into<String>,
        transport: Box<dyn Transport>,
    ) -> Self {
        Self {
            api_key: api_key.into(),
            transport,
            plan: Mutex::new(PlanCache::default()),
        }
    }

    /// Fetches the quota, the credits, the usage over `range` and the plan name.
    ///
    /// # Errors
    ///
    /// - [`Error::Auth`] if the key is rejected, or cannot be sent because it is
    ///   empty or holds a character other than printable ASCII.
    /// - [`Error::RateLimited`] if ollama.com rate-limits `/api/balance`.
    /// - [`Error::Network`] or [`Error::Api`] if both `/api/balance` and
    ///   `/api/usage` fail.
    ///
    /// When only one of them fails, the report is returned with that part empty
    /// and a warning; see [`Report::is_partial`].
    pub fn fetch(&self, range: Range) -> Result<Report, Error> {
        self.fetch_at(range, OffsetDateTime::now_utc(), Instant::now())
    }

    fn fetch_at(&self, range: Range, now: OffsetDateTime, clock: Instant) -> Result<Report, Error> {
        check_key(&self.api_key)?;
        let balance = self
            .get(&format!("{BASE_URL}/api/balance"))
            .and_then(|body| parse::balance(&body));
        match &balance {
            Err(EndpointError::Auth(message)) => return Err(Error::Auth(message.clone())),
            Err(EndpointError::RateLimited(retry_after)) => {
                return Err(Error::RateLimited {
                    retry_after: *retry_after,
                });
            }
            _ => {}
        }

        let usage = self
            .get(&format!(
                "{BASE_URL}/api/usage?range={range}&group_by=model"
            ))
            .and_then(|body| parse::usage(&body, range));
        if let Err(EndpointError::Auth(message)) = &usage {
            return Err(Error::Auth(message.clone()));
        }
        let rate_limited = matches!(usage, Err(EndpointError::RateLimited(_)));

        let (balance, usage) = match (balance, usage) {
            (Err(balance), Err(usage)) => return Err(EndpointError::combine(balance, usage)),
            pair => pair,
        };

        let mut warnings = Vec::new();
        let (windows, credits) = match balance {
            Ok(balance) => {
                warnings.extend(balance.warnings);
                (balance.windows, Some(balance.credits))
            }
            Err(error) => {
                warnings.push(Warning::new(
                    WarningCode::BalanceUnavailable,
                    format!("/api/balance: {error}"),
                ));
                (Windows::default(), None)
            }
        };
        let usage = usage
            .map_err(|error| {
                warnings.push(Warning::new(
                    WarningCode::UsageUnavailable,
                    format!("/api/usage: {error}"),
                ));
            })
            .ok();

        let plan = if rate_limited {
            warnings.push(Warning::new(
                WarningCode::PlanUnavailable,
                "/api/me: skipped after a rate limit",
            ));
            None
        } else {
            self.plan(clock)
                .map_err(|reason| {
                    warnings.push(Warning::new(
                        WarningCode::PlanUnavailable,
                        format!("/api/me: {reason}"),
                    ));
                })
                .ok()
        };

        Ok(Report {
            schema_version: SCHEMA_VERSION.to_owned(),
            fetched_at: now.replace_nanosecond(0).unwrap_or(now),
            plan,
            windows,
            credits,
            usage,
            warnings,
        })
    }

    fn plan(&self, clock: Instant) -> Result<String, String> {
        // The cache only saves requests, so a panic elsewhere must not disable it.
        let mut cache = self.plan.lock().unwrap_or_else(PoisonError::into_inner);
        if let Some(cached) = cache.get(clock) {
            return cached;
        }
        let fresh = self
            .send(Method::Post, &format!("{BASE_URL}/api/me"))
            .and_then(|body| parse::plan(&body))
            .map_err(|error| error.to_string());
        cache.put(clock, fresh.clone());
        fresh
    }

    fn get(&self, url: &str) -> Result<String, EndpointError> {
        self.send(Method::Get, url)
    }

    fn send(&self, method: Method, url: &str) -> Result<String, EndpointError> {
        let response = self
            .transport
            .send(method, url, &self.api_key)
            .map_err(EndpointError::Network)?;
        classify(response)
    }
}

impl fmt::Debug for Client {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        f.debug_struct("Client")
            .field("api_key", &"<redacted>")
            .finish_non_exhaustive()
    }
}

/// Rejects a key that could not be sent in a header, which would otherwise
/// surface as a confusing network error. Copied keys sometimes carry an
/// invisible character, such as a byte order mark.
fn check_key(key: &str) -> Result<(), Error> {
    if key.is_empty() {
        return Err(Error::Auth("the API key is empty".to_owned()));
    }
    match key.chars().find(|c| !c.is_ascii_graphic()) {
        Some(c) => Err(Error::Auth(format!(
            "the API key contains the character {}, which a key cannot hold; \
             check for an invisible character copied with it",
            c.escape_unicode()
        ))),
        None => Ok(()),
    }
}

fn classify(response: Response) -> Result<String, EndpointError> {
    match response.status {
        200..=299 => Ok(response.body),
        401 => Err(EndpointError::Auth(
            "ollama.com rejected the API key (HTTP 401)".to_owned(),
        )),
        403 => Err(EndpointError::Auth(match server_message(&response.body) {
            Some(message) => format!("ollama.com denied access (HTTP 403): {message}"),
            None => "ollama.com denied access (HTTP 403): the account may be suspended".to_owned(),
        })),
        429 => Err(EndpointError::RateLimited(response.retry_after)),
        status => Err(EndpointError::Http {
            status,
            message: server_message(&response.body),
        }),
    }
}

/// The `error` string Ollama puts in error responses, shortened.
fn server_message(body: &str) -> Option<String> {
    #[derive(serde::Deserialize)]
    struct ErrorBody {
        error: String,
    }
    let message = serde_json::from_str::<ErrorBody>(body).ok()?.error;
    let message = message.trim();
    (!message.is_empty()).then(|| message.chars().take(200).collect())
}

#[derive(Debug, Default)]
struct PlanCache {
    entry: Option<(Instant, Result<String, String>)>,
}

impl PlanCache {
    fn get(&self, clock: Instant) -> Option<Result<String, String>> {
        let (stored_at, result) = self.entry.as_ref()?;
        let ttl = if result.is_ok() {
            PLAN_TTL
        } else {
            PLAN_RETRY_AFTER
        };
        (clock.saturating_duration_since(*stored_at) < ttl).then(|| result.clone())
    }

    fn put(&mut self, clock: Instant, result: Result<String, String>) {
        self.entry = Some((clock, result));
    }
}

#[cfg(test)]
mod tests {
    use std::collections::HashMap;
    use std::sync::Arc;

    use time::macros::datetime;

    use super::*;

    const BALANCE_CURRENT: &str = include_str!("../../../fixtures/api/balance_current.json");
    const BALANCE_LEGACY: &str = include_str!("../../../fixtures/api/balance_legacy.json");
    const USAGE_30D: &str = include_str!("../../../fixtures/api/usage_30d.json");
    const ME: &str = include_str!("../../../fixtures/api/me.json");
    const REPORT_CURRENT: &str = include_str!("../../../fixtures/reports/current.json");
    const REPORT_LEGACY: &str = include_str!("../../../fixtures/reports/legacy.json");

    const NOW: OffsetDateTime = datetime!(2026-01-10 12:00:00.250 UTC);
    const KEY: &str = "test-key";

    #[derive(Clone)]
    enum Reply {
        Status(u16, &'static str),
        RateLimited(Option<u64>),
        Down,
    }

    /// Answers by endpoint path and records every request.
    #[derive(Clone, Default)]
    struct FakeApi {
        replies: Arc<Mutex<HashMap<&'static str, Reply>>>,
        requests: Arc<Mutex<Vec<String>>>,
    }

    impl FakeApi {
        fn with(replies: &[(&'static str, Reply)]) -> Self {
            let fake = Self::default();
            fake.replies.lock().unwrap().extend(replies.iter().cloned());
            fake
        }

        fn set(&self, path: &'static str, reply: Reply) {
            self.replies.lock().unwrap().insert(path, reply);
        }

        fn requests(&self) -> Vec<String> {
            self.requests.lock().unwrap().clone()
        }

        fn client(&self) -> Client {
            Client::with_transport(KEY, Box::new(self.clone()))
        }
    }

    impl Transport for FakeApi {
        fn send(&self, method: Method, url: &str, api_key: &str) -> Result<Response, String> {
            assert_eq!(api_key, KEY);
            let path = url.strip_prefix(BASE_URL).unwrap();
            self.requests
                .lock()
                .unwrap()
                .push(format!("{method} {path}"));
            let endpoint = path.split('?').next().unwrap();
            let reply = self.replies.lock().unwrap().get(endpoint).cloned();
            match reply.unwrap_or_else(|| panic!("unexpected request to {endpoint}")) {
                Reply::Status(status, body) => Ok(Response {
                    status,
                    retry_after: None,
                    body: body.to_owned(),
                }),
                Reply::RateLimited(seconds) => Ok(Response {
                    status: 429,
                    retry_after: seconds.map(Duration::from_secs),
                    body: r#"{"error":"too many requests"}"#.to_owned(),
                }),
                Reply::Down => Err("connection refused".to_owned()),
            }
        }
    }

    fn healthy() -> FakeApi {
        FakeApi::with(&[
            ("/api/balance", Reply::Status(200, BALANCE_CURRENT)),
            ("/api/usage", Reply::Status(200, USAGE_30D)),
            ("/api/me", Reply::Status(200, ME)),
        ])
    }

    fn fetch(client: &Client) -> Result<Report, Error> {
        client.fetch_at(Range::Days30, NOW, Instant::now())
    }

    fn json(report: &Report) -> serde_json::Value {
        serde_json::to_value(report).unwrap()
    }

    fn codes(report: &Report) -> Vec<WarningCode> {
        report.warnings.iter().map(|warning| warning.code).collect()
    }

    #[test]
    fn a_current_plan_matches_the_reference_report() {
        let report = fetch(&healthy().client()).unwrap();
        let expected: serde_json::Value = serde_json::from_str(REPORT_CURRENT).unwrap();
        assert_eq!(json(&report), expected);
    }

    #[test]
    fn a_legacy_plan_matches_the_reference_report() {
        let api = healthy();
        api.set("/api/balance", Reply::Status(200, BALANCE_LEGACY));
        api.set("/api/me", Reply::Status(200, r#"{"Plan":"pro"}"#));
        let report = fetch(&api.client()).unwrap();
        let expected: serde_json::Value = serde_json::from_str(REPORT_LEGACY).unwrap();
        assert_eq!(json(&report), expected);
    }

    #[test]
    fn the_reference_reports_deserialize_back_to_reports() {
        for golden in [REPORT_CURRENT, REPORT_LEGACY] {
            let report: Report = serde_json::from_str(golden).unwrap();
            assert_eq!(
                json(&report),
                serde_json::from_str::<serde_json::Value>(golden).unwrap()
            );
        }
    }

    #[test]
    fn a_fetch_asks_each_endpoint_once_with_the_requested_range() {
        let api = healthy();
        api.client()
            .fetch_at(Range::Hours24, NOW, Instant::now())
            .unwrap();
        assert_eq!(
            api.requests(),
            [
                "GET /api/balance",
                "GET /api/usage?range=24h&group_by=model",
                "POST /api/me",
            ]
        );
    }

    #[test]
    fn the_plan_is_reused_for_a_day() {
        let api = healthy();
        let client = api.client();
        let start = Instant::now();
        client.fetch_at(Range::Days30, NOW, start).unwrap();
        client
            .fetch_at(Range::Days30, NOW, start + Duration::from_hours(23))
            .unwrap();
        assert_eq!(
            api.requests()
                .iter()
                .filter(|r| r.ends_with("/api/me"))
                .count(),
            1
        );

        client
            .fetch_at(Range::Days30, NOW, start + Duration::from_hours(24))
            .unwrap();
        assert_eq!(
            api.requests()
                .iter()
                .filter(|r| r.ends_with("/api/me"))
                .count(),
            2
        );
    }

    #[test]
    fn a_failed_plan_is_retried_after_an_hour() {
        let api = healthy();
        api.set("/api/me", Reply::Status(404, "{}"));
        let client = api.client();
        let start = Instant::now();
        let report = client.fetch_at(Range::Days30, NOW, start).unwrap();
        assert_eq!(report.plan, None);
        assert_eq!(codes(&report), [WarningCode::PlanUnavailable]);
        assert!(!report.is_partial());

        api.set("/api/me", Reply::Status(200, ME));
        let later = client
            .fetch_at(Range::Days30, NOW, start + Duration::from_mins(59))
            .unwrap();
        assert_eq!(later.plan, None);
        let after_an_hour = client
            .fetch_at(Range::Days30, NOW, start + Duration::from_hours(1))
            .unwrap();
        assert_eq!(after_an_hour.plan.as_deref(), Some("free"));
    }

    #[test]
    fn a_key_that_cannot_be_sent_is_refused_before_any_request() {
        for key in ["\u{feff}test-key", "test key", "test-key\n", ""] {
            let api = healthy();
            let client = Client::with_transport(key, Box::new(api.clone()));
            let error = client
                .fetch_at(Range::Days30, NOW, Instant::now())
                .unwrap_err();
            assert!(matches!(error, Error::Auth(_)), "{key:?}: {error:?}");
            assert_eq!(api.requests(), Vec::<String>::new(), "{key:?}");
        }
    }

    #[test]
    fn the_refusal_names_the_character_but_not_the_key() {
        let message = check_key("\u{feff}secret").unwrap_err().to_string();
        assert!(message.contains(r"\u{feff}"), "{message}");
        assert!(!message.contains("secret"), "{message}");
    }

    #[test]
    fn a_rejected_key_stops_at_the_first_request() {
        let api = healthy();
        api.set("/api/balance", Reply::Status(401, ""));
        let error = fetch(&api.client()).unwrap_err();
        assert!(matches!(error, Error::Auth(_)));
        assert_eq!(api.requests(), ["GET /api/balance"]);
    }

    #[test]
    fn a_suspended_account_is_an_auth_error_with_the_server_message() {
        let api = healthy();
        api.set(
            "/api/balance",
            Reply::Status(403, r#"{"error":"account suspended"}"#),
        );
        assert_eq!(
            fetch(&api.client()).unwrap_err(),
            Error::Auth("ollama.com denied access (HTTP 403): account suspended".to_owned())
        );
    }

    #[test]
    fn a_key_rejected_by_usage_is_still_an_auth_error() {
        let api = healthy();
        api.set("/api/usage", Reply::Status(401, ""));
        assert!(matches!(fetch(&api.client()), Err(Error::Auth(_))));
    }

    #[test]
    fn a_rate_limited_balance_stops_everything() {
        let api = healthy();
        api.set("/api/balance", Reply::RateLimited(Some(30)));
        assert_eq!(
            fetch(&api.client()).unwrap_err(),
            Error::RateLimited {
                retry_after: Some(Duration::from_secs(30))
            }
        );
        assert_eq!(api.requests(), ["GET /api/balance"]);
    }

    #[test]
    fn a_rate_limited_usage_gives_a_partial_report_without_asking_for_the_plan() {
        let api = healthy();
        api.set("/api/usage", Reply::RateLimited(Some(30)));
        let report = fetch(&api.client()).unwrap();
        assert!(report.is_partial());
        assert_eq!(report.usage, None);
        assert!(report.windows.monthly.is_some());
        assert_eq!(
            codes(&report),
            [WarningCode::UsageUnavailable, WarningCode::PlanUnavailable]
        );
        assert_eq!(
            report.warnings[0].message,
            "/api/usage: rate-limited, retry in 30 s"
        );
        assert_eq!(api.requests().len(), 2);
    }

    #[test]
    fn a_failed_balance_still_reports_the_usage() {
        let api = healthy();
        api.set(
            "/api/balance",
            Reply::Status(503, r#"{"error":"temporarily unavailable"}"#),
        );
        let report = fetch(&api.client()).unwrap();
        assert!(report.is_partial());
        assert_eq!(report.windows, Windows::default());
        assert_eq!(report.credits, None);
        assert!(report.usage.is_some());
        assert_eq!(report.plan.as_deref(), Some("free"));
        assert_eq!(
            report.warnings[0].message,
            "/api/balance: HTTP 503: temporarily unavailable"
        );
    }

    #[test]
    fn both_endpoints_unreachable_is_a_network_error() {
        let api = healthy();
        api.set("/api/balance", Reply::Down);
        api.set("/api/usage", Reply::Down);
        assert_eq!(
            fetch(&api.client()).unwrap_err(),
            Error::Network("connection refused".to_owned())
        );
        assert_eq!(api.requests().len(), 2);
    }

    #[test]
    fn both_endpoints_failing_differently_is_an_api_error() {
        let api = healthy();
        api.set("/api/balance", Reply::Status(500, ""));
        api.set("/api/usage", Reply::Status(200, "not json"));
        assert!(matches!(fetch(&api.client()), Err(Error::Api(_))));
    }

    #[test]
    fn the_fetch_time_is_kept_to_the_second() {
        let report = fetch(&healthy().client()).unwrap();
        assert_eq!(report.fetched_at, datetime!(2026-01-10 12:00 UTC));
    }

    #[test]
    fn the_debug_output_never_shows_the_key() {
        let debug = format!("{:?}", Client::new("secret-key"));
        assert!(!debug.contains("secret-key"), "{debug}");
    }

    #[test]
    fn long_server_messages_are_shortened() {
        let body = format!(r#"{{"error":"{}"}}"#, "x".repeat(500));
        assert_eq!(server_message(&body).unwrap().len(), 200);
        assert_eq!(server_message("<html>"), None);
    }
}
