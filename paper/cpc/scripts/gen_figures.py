#!/usr/bin/env python3
"""Figures for the CPC manuscript.

Numbers are the verified restart series and the layered timings.
The colour palette is the one used for this manuscript.
"""

from __future__ import annotations

from pathlib import Path

import matplotlib

matplotlib.use("Agg")
matplotlib.rcParams["pdf.fonttype"] = 42
matplotlib.rcParams["ps.fonttype"] = 42
matplotlib.rcParams["font.size"] = 9
import matplotlib.pyplot as plt
from matplotlib.patches import FancyBboxPatch

OUT = Path(__file__).resolve().parents[1] / "src" / "figures" / "generated"

ORANGE = "#E69F00"
SKY = "#56B4E9"
GREEN = "#009E73"
BLUE = "#0072B2"
BLACK = "#000000"


def _box(ax, x, y, w, h, text, color):
    ax.add_patch(
        FancyBboxPatch(
            (x, y),
            w,
            h,
            boxstyle="round,pad=0.02,rounding_size=0.08",
            facecolor=color,
            edgecolor=BLACK,
            linewidth=0.6,
        )
    )
    ax.text(x + w / 2, y + h / 2, text, ha="center", va="center", fontsize=8, color=BLACK)


def workflow() -> None:
    fig, ax = plt.subplots(figsize=(7.2, 2.15))
    ax.set_xlim(0, 4)
    ax.set_ylim(0, 1)
    ax.axis("off")
    boxes = [
        (0.08, "Search writes\na frame", SKY),
        (1.08, "Queue or client\nstops the job", ORANGE),
        (2.08, "Next client\nreads the frame", GREEN),
        (3.08, "Search continues\non that state", BLUE),
    ]
    for x, text, color in boxes:
        _box(ax, x, 0.28, 0.84, 0.48, text, color)
    for x in (0.94, 1.94, 2.94):
        ax.annotate(
            "",
            xy=(x + 0.12, 0.52),
            xytext=(x, 0.52),
            arrowprops={"arrowstyle": "->", "color": BLACK, "lw": 0.8},
        )
    fig.tight_layout()
    fig.savefig(OUT / "workflow.pdf")
    plt.close(fig)


def architecture() -> None:
    """Layer diagram. Replace figures/generated/architecture.pdf to swap it."""
    fig, ax = plt.subplots(figsize=(7.2, 3.4))
    ax.set_xlim(0, 10)
    ax.set_ylim(0, 6)
    ax.axis("off")
    _box(ax, 3.15, 4.55, 3.7, 1.05, "Rust core\nparse and write", SKY)
    _box(ax, 3.15, 2.85, 3.7, 1.05, "C ABI\nnull on failure, caller frees", ORANGE)
    callers = [
        (0.25, "C"),
        (2.15, "C++\neOn"),
        (4.05, "Python"),
        (5.95, "Julia"),
        (7.85, "Fortran"),
    ]
    for x, name in callers:
        _box(ax, x, 0.55, 1.75, 0.95, name, GREEN)
    ax.annotate(
        "",
        xy=(5.0, 3.95),
        xytext=(5.0, 4.5),
        arrowprops={"arrowstyle": "->", "color": BLACK, "lw": 0.8},
    )
    for x, _name in callers:
        ax.annotate(
            "",
            xy=(x + 0.87, 1.55),
            xytext=(5.0, 2.8),
            arrowprops={"arrowstyle": "->", "color": BLACK, "lw": 0.6},
        )
    fig.tight_layout()
    fig.savefig(OUT / "architecture.pdf")
    plt.close(fig)


