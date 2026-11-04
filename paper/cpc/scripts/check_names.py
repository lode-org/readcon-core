#!/usr/bin/env python3
"""Fail when a file, a commit message or a commit identity credits the work
to, or ties it to, an excluded name. Plain usage, such as a tool the software
supports or uses, a hook path or a harness, passes.

The names are kept here only as SHA-256 digests of their lowercase spelling,
and the tie words for a helper as base64, so this file does not contain them.
Text is split into runs of letters; each run is checked whole and split at
case changes, and each pair of adjacent runs is checked as a two-word name.

Two classes of name:

  TIE    companies and affiliations, and the generic phrases for an
         automated author. Any mention fails.
  CREDIT products, models and the generic words for generated text and the
         tools that write it. A mention fails only in a credit or tie
         context:
           - a commit author or committer, or a patch From: line
           - a trailer such as Co-authored-by: or Generated-by:
           - the credit tail of a changelog entry, "- text - (sha) - names"
           - an author, affiliation, maintainer or contributor field
           - a credit phrase before it ("generated with", "written by",
             "thanks to", "with help from", "on behalf of", ...)
           - a tie word next to it (a word for a helper, referee, reviewer,
             affiliation, employer, acknowledgement, ...)
           - a version number right after it, as in a model label
             ("name-5.5" always, "Name 3.5" when capitalised)
         A name that is also a common English word counts after a credit
         phrase only when it is capitalised, so a data structure that
         shares the word is usage.

One CI identity and one compound given name are allowed; they are stored
base64-encoded for the same reason as the digests.

  check_names.py [--show] PATH...            files and directories; .pdf via
                                             pdftotext, .tar.gz members, and
                                             patches without their removed lines
                                             and the base85 data of their binary
                                             hunks
  check_names.py --git-tree REPO REV ...     every blob of REV
  check_names.py --git-log REPO RANGE ...    messages and identities of RANGE
  check_names.py --self-test                 the context rules on fixed lines

Exit 1 when anything matches. Matches are printed masked unless --show.
"""
import argparse
import base64
import hashlib
import io
import re
import subprocess
import sys
import tarfile
from pathlib import Path

TIE = {
    "400710ceff5f4f8cc416194ee65f3045084d43e60d0657909fd1b113a07e26bf",
    "5e0adc39e4d24ec9f5289c5494546291b0e56981eb7e6bf72f780162e3cb4c11",
    "68447275a0bba53daf86c76697394ed09bbdd40f5f908a0e21b199f42be316b7",
    "6fcba5d96a4fadfdd63064cf21da843c31de9a702bbee7fe306d4754fc9dd262",
    "74f3bba0747b8bf59e3d8628f71c2d15711322c489fc64f7519c4627f3872a5a",
    "951c40d281bfd25bccbf6a20fa16e3a3631682896511f80dcb7714635edf4976",
    "97fbdc11d22ef236d0a241e2b1f6342e7f447712386ffc8c5ee6d17b1c65a97e",
    "9c6b20635ca6c678dd69a4e562b162d733a13c53b79ce83b7bac355591f857d7",
    "a20dded364d4d9fcf2e376a72237b288545eb21dfc68a4cf396686e90b8d169a",
    "e78bdebae031095bebcfd3e8954e4b880796dcec73d2a7f4701f5dd62a11f7af",
    # Generic phrases for an automated author, with plurals.
    "31a85e22a24a7a4fba06c2c64be937d96cf5871f0e027919dd6b24fe4b764705",
    "4d81abbac56503dfcaaa0e42c4893e281c14d0c8210308fa4b1f18697338b1c0",
    "53beb385cf69a2c6c9d58738452aea03672bfd803fba2c357497e1c5ad5b27b4",
    "5e3176a3b09f46782fced3be659ace19da10d70e5c1bdd99cb213b426cda5701",
    "674d4324254589d7427d9a8bd063513ded8b485812c9920b2eca70f6a78991ab",
    "a4d76a4d59584d6f8772dcd8b25444e6263ded2d928fc5d896cd2eb87ba87532",
    "c5f9d8f01eaaecc599699fbc9ada0dd9c4da6a59258bc55d6e464373afc049d5",
    "ce506c08e617f713db351b024da890bfd26aa270d7ef452a73cf533c05b01103",
    "e748f8750672ca8b04b242bef501be5fab814415306bbcf46ca52e70a9e8c9e6",
    "e98a9cd4720d73ab9bae251042947c610155531747aaf03b535afdeedcbe9827",
    "ee662f0a4316976d226a3fafe98060cd4995718d09c62f78dd1d359399a75528",
    "eeba6559d461376f8be2b58ce11cf6b75824f192caf82f95aff6ec50ee215905",
    "fafff6df80ac162a1fcd273d2b841e8de2a9af1fd3e2e5092380a0b389e3d68b",
}

