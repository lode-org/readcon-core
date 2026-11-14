==============================
Notes after the tagged release
==============================


These calls are in the tree and not yet in a numbered release.

Short decimals
--------------

A round-trip coordinate that is an exact decimal of at most six places is
spelled directly. Two spellings that are equally close take the even last
digit, the same side ryu prints, and a place is dropped when the shorter
spelling still round-trips. Any other finite value uses ryu. The file still
reads back as the same binary64 value.

.. code:: python

    """Short CON decimals match a round trip, including a tie."""

    import sys
    import tempfile
    from pathlib import Path

    import readcon


    def main() -> None:
        atom = readcon.Atom(
            "Cu",
            1.5,
            0.25,
            2.0,
            fixed=[False, False, False],
            atom_id=1,
            mass=63.546,
        )
        frame = readcon.ConFrame((10.0, 10.0, 10.0), (90.0, 90.0, 90.0), [atom])
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "short.con"
            readcon.write_con(str(path), [frame])
            text = path.read_text(encoding="utf-8")
            for spelling in ("1.5", "0.25", "2.0"):
                if spelling not in text:
                    raise SystemExit(f"missing short decimal {spelling}")
            back = readcon.read_con(str(path))
            got = back[0].atoms[0]
            if (got.x, got.y, got.z) != (1.5, 0.25, 2.0):
                raise SystemExit(f"round trip changed coordinates: {got.x} {got.y} {got.z}")


    if __name__ == "__main__":
        main()
        sys.exit(0)

.. code:: rust

    //! Examples for the notes after the tagged release.
    //!
    //! Short decimals, a crash-safe path publish, and a same-length rewrite.

    use std::fs;
    use std::path::Path;

    use readcon_core::iterators::read_first_frame;
    use readcon_core::types::ConFrameBuilder;
    use readcon_core::writer::{rewrite_frame_refs_to_path, write_frame_refs_to_path};

    fn one_atom(x: f64, fixed: [bool; 3], atom_id: u64) -> readcon_core::types::ConFrame {
        let mut builder = ConFrameBuilder::new([10.0, 10.0, 10.0], [90.0, 90.0, 90.0]);
        builder.add_atom("Cu", x, 0.25, 2.0, fixed, atom_id, 63.546);
        builder.build().expect("frame")
    }

    fn scratches(dir: &Path) -> Vec<String> {
        fs::read_dir(dir)
            .expect("dir")
            .filter_map(|item| item.ok())
            .map(|item| item.file_name().to_string_lossy().into_owned())
            .filter(|name| name.starts_with(".readcon-write-"))
            .collect()
    }

    #[test]
    fn short_decimals_round_trip() {
        let dir = Path::new("build/test").join(format!("rc-doc-fmt-{}", std::process::id()));
        let _ = fs::remove_dir_all(&dir);
        fs::create_dir_all(&dir).unwrap();
        let path = dir.join("short.con");
        let frame = one_atom(1.5, [false, false, false], 1);
        write_frame_refs_to_path(&path, &[&frame], 1, None, false, false).unwrap();
        let text = fs::read_to_string(&path).unwrap();
        assert!(text.contains("1.5") && text.contains("0.25") && text.contains("2.0"), "{text}");
        assert!(scratches(&dir).is_empty());
        let back = read_first_frame(&path).unwrap();
        assert_eq!(back.atom_data[0].x(), 1.5);
        let _ = fs::remove_dir_all(&dir);
    }

    #[test]
    fn rewrite_publishes_one_complete_file() {
        let dir = Path::new("build/test").join(format!("rc-doc-rew-{}", std::process::id()));
        let _ = fs::remove_dir_all(&dir);
        fs::create_dir_all(&dir).unwrap();
        let path = dir.join("traj.con");
        let first = one_atom(1.0, [false, false, false], 1);
        write_frame_refs_to_path(&path, &[&first], 1, None, false, false).unwrap();
        let next = one_atom(3.5, [false, false, false], 1);
        rewrite_frame_refs_to_path(&path, &[&next], 1, None, false, true, false).unwrap();
        let spare = dir.join("traj.con.rewrite");
        assert!(!spare.exists(), "keep_spare false left the spare");
        let text = fs::read_to_string(&path).unwrap();
        assert!(text.contains("3.5"), "{text}");
        assert!(scratches(&dir).is_empty());
        let _ = fs::remove_dir_all(&dir);
    }

