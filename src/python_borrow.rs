// Borrows of `ConFrame` and `Atom` objects that other threads share.
//
// Included from `python.rs` so these items share that module.
//
// PyO3 checks a pyclass borrow at runtime and fails it when it overlaps an
// incompatible one. With the GIL that only happens on reentry. On a
// free-threaded build it happens whenever two threads touch one object, so
// these borrows wait for the other thread instead. Each borrow keeps the
// borrow flag as the lock: shared borrows run together, an exclusive one
// runs alone, and a waiting thread detaches so the holder can reach a
// stop-the-world pause. A borrow that conflicts with one the same thread
// already holds can never be released while it waits, so it fails at once
// with PyO3's `RuntimeError`, as it does with the GIL.

use std::cell::RefCell;
use std::ops::{Deref, DerefMut};

use pyo3::PyClass;
use pyo3::pyclass::boolean_struct::False as Mutable;

thread_local! {
    /// Objects this thread borrows through `shared` or `exclusive`.
    static HELD: RefCell<Vec<(usize, bool)>> = const { RefCell::new(Vec::new()) };
}

fn held_conflicts(ptr: usize, exclusive: bool) -> bool {
    HELD.with(|held| {
        held.borrow()
            .iter()
            .any(|&(at, mutable)| at == ptr && (mutable || exclusive))
    })
}

struct HeldBorrow(usize, bool);

impl HeldBorrow {
    fn push(ptr: usize, exclusive: bool) -> Self {
        HELD.with(|held| held.borrow_mut().push((ptr, exclusive)));
        Self(ptr, exclusive)
    }
}

impl Drop for HeldBorrow {
    fn drop(&mut self) {
        HELD.with(|held| {
            let mut held = held.borrow_mut();
            if let Some(at) = held.iter().rposition(|&entry| entry == (self.0, self.1)) {
                held.swap_remove(at);
            }
        });
    }
}

fn wait_for_borrow<R, E: Into<PyErr>>(
    py: Python<'_>,
    ptr: usize,
    exclusive: bool,
    mut attempt: impl FnMut() -> Result<R, E>,
) -> PyResult<R> {
    let mut waits = 0u32;
    loop {
        match attempt() {
            Ok(borrowed) => return Ok(borrowed),
            Err(err) if held_conflicts(ptr, exclusive) => return Err(err.into()),
            Err(_) => {
                waits = waits.saturating_add(1);
                py.detach(|| {
                    if waits < 64 {
                        std::thread::yield_now();
                    } else {
                        std::thread::sleep(std::time::Duration::from_micros(20));
                    }
                });
            }
        }
    }
}

/// A shared borrow that waits out another thread's exclusive one.
struct Shared<'py, T: PyClass> {
    guard: PyRef<'py, T>,
    _held: HeldBorrow,
}

/// An exclusive borrow that waits out every other thread's borrow.
struct Exclusive<'py, T: PyClass<Frozen = Mutable>> {
    guard: PyRefMut<'py, T>,
    _held: HeldBorrow,
}

fn shared<'py, T: PyClass>(obj: &Bound<'py, T>) -> PyResult<Shared<'py, T>> {
    let ptr = obj.as_ptr() as usize;
    let guard = wait_for_borrow(obj.py(), ptr, false, || obj.try_borrow())?;
    Ok(Shared {
        guard,
        _held: HeldBorrow::push(ptr, false),
    })
}

fn exclusive<'py, T: PyClass<Frozen = Mutable>>(
    obj: &Bound<'py, T>,
) -> PyResult<Exclusive<'py, T>> {
    let ptr = obj.as_ptr() as usize;
    let guard = wait_for_borrow(obj.py(), ptr, true, || obj.try_borrow_mut())?;
    Ok(Exclusive {
        guard,
        _held: HeldBorrow::push(ptr, true),
    })
}

impl<T: PyClass> Deref for Shared<'_, T> {
    type Target = T;
    fn deref(&self) -> &T {
        &self.guard
    }
}

impl<T: PyClass<Frozen = Mutable>> Deref for Exclusive<'_, T> {
    type Target = T;
    fn deref(&self) -> &T {
        &self.guard
    }
}

impl<T: PyClass<Frozen = Mutable>> DerefMut for Exclusive<'_, T> {
    fn deref_mut(&mut self) -> &mut T {
        &mut self.guard
    }
}

/// A copy of `obj` when it is an `Atom`, taken with a waiting borrow.
fn atom_datum(obj: &Bound<'_, PyAny>) -> Option<PyResult<PyAtomDatum>> {
    let atom = obj.cast::<PyAtomDatum>().ok()?;
    Some(shared(atom).map(|atom| atom.clone()))
}

/// Every `ConFrame` of a sequence, each held by a waiting shared borrow.
fn shared_frames<'py>(obj: &Bound<'py, PyAny>) -> PyResult<Vec<Shared<'py, PyConFrame>>> {
    let frames = obj.extract::<Vec<Bound<'py, PyConFrame>>>()?;
    frames.iter().map(shared).collect()
}