CREDIT = {
    # Generic words for generated text and its tools, with plurals.
    # The journal's declaration of tool use names them as plain usage.
    "0677069fdf937bd1e36cb0f16701b00ee98436d5638157bae9d36f602ad62aba",
    "2aec951c48c8623bf7ed02b12966bd692e84f939978c8dfe87bad55dea191c30",
    "386ebc0efd04339aa982703eb666c335d8458b8657343d9783185debf0bf0c26",
    "442e56863b7e9cf893fd1d134d4b24b57e98acc6a3f8501d163d042259065871",
    "4dc8fe0fdb3b6b70fec2bedfe3da13b828902a91b48a93e12d70b29b3e337a99",
    "5eff592cc497fccb48ebfffaca38a83f9167bc1661b4477e1fc1b66b658cd5a0",
    "76dc0ddaccd2ca538f0d3ff7af15d9966f1af70e158bcf983bb4e46d42d3049b",
    "a5ea7d719f7aba21d3f940a263d619ebb130a56a7faf669f8e333bcf59b65603",
    "cdcbb68a3444fdd629ab0af770af3fc99e4d5dde43b576d5f855691e155283ec",
    "d47964e026643905b878d899a2ecfafc1ac1eca0d65bcebfa445d30bf14f2564",
    "e75bf69043bc4d4f8094359c07acd9a267208448b499c46756131f6bbdb4551f",
    "053ea4804ef1bb33d4a3d6fb024a614b6d257cebc2bc7cd915da9c9522f37ffc",
    "0ac0192d441f96da3a4a3174330c3a74e034a3a4704fded0e87515d1a97c19dc",
    "10b8ecc0d7ffa69355fc2ad96eae450ee66556bf2f10dba7dc85a2fbcddcdea1",
    "2bf548d8056029c73e6e28132d19a3a277a49daf32b1c1ba7b0b7fc7e78bf5cd",
    "3ea125d0bff386e6754b3782b300016fc79a9cf8f8669c0a5c3db64467ddb681",
    "4016c3db3bc3c731a4148022f43ebd6d4422b77976763135b9d9afcb9b71b2c1",
    "45d780f82c9247fc1142f8b60c12b6c6cd3d9f23dd836cfa6e84c498d2f83292",
    "46a4eebd20d881ecfc0ecb54f6d8346524fadb143726d256b1a045303fc67717",
    "487b91042c7cf27a19e23ea8699f5f354b1a0c3af9e418138dc6150d830f970d",
    "5792d2981981be5a2677cd353db6f55cd9d2779570061ae8d86176635b3cc745",
    "57de4cf40144bdf7d00010f2f5557a7d642c2b9705309bfade167dd313e2ca93",
    "5d0c0ab127fdea24d94e7e3326b6ceb965ab82ad897f9de1bd6b1a9a23f87578",
    "5d72436256ada53828b51895a94bb8489e9f1ac4fe937a8024ef1594e7045ff6",
    "60965168ce762e949600281ba6d01fee136e5b6e8257b1f216f9025ed324474c",
    "67f2d22514622d1be30c14ee9f3cb104503a159a33a656ca91a1953aa9616429",
    "6f7ac1823da81d2e52d1a1549ee69c85bbf8bb56d06682849e7c09da2785ce3b",
    "7d3194f79e645c42e4396dda38be04766810ec6a00d00aced3ffc2a0a1f1a9ef",
    "9058f79c893a1d7e20b13009b95b9cf3211478a91a47e2ad65bdfedad6fc98f4",
    "920510199770f4d65cb8aaa2cd12bdb2b8c37f5b3907c50a734a0e3409da2823",
    "97f128115e33c7693db6156c493d1fcbe0ebf4a870b6b49cd4b6b865233f7725",
    "9d74932bdb6f21dc7ab21d6fc5260f474e0d538571fba7a82b74ffe47e6f9a10",
    "add92b9cde2bdbf3daaf65a0db79e9b1a7fa428b71b4d6ce38c742eb6dca0c1c",
    "c70eca6b0f88f44d81a41311647e50fda1ac454ec04ffd442b0eb4743a993131",
    "c857d09db23e6822e3600bc06ad8d58f92ed62bc8efd81c753f77048662cb97d",
    "c97504235ab15009f6c5f11ba890007a5f3fdd20c9e57b53ea74855033572ddf",
    "c9ad8f2cc1294afa0ef22fc2c019ff7243cdd272b2147ddca3f34c5036b05768",
    "de2187af3fb011708ca4ff6d21e4845236d6a6d25e7e90531b26a7923d16c73f",
    "e12ce8285efc67c6d93d3a122e2589ed95089bcbb775ba5634d94e2b8385db07",
    "e4f9c522e1c89280e9561b825f4f24fe32b51ff82d61e5c2b1dfd0321c35a90b",
    "fc5a1047f5919892fcdf8aa79ea5d6bb6531b5c176939ef0110906cb225941c1",
}