.. code:: c

    /* Short decimals of at most six places are spelled directly. */
    #include "readcon-core.h"

    #include <stdio.h>
    #include <stdlib.h>
    #include <string.h>

    static void die(const char *what) {
        const char *detail = rkr_last_error_message();
        fprintf(stderr, "%s%s%s\n", what, detail ? ": " : "", detail ? detail : "");
        exit(1);
    }

    int main(int argc, char **argv) {
        const char *dir = argc > 1 ? argv[1] : ".";
        char path[512];
        snprintf(path, sizeof path, "%s/short.con", dir);
        double cell[3] = {10.0, 10.0, 10.0};
        double angles[3] = {90.0, 90.0, 90.0};
        struct RKRConFrameBuilder *builder =
            rkr_frame_new(cell, angles, NULL, NULL, NULL, NULL);
        if (builder == NULL) {
            die("builder");
        }
        if (rkr_frame_add_atom(builder, "Cu", 1.5, 0.25, 2.0, false, 1, 63.546) !=
            RKR_STATUS_SUCCESS) {
            die("add atom");
        }
        struct RKRConFrame *frame = rkr_frame_builder_build(builder);
        free_rkr_frame_builder(builder);
        if (frame == NULL) {
            die("build");
        }
        struct RKRConFrameWriter *writer = create_writer_from_path_round_trip_c(path);
        if (writer == NULL) {
            die("writer");
        }
        const struct RKRConFrame *handles[1] = {frame};
        if (rkr_writer_extend(writer, handles, 1) != RKR_STATUS_SUCCESS) {
            die("write");
        }
        free_rkr_writer(writer);
        free_rkr_frame(frame);
        FILE *file = fopen(path, "r");
        if (file == NULL) {
            die("open");
        }
        char text[4096];
        size_t n = fread(text, 1, sizeof text - 1, file);
        text[n] = '\0';
        fclose(file);
        if (strstr(text, "1.5") == NULL || strstr(text, "0.25") == NULL ||
            strstr(text, "2.0") == NULL) {
            die("short decimal spelling");
        }
        /* The cdylib's process teardown can stall after a successful check. */
        _Exit(0);
    }

Publishing a path
-----------------

A path write stores the new bytes before it publishes them. On Linux the
store is an unnamed file. ``linkat`` and ``rename`` run in a helper that
outlives the writer, so a kill does not leave a partial destination or a
scratch name. Where that unnamed file is unavailable, a
``.readcon-write-*.tmp`` is removed if the write fails. The published path
is either the previous complete file or the finished new one. CON-bin uses
the same publish. The new inode is a second copy until the rename.

Rewrite
-------

``rewrite_frame_refs_to_path``, ``write_con`` with ``rewrite=True``, and
``rkr_rewrite_path`` fill a spare named ``path`` plus ``.rewrite`` and rename it
over the path. ``keep_spare=True`` parks the previous inode at that spare, so
the trajectory occupies two copies. ``keep_spare=False`` deletes the spare
after the rename, and the next rewrite allocates again. A partial spare is
never given the published name. A crash leaves the published path as the
previous complete file, or as the finished new one once the rename has run.

.. code:: python

    """Rewrite replaces the path only after the spare is a complete file."""

    import sys
    import tempfile
    from pathlib import Path

    import readcon


    def frame_at(x: float) -> readcon.ConFrame:
        atom = readcon.Atom(
            "Cu",
            x,
            0.0,
            0.0,
            fixed=[False, False, False],
            atom_id=1,
            mass=63.546,
        )
        return readcon.ConFrame((10.0, 10.0, 10.0), (90.0, 90.0, 90.0), [atom])


    def main() -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "traj.con"
            spare = Path(str(path) + ".rewrite")
            readcon.write_con(str(path), [frame_at(1.0)])
            readcon.write_con(str(path), [frame_at(3.5)], rewrite=True, keep_spare=False)
            if spare.exists():
                raise SystemExit("keep_spare=False left the spare")
            text = path.read_text(encoding="utf-8")
            if "3.5" not in text or "1.0" in text.split("Coordinates")[-1]:
                raise SystemExit("published file is not the finished rewrite")
            readcon.write_con(str(path), [frame_at(4.0)], rewrite=True, keep_spare=True)
            if not spare.exists():
                raise SystemExit("keep_spare=True did not park the previous inode")


    if __name__ == "__main__":
        main()
        sys.exit(0)

