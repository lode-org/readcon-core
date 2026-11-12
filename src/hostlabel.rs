//! CPU model string used when a bench records one.
//!
//! The value is the `model name` line from `/proc/cpuinfo`, written the
//! same way as `benches/cpu_model.py`: trademark marks removed, and any
//! Xeon collapsed to one plain name. Missing input is `unknown`.

use std::fs;

/// Same spelling as `normalize_cpu` in `benches/cpu_model.py`.
pub fn normalize_cpu(raw: &str) -> String {
    let stripped = raw.replace("(R)", "").replace("(TM)", "").replace('®', "");
    let cleaned = stripped.split_whitespace().collect::<Vec<_>>().join(" ");
    if cleaned.contains("Xeon") {
        return "Intel Xeon Processor".to_string();
    }
    if cleaned.is_empty() {
        "unknown".to_string()
    } else {
        cleaned
    }
}

/// CPU model from `/proc/cpuinfo`, or `unknown` when that line is absent.
pub fn cpu_model() -> String {
    if let Ok(text) = fs::read_to_string("/proc/cpuinfo") {
        for line in text.lines() {
            if line.to_ascii_lowercase().starts_with("model name")
                && let Some((_, value)) = line.split_once(':') {
                    let value = value.trim();
                    if !value.is_empty() {
                        return normalize_cpu(value);
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
    fn normalize_cpu_matches_the_python_record_name() {
        assert_eq!(
            super::normalize_cpu("Intel(R) Xeon(R) Processor"),
            "Intel Xeon Processor"
        );
        assert_eq!(
            super::normalize_cpu("Intel(R) Core(TM) i7"),
            "Intel Core i7"
        );
        assert_eq!(super::normalize_cpu("  AMD   EPYC  "), "AMD EPYC");
        assert_eq!(super::normalize_cpu("   "), "unknown");
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
