use std::io::ErrorKind;
use std::path::{Path, PathBuf};

use serde::Deserialize;

/// The configuration file, `config.toml` in the platform's configuration
/// directory.
#[derive(Debug, Default, Deserialize)]
#[serde(deny_unknown_fields)]
pub(crate) struct Config {
    pub(crate) api_key: Option<String>,
}

pub(crate) fn default_path() -> Option<PathBuf> {
    dirs::config_dir().map(|dir| dir.join("ollama-usage").join("config.toml"))
}

pub(crate) fn describe_default_path() -> String {
    default_path().map_or_else(
        || "a file passed with --config".to_owned(),
        |path| path.display().to_string(),
    )
}

/// Reads `explicit`, which must exist, or else the default file if there is one.
pub(crate) fn load(explicit: Option<&Path>) -> Result<Config, String> {
    let (path, required) = match explicit {
        Some(path) => (path.to_path_buf(), true),
        None => match default_path() {
            Some(path) => (path, false),
            None => return Ok(Config::default()),
        },
    };
    match std::fs::read_to_string(&path) {
        Ok(text) => parse(&text).map_err(|error| format!("{}: {error}", path.display())),
        Err(error) if error.kind() == ErrorKind::NotFound && !required => Ok(Config::default()),
        Err(error) => Err(format!("{}: {error}", path.display())),
    }
}

fn parse(text: &str) -> Result<Config, toml::de::Error> {
    toml::from_str(text)
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn the_key_is_read() {
        let config = parse(r#"api_key = "abc""#).unwrap();
        assert_eq!(config.api_key.as_deref(), Some("abc"));
    }

    #[test]
    fn an_empty_file_is_an_empty_configuration() {
        assert_eq!(parse("").unwrap().api_key, None);
    }

    #[test]
    fn a_misspelt_setting_is_refused() {
        let error = parse(r#"apikey = "abc""#).unwrap_err();
        assert!(error.to_string().contains("apikey"), "{error}");
    }

    #[test]
    fn an_explicit_file_must_exist() {
        let error = load(Some(Path::new("does/not/exist.toml"))).unwrap_err();
        assert!(error.contains("exist.toml"), "{error}");
    }
}
