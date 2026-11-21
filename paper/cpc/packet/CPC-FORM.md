<!-- Written by paper/cpc/packet/make_packet.py from CPC-FORM.md.in; edit the template, not this file -->
# CPC submission form: readcon-core: a versioned geometry checkpoint for resumed saddle searches

Status: Prepared, not submitted.

Packet state: draft

Every count and quoted text below is written by `make_packet.py` from the sources and the `build_tex.sh`
build of the paper, for readcon-core 0.17.3, measured commit `5e1430ddf6da5d2b0d4652f47dce889e7895598f`, library digest `b49c0be7352a`.

## Sources

- [GFA] CPC Guide for Authors: https://www.sciencedirect.com/journal/computer-physics-communications/publish/guide-for-authors
  (the live page answers the box with a captcha; the text was read from the Wayback snapshot
  https://web.archive.org/web/20250802150417/https://www.sciencedirect.com/journal/computer-physics-communications/publish/guide-for-authors)
- [TPL] CPiP LaTeX template: https://legacyfileshare.elsevier.com/promis_misc/cpc-cpip-template.tex
- [EM] Editorial Manager: https://www.editorialmanager.com/comphy/ (the page carried the banner "Site under
  development. Do not use for live manuscript submission." when it was read)
- [EMTEX] Elsevier LaTeX in EM: https://www.elsevier.support/publishing/answer/how-to-submit-a-latex-file-in-editorial-manager and https://www.ariessys.com/wp-content/uploads/EM_PM_LaTeX_Guide.pdf
- [SHARE] Elsevier article sharing: https://www.elsevier.com/about/policies-and-standards/sharing
- [MDATA] CPC Program Library on Mendeley Data: https://data.mendeley.com/journal/00104655

## Requirements and the manuscript

| Item | Requirement | Source | Manuscript and packet |
|---|---|---|---|
| System | Editorial Manager, `editorialmanager.com/comphy` | GFA, TPL, EM | Start from the "Submit your article" button on the journal page and confirm the route there. |
| Article type | CPiP: programs archived in the CPC Program Library on Mendeley Data under an approved licence | GFA | Computer Programs in Physics: the paper has a Program Summary and describes a program. |
| Licence | One of MIT, Apache-2.0, BSD 2/3-clause, GPLv2/3, LGPL, MPL-2.0, CeCILL, CeCILL-B, CC BY 4.0, CC0 1.0, CC BY-NC 3.0 | GFA | MIT, the Program Summary's licensing provision. |
| Program Summary | Immediately after the abstract. Fields: Program title; CPC Library link (Technical Editor); Developer's repository link; Licensing provisions; Programming language; Supplementary material; Nature of problem, Solution method, Additional comments (each in the 50 to 250 word range the guide gives); References | GFA, TPL | All fields, in the CPC order, after the abstract. Word counts: Nature of problem 162, Solution method 182, Additional comments 122. |
| Program files | Compressed archive with source, README (file layout, install, run), sample input and output of one full test run, manual if needed. Upload at "Attach Files". | GFA, TPL | `readcon-core.bundle`, the git bundle that holds the measured commit `5e1430ddf6da5d2b0d4652f47dce889e7895598f` with its whole history (`git clone readcon-core.bundle` checks it out), and `patches/`, a patch series that `git am --keep-cr` applies on commit `d0b7d3c7` in that clone to give the tree of that commit. The commit descends from `d0b7d3c7`, the head of pull request 80 to the main branch after the published release 0.17.3 (tag v0.17.3 at commit `12ca800b`), and its change log lists every change since 0.17.3 under 0.17.3. This commit is not a release tag. |
| Source format | Editable source, `.tex` for LaTeX. A PDF is not a source file. | GFA | The LaTeX sources of `paper/cpc/src`. |
| EM LaTeX build | No subfolders. `.tex`, `.bbl` and support files as item type Manuscript, images as Figure. Order: `.tex`, bibliography, styles, figures. | EMTEX | `make_em_flat.py` writes the flat set (Packet files below). |
| Abstract | At most 250 words, stands alone, define uncommon abbreviations at first use | GFA | 207 words by `check_manuscript.py`'s count. |
| Keywords | 1 to 7 | GFA | 5: geometry checkpoint; file format specification; saddle search; conformance corpus; nudged elastic band. |
| Highlights | 3 to 5 bullets, each at most 85 characters with spaces, separate editable file with "highlights" in the name | GFA | 5 bullets of 71, 72, 74, 81, 83 characters in `paper/cpc/highlights.txt`, the same text as the highlights of `rg_main.tex`. |
| Graphical abstract | Not mentioned in the CPC guide | GFA | `rg_main.tex` has a graphical abstract; upload it in the graphical abstract slot. |
| Title page | Full postal address of each affiliation with country; corresponding author email on the title page | GFA | TurtleTech ehf., Fornhaga 24, 107 Reykjavík, Iceland; rgoswami@ieee.org. |
| Corresponding author | Full contact details incl. postal address and phone in EM | GFA checklist | The author enters them in EM. |
| Cover letter | Not listed in the guide; EM accepts one | EM | The author's cover letter; it is not part of the supplementary material. |
| Suggested reviewers | Not listed in the guide; EM asks for them | EM | The author enters them in EM. |
| CRediT | Required | GFA | Section "CRediT authorship contribution statement". |
| Competing interests | Statement plus the Elsevier declarations tool `.docx` uploaded at Attach Files | GFA | Section "Declaration of competing interest" declares none; the `.docx` comes from the declarations tool during submission. |
| Funding | Guide asks for disclosure | GFA | Section "Funding" carries the guide's sentence for research without specific funding. |
| Generative AI in writing | Declare in a section before the references if used in writing | GFA | Section "Declaration of generative AI and AI-assisted technologies in the manuscript preparation process", the last section before the references, in Elsevier's form. |
| Data availability | Option C: deposit, cite and link data, plus a data statement at submission | GFA | Section "Data availability" names readcon-core 0.17.3, its measured commit `5e1430ddf6da5d2b0d4652f47dce889e7895598f`, the digest `b49c0be7352a` of that commit's library, and says the records name the libraries they ran. The version map names each of those libraries. The git bundle is `readcon-core.bundle`. Links: https://github.com/lode-org/readcon-core, https://doi.org/10.5281/zenodo.18753567. |
| References | Numbered, elsarticle-num, software cited with identifier | GFA | elsarticle-num; 77 references in the manuscript and 65 in the supplement; no undefined reference or citation in either pdfTeX log. |
| Tables | Editable, no vertical rules | GFA | 9 tables; no tabular has a vertical rule. |
| Preprint | Sharing a preprint anywhere at any time is allowed, and a preprint is not prior publication | GFA, SHARE | The preprint is on arXiv. |

## Packet files

| File | Use in EM |
|---|---|
| `DIR/em-flat/` from `python3 paper/cpc/scripts/make_em_flat.py --out DIR` (TeX Live 2025) | `rg_main.tex` first, then `rg_main.bbl`, then every other file of the set, then the figure PDFs |
| `paper/cpc/highlights.txt` | Highlights |
| `paper/cpc/src/rg_supp.pdf` (90 pages, sha256 `de3402a7ecee856e001a2c3871dc98fa744295f31a3608bd680a36b104ec2a1f`) | Supplementary material |
| `paper-cpc.tar.gz`, the directory `paper/cpc` (`paper/cpc/REPRO-ARCHIVE.md`) | Supplementary material |
| `readcon-core.bundle` and `patches/` | Program files |
| The author's cover letter | Cover letter |

`em-flat/` differs from the arXiv source in two ways: `figures/generated/` prefixes are removed, and
`\bibliographystyle{elsarticle-num}\bibliography{rg_main}` becomes `\input{rg_main.bbl}` (method B in EMTEX).

Data availability names readcon-core 0.17.3, measured commit `5e1430ddf6da5d2b0d4652f47dce889e7895598f`, which
`readcon-core.bundle` holds with its whole history, and links the concept record https://doi.org/10.5281/zenodo.18753567
of readcon-core. This commit is not a release tag.
`rg_main.pdf` has 43 pages, sha256 `c002d17a315e0f5d0057148ba82fbedd0e03d0f61ace507d53eb526ed537f901`.

## Form answers

**Article type:** Computer Programs in Physics

**Title:** readcon-core: a versioned geometry checkpoint for resumed saddle searches

**Authors:** Rohit Goswami (corresponding), TurtleTech ehf., Fornhaga 24, 107 Reykjavík, Iceland. Email rgoswami@ieee.org. ORCID 0000-0002-2393-8056.
The author enters the phone number in EM.

**Abstract:** plain text, 1252 characters, 206 words (`check_manuscript.py` counts
207 in the TeX source, limit 250). Macros expanded: `\corpusFiles` = 165, `\dlpackAtoms` = 65536, `\dlpackRatio` = 0.461, `\eFivePrefactorRatioFree` = 36.8.

```
Saddle-point and rare-event searches are often stopped and resumed, sometimes in a different code from the one that started them. The geometry file used for the restart then has to keep the per-component atomic constraints, the atom identifiers, the time unit of the velocities and the binary64 coordinates. CON is a text geometry format used in eOn, ASE and other codes, and it has had no specification. Here, we describe CON 3.1, a versioned grammar that formalizes and extends CON, and readcon-core, its reference reader and writer. A JSON header on the second line of each frame declares the grammar version and the physical units, each coordinate row stores a three-bit constraint mask and an atom identifier, and a reader of a given major version accepts later minor revisions. Two conformance corpora of 165 legal and illegal files fix what a conforming reader returns, and every Python and C read path in readcon-core returns the verdict of every corpus file. On a platinum slab, a climbing-image band resumed from CON 3.1 reproduces the uninterrupted band exactly, whereas dropping the height constraint of the adatom changes the prefactor by a factor of 37. A borrowed DLPack view of 65536 atomic positions costs 0.461 times an explicit copy.
```

**Keywords:** geometry checkpoint; file format specification; saddle search; conformance corpus; nudged elastic band

**Program title:** readcon-core
**Developer's repository link:** https://github.com/lode-org/readcon-core
**Licence:** MIT
**Programming language:** Rust, with C, C++, Python, Julia and Fortran 2008 interfaces

**Highlights:** upload `paper/cpc/highlights.txt`.

**Cover letter:** upload the author's cover letter.

**Suggested reviewers:** the author enters name, institution, email and reason for each.

**Opposed reviewers:** none.

**Competing interests:** the manuscript's Declaration of competing interest states "The author declares that he has no known competing financial interests or personal relationships that could have appeared to influence the work reported in this paper." In the
declarations tool, choose the first option, no known competing financial interests or personal relationships.
Upload the `.docx` the tool produces.

**CRediT:** Rohit Goswami: Conceptualization, Methodology, Software, Visualization, Writing -- original draft, Writing -- review and editing.

**Funding:** "This research did not receive any specific grant from funding agencies in the public, commercial, or not-for-profit sectors." (Section "Funding").

**Generative AI declaration question:** AI tools were used, as Section "Declaration of generative AI and AI-assisted technologies in the manuscript preparation process" states: "During the preparation of this work the author used Cursor, routing between Claude Opus 5.5, GPT-5.6 Sol and Grok 4.7, to refine certain turns of phrase and to speed through some implementation details. After using this tool, the author reviewed and edited the content as needed and takes full responsibility for the content of the publication."

**Data statement:** "The software is readcon-core 0.17.3, measured commit 5e1430ddf6da5d2b0d4652f47dce889e7895598f, which the git bundle readcon-core.bundle of the supplementary material holds with its whole history. This commit is not a release tag. The library of that commit has digest b49c0be7352a. A record names the library it ran, and that digest is not b49c0be7352a for every record. The version map in the supplement names the library of each record. The concept record of readcon-core is https://doi.org/10.5281/zenodo.18753567. The scripts, records and sources of the paper are the directory paper/cpc of the supplementary material." Links: https://github.com/lode-org/readcon-core, https://doi.org/10.5281/zenodo.18753567

**Preprint:** the arXiv identifier of the preprint. Decline the SSRN option, since the preprint is on arXiv.

**Open access or subscription:** subscription (non-open-access).

**Submission declaration:** not published elsewhere except as a preprint, not under consideration elsewhere.
