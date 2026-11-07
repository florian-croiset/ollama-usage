use std::path::PathBuf;

use clap::Parser;
use clap::builder::{PossibleValuesParser, TypedValueParser};
use ollama_usage::Range;

/// Show your Ollama Cloud quota, credits and per-model usage.
#[derive(Debug, Parser)]
#[command(name = "ollama-usage", bin_name = "ollama-usage", version, after_help = EXIT_CODES)]
pub(crate) struct Args {
    /// API key. Prefer the environment variable, which stays out of your shell
    /// history.
    #[arg(
        long,
        value_name = "KEY",
        env = "OLLAMA_API_KEY",
        hide_env_values = true
    )]
    pub(crate) api_key: Option<String>,

    /// Period covered by the per-model usage.
    #[arg(
        long,
        value_name = "RANGE",
        default_value = "30d",
        value_parser = PossibleValuesParser::new(Range::ALL.map(Range::as_str))
            .try_map(|text| text.parse::<Range>()),
    )]
    pub(crate) range: Range,

    /// Print the report as JSON.
    #[arg(long, conflicts_with = "quiet")]
    pub(crate) json: bool,

    /// Print nothing: only the exit code tells the outcome.
    #[arg(long, short)]
    pub(crate) quiet: bool,

    /// Exit with code 1 when a quota window is at or above PCT percent, and say
    /// which on stderr.
    #[arg(long, value_name = "PCT", value_parser = percent)]
    pub(crate) alert: Option<f64>,

    /// Read the configuration from PATH instead of the default location.
    #[arg(long, value_name = "PATH")]
    pub(crate) config: Option<PathBuf>,

    /// Log each request to stderr. The key is never logged.
    #[arg(long)]
    pub(crate) debug: bool,
}

const EXIT_CODES: &str = "\
Exit codes:
  0   ok
  1   --alert threshold reached
  2   partial report: /api/balance or /api/usage failed
  3   no report: both failed, or ollama.com rate-limited the key
  4   no API key, or the key was rejected
  64  invalid arguments or configuration";

fn percent(text: &str) -> Result<f64, String> {
    match text.parse::<f64>() {
        Ok(value) if (0.0..=100.0).contains(&value) => Ok(value),
        _ => Err("expected a number from 0 to 100".to_owned()),
    }
}

#[cfg(test)]
mod tests {
    use clap::CommandFactory;

    use super::*;

    fn parse(arguments: &[&str]) -> Result<Args, clap::Error> {
        Args::try_parse_from(std::iter::once("ollama-usage").chain(arguments.iter().copied()))
    }

    #[test]
    fn the_definition_is_consistent() {
        Args::command().debug_assert();
    }

    #[test]
    fn the_range_defaults_to_30_days() {
        assert_eq!(parse(&[]).unwrap().range, Range::Days30);
        assert_eq!(parse(&["--range", "24h"]).unwrap().range, Range::Hours24);
    }

    #[test]
    fn an_unknown_range_is_refused() {
        assert!(parse(&["--range", "1y"]).is_err());
    }

    #[test]
    fn the_alert_threshold_is_a_percentage() {
        assert_eq!(parse(&["--alert", "80"]).unwrap().alert, Some(80.0));
        assert!(parse(&["--alert", "101"]).is_err());
        assert!(parse(&["--alert", "high"]).is_err());
    }

    #[test]
    fn json_and_quiet_are_exclusive() {
        assert!(parse(&["--json", "--quiet"]).is_err());
    }
}
