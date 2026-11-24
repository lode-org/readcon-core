//! The change log of docs/orgmode/spec.org cites the clause that states each change.

const SPEC: &str = include_str!("../docs/orgmode/spec.org");

fn clause_text(id: &str) -> &'static str {
    let head = format!("- {id} :: ");
    SPEC.lines()
        .find(|line| line.starts_with(&head))
        .unwrap_or_else(|| panic!("no clause {id}"))
}

fn changelog_line(phrase: &str) -> &'static str {
    let start = SPEC.find("Changes in 4.0.0:").expect("change log");
    let mut found = SPEC[start..].lines().filter(|line| line.contains(phrase));
    let line = found
        .next()
        .unwrap_or_else(|| panic!("no change-log line with {phrase:?}"));
    assert!(found.next().is_none(), "{phrase:?} is ambiguous");
    line
}

#[test]
fn changelog_cites_the_clause_that_states_each_change() {
    for (phrase, id, wording) in [
        (
            "unsigned 64-bit integer (=",
            "CON-line2.22",
            "unsigned 64-bit integer",
        ),
        (
            "must not repeat a name",
            "CON-line2.23",
            "MUST NOT repeat a name",
        ),
        (
            "the schema is informative",
            "CON-line2.24",
            "schema MUST be informative",
        ),
        (
            "no numeric meaning here",
            "CON-line2.21",
            "MUST NOT reject the frame",
        ),
        ("A reserved key remains", "CON-line2.19", "A reserved key"),
        (
            "not part of that reading",
            "CON-line2.16",
            "missing =con_spec_patch=",
        ),
        (
            "not part of that reading",
            "CON-line2.10",
            "missing =con_spec_minor=",
        ),
        (
            "is read by =CON-line2.10=",
            "CON-line2.16",
            "missing =con_spec_patch=",
        ),
    ] {
        let line = changelog_line(phrase);
        assert!(
            line.contains(&format!("={id}=")),
            "{phrase:?} should cite {id}: {line}"
        );
        assert!(
            clause_text(id).contains(wording),
            "{id} does not state {wording:?}"
        );
    }
}
