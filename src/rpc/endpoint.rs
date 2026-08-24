//! RPC listen/connect targets. Cap'n is the encoding; this is the byte pipe.
//!
//! - `host:port` and `[ipv6]:port` are TCP.
//! - `unix:/abs/path`, `unix://abs/path`, or a path beginning with `/` is
//!   a Unix domain socket (same-node HPC default).
//!
//! UCX/libfabric/ADIOS are not transports in this crate. They are optional
//! later adapters if a campaign consumer exists.

use std::path::PathBuf;

/// Where the Cap'n two-party vat binds or connects.
#[derive(Debug, Clone, PartialEq, Eq)]
pub enum Endpoint {
    Tcp(String),
    #[cfg(unix)]
    Unix(PathBuf),
}

impl Endpoint {
    /// Parse a listen/connect spec.
    pub fn parse(spec: &str) -> Result<Self, String> {
        let s = spec.trim();
        if s.is_empty() {
            return Err("empty RPC endpoint".into());
        }
        if let Some(rest) = s.strip_prefix("unix:") {
            let path = rest.strip_prefix("//").unwrap_or(rest);
            return unix_path(path);
        }
        if s.starts_with('/') {
            return unix_path(s);
        }
        Ok(Endpoint::Tcp(s.to_string()))
    }
}

#[cfg(unix)]
fn unix_path(path: &str) -> Result<Endpoint, String> {
    if path.is_empty() {
        return Err("unix endpoint missing path".into());
    }
    Ok(Endpoint::Unix(PathBuf::from(path)))
}

#[cfg(not(unix))]
fn unix_path(_path: &str) -> Result<Endpoint, String> {
    Err("unix RPC endpoints require a Unix host".into())
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn parses_tcp_host_port() {
        assert_eq!(
            Endpoint::parse("127.0.0.1:9876").unwrap(),
            Endpoint::Tcp("127.0.0.1:9876".into())
        );
    }

    #[test]
    fn parses_tcp_ipv6() {
        assert_eq!(
            Endpoint::parse("[::1]:9876").unwrap(),
            Endpoint::Tcp("[::1]:9876".into())
        );
    }

    #[cfg(unix)]
    #[test]
    fn parses_unix_prefix_and_absolute_path() {
        assert_eq!(
            Endpoint::parse("unix:/tmp/readcon.sock").unwrap(),
            Endpoint::Unix(PathBuf::from("/tmp/readcon.sock"))
        );
        assert_eq!(
            Endpoint::parse("unix:///var/run/readcon.sock").unwrap(),
            Endpoint::Unix(PathBuf::from("/var/run/readcon.sock"))
        );
        assert_eq!(
            Endpoint::parse("/tmp/readcon.sock").unwrap(),
            Endpoint::Unix(PathBuf::from("/tmp/readcon.sock"))
        );
    }

    #[test]
    fn rejects_empty() {
        assert!(Endpoint::parse("").is_err());
        assert!(Endpoint::parse("   ").is_err());
    }

    #[cfg(unix)]
    #[test]
    fn rejects_unix_without_path() {
        assert!(Endpoint::parse("unix:").is_err());
    }
}