COMMON = {
    "4016c3db3bc3c731a4148022f43ebd6d4422b77976763135b9d9afcb9b71b2c1",
    "45d780f82c9247fc1142f8b60c12b6c6cd3d9f23dd836cfa6e84c498d2f83292",
    "46a4eebd20d881ecfc0ecb54f6d8346524fadb143726d256b1a045303fc67717",
    "5792d2981981be5a2677cd353db6f55cd9d2779570061ae8d86176635b3cc745",
    "57de4cf40144bdf7d00010f2f5557a7d642c2b9705309bfade167dd313e2ca93",
    "5d72436256ada53828b51895a94bb8489e9f1ac4fe937a8024ef1594e7045ff6",
    "9058f79c893a1d7e20b13009b95b9cf3211478a91a47e2ad65bdfedad6fc98f4",
    "920510199770f4d65cb8aaa2cd12bdb2b8c37f5b3907c50a734a0e3409da2823",
    "c9ad8f2cc1294afa0ef22fc2c019ff7243cdd272b2147ddca3f34c5036b05768",
    "e12ce8285efc67c6d93d3a122e2589ed95089bcbb775ba5634d94e2b8385db07",
    "fc5a1047f5919892fcdf8aa79ea5d6bb6531b5c176939ef0110906cb225941c1",
}

ALLOW = [base64.b64decode(s).decode() for s in (
    "SmVhbi1DbGF1ZGU=",
)]

CI_IDENTITY = base64.b64decode("Z2l0aHViXC1hY3Rpb25zXFtib3RcXQ==").decode()
CI_RE = re.compile(CI_IDENTITY + r"(@users\.noreply\.github\.com)?")
ALLOW_RE = [re.compile(re.escape(a)) for a in ALLOW]

RUN = re.compile(r"[A-Za-z]+")
CAMEL = re.compile(r"[A-Z]?[a-z]+|[A-Z]+(?![a-z])")

