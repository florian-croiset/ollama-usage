//! The `ollama-usage` command. Its behaviour is documented in the README; this
//! crate is not meant to be used as a library.

mod args;
mod config;
mod outcome;
mod render;

use std::ffi::OsString;
use std::process::ExitCode;

use anstream::{eprintln, print, println};
use clap::Parser;
use clap::error::ErrorKind;
use ollama_usage::{Client, Error, Report};
use owo_colors::OwoColorize;
use time::OffsetDateTime;

use crate::args::Args;
use crate::outcome::Outcome;

const KEYS_URL: &str = "https://ollama.com/settings/keys";

/// Runs the command with the process arguments.
pub fn main() -> ExitCode {
    ExitCode::from(run(std::env::args_os()))
}

/// Runs the command with `args`, the first being the program name, and returns
/// its exit code. Used by the binary and by the Python package's entry point.
pub fn run<I, T>(args: I) -> u8
where
    I: IntoIterator<Item = T>,
    T: Into<OsString> + Clone,
{
    let args = match Args::try_parse_from(args) {
        Ok(args) => args,
        Err(error) => {
            let shown_on_request = matches!(
                error.kind(),
                ErrorKind::DisplayHelp | ErrorKind::DisplayVersion
            );
            // Nothing useful can be done if the terminal is gone.
            let _ = error.print();
            let outcome = if shown_on_request {
                Outcome::Ok
            } else {
                Outcome::Usage
            };
            return outcome as u8;
        }
    };
    configure_colors();
    if args.debug {
        // Already installed when the Python entry point runs twice in a process.
        let _ = env_logger::Builder::new()
            .filter_module("ollama_usage", log::LevelFilter::Debug)
            .format_timestamp(None)
            .try_init();
    }
    execute(&args) as u8
}

fn execute(args: &Args) -> Outcome {
    let api_key = match api_key(args) {
        Ok(Some(key)) => key,
        Ok(None) => {
            if !args.quiet {
                print_error("no API key");
                eprintln!(
                    "  Create one at {KEYS_URL}, then set OLLAMA_API_KEY, pass --api-key, or add \
                     `api_key = \"…\"` to {}.",
                    config::describe_default_path()
                );
            }
            return Outcome::NoUsableKey;
        }
        Err(message) => {
            if !args.quiet {
                print_error(&format!("invalid configuration: {message}"));
            }
            return Outcome::Usage;
        }
    };

    match Client::new(api_key).fetch(args.range) {
        Ok(report) => {
            if !args.quiet {
                show(&report, args.json);
                if let Some(threshold) = args.alert {
                    for (kind, used_pct) in outcome::reached(&report, threshold) {
                        eprintln!(
                            "{} {kind} usage at {used_pct:.1}%, threshold {threshold}%",
                            "alert:".red().bold()
                        );
                    }
                }
            }
            Outcome::of(&report, args.alert)
        }
        Err(error) => {
            if !args.quiet {
                print_error(&error.to_string());
                if matches!(error, Error::Auth(_)) {
                    eprintln!("  Check the key at {KEYS_URL}.");
                }
            }
            Outcome::of_error(&error)
        }
    }
}

/// The key from `--api-key` or `OLLAMA_API_KEY`, else from the configuration
/// file, which is only read when it is needed.
fn api_key(args: &Args) -> Result<Option<String>, String> {
    if let Some(key) = non_empty(args.api_key.as_deref()) {
        return Ok(Some(key));
    }
    let config = config::load(args.config.as_deref())?;
    Ok(non_empty(config.api_key.as_deref()))
}

fn non_empty(key: Option<&str>) -> Option<String> {
    key.map(str::trim)
        .filter(|key| !key.is_empty())
        .map(str::to_owned)
}

fn show(report: &Report, json: bool) {
    if json {
        match serde_json::to_string_pretty(report) {
            Ok(text) => println!("{text}"),
            Err(error) => print_error(&format!("could not encode the report: {error}")),
        }
        return;
    }
    print!("{}", render::text(report, OffsetDateTime::now_utc()));
    for warning in &report.warnings {
        eprintln!("{} {}", "warning:".yellow().bold(), warning.message);
    }
}

fn print_error(message: &str) {
    eprintln!("{} {message}", "error:".red().bold());
}

/// Honours `NO_COLOR` and terminal detection through anstream, and adds
/// `FORCE_COLOR`, which anstream does not read.
fn configure_colors() {
    let set = |name| std::env::var_os(name).is_some_and(|value| !value.is_empty());
    if set("FORCE_COLOR") && !set("NO_COLOR") {
        anstream::ColorChoice::Always.write_global();
    }
}
