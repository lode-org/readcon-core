//! CPU model string used when a bench records one.
//!
//! The value is the `model name` line from `/proc/cpuinfo`, or `unknown`.

use std::fs;

/// CPU model from `/proc/cpuinfo`, or `unknown` when that line is absent.
pub fn cpu_model() -> String {
    if let Ok(text) = fs::read_to_string("/proc/cpuinfo") {
        for line in text.lines() {
            if line.to_ascii_lowercase().starts_with("model name") {
                if let Some((_, value)) = line.split_once(':') {
                    let value = value.trim();
                    if !value.is_empty() {
                        return value.to_string();
                    }
                }
            }
        }
    }
    "unknown".to_string()
}

#[cfg(test)]
mod tests {
    use super::cpu_model;
    use std::fs;

    #[test]
    fn cpu_model_value() {
        println!("CPU_MODEL={}", cpu_model());
    }

    #[test]
    fn cpu_model_is_not_a_hostname_token() {
        let cpu = cpu_model();
        assert!(!cpu.is_empty());
        match fs::read_to_string("/etc/hostname") {
            Ok(text) => {
                let node = text.trim();
                if !node.is_empty() {
                    assert!(cpu.split('-').all(|token| token != node));
                }
            }
            Err(err) if err.kind() == std::io::ErrorKind::NotFound => {}
            Err(err) => panic!("reading /etc/hostname failed: {err}"),
        }
    }
}