CREDIT_VERBS = {
    "generated", "written", "wrote", "created", "authored", "coauthored",
    "drafted", "produced", "prepared", "developed", "assisted", "reviewed",
    "refereed", "edited", "coded", "implemented", "contributed", "designed",
    "built", "made", "fixed", "found", "proposed", "suggested", "done",
    "performed", "conducted", "carried", "helped", "supported", "funded",
    "sponsored", "powered", "provided", "aided", "co",
}
CREDIT_PREPS = {"by", "with", "using", "via", "through", "from", "of", "out"}
TIE_WORDS = {
    "thanks", "thank", "thanked", "acknowledge", "acknowledged",
    "acknowledgement", "acknowledgements", "acknowledgment",
    "acknowledgments", "courtesy", "credit", "credits", "credited",
    "affiliation", "affiliations", "affiliated", "employer", "employers",
    "employed", "employee", "employees", "behalf", "collaboration",
    "partnership", "referee", "referees", "reviewer", "reviewers",
    "coauthor", "coauthors", "contributor", "contributors", "maintainer",
    "maintainers", "help", "assistance",
} | {base64.b64decode(s).decode() for s in ("YXNzaXN0YW50", "YXNzaXN0YW50cw==", "YWdlbnQ=", "YWdlbnRz")}
TRAILER = re.compile(r"^\s*[A-Za-z][A-Za-z-]*-[Bb]y:\s")
CHANGELOG_TAIL = re.compile(r"\s-\s\([0-9a-f]{7,40}\)\s-\s(.*)$")
FIELD = re.compile(
    r"""^\s*(?:[-*]\s*)?(?:\\(?:author|affiliation|affil|address|institute|thanks)\b"""
    r"""|["']?(?:authors?|affiliations?|maintainers?|contributors?|creators?|"""
    r"""given-names|family-names|copyright-holders?)["']?\s*[:=])""",
    re.IGNORECASE)
IDENTITY = re.compile(r"^(?:From|Author|Committer):\s")
MODEL_LABEL = re.compile(r"-\d")
SPACED_LABEL = re.compile(r"\s\d+\.\d")
# The base85 lines of a binary hunk encode the bytes of a binary file, which is skipped like the file
# itself; their letter runs spell words at random.
BINARY_HUNK = "GIT binary patch"
BINARY_DATA = re.compile(r"(?:literal|delta) \d+|[A-Za-z][0-9A-Za-z!#$%&()*+;<=>?@^_`{|}~-]*|")


def digest(word):
    return hashlib.sha256(word.encode()).hexdigest()


def mask(word):
    return word[0] + "*" * (len(word) - 1)


def tokens(line):
    """Runs of letters with the lowercase spellings each run stands for."""
    out = []
    for m in RUN.finditer(line):
        run = m.group(0)
        forms = {run.lower()} | {p.lower() for p in CAMEL.findall(run)}
        out.append((m.start(), run.lower(), forms, run[0].isupper()))
    return out


def names_in(line):
    """(index, start, spelling, class) for every excluded name in the line."""
    toks = tokens(line)
    found = []
    for k, (start, run, forms, upper) in enumerate(toks):
        for w in forms:
            h = digest(w)
            if h in TIE:
                found.append((k, start, w, "tie"))
            elif h in CREDIT:
                found.append((k, start, w, "credit"))
        if k + 1 < len(toks):
            pair = f"{run} {toks[k + 1][1]}"
            if digest(pair) in TIE:
                found.append((k, start, pair, "tie"))
            elif digest(pair) in CREDIT:
                found.append((k, start, pair, "credit"))
    return toks, found


def credit_phrase(toks, k):
    before = [t[1] for t in toks[max(0, k - 5):k]]
    for i, w in enumerate(before):
        if w in CREDIT_VERBS and any(p in CREDIT_PREPS for p in before[i + 1:]):
            return True
    return False


