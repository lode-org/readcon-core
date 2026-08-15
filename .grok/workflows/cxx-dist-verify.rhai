let meta = #{
    name: "cxx-dist-verify",
    description: "Verify CMake FetchContent, Meson wrap, and pkg-config never require cbindgen",
    phases: [
        #{ title: "Gate", detail: "structural no-cbindgen checks" },
        #{ title: "Verify", detail: "adversarial review of CMake and Meson" },
    ],
};

let findings_schema = #{
    "type": "object", "required": ["findings"],
    "properties": #{
        "findings": #{ "type": "array", "maxItems": 8, "items": #{
            "type": "object", "required": ["file", "issue"],
            "properties": #{
                "file": #{ "type": "string" },
                "issue": #{ "type": "string" },
            },
        }},
    },
};

let repo = if args == () { () } else { args.repo };
if repo == () { pause("verification", "Pass args.repo — readcon-core or readcon-db checkout path."); }

phase("Gate");
let gate = agent(
    "Read " + repo + "/scripts/check-cxx-dist.sh, CMakeLists.txt, meson.build, cmake/*.pc.in, packaging/wrapdb/. Use read_file and grep. Confirm cbindgen is not required at consume time, pkg-config filebase matches the project name, and FetchContent/wrap targets exist. Report at most 8 {file, issue} findings; empty list only after you have read the files.",
    #{ label: "gate", capability_mode: "read-only", output_schema: findings_schema },
);

phase("Verify");
let jobs = [];
jobs.push(#{
    prompt: "Adversarially verify that " + repo + "/CMakeLists.txt never requires cbindgen or Corrosion. Use grep and read_file. Set findings empty only after inspecting the file.",
    label: "verify-cmake",
    capability_mode: "read-only",
    output_schema: findings_schema,
});
jobs.push(#{
    prompt: "Adversarially verify that " + repo + "/meson.build generates a standard .pc (filebase equals the project, no meson- prefix, override_dependency present) and does not find_program cbindgen. Use grep and read_file.",
    label: "verify-meson",
    capability_mode: "read-only",
    output_schema: findings_schema,
});
let results = parallel(jobs);

let all = [];
if gate != () && gate.success && gate.output.findings != () {
    for f in gate.output.findings { all.push(f); }
}
for r in results {
    if r != () && r.success && r.output.findings != () {
        for f in r.output.findings { all.push(f); }
    }
}
complete(#{ summary: all.len().to_string() + " findings", findings: all });
