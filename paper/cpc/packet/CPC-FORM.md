<!-- Written by paper/cpc/packet/make_packet.py from CPC-FORM.md.in; edit the template, not this file -->
# CPC submission form: readcon-core: a versioned geometry checkpoint for resumed saddle searches

Status: Prepared, not submitted.

Every count and quoted text below is written by `make_packet.py` from the sources and the `build_tex.sh` build of the paper, for readcon-core `\readconCargoVersion`. The timing records name commit `5e1430ddf6da5d2b0d4652f47dce889e7895598f`, which is readcon-core 0.17.3 and is not a release tag. The library those records name has digest `3b4d00ae2427`.

## Sources

- [GFA] CPC Guide for Authors: https://www.sciencedirect.com/journal/computer-physics-communications/publish/guide-for-authors (the live page answers the box with a captcha; the text was read from the Wayback snapshot https://web.archive.org/web/20250802150417/https://www.sciencedirect.com/journal/computer-physics-communications/publish/guide-for-authors)
- [TPL] CPiP LaTeX template: https://legacyfileshare.elsevier.com/promis_misc/cpc-cpip-template.tex
- [EM] Editorial Manager: https://www.editorialmanager.com/comphy/ (the page carried the banner "Site under development. Do not use for live manuscript submission." when it was read)
- [EMTEX] Elsevier LaTeX in EM: https://www.elsevier.support/publishing/answer/how-to-submit-a-latex-file-in-editorial-manager and https://www.ariessys.com/wp-content/uploads/EM_PM_LaTeX_Guide.pdf
- [SHARE] Elsevier article sharing: https://www.elsevier.com/about/policies-and-standards/sharing
- [MDATA] CPC Program Library on Mendeley Data: https://data.mendeley.com/journal/00104655

## Requirements and the manuscript

