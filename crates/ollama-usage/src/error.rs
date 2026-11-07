use std::fmt;
use std::time::Duration;

/// Why [`Client::fetch`](crate::Client::fetch) returned no report at all.
#[derive(Debug, Clone, PartialEq, Eq)]
#[non_exhaustive]
pub enum Error {
    /// ollama.com rejected the API key, or the account is suspended.
    Auth(String),
    /// ollama.com rate-limited the key. The API allows 10 requests per minute per
    /// user, shared by every key and device.
    RateLimited {
        /// How long ollama.com asked to wait, when it said.
        retry_after: Option<Duration>,
    },
    /// Neither endpoint could be reached.
    Network(String),
    /// Both endpoints answered with an error or with a response that could not be
    /// read.
    Api(String),
}

impl fmt::Display for Error {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        match self {
            Self::Auth(message) | Self::Api(message) => f.write_str(message),
            Self::RateLimited {
                retry_after: Some(wait),
            } => write!(
                f,
                "rate-limited by ollama.com, retry in {} s",
                wait.as_secs()
            ),
            Self::RateLimited { retry_after: None } => f.write_str("rate-limited by ollama.com"),
            Self::Network(message) => write!(f, "could not reach ollama.com: {message}"),
        }
    }
}

impl std::error::Error for Error {}

/// Why a single endpoint gave nothing usable.
#[derive(Debug, Clone, PartialEq, Eq)]
pub(crate) enum EndpointError {
    Auth(String),
    RateLimited(Option<Duration>),
    Network(String),
    Http {
        status: u16,
        message: Option<String>,
    },
    Parse(String),
}

impl EndpointError {
    /// Merges the failures of `/api/balance` and `/api/usage` into the error
    /// reported for the whole fetch. Authentication failures never reach this
    /// point: they abort the fetch as soon as they happen.
    pub(crate) fn combine(balance: Self, usage: Self) -> Error {
        match (balance, usage) {
            (Self::RateLimited(retry_after), _) | (_, Self::RateLimited(retry_after)) => {
                Error::RateLimited { retry_after }
            }
            (Self::Network(message), Self::Network(_)) => Error::Network(message),
            (balance, usage) => Error::Api(format!("/api/balance: {balance}; /api/usage: {usage}")),
        }
    }
}

impl fmt::Display for EndpointError {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        match self {
            Self::Auth(message) => f.write_str(message),
            Self::RateLimited(Some(wait)) => {
                write!(f, "rate-limited, retry in {} s", wait.as_secs())
            }
            Self::RateLimited(None) => f.write_str("rate-limited"),
            Self::Network(message) => write!(f, "unreachable: {message}"),
            Self::Http {
                status,
                message: Some(message),
            } => write!(f, "HTTP {status}: {message}"),
            Self::Http {
                status,
                message: None,
            } => write!(f, "HTTP {status}"),
            Self::Parse(message) => write!(f, "unexpected response: {message}"),
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn a_rate_limit_on_either_endpoint_wins() {
        let wait = Some(Duration::from_secs(30));
        assert_eq!(
            EndpointError::combine(
                EndpointError::Network("down".into()),
                EndpointError::RateLimited(wait)
            ),
            Error::RateLimited { retry_after: wait }
        );
    }

    #[test]
    fn two_network_failures_stay_a_network_failure() {
        assert_eq!(
            EndpointError::combine(
                EndpointError::Network("timed out".into()),
                EndpointError::Network("refused".into())
            ),
            Error::Network("timed out".into())
        );
    }

    #[test]
    fn mixed_failures_name_both_endpoints() {
        let error = EndpointError::combine(
            EndpointError::Http {
                status: 503,
                message: None,
            },
            EndpointError::Parse("missing field `totals`".into()),
        );
        assert_eq!(
            error.to_string(),
            "/api/balance: HTTP 503; /api/usage: unexpected response: missing field `totals`"
        );
    }

    #[test]
    fn the_wait_is_shown_in_seconds() {
        let error = Error::RateLimited {
            retry_after: Some(Duration::from_secs(42)),
        };
        assert_eq!(
            error.to_string(),
            "rate-limited by ollama.com, retry in 42 s"
        );
    }
}
