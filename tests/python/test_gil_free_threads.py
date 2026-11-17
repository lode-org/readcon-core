from __future__ import annotations

import concurrent.futures
import hashlib
import threading
import time
from pathlib import Path


def _write_large_con(path: Path, n_frames: int, n_atoms: int) -> None:
    header = (
        "\n"
        '{"con_spec_version":3,"con_spec_minor":1,'
        '"units":{"length":"angstrom","energy":"eV"}}\n'
        "30.000000 30.000000 30.000000\n90.000000 90.000000 90.000000\n\n\n1\n"
        f"{n_atoms}\n63.546000\nCu\nCoordinates of Component 1\n"
    )
    parts: list[str] = []
    for frame in range(n_frames):
        parts.append(header)
        for atom in range(n_atoms):
            x = ((frame + atom) % 17) + 0.111111
            y = ((frame * 3 + atom) % 19) + 0.222222
            z = ((frame + atom * 7) % 23) + 0.333333
            parts.append(f"{x:.8f} {y:.8f} {z:.8f} 0 {atom}\n")
    path.write_text("".join(parts), encoding="utf-8")


def _sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def test_read_write_concurrent_matches_serial(tmp_path: Path) -> None:
    import readcon

    n_workers = 6
    n_frames = 10
    n_atoms = 3000
    paths = []
    for i in range(n_workers):
        path = tmp_path / f"in-{i}.con"
        _write_large_con(path, n_frames=n_frames, n_atoms=n_atoms)
        paths.append(path)

    serial = {}
    for path in paths:
        frames = readcon.read_con(str(path), n_threads=1)
        serial[path.name] = _sha256_bytes(
            readcon.write_con_string(frames, canonical=True).encode("utf-8")
        )

    def worker(path: Path) -> tuple[str, str]:
        frames = readcon.read_con(str(path), n_threads=1)
        out = tmp_path / f"out-{path.name}"
        readcon.write_con(str(out), frames, canonical=True, n_threads=1)
        digest = _sha256_bytes(out.read_bytes())
        return path.name, digest

    with concurrent.futures.ThreadPoolExecutor(max_workers=n_workers) as pool:
        results = dict(pool.map(worker, paths))

    assert results == serial


def test_read_con_releases_gil(tmp_path: Path) -> None:
    import readcon

    path = tmp_path / "gil-read.con"
    _write_large_con(path, n_frames=20, n_atoms=5000)
    ticks = 0
    stop = threading.Event()

    def counter() -> None:
        nonlocal ticks
        while not stop.is_set():
            ticks += 1

    t = threading.Thread(target=counter, daemon=True)
    t.start()
    time.sleep(0.05)
    before = ticks
    _ = readcon.read_con(str(path), n_threads=1)
    after = ticks
    stop.set()
    t.join(timeout=1.0)

    assert after - before > 50_000
