A materialized frame copies its atom list under one critical section.
On free-threaded Python 3.13 a nested list lock no longer lets one
read mix two writes.