| Item | Requirement | Source | Manuscript and packet |
|---|---|---|---|
| System | Editorial Manager, `editorialmanager.com/comphy` | GFA, TPL, EM | Start from the "Submit your article" button on the journal page and confirm the route there. |
| Article type | CPiP: programs archived in the CPC Program Library on Mendeley Data under an approved licence | GFA | Computer Programs in Physics: the paper has a Program Summary and describes a program. |
| Licence | One of MIT, Apache-2.0, BSD 2/3-clause, GPLv2/3, LGPL, MPL-2.0, CeCILL, CeCILL-B, CC BY 4.0, CC0 1.0, CC BY-NC 3.0 | GFA | MIT, the Program Summary's licensing provision. |
| Program Summary | Immediately after the abstract. Fields: Program title; CPC Library link (Technical Editor); Developer's repository link; Licensing provisions; Programming language; Supplementary material; Nature of problem, Solution method, Additional comments (each in the 50 to 250 word range the guide gives); References | GFA, TPL | All fields, in the CPC order, after the abstract. Word counts: Nature of problem 157, Solution method 199, Additional comments 121. |
| Program files | Compressed archive with source, README (file layout, install, run), sample input and output of one full test run, manual if needed. Upload at "Attach Files". | GFA, TPL | `readcon-core.bundle`, the git bundle that holds the candidate commit `5e1430ddf6da5d2b0d4652f47dce889e7895598f` (readcon-core 0.17.3, not a release tag) with its whole history (`git clone readcon-core.bundle` checks it out), and `patches/`, a patch series that `git am --keep-cr` applies on commit `d0b7d3c7a5a7e7d7a6a963d515e9524c575c09fd` in that clone to give the tree of that commit. The commit descends from `d0b7d3c7a5a7e7d7a6a963d515e9524c575c09fd`, the head of pull request 80 to the main branch after the published release 0.17.3 (tag v0.17.3 at commit `12ca800bc2212c565941e04094cba6b4d99a62e0`). Cargo.toml of this tree is the version `\readconCargoVersion` names. The latest release tag is v0.23.2 at `8c2d9984c40aedfb2e0084fedefaa02e930957f2`. |
| Source format | Editable source, `.tex` for LaTeX. A PDF is not a source file. | GFA | The LaTeX sources of `paper/cpc/src`. |
| EM LaTeX build | No subfolders. `.tex`, `.bbl` and support files as item type Manuscript, images as Figure. Order: `.tex`, bibliography, styles, figures. | EMTEX | `make_em_flat.py` writes the flat set (Packet files below). |
| Abstract | At most 250 words, stands alone, define uncommon abbreviations at first use | GFA | 248 words by `check_manuscript.py`'s count. |
| Keywords | 1 to 7 | GFA | 5: geometry checkpoint; file format specification; saddle search; conformance corpus; nudged elastic band. |
| Highlights | 3 to 5 bullets, each at most 85 characters with spaces, separate editable file with "highlights" in the name | GFA | 5 bullets of 76, 81, 79, 85, 83 characters in `paper/cpc/highlights.txt`, the same text as the highlights of `rg_main.tex`. |
| Graphical abstract | Not mentioned in the CPC guide | GFA | `rg_main.tex` has none; leave the slot empty. |
| Title page | Full postal address of each affiliation with country; corresponding author email on the title page | GFA | TurtleTech ehf., Fornhaga 24, 107 Reykjavík, Iceland; rgoswami@ieee.org. |
| Corresponding author | Full contact details incl. postal address and phone in EM | GFA checklist | The author enters them in EM. |
| Cover letter | Not listed in the guide; EM accepts one | EM | The author's cover letter; it is not part of the supplementary material. |
| Suggested reviewers | Not listed in the guide; EM asks for them | EM | The author enters them in EM. |
| CRediT | Required | GFA | Section "CRediT authorship contribution statement". |
| Competing interests | Statement plus the Elsevier declarations tool `.docx` uploaded at Attach Files | GFA | Section "Declaration of competing interest" declares none; the `.docx` comes from the declarations tool during submission. |
| Funding | Guide asks for disclosure | GFA | Section "Funding" carries the guide's sentence for research without specific funding. |
| Generative AI in writing | Declare in a section before the references if used in writing | GFA | Section "Declaration of generative AI and AI-assisted technologies in the manuscript preparation process", the last section before the references, in Elsevier's form. |
| Data availability | Option C: deposit, cite and link data, plus a data statement at submission | GFA | Section "Data availability" names readcon-core `\readconCargoVersion`. The timing records name commit `5e1430ddf6da5d2b0d4652f47dce889e7895598f` (readcon-core 0.17.3, not a release tag), the digest `3b4d00ae2427` of the library those records measured, and the git bundle `readcon-core.bundle` of the supplementary material, and links https://doi.org/10.5281/zenodo.18753567. |
| References | Numbered, elsarticle-num, software cited with identifier | GFA | elsarticle-num; 72 references in the manuscript and 48 in the supplement; no undefined reference or citation in either pdfTeX log. |
| Tables | Editable, no vertical rules | GFA | 11 tables; no tabular has a vertical rule. |
| Preprint | Sharing a preprint anywhere at any time is allowed, and a preprint is not prior publication | GFA, SHARE | The preprint is on arXiv. |

## Packet files

| File | Use in EM |
|---|---|
| `DIR/em-flat/` from `python3 paper/cpc/scripts/make_em_flat.py --out DIR` (TeX Live 2025) | `rg_main.tex` first, then `rg_main.bbl`, then every other file of the set, then the figure PDFs |
| `paper/cpc/highlights.txt` | Highlights |
| `paper/cpc/src/rg_supp.pdf` (79 pages, sha256 `9b61b86a4853d597c366830007526d84c92e3bc2f32e919ab0e8843cc2f27ff1`) | Supplementary material |
| `paper-cpc.tar.gz`, the directory `paper/cpc` (`paper/cpc/REPRO-ARCHIVE.md`) | Supplementary material |
| `readcon-core.bundle` and `patches/` | Program files |
| The author's cover letter | Cover letter |

`em-flat/` differs from the arXiv source in two ways: `figures/generated/` prefixes are removed, and `\bibliographystyle{elsarticle-num}\bibliography{rg_main}` becomes `\input{rg_main.bbl}` (method B in EMTEX).

Data availability names readcon-core `\readconCargoVersion`. The timing records name commit `5e1430ddf6da5d2b0d4652f47dce889e7895598f`, which is readcon-core 0.17.3 and is not a release tag. `readcon-core.bundle` holds that commit with its whole history, and the text links the concept record https://doi.org/10.5281/zenodo.18753567 of readcon-core.
The latest release tag is v0.23.2 at `8c2d9984c40aedfb2e0084fedefaa02e930957f2`.
`rg_main.pdf` has 42 pages, sha256 `fb5a052cc23de991fc1b6c2f9b2b07d5f9d24faf6c9f012076e924a3d3668da8`.