.. code:: c

    /* The published path is the previous file or the finished rewrite. */
    #include "readcon-core.h"

    #include <stdio.h>
    #include <stdlib.h>
    #include <string.h>
    #include <unistd.h>

    static void die(const char *what) {
        const char *detail = rkr_last_error_message();
        fprintf(stderr, "%s%s%s\n", what, detail ? ": " : "", detail ? detail : "");
        exit(1);
    }

    static struct RKRConFrame *one_atom(double x) {
        double cell[3] = {10.0, 10.0, 10.0};
        double angles[3] = {90.0, 90.0, 90.0};
        struct RKRConFrameBuilder *builder =
            rkr_frame_new(cell, angles, NULL, NULL, NULL, NULL);
        if (builder == NULL) {
            die("builder");
        }
        if (rkr_frame_add_atom(builder, "Cu", x, 0.0, 0.0, false, 1, 63.546) !=
            RKR_STATUS_SUCCESS) {
            die("add atom");
        }
        struct RKRConFrame *frame = rkr_frame_builder_build(builder);
        free_rkr_frame_builder(builder);
        if (frame == NULL) {
            die("build");
        }
        return frame;
    }

    static void write_fresh(const char *path, struct RKRConFrame *frame) {
        struct RKRConFrameWriter *writer = create_writer_from_path_round_trip_c(path);
        if (writer == NULL) {
            die("writer");
        }
        const struct RKRConFrame *handles[1] = {frame};
        if (rkr_writer_extend(writer, handles, 1) != RKR_STATUS_SUCCESS) {
            die("write");
        }
        free_rkr_writer(writer);
    }

    int main(int argc, char **argv) {
        const char *dir = argc > 1 ? argv[1] : ".";
        char path[512];
        char spare[520];
        snprintf(path, sizeof path, "%s/traj.con", dir);
        snprintf(spare, sizeof spare, "%s.rewrite", path);
        struct RKRConFrame *first = one_atom(1.0);
        write_fresh(path, first);
        free_rkr_frame(first);
        struct RKRConFrame *next = one_atom(3.5);
        const struct RKRConFrame *handles[1] = {next};
        if (rkr_rewrite_path(path, handles, 1, 1, 0) != RKR_STATUS_SUCCESS) {
            die("rewrite");
        }
        free_rkr_frame(next);
        if (access(spare, F_OK) == 0) {
            die("keep_spare 0 left the spare");
        }
        FILE *file = fopen(path, "r");
        if (file == NULL) {
            die("open");
        }
        char text[4096];
        size_t n = fread(text, 1, sizeof text - 1, file);
        text[n] = '\0';
        fclose(file);
        if (strstr(text, "3.5") == NULL) {
            die("published path is not the finished rewrite");
        }
        _Exit(0);
    }

Ranked writes
-------------

One ``MPI_Allgather`` shares each rank's byte length and frame count.
The default store is a fresh file, not a spare reused in place. Rank 0
renames that file onto the path only after every byte is stored. On ext2,
ext3, ext4, XFS, and btrfs, rank 0 writes the slices in order. Other
filesystems keep one write per rank. ``READCON_RANKED_WRITE=parallel`` or
``sequential``, read on rank 0, overrides that. One gather of the frame offsets and block hashes then writes the ``.rcidx``
sidecar. Until the rename the new bytes are a second copy, and the
published path is still the previous complete file. After the rename it
is the finished new one.

.. code:: python

    """A fresh-file publish leaves no scratch name beside the path.

    Ranked writes do this by default. One MPI_Allgather shares each rank's
    byte length and frame count. Rank 0 renames the finished file onto the
    path, then one gather writes the .rcidx sidecar. Spare reuse is not the
    default.
    """

    import sys
    import tempfile
    from pathlib import Path

    import readcon


    def main() -> None:
        atom = readcon.Atom(
            "Cu",
            1.25,
            0.0,
            0.0,
            fixed=[True, False, False],
            atom_id=7,
            mass=63.546,
        )
        frame = readcon.ConFrame((8.0, 8.0, 8.0), (90.0, 90.0, 90.0), [atom])
        with tempfile.TemporaryDirectory() as tmp:
            directory = Path(tmp)
            path = directory / "ranked.con"
            readcon.write_con(str(path), [frame])
            scratches = [
                item.name
                for item in directory.iterdir()
                if item.name.startswith(".readcon-write-")
            ]
            if scratches:
                raise SystemExit(f"publish left a scratch name: {scratches}")
            back = readcon.read_first_frame(str(path))
            got = back.atoms[0]
            if got.symbol != "Cu" or got.atom_id != 7 or got.x != 1.25:
                raise SystemExit("fresh file dropped a field the text round trip keeps")
            if list(got.fixed) != [True, False, False]:
                raise SystemExit(f"fixed flags were not kept: {got.fixed}")


    if __name__ == "__main__":
        main()
        sys.exit(0)

