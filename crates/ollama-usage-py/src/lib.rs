//! Native part of the `ollama_cloud_usage` Python package. It hands the report
//! over as schema 1.0 JSON; the typed Python API lives in
//! `python/ollama_cloud_usage`. It also
//! runs the command-line tool for the package's `ollama-usage` entry point.

use std::time::Duration;

use ollama_usage::{Client, Error, Range};
use pyo3::create_exception;
use pyo3::exceptions::{PyException, PyValueError};
use pyo3::prelude::*;

create_exception!(
    _ollama_usage,
    FetchError,
    PyException,
    "A failed fetch. Its arguments are `(kind, message, retry_after)`."
);

/// A client for one API key.
#[pyclass(frozen, name = "Client", module = "ollama_cloud_usage._ollama_usage")]
#[derive(Debug)]
struct PyClient {
    inner: Client,
}

#[pymethods]
impl PyClient {
    #[new]
    fn new(api_key: String, timeout: f64) -> PyResult<Self> {
        let timeout = Duration::try_from_secs_f64(timeout)
            .ok()
            .filter(|timeout| !timeout.is_zero())
            .ok_or_else(|| PyValueError::new_err("timeout must be a positive number of seconds"))?;
        Ok(Self {
            inner: Client::with_timeout(api_key, timeout),
        })
    }

    /// Fetches the report and returns it as JSON. The GIL is released meanwhile.
    fn fetch_json(&self, py: Python<'_>, range: &str) -> PyResult<String> {
        let range: Range = range
            .parse()
            .map_err(|error: ollama_usage::ParseRangeError| {
                PyValueError::new_err(error.to_string())
            })?;
        let report = py
            .detach(|| self.inner.fetch(range))
            .map_err(|error| fetch_error(&error))?;
        serde_json::to_string(&report)
            .map_err(|error| FetchError::new_err(("api", error.to_string(), None::<f64>)))
    }
}

fn fetch_error(error: &Error) -> PyErr {
    let (kind, retry_after) = match error {
        Error::Auth(_) => ("auth", None),
        Error::RateLimited { retry_after } => {
            ("rate_limited", retry_after.map(|wait| wait.as_secs_f64()))
        }
        Error::Network(_) => ("network", None),
        _ => ("api", None),
    };
    FetchError::new_err((kind, error.to_string(), retry_after))
}

/// Runs the `ollama-usage` command with `args`, the first being the program
/// name, and returns its exit code. The GIL is released meanwhile.
#[pyfunction]
fn run_cli(py: Python<'_>, args: Vec<String>) -> u8 {
    py.detach(|| ollama_usage_cli::run(args))
}

#[pymodule]
fn _ollama_usage(module: &Bound<'_, PyModule>) -> PyResult<()> {
    module.add_class::<PyClient>()?;
    module.add_function(wrap_pyfunction!(run_cli, module)?)?;
    module.add("FetchError", module.py().get_type::<FetchError>())?;
    module.add("__version__", env!("CARGO_PKG_VERSION"))?;
    module.add("SCHEMA_VERSION", ollama_usage::SCHEMA_VERSION)?;
    Ok(())
}