## Form answers

**Article type:** Computer Programs in Physics

**Title:** readcon-core: a versioned geometry checkpoint for resumed saddle searches

**Authors:** Rohit Goswami (corresponding), TurtleTech ehf., Fornhaga 24, 107 Reykjavík, Iceland.
Email rgoswami@ieee.org.
ORCID 0000-0002-2393-8056.
The author enters the phone number in EM.

**Abstract:** plain text, 1474 characters, 247 words (`check_manuscript.py` counts 248 in the TeX source, limit 250).
Macros expanded: `\corpusFiles` = 165, `\eFivePrefactorRatioFree` = 36.8, `\rcRatioAseExtxyz` = 0.46, `\rcRatioHfivepy` = 16.

```
Rare-event campaigns stop and resume thousands of saddle searches from stored geometries. A restart reads the fixed components of each atom, the identity of each row and the velocity time unit, and repeats the interrupted search bit for bit only when the coordinates read back as the binary64 values written. General-purpose formats keep these fields in one library's layout or not at all, and the configuration (CON) text of the eOn code lacked a specification. Here, we describe CON 3.1, a versioned grammar for that text, and its reference reader and writer readcon-core, a Rust library with C, C++, Python, Julia and Fortran interfaces. A JSON line declares the version, units and periodic flags, each coordinate row carries a mask of fixed components and an atom identifier, and readers accept any later minor of a known major. Two corpora of 165 legal and illegal files decide what a conforming reader accepts, and every read path of the readcon-core Python module and C library returns the verdict their manifests name. On a platinum slab with its adatom held at a fixed height, a climbing-image band resumed from its checkpoint repeats the uninterrupted band bit for bit, and without the hold the band crosses a saddle with a prefactor 37 times larger. From Python on one core, a trajectory with velocities, masks and identifiers takes 0.46 times the wall time of the extended XYZ reader of the Atomic Simulation Environment and 16 times that of h5py on binary H5MD.
```

**Keywords:** geometry checkpoint; file format specification; saddle search; conformance corpus; nudged elastic band

**Program title:** readcon-core **Developer's repository link:** https://github.com/lode-org/readcon-core **Licence:** MIT **Programming language:** Rust, with C, C++, Python, Julia and Fortran 2008 interfaces

**Highlights:** upload `paper/cpc/highlights.txt`.

**Cover letter:** upload the author's cover letter.

**Suggested reviewers:** the author enters name, institution, email and reason for each.

**Opposed reviewers:** none.

**Competing interests:** the manuscript's Declaration of competing interest states "The author declares no competing interests."
In the declarations tool, choose the first option, no known competing financial interests or personal relationships.
Upload the `.docx` the tool produces.

**CRediT:** Rohit Goswami: Conceptualization, Methodology, Software, Visualization, Writing – original draft, Writing – review and editing.

**Funding:** "This research did not receive any specific grant from funding agencies in the public, commercial, or not-for-profit sectors."
(Section "Funding").

**Generative AI declaration question:** AI tools were used, as Section "Declaration of generative AI and AI-assisted technologies in the manuscript preparation process" states: "The author reviewed and edited all tool output as needed and takes full responsibility for the content of the published article. Chatbots were used to refine certain turns of phrase and to speed through some implementation details; all the work is the author's own."

**Data statement:** "The software described here is readcon-core `\readconCargoVersion`. The deposited timing records name commit 5e1430ddf6da5d2b0d4652f47dce889e7895598f, which is readcon-core 0.17.3 and is not a release tag. The git bundle readcon-core.bundle of the supplementary material holds that commit with its whole history. Every record of the paper names the library of that commit by its digest, 3b4d00ae2427. The latest release tag is v0.23.2 at 8c2d9984c40aedfb2e0084fedefaa02e930957f2. The concept record of readcon-core is https://doi.org/10.5281/zenodo.18753567. The scripts, records and sources of the paper are the directory paper/cpc of the supplementary material." Links: https://doi.org/10.5281/zenodo.18753567

**Preprint:** the arXiv identifier of the preprint.
Decline the SSRN option, since the preprint is on arXiv.

**Open access or subscription:** subscription (non-open-access).

**Submission declaration:** not published elsewhere except as a preprint, not under consideration elsewhere.
