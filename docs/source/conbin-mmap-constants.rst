=============================
CON-bin measurement constants
=============================


The rows of ``benches/conbin_mmap_constants.tsv`` point at these sections.
The paper is ``paper/cpc/src/conbin-mmap.tex``.

field\_bytes
------------

Magic, version, flags, frames, atoms and offset use 8+4+4+8+8+8 bytes.

header\_page
------------

The payload starts on a page boundary.
The stored offset equals that one host page.
On this host sysconf(SC\_PAGESIZE) returns 4096 bytes.

madv\_sequential
----------------

MADV\_SEQUENTIAL marks one forward pass over the mapping.
man 2 madvise defines that advice.

madv\_willneed
--------------

MADV\_WILLNEED asks the kernel to fault the pages ahead.
The caller is about to read those pages.
man 2 madvise names that advice.

madv\_hugepage
--------------

MADV\_HUGEPAGE requests pages of Hugepagesize.
Transparent pages are in madvise mode on this kernel.
That mode is CONFIG\_TRANSPARENT\_HUGEPAGE\_MADVISE.
File-backed pages of that size also need CONFIG\_READ\_ONLY\_THP\_FOR\_FS.
/proc/config.gz leaves that option unset.
Documentation/admin-guide/mm/transhuge.rst records the option.
FilePmdMapped stayed 0.
The advice is the documented switch.
The advice changes nothing while that option is unset.

madv\_populate\_read
--------------------

Linux 5.14 added MADV\_POPULATE\_READ.
The call waits until the pages are resident.
The call returns an error on failure.
man 2 madvise says MAP\_POPULATE hides errors.
MADV\_POPULATE\_READ applies to a span after mmap returns.

map\_flags
----------

memmap2 map\_copy uses MAP\_PRIVATE and PROT\_READ|PROT\_WRITE.
A store copies the page and leaves the file bytes unchanged.
mmap(2) defines MAP\_PRIVATE.

max\_sectors\_kb
----------------

queue/max\_sectors\_kb reads 1280 on this host.
The sysfs-block ABI calls that the largest request, in kibibytes.
Times 1024 is one readahead piece.
The ABI text is the sysfs-block page for max\_sectors\_kb.

max\_request
------------

That request is max\_sectors\_kb times 1024 bytes.
On this host 1280 \* 1024 = 1310720.
The piece is then aligned down to the page.

nr\_requests
------------

queue/nr\_requests reads 256 on this host.
blk-mq applies this depth to each hardware queue.
The depth is one pool per queue, not one pool for the device.
The ABI text is the sysfs-block page for nr\_requests.

nr\_hw\_queues
--------------

queue/nr\_hw\_queues is absent on this host.
*sys/block device mq* has one directory.
That directory is one hardware queue.

read\_ahead
-----------

The kernel readahead window is read\_ahead\_kb times 1024.
A shorter hint still pulls this window.
On this host read\_ahead\_kb is 128.

worker\_span
------------

The explicit chunked prefetch modes use this span.
At 8 workers on this host the span is 41943040 bytes.
sum\_mapped reads the file as one stream.

rotational
----------

queue/rotational on this host reads 1.
The row records that value.
The plan stays one stream.
A virtio disk can report 1.
A sequential read can still run far above spinning-disk rates.

one\_stream
-----------

Two sessions on one boot compared one stream with a stream per span.
Neither plan won at every thread count in both.
The host cache was not controlled.
The default stays one stream, the simpler plan.

split\_streams
--------------

Each worker readaheads its own span.
The one\_stream section records the comparison and the default.

queue\_missing
--------------

A partition is walked to the parent disk.
That disk is the sysfs node for queue/.
The queue file can still be absent on btrfs, tmpfs or overlayfs.
It can also be absent on Network File System (NFS).
The byte sizes are then the host page.
The unit is the one madvise accepts, and the depth is 1.

threads
-------

os.sched\_getaffinity(0) lists the allowed CPUs.
The key is physical\_package\_id and core\_id from cpu topology sysfs.
Every integer from 1 through that count is a thread count.
The count uses no host literal.

repeats
-------

1 - 2\*\*(1-n) >= 0.95 at n = 6.
The reported sample is the upper median, sorted index n//2.

drop\_caches
------------

Documentation/admin-guide/sysctl/vm.rst defines the bit mask.
The value 3 drops the page cache, dentries and inodes.

