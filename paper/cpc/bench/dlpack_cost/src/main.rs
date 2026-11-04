//! Time a borrowed DLPack view of positions against an explicit copy.
//!
//! Six timed repeats follow one warm-up. Each repeat runs the view and the
//! copy, and the starting arm alternates. The program prints one raw time
//! per line. A later step reports the median and the type 7 interquartile
//! range.

use readcon_core::types::ConFrameBuilder;
use std::hint::black_box;
use std::time::Instant;

const ATOMS: usize = 65_536;
const REPEATS: usize = 6;

fn builder() -> ConFrameBuilder {
    let mut frame = ConFrameBuilder::new([40.0, 40.0, 40.0], [90.0, 90.0, 90.0]);
    for i in 0..ATOMS {
        let x = (i % 64) as f64 * 0.5;
        let y = ((i / 64) % 64) as f64 * 0.5;
        let z = (i / 4096) as f64 * 0.5;
        frame.add_atom("Cu", x, y, z, [false, false, false], i as u64, 63.546);
    }
    frame
}

fn checksum_view(frame: &ConFrameBuilder) -> f64 {
    let tensor = frame.positions_dlpack().expect("positions view");
    let ptr = tensor.data_ptr::<f64>().expect("f64 view");
    let n = tensor.shape().iter().product::<i64>() as usize;
    let mut sum = 0.0;
    for i in 0..n {
        sum += unsafe { *ptr.add(i) };
    }
    sum
}

fn checksum_copy(frame: &ConFrameBuilder) -> f64 {
    let tensor = frame.positions_dlpack().expect("positions view");
    let ptr = tensor.data_ptr::<f64>().expect("f64 view");
    let n = tensor.shape().iter().product::<i64>() as usize;
    let mut owned = vec![0.0_f64; n];
    unsafe {
        std::ptr::copy_nonoverlapping(ptr, owned.as_mut_ptr(), n);
    }
    owned.iter().sum()
}

fn time_arm(frame: &ConFrameBuilder, view: bool) -> (u128, f64) {
    let start = Instant::now();
    let sum = if view {
        checksum_view(frame)
    } else {
        checksum_copy(frame)
    };
    let elapsed = start.elapsed().as_nanos();
    (elapsed, black_box(sum))
}

fn main() {
    let frame = builder();
    let (warm_view, warm_copy) = (checksum_view(&frame), checksum_copy(&frame));
    assert_eq!(warm_view, warm_copy);
    println!("atoms {ATOMS}");
    println!("warmup_sum {warm_view}");
    for repeat in 0..REPEATS {
        let view_first = repeat % 2 == 0;
        let (view_ns, copy_ns) = if view_first {
            let (v, _) = time_arm(&frame, true);
            let (c, _) = time_arm(&frame, false);
            (v, c)
        } else {
            let (c, _) = time_arm(&frame, false);
            let (v, _) = time_arm(&frame, true);
            (v, c)
        };
        println!("repeat {repeat} view_ns {view_ns} copy_ns {copy_ns}");
    }
}