def tie_word(toks, k):
    near = [t[1] for t in toks[max(0, k - 4):k]] + [t[1] for t in toks[k + 1:k + 4]]
    return any(w in TIE_WORDS for w in near)


def line_hits(line, identity=False):
    stripped = CI_RE.sub(" ", line)
    for rx in ALLOW_RE:
        stripped = rx.sub(" ", stripped)
    toks, found = names_in(stripped)
    if not found:
        return []
    whole = identity or IDENTITY.match(stripped) or TRAILER.match(stripped) \
        or FIELD.match(stripped)
    tail = CHANGELOG_TAIL.search(stripped)
    hits = []
    for k, start, w, cls in found:
        end = start + len(toks[k][1])
        label = MODEL_LABEL.match(stripped, end) or \
            (toks[k][3] and SPACED_LABEL.match(stripped, end))
        if cls == "tie" or whole or label or (tail and start >= tail.start(1)) \
                or tie_word(toks, k):
            hits.append(w)
        elif credit_phrase(toks, k) and (toks[k][3] or digest(w) not in COMMON):
            hits.append(w)
    return hits


def is_patch(name):
    return name.endswith((".patch", ".diff"))


def removed(line):
    return line.startswith(("-", "diff --git ", "index ", "rename from ", "copy from "))


def scan_text(label, text, patch=False):
    found = []
    binary = False
    for n, line in enumerate(text.splitlines(), 1):
        if patch:
            if line == BINARY_HUNK or binary and BINARY_DATA.fullmatch(line):
                binary = True
                continue
            binary = False
            if removed(line):
                continue
        for w in line_hits(line):
            found.append((label, n, w))
    return found


def text_of(data):
    if b"\0" in data[:8192]:
        return None
    return data.decode("utf-8", errors="replace")


def scan_bytes(label, data):
    if label.endswith(".pdf"):
        p = subprocess.run(["pdftotext", "-layout", "-", "-"], input=data,
                           capture_output=True, check=True)
        return scan_text(label, p.stdout.decode("utf-8", errors="replace"))
    if label.endswith((".tar.gz", ".tgz", ".tar")):
        found = []
        with tarfile.open(fileobj=io.BytesIO(data)) as tar:
            for m in tar.getmembers():
                found += scan_text(f"{label}:{m.name}", m.name)
                if m.isfile():
                    found += scan_bytes(f"{label}:{m.name}", tar.extractfile(m).read())
        return found
    text = text_of(data)
    if text is None:
        return []
    return scan_text(label, text, patch=is_patch(label))


def scan_paths(paths):
    found = []
    for root in paths:
        root = Path(root)
        files = [root] if root.is_file() else sorted(p for p in root.rglob("*") if p.is_file())
        for f in files:
            if f.suffix == ".bundle" or f.name.endswith(".git"):
                continue
            rel = str(f)
            found += scan_text(rel, rel)
            found += scan_bytes(rel, f.read_bytes())
    return found


def git(repo, *args, data=None):
    return subprocess.run(["git", "-C", repo, *args], input=data, capture_output=True,
                          check=True).stdout


def scan_git_tree(repo, rev):
    found = []
    listing = git(repo, "ls-tree", "-r", "-z", rev).split(b"\0")
    entries = []
    for e in listing:
        if not e:
            continue
        meta, path = e.split(b"\t", 1)
        mode, kind, oid = meta.split()
        if kind == b"blob":
            entries.append((path.decode(), oid.decode()))
    for path, oid in entries:
        label = f"{rev}:{path}"
        found += scan_text(label, path)
        found += scan_bytes(label, git(repo, "cat-file", "blob", oid))
    return found


def scan_git_log(repo, rng):
    fmt = "%H%n%an <%ae>%n%cn <%ce>%n%B%x00"
    out = git(repo, "log", f"--format={fmt}", rng).decode("utf-8", errors="replace")
    found = []
    for rec in out.split("\0"):
        rec = rec.strip("\n")
        if not rec:
            continue
        lines = rec.split("\n")
        label = f"commit {lines[0][:12]}"
        for n, line in enumerate(lines[1:], 2):
            for w in line_hits(line, identity=n <= 3):
                found.append((label, n, w))
    return found