.. code:: c

    /* A finished publish leaves the path and no scratch name.

       Ranked writes are fresh-file by default. One MPI_Allgather shares each
       rank's byte length and frame count. Rank 0 renames the finished file
       onto the path. One gather then writes the .rcidx sidecar. The call is
       rkr_mpi_write_block. Spare reuse is not the default.
    */
    #include "readcon-core.h"

    #include <dirent.h>
    #include <stdio.h>
    #include <stdlib.h>
    #include <string.h>

    static void die(const char *what) {
        const char *detail = rkr_last_error_message();
        fprintf(stderr, "%s%s%s\n", what, detail ? ": " : "", detail ? detail : "");
        exit(1);
    }

    int main(int argc, char **argv) {
        const char *dir = argc > 1 ? argv[1] : ".";
        char path[512];
        snprintf(path, sizeof path, "%s/ranked.con", dir);
        double cell[3] = {8.0, 8.0, 8.0};
        double angles[3] = {90.0, 90.0, 90.0};
        struct RKRConFrameBuilder *builder =
            rkr_frame_new(cell, angles, NULL, NULL, NULL, NULL);
        if (builder == NULL) {
            die("builder");
        }
        if (rkr_frame_add_atom_with_fixed_mask(builder, "Cu", 1.25, 0.0, 0.0, true, false,
                                               false, 7, 63.546) != RKR_STATUS_SUCCESS) {
            die("add atom");
        }
        struct RKRConFrame *frame = rkr_frame_builder_build(builder);
        free_rkr_frame_builder(builder);
        if (frame == NULL) {
            die("build");
        }
        struct RKRConFrameWriter *writer = create_writer_from_path_round_trip_c(path);
        if (writer == NULL) {
            die("writer");
        }
        const struct RKRConFrame *handles[1] = {frame};
        if (rkr_writer_extend(writer, handles, 1) != RKR_STATUS_SUCCESS) {
            die("write");
        }
        free_rkr_writer(writer);
        free_rkr_frame(frame);
        DIR *listing = opendir(dir);
        if (listing == NULL) {
            die("directory");
        }
        struct dirent *entry;
        while ((entry = readdir(listing)) != NULL) {
            if (strncmp(entry->d_name, ".readcon-write-", 15) == 0) {
                die("publish left a scratch name");
            }
        }
        closedir(listing);
        struct RKRConFrame *back = rkr_read_first_frame(path);
        if (back == NULL) {
            die("read");
        }
        uintptr_t n = 0;
        const double *xyz = rkr_frame_xyz_f64(back, &n);
        if (xyz == NULL || n < 1 || xyz[0] != 1.25) {
            die("published file is not the finished frame");
        }
        free_rkr_frame(back);
        _Exit(0);
    }

The default collective call is ``rkr_mpi_write_block`` in C and ``write_con``
with ``comm=`` in Python. Rust calls ``write_block`` or ``write_ranked_bytes``
with rewrite left off. The same ``rewrite`` and ``keep_spare`` switch used for
a threaded rewrite opts the ranked write into the spare: those Rust
functions take the two flags, ``write_con`` takes ``rewrite=True`` together
with ``comm=``, and C calls ``rkr_mpi_rewrite_block``. ``keep_spare`` parks the
previous inode at ``path`` plus ``.rewrite``, a second copy of the file. The
default leaves no spare. ``tests/doc_release_notes.rs`` runs the fresh-file
publish.

Serial CON text
---------------

The serial writer formats from the column arrays. The bytes match a
binding rewrite. It does not build a heap tail for each atom.

Gzip members
------------

A ``.gz`` write still splits a wide frame into independent members, so a
read can inflate them together. Formatting uses the caller's thread count.
Deflate uses one worker per core when the caller did not ask for two or
more threads, instead of one deflate thread for every member. One member
stays one thread.

.. code:: python

    import readcon
    readcon.write_con("frame.con.gz", frames, n_threads=1)

What a round trip keeps
-----------------------

A text round trip keeps the cell, symbols, coordinates, masses, atom ids,
fixed flags, and velocities when they were present. NaN and infinity are
spelled and rejected on read, so a file that contains them is not a round
trip. CON-bin version 2 stores positions, velocities (a missing section as
zeros), forces when any frame has them, masses, the cell, atom ids, and
the per-axis fixed flags. It does not store symbols. Version 1 files still
open and hold positions and velocities only. binary32 does not keep
binary64 bits. See the CON-bin section of the how-to.

The cxx wrap pin
----------------

``scripts/check_cxx_wrap_pin.sh`` rebuilds the slim cxx archive with the
saved source-date-epoch and fails when that digest is not the wrap pin.
A push that changes only ``bench/**`` does not run the job. A stale pin
is reported before a tag is cut. The upload still refuses a different
digest.

.. code:: shell

    bash scripts/check_cxx_wrap_pin.sh
