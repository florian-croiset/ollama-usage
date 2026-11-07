//! Read your [Ollama Cloud](https://ollama.com) quota from the official API.
//!
//! One [`Client::fetch`] queries
//! [`/api/balance`](https://docs.ollama.com/api/balance) for the quota windows and
//! credits, [`/api/usage`](https://docs.ollama.com/api/cloud-usage) for requests,
//! cost and tokens per model, and the undocumented `/api/me` for the plan name.
//! The result is a [`Report`] whose JSON form follows the versioned schema
//! [`SCHEMA_VERSION`].
//!
//! ```no_run
//! use ollama_usage::{Client, Range};
//!
//! let client = Client::new(std::env::var("OLLAMA_API_KEY")?);
//! let report = client.fetch(Range::Days30)?;
//! if let Some(monthly) = &report.windows.monthly {
//!     println!("{:.1}% of the monthly allowance used", monthly.used_pct);
//! }
//! # Ok::<(), Box<dyn std::error::Error>>(())
//! ```
//!
//! A fetch fails only when the key is rejected, when ollama.com rate-limits it, or
//! when both documented endpoints fail. If only one of them answers, the report is
//! partial: the missing part is `None` and [`Report::warnings`] says why.

#![warn(missing_docs)]

mod client;
mod error;
mod http;
mod parse;
mod report;

pub use client::{Client, DEFAULT_TIMEOUT};
pub use error::Error;
pub use report::{
    Credits, IncludedCredits, Metrics, ModelUsage, OtherUsage, ParseRangeError, Range, Report,
    SCHEMA_VERSION, Usage, Warning, WarningCode, Window, WindowKind, Windows,
};