ABNF_LISTING = r"""\begin{lstlisting}[caption={Non-normative ABNF for one frame.},label={lst:abnf}]
file = [bom] 1*frame *(*ws nl)
bom = %xFEFF
; An empty free_line on line 1 is the user line.
header_open = free_line nl metadata_line nl float3_line float3_line free_line nl free_line nl
frame = header_open (zero_atom / typed_body)
free_line = *(%x00-09 / %x0B-0C / %x0E-FF)
metadata_line = *ws (json_object / legacy_metadata)
; An empty legacy_metadata line is implicit version 1.
legacy_metadata = *ws [(%x00-09 / %x0B-0C / %x0E-7A / %x7C-FF) *(%x00-09 / %x0B-0C / %x0E-FF)]
json_object = "{" *ws [json_pair *(*ws "," *ws json_pair)] *ws "}" *ws
json_pair = json_string *ws ":" *ws json_value
json_value = json_string / json_number / json_object / json_array / "true" / "false" / "null"
json_array = "[" *ws [json_value *(*ws "," *ws json_value)] *ws "]"
json_string = DQUOTE *json_char DQUOTE
json_char = "\" DQUOTE / "\\" / "\/" / "\b" / "\f" / "\n" / "\r" / "\t" / ("\u" 4HEXDIG) / (%x20-21 / %x23-5B / %x5D-FF)
json_number = ["-"] 1*DIGIT ["." 1*DIGIT] [("e" / "E") ["+" / "-"] 1*DIGIT]
float3_line = *ws float 1*ws float 1*ws float *ws nl
count_line = *ws positive_integer *ws nl
count_list_line = *ws positive_integer *(1*ws positive_integer) *ws nl
float_list_line = *ws float *(1*ws float) *ws nl
zero_integer = 1*"0"
zero_count_line = *ws zero_integer *ws [nl]
blank_line = *ws nl
zero_atom = zero_count_line (blank_line (blank_line / "") / "")
typed_body = count_line count_list_line float_list_line 1*type_block *section
type_block = symbol_line nl coord_label nl vector_atom_line *(nl vector_atom_line) [nl]
symbol_line = *ws symbol *ws
symbol = ALPHA *(ALPHA / DIGIT / "_")
coord_label = *ws "Coordinates of Component" 1*ws positive_integer *ws
vector_atom_line = *ws float 1*ws float 1*ws float 1*ws integer [1*ws integer] *ws
scalar_atom_line = *ws float 1*ws integer 1*ws integer *ws
atom_line = vector_atom_line
; A blank_line is a section only when a block follows, including a velocity block.
; Otherwise that line is line 1 of the next frame.
section = blank_line (1*section_type_block_vector / 1*section_type_block_scalar / 1*generic_type_block)
section_type_block_vector = symbol_line nl section_label_vector nl vector_section_line *(nl vector_section_line) [nl]
section_type_block_scalar = symbol_line nl section_label_scalar nl scalar_atom_line *(nl scalar_atom_line) [nl]
generic_type_block = symbol_line nl generic_label nl token_line *(nl token_line) [nl]
generic_label = *ws symbol *(1*ws (symbol / positive_integer)) *ws
token_line = *ws (float / integer) *(1*ws (float / integer)) *ws
vector_section_line = *ws float 1*ws float 1*ws float 1*ws integer 1*ws integer *ws
section_kind_vector = "Velocities" / "Forces" / "Magmoms" / "Displacements" / "Spreads"
section_kind_scalar = "Energies" / "Charges" / "Spins"
section_kind = section_kind_vector / section_kind_scalar
section_label_vector = *ws section_kind_vector 1*ws "of Component" 1*ws positive_integer *ws
section_label_scalar = *ws section_kind_scalar 1*ws "of Component" 1*ws positive_integer *ws
float = finite_float / non_finite
finite_float = ["+" / "-"] (1*DIGIT ["." *DIGIT] / "." 1*DIGIT) [("e" / "E") ["+" / "-"] 1*DIGIT]
non_finite = ["+" / "-"] ("infinity" / "nan" / "inf")
integer = 1*DIGIT
positive_integer = (%x31-39) *DIGIT
ws = SP / HTAB
NL = CRLF / LF
nl = NL
\end{lstlisting}
"""


def abnf_placeholder() -> None:
    """Write the appendix listing.

    The older draft is not the source. An empty user line, an empty second
    header line, and a blank line that is the next frame are part of this text.
    """
    path = OUT / "con_abnf.tex"
    path.write_text(ABNF_LISTING)


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    workflow()
    architecture()
    abnf_placeholder()
    from plot_figures import main as plot_data

    plot_data()


if __name__ == "__main__":
    main()
