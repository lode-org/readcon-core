//! Distinct CON frames. The seed matches ``bench/h2h/frames_guard.py``.

pub fn distinct_frames(text: &str, n: usize) -> String {
    let one = if text.ends_with('\n') {
        text.to_string()
    } else {
        format!("{text}\n")
    };
    let mut out = String::with_capacity(one.len().saturating_mul(n));
    for frame in 0..n {
        out.push_str(&perturb_frame(&one, frame));
    }
    out
}

fn perturb_frame(text: &str, frame: usize) -> String {
    let mut atom = 0usize;
    let mut out = String::with_capacity(text.len());
    for line in text.split_inclusive('\n') {
        if let Some(rewritten) = perturb_line(line, frame, atom) {
            out.push_str(&rewritten);
            atom += 1;
        } else {
            out.push_str(line);
        }
    }
    out
}

fn perturb_line(line: &str, frame: usize, atom: usize) -> Option<String> {
    let newline = line.ends_with('\n');
    let body = line.trim_end_matches('\n');
    let parts: Vec<&str> = body.split_whitespace().collect();
    if parts.len() < 5 {
        return None;
    }
    let x: f64 = parts[0].parse().ok()?;
    let _: f64 = parts[1].parse().ok()?;
    let _: f64 = parts[2].parse().ok()?;
    let _: i64 = parts[3].parse().ok()?;
    let _: i64 = parts[4].parse().ok()?;
    let nudge = ((1 + (frame + 1) * 1_000_003 + atom * 17) % 997) as f64 * 1e-6;
    let mut owned: Vec<String> = parts.iter().map(|part| (*part).to_string()).collect();
    owned[0] = format!("{:.8}", x + nudge);
    let mut joined = owned.join(" ");
    if newline {
        joined.push('\n');
    }
    Some(joined)
}