def self_test():
    def d(s):
        return base64.b64decode(s).decode()

    # Encoded so the fixtures do not spell the names either.
    fail = [d(s) for s in (
        "Q28tYXV0aG9yZWQtYnk6IENvcGlsb3QgPGNvcGlsb3RAZXhhbXBsZS5jb20+",
        "R2VuZXJhdGVkIHdpdGggQ2xhdWRlIENvZGU=",
        "LSBGaXggdGVzdCBbQkVOQ0hdIC0gKGI1M2ZhOTEpIC0gKkhhb1pla2UqLCAqQ29waWxvdCo=",
        "VGhpcyB3b3JrIHdhcyBkb25lIGJ5IGEgQ3Vyc29yIGNsb3VkIGFnZW50Lg==",
        "VGhhbmtzIHRvIEdyb2sgZm9yIHRoZSByZXZpZXcu",
        "UmVmZXJlZSBvcHVzLTUuNSBhc2tlZCBmb3IgYSByZXJ1bi4=",
        "YXV0aG9yOiBHcm9r",
        "XGFmZmlsaWF0aW9ue1NwYWNlWH0=",
        "VGhlIHJ1bnMgdXNlZCBhIFRlYWNoWCBtYWNoaW5lLg==",
        "RnJvbTogQ3Vyc29yIEFnZW50IDxjdXJzb3JhZ2VudEBjdXJzb3IuY29tPg==",
        "SW1wbGVtZW50ZWQgYnkgQ3Vyc29y",
        "YXV0aG9ycyA9IFsiQ29waWxvdCJd",
        "U2VlIGJhdGNoMS9ncHQtNS42LXNvbC9SRUZFUkVFLXIzLm1k",
        "dGhlIGdsbS01LjMgcmVwb3J0",
        "Q2xhdWRlIDMuNSB3cm90ZSB0aGUgZmlyc3QgZHJhZnQu",
        "VGhlIGVudHJ5IG9mIGI1M2ZhOTEgbGlzdGVkIGEgY29kZSBhc3Npc3RhbnQgdHdpY2Uu",
        "ZG9jcyhjaGFuZ2Vsb2cpOiBkcm9wIHRoZSBhc3Npc3RhbnQgY28tYXV0aG9yIGNyZWRpdCBvbiBiNTNmYTkx",
        "TW9zdCBvZiB0aGUgcGFyc2VyIHdhcyB3cml0dGVuIHdpdGggYW4gQUkgYXNzaXN0YW50Lg==",
        "VGhpcyBwYXJzZXIgd2FzIHdyaXR0ZW4gd2l0aCBhIGxhbmd1YWdlIG1vZGVsLg==",
    )]
    pass_ = [d(s) for s in (
        "bGV0IG11dCBjdXJzb3IgPSBzdGQ6OmlvOjpDdXJzb3I6Om5ldyhieXRlcyk7",
        "LSAoKipwYXJzZXIqKikgbWVtY2hyIGxpbmUgY3Vyc29yLCBjb29yZHMtb25seSBhc3NlbWJsZSAtICgzM2EwYzY4KSAtICpIYW9aZWtlKg==",
        "LSAoKipiZW5jaCoqKSByZWZyZXNoIENhY2hlZ3JpbmQgSS1yZWZzIGZvciBkb2NzIC0gKGE1ZjhhMmYpIC0gZ2l0aHViLWFjdGlvbnNbYm90XQ==",
        "ICBnaXQgY29uZmlnIHVzZXIubmFtZSAiZ2l0aHViLWFjdGlvbnNbYm90XSI=",
        "Lmdyb2sv",
        "MSxjdWgyeDEwMCxiYXNlLDAuMDA0LDE2NzcxMDAsMTAwLG9rLCxjdXJzb3IsSW50ZWwoUikgWGVvbihSKQ==",
        "SmVhbi1DbGF1ZGUgUGVkZXJzZW4=",
        "Ly8vIEltcGxlbWVudGVkIGJ5IHRoZSBtZW1jaHIgY3Vyc29yIG9uIHRoZSBob3QgaXRlcmF0b3IgcGF0aCBhbmQgYnk=",
        "ICBhdXRob3IgPSB7QmVydGhldCwgSmVhbi1DbGF1ZGUgYW5kIFBlZGVyc2VuLCBBbmRyZWFzfSw=",
        "Zm9yIChpLCBjdXJzb3IpIGluIHJvd3MuaXRlcigpLmVudW1lcmF0ZSgpIHs=",
        "Y3Vyc29yXzIgPSBjdXJzb3IgKyAx",
        "TGludXggY3Vyc29yIDYuMTIuOTQrICMxIFNNUCBQUkVFTVBUX0RZTkFNSUMgeDg2XzY0IEdOVS9MaW51eA==",
        "Q2hhdGJvdHMgd2VyZSB1c2VkIHRvIHJlZmluZSBjZXJ0YWluIHR1cm5zIG9mIHBocmFzZSBhbmQgdG8gc3BlZWQgdGhyb3VnaCBzb21lIGltcGxlbWVudGF0aW9uIGRldGFpbHM7IGFsbCB0aGUgd29yayBpcyB0aGUgYXV0aG9yJ3Mgb3duLg==",
        "XHNlY3Rpb24qe0RlY2xhcmF0aW9uIG9mIGdlbmVyYXRpdmUgQUkgYW5kIEFJLWFzc2lzdGVkIHRlY2hub2xvZ2llcyBpbiB0aGUgbWFudXNjcmlwdCBwcmVwYXJhdGlvbiBwcm9jZXNzfQ==",
    )]
    bad = [s for s in fail if not line_hits(s)] + [s for s in pass_ if line_hits(s)]
    data, credit = d("enYreEFJJigxKiU4YSMzJDE7clY="), d("VGhhbmtzIHRvIEdyb2sgZm9yIHRoZSByZXZpZXcu")
    patch = "\n".join(["diff --git a/bands.npz b/bands.npz", "index 1111111..2222222 100644", "GIT binary patch",
                       "delta 23", data, "", "delta 23", data, "", "diff --git a/notes.txt b/notes.txt",
                       "--- a/notes.txt", "+++ b/notes.txt", "@@ -0,0 +1 @@", "+" + credit])
    if len(scan_text("fixture.patch", patch, patch=True)) != 1 or len(scan_text("fixture", patch)) != 3:
        bad.append("the binary hunk of a patch")
    print(f"check_names self-test: {len(fail)} credit lines, {len(pass_)} usage lines, "
          f"1 patch with a binary hunk, {len(bad)} misclassified")
    return 1 if bad else 0


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--show", action="store_true")
    ap.add_argument("--self-test", action="store_true")
    ap.add_argument("--git-tree", nargs=2, action="append", default=[], metavar=("REPO", "REV"))
    ap.add_argument("--git-log", nargs=2, action="append", default=[], metavar=("REPO", "RANGE"))
    ap.add_argument("paths", nargs="*")
    a = ap.parse_args()
    if a.self_test:
        return self_test()
    found = scan_paths(a.paths)
    for repo, rev in a.git_tree:
        found += scan_git_tree(repo, rev)
    for repo, rng in a.git_log:
        found += scan_git_log(repo, rng)
    for label, n, w in found:
        print(f"{label}:{n}: {w if a.show else mask(w)}")
    scopes = len(a.paths) + len(a.git_tree) + len(a.git_log)
    print(f"check_names: {len(found)} match(es) in {scopes} scope(s)")
    return 1 if found else 0


if __name__ == "__main__":
    sys.exit(main())
