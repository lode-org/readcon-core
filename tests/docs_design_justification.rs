//! Local link and anchor check for the org sources and the README.
//!
//! A `file:` link must resolve. A `::#id` search needs a `CUSTOM_ID`.
//! A `::*Heading` search needs that headline.

use std::fs;
use std::path::{Path, PathBuf};

fn repo() -> PathBuf {
    PathBuf::from(env!("CARGO_MANIFEST_DIR"))
}

fn org_files() -> Vec<PathBuf> {
    let mut out = Vec::new();
    let root = repo().join("docs/orgmode");
    fn walk(dir: &Path, out: &mut Vec<PathBuf>) {
        for entry in fs::read_dir(dir).unwrap() {
            let entry = entry.unwrap();
            let path = entry.path();
            if path.is_dir() {
                walk(&path, out);
            } else if path.extension().and_then(|e| e.to_str()) == Some("org") {
                out.push(path);
            }
        }
    }
    walk(&root, &mut out);
    out.push(repo().join("README.md"));
    out.sort();
    out
}

fn custom_ids(text: &str) -> Vec<String> {
    let mut ids = Vec::new();
    for line in text.lines() {
        let trimmed = line.trim();
        if let Some(rest) = trimmed.strip_prefix(":CUSTOM_ID:") {
            ids.push(rest.trim().to_string());
        }
        if let Some(start) = trimmed.find("<<") {
            if let Some(end) = trimmed[start + 2..].find(">>") {
                ids.push(trimmed[start + 2..start + 2 + end].to_string());
            }
        }
    }
    ids
}

fn headings(text: &str) -> Vec<String> {
    text.lines()
        .filter_map(|line| {
            let trimmed = line.trim();
            let stars = trimmed.chars().take_while(|c| *c == '*').count();
            if stars > 0 && trimmed.as_bytes().get(stars) == Some(&b' ') {
                Some(trimmed[stars + 1..].trim().to_string())
            } else {
                None
            }
        })
        .collect()
}

fn resolve(from: &Path, raw: &str) -> PathBuf {
    let path = Path::new(raw);
    if path.is_absolute() {
        path.to_path_buf()
    } else {
        from.parent().unwrap().join(path)
    }
}

fn check_org_links(path: &Path, text: &str) {
    let bytes = text.as_bytes();
    let mut i = 0;
    while i + 7 < bytes.len() {
        if &bytes[i..i + 7] != b"[[file:" {
            i += 1;
            continue;
        }
        let start = i + 7;
        let Some(rel_end) = text[start..].find("]]") else {
            panic!("{}: unclosed file link at {i}", path.display());
        };
        let mut body = &text[start..start + rel_end];
        if let Some(desc) = body.find("][") {
            body = &body[..desc];
        }
        let (file, search) = body.split_once("::").unwrap_or((body, ""));
        let target = resolve(path, file);
        assert!(
            target.is_file(),
            "{}: missing link target {}",
            path.display(),
            target.display()
        );
        if let Some(id) = search.strip_prefix('#') {
            let dest = fs::read_to_string(&target).unwrap();
            assert!(
                custom_ids(&dest).iter().any(|got| got == id),
                "{}: missing anchor #{id} in {}",
                path.display(),
                target.display()
            );
        } else if let Some(heading) = search.strip_prefix('*') {
            let dest = fs::read_to_string(&target).unwrap();
            assert!(
                headings(&dest).iter().any(|got| got == heading),
                "{}: missing heading {heading} in {}",
                path.display(),
                target.display()
            );
        }
        i = start + rel_end + 2;
    }
}

fn check_markdown_links(path: &Path, text: &str) {
    let mut rest = text;
    while let Some(open) = rest.find("](") {
        rest = &rest[open + 2..];
        let Some(end) = rest.find(')') else { break };
        let link = &rest[..end];
        rest = &rest[end + 1..];
        if link.is_empty()
            || link.starts_with('#')
            || link.starts_with("http://")
            || link.starts_with("https://")
            || link.starts_with("mailto:")
        {
            continue;
        }
        let file = link.split('#').next().unwrap();
        if file.is_empty() {
            continue;
        }
        let target = resolve(path, file);
        assert!(
            target.exists(),
            "{}: missing markdown target {}",
            path.display(),
            target.display()
        );
    }
}

#[test]
fn docs_links_and_anchors_resolve() {
    for path in org_files() {
        let text = fs::read_to_string(&path).unwrap();
        if path.extension().and_then(|e| e.to_str()) == Some("org") {
            check_org_links(&path, &text);
        }
        if path.extension().and_then(|e| e.to_str()) == Some("md") {
            check_markdown_links(&path, &text);
        }
    }
}