frames
------

The frame count is 100 at every size in the paper size series.

atoms
-----

The million-atom file in that size series has 1000000 atoms.

payload\_bytes
--------------

The shared rate numerator is frames times atoms times 3 times 8 times 2.
That product is 4800000000 bytes.

eagain\_retries
---------------

man 2 madvise defines EAGAIN.
EAGAIN means a kernel resource was temporarily unavailable.
One retry per page is the fault work that advice was asked to do.

warmup
------

Repeat 0 is the first touch of that cell.
Repeat 0 is kept.
The upper median is sorted index n//2.
The same rule applies to every reader.

order\_seed
-----------

random.Random(boot\_id) shuffles modes and thread counts.
The shuffle is inside each repeat.
The seed is the boot, and the JSON records it.

rss\_column
-----------

The kernel high-water mark of each reader process is VmHWM, in kB.
The mark comes from /proc/self/status.
There is no sampling interval.
An h5py pool adds the parent's mark and each worker's mark.
That sum is an upper bound on the concurrent peak.
VmHWM omits page cache that no process maps.
The cgroup high-water mark is recorded beside it as cgroup\_peak\_kb.
proc.html and the cgroup-v2 page on docs.kernel.org describe the files.

sum\_exact
----------

write\_known stores i/4 and -i/2.
Every value and partial sum is a multiple of 2^-2.
The magnitude is at most sum|x| = 13752.
That magnitude is far below 2^51.
2^51 equals 2^53 times 2^-2.
Every binary64 addition is therefore exact.

pid\_read\_bytes
----------------

The parent reads the child's pid until a newline.
64 bytes covers one pid line.
The loop stops at the newline.
A smaller buffer yields the same pid.

pss\_poll\_s
------------

The removed reader loop slept 0.02 s between smaps\_rollup reads.
That interval had no derivation.
The reader now reports VmHWM after the process exits.
No poll remains.

handshake\_child\_s
-------------------

The removed reader loop slept 0.005 s.
The child was waiting for a flag file.
The child now blocks in read on a pipe until the parent writes one byte.
POSIX read is the wait.
No sleep remains.

handshake\_parent\_tries
------------------------

The removed reader loop polled a pid file 500 times.
It slept 0.01 s between polls.
The parent now blocks in read until the child writes its pid.
No poll remains, and no sleep remains.

disk\_cache\_mode
-----------------

The probe discovers the disk from st\_dev of the work directory.
It then reads queue/write\_cache and cache\_type.
Both read write through on this boot.
The boot id is 7d1fc2c7-0885-41f6-9949-83f54b109ae2.
That read was at unix time 1793667550.
After drop\_caches 3 the benchmark file read at 397.7 MB/s.
An O\_DIRECT write then read at 2934.1 MB/s buffered.
The two O\_DIRECT reads were 2188.4 MB/s and 2246.7 MB/s.

guest\_drop
-----------

drop\_caches 3 clears the guest page cache.
Documentation/admin-guide/sysctl/vm.rst defines that drop.
The disk\_cache\_mode row leaves the host cache in the path.
The JSON sample key is guest\_drop.
The later session has its first sample at unix time 1793662535.
Its slowest sample is the first read of each file.
No sample records whether a host cache served it.

probe\_size
-----------

1 GiB, 2^30 bytes, is a multiple of probe\_chunk.
time.perf\_counter resolves 1 ns (time.get\_clock\_info).
A read of at least 0.18 s resolves to better than 1 part in 10^8.
The size is a measured length, above any timing floor.

probe\_chunk
------------

1 MiB is 2^20 bytes.
O\_DIRECT requires a multiple of queue/logical\_block\_size.
2^20 is a multiple of 512 and of 4096.
The probe asserts that.

probe\_read\_block
------------------

8 MiB is 2^23 bytes.
The buffered read uses this multiple of the page.
The block is the buffered read size.

probe\_seed\_buffered
---------------------

This is one of three distinct seeds.
The three probe files then carry different bytes.

probe\_seed\_direct
-------------------

This is the second distinct seed.
Its bytes differ from probe\_seed\_buffered.

probe\_seed\_dsync
------------------

This is the third distinct seed.
Its bytes differ from the other two probe files.

probe\_weyl
-----------

The value is the fractional part of the golden ratio, times 2^64.
The Weyl increment makes successive 8-byte words differ.
It only separates the byte patterns.
