use std::fmt;
use std::time::{Duration, Instant};

/// Responses are small JSON documents; anything larger is not one of them.
const MAX_BODY_BYTES: u64 = 1024 * 1024;

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub(crate) enum Method {
    Get,
    Post,
}

impl fmt::Display for Method {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        f.write_str(match self {
            Self::Get => "GET",
            Self::Post => "POST",
        })
    }
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub(crate) struct Response {
    pub(crate) status: u16,
    pub(crate) retry_after: Option<Duration>,
    pub(crate) body: String,
}

/// Sends one authenticated request. Abstracted so the client can be tested
/// without a network.
pub(crate) trait Transport: Send + Sync {
    /// Returns the response whatever its status, or why there was none.
    fn send(&self, method: Method, url: &str, api_key: &str) -> Result<Response, String>;
}

#[derive(Debug)]
pub(crate) struct UreqTransport {
    agent: ureq::Agent,
}

impl UreqTransport {
    pub(crate) fn new(timeout: Duration) -> Self {
        let agent = ureq::Agent::config_builder()
            .timeout_global(Some(timeout))
            .user_agent(concat!("ollama-usage/", env!("CARGO_PKG_VERSION")))
            .http_status_as_error(false)
            // A redirect would carry the key to wherever it points.
            .max_redirects(0)
            .max_redirects_will_error(false)
            .build()
            .into();
        Self { agent }
    }
}

impl Transport for UreqTransport {
    fn send(&self, method: Method, url: &str, api_key: &str) -> Result<Response, String> {
        let authorization = format!("Bearer {api_key}");
        let started = Instant::now();
        let result = match method {
            Method::Get => self
                .agent
                .get(url)
                .header("accept", "application/json")
                .header("authorization", &authorization)
                .call(),
            Method::Post => self
                .agent
                .post(url)
                .header("accept", "application/json")
                .header("authorization", &authorization)
                .send_empty(),
        };
        let mut response = result.map_err(|error| match error {
            ureq::Error::Timeout(_) => "timed out".to_owned(),
            other => other.to_string(),
        })?;

        let status = response.status().as_u16();
        let retry_after = response
            .headers()
            .get("retry-after")
            .and_then(|value| value.to_str().ok())
            .and_then(parse_retry_after);
        let body = response
            .body_mut()
            .with_config()
            .limit(MAX_BODY_BYTES)
            .read_to_string()
            .map_err(|error| format!("could not read the response: {error}"))?;

        log::debug!(
            "{method} {url} -> {status} in {} ms",
            started.elapsed().as_millis()
        );
        Ok(Response {
            status,
            retry_after,
            body,
        })
    }
}

/// Reads `Retry-After` in its delay-seconds form, the only one Ollama documents.
fn parse_retry_after(value: &str) -> Option<Duration> {
    value.trim().parse().ok().map(Duration::from_secs)
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn retry_after_is_read_in_seconds() {
        assert_eq!(parse_retry_after(" 30 "), Some(Duration::from_secs(30)));
    }

    #[test]
    fn an_http_date_retry_after_is_ignored() {
        assert_eq!(parse_retry_after("Wed, 21 Oct 2026 07:28:00 GMT"), None);
    }
}
