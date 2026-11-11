//! CPU model string used when a bench records one.
//!
//! The value is the `model name` line from `/proc/cpuinfo`, or `unknown`.
//! Trademark marks are stripped and whitespace is collapsed, the same rule
//! as `benches/cpu_model.py`. A name that contains `Xeon` is
//! `Intel Xeon Processor`.

use std::fs;

/// Plain processor name, matching `normalize_cpu` in `benches/cpu_model.py`.
///
/// `(R)`, `(TM)`, and `®` are removed and whitespace is collapsed. A name
/// that contains `Xeon` is `Intel Xeon Processor`.
fn normalize_cpu(raw: &str) -> String {
    let cleaned = raw.replace("(R)", "").replace("(TM)", "").replace('®', "");
    let cleaned = cleaned.split_whitespace().collect::<Vec<_>>().join(" ");
    if cleaned.contains("Xeon") {
        "Intel Xeon Processor".to_string()
    } else if cleaned.is_empty() {
        "unknown".to_string()
    } else {
        cleaned
    }
}

/// CPU model from `/proc/cpuinfo`, or `unknown` when that line is absent.
pub fn cpu_model() -> String {
    match fs::read_to_string("/proc/cpuinfo") {
        Ok(text) => cpu_model_from_cpuinfo(&text),
        Err(_) => "unknown".to_string(),
    }
}

fn cpu_model_from_cpuinfo(text: &str) -> String {
    for line in text.lines() {
        if line.to_ascii_lowercase().starts_with("model name") {
            if let Some((_, value)) = line.split_once(':') {
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
    use super::{cpu_model, cpu_model_from_cpuinfo};
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

    /// Marked and unmarked vendor strings share one label. The strings are
    /// fixtures, so the result does not depend on the host CPU.
    #[test]
    fn marked_and_unmarked_vendor_strings_share_one_label() {
        let marked_xeon = "\
processor\t: 0
model name\t: Intel(R) Xeon(R) Processor
";
        let plain_xeon = "\
processor\t: 0
model name\t: Intel Xeon Processor
";
        assert_eq!(cpu_model_from_cpuinfo(marked_xeon), "Intel Xeon Processor");
        assert_eq!(
            cpu_model_from_cpuinfo(marked_xeon),
            cpu_model_from_cpuinfo(plain_xeon)
        );

        let marked_sku = "model name\t: Intel(R) Xeon(R) Platinum 8488C CPU @ 2.40GHz\n";
        let plain_sku = "model name\t: Intel Xeon Platinum 8488C CPU @ 2.40GHz\n";
        assert_eq!(cpu_model_from_cpuinfo(marked_sku), "Intel Xeon Processor");
        assert_eq!(
            cpu_model_from_cpuinfo(marked_sku),
            cpu_model_from_cpuinfo(plain_sku)
        );

        let spaced = "model name\t:   Intel(R)   Xeon(R)    Processor  \n";
        assert_eq!(cpu_model_from_cpuinfo(spaced), "Intel Xeon Processor");

        let marked_core = "model name\t: Intel(R) Core(TM) i7-8700 CPU @ 3.20GHz\n";
        let plain_core = "model name\t: Intel Core i7-8700 CPU @ 3.20GHz\n";
        assert_eq!(
            cpu_model_from_cpuinfo(marked_core),
            "Intel Core i7-8700 CPU @ 3.20GHz"
        );
        assert_eq!(
            cpu_model_from_cpuinfo(marked_core),
            cpu_model_from_cpuinfo(plain_core)
        );

        let registered = "model name\t: Intel® Core® i5-8400 CPU @ 2.80GHz\n";
        let plain_registered = "model name\t: Intel Core i5-8400 CPU @ 2.80GHz\n";
        assert_eq!(
            cpu_model_from_cpuinfo(registered),
            cpu_model_from_cpuinfo(plain_registered)
        );
        assert_eq!(
            cpu_model_from_cpuinfo(plain_registered),
            "Intel Core i5-8400 CPU @ 2.80GHz"
        );

        let amd = "model name\t: AMD EPYC 7763 64-Core Processor\n";
        assert_eq!(
            cpu_model_from_cpuinfo(amd),
            "AMD EPYC 7763 64-Core Processor"
        );
    }
}
