//! Runs the binary on the paths that need no network.

use std::path::PathBuf;
use std::process::{Command, Output};

fn run(arguments: &[&str]) -> Output {
    Command::new(env!("CARGO_BIN_EXE_ollama-usage"))
        .args(arguments)
        .env_remove("OLLAMA_API_KEY")
        .env("NO_COLOR", "1")
        .output()
        .expect("the binary runs")
}

/// A configuration file that is removed when dropped.
struct TempConfig(PathBuf);

impl TempConfig {
    fn new(name: &str, contents: &str) -> Self {
        let path = std::env::temp_dir().join(format!(
            "ollama-usage-test-{}-{name}.toml",
            std::process::id()
        ));
        std::fs::write(&path, contents).expect("the temporary file is written");
        Self(path)
    }

    fn path(&self) -> &str {
        self.0.to_str().expect("the temporary path is UTF-8")
    }
}

impl Drop for TempConfig {
    fn drop(&mut self) {
        let _ = std::fs::remove_file(&self.0);
    }
}

fn stderr(output: &Output) -> String {
    String::from_utf8_lossy(&output.stderr).into_owned()
}

#[test]
fn without_a_key_it_exits_with_4_and_explains_where_to_put_one() {
    let config = TempConfig::new("empty", "");
    let output = run(&["--json", "--config", config.path()]);
    assert_eq!(output.status.code(), Some(4));
    assert_eq!(
        String::from_utf8_lossy(&output.stdout),
        "",
        "stdout must stay parseable"
    );
    let stderr = stderr(&output);
    assert!(stderr.contains("no API key"), "{stderr}");
    assert!(stderr.contains("OLLAMA_API_KEY"), "{stderr}");
}

#[test]
fn quiet_prints_nothing_at_all() {
    let config = TempConfig::new("quiet", "");
    let output = run(&["--quiet", "--config", config.path()]);
    assert_eq!(output.status.code(), Some(4));
    assert_eq!(String::from_utf8_lossy(&output.stdout), "");
    assert_eq!(stderr(&output), "");
}

#[test]
fn a_malformed_configuration_exits_with_64() {
    let config = TempConfig::new("malformed", "api_key = ");
    let output = run(&["--config", config.path()]);
    assert_eq!(output.status.code(), Some(64));
    assert!(stderr(&output).contains("invalid configuration"));
}

#[test]
fn a_missing_explicit_configuration_exits_with_64() {
    let output = run(&["--config", "does-not-exist.toml"]);
    assert_eq!(output.status.code(), Some(64));
}

#[test]
fn invalid_arguments_exit_with_64() {
    for arguments in [
        &["--range", "1y"][..],
        &["--alert", "150"],
        &["--json", "--quiet"],
        &["--no-such-flag"],
    ] {
        assert_eq!(run(arguments).status.code(), Some(64), "{arguments:?}");
    }
}

#[test]
fn help_lists_the_exit_codes_and_exits_with_0() {
    let output = run(&["--help"]);
    assert_eq!(output.status.code(), Some(0));
    let help = String::from_utf8_lossy(&output.stdout);
    assert!(help.contains("Exit codes:"), "{help}");
    assert!(help.contains("Usage: ollama-usage [OPTIONS]"), "{help}");
    assert!(help.contains("possible values: 24h,"), "{help}");
}

#[test]
fn version_exits_with_0() {
    let output = run(&["--version"]);
    assert_eq!(output.status.code(), Some(0));
    assert!(String::from_utf8_lossy(&output.stdout).starts_with("ollama-usage "));
}
