#!/bin/sh
set -eu
# From the workspace root, in a clean copy with the frozen upstream study archives.
study=studies/sam2_raft_end_to_end_v1
cpu_python=outputs/corepp_cpu_audit/venv/bin/python
export OPENBLAS_NUM_THREADS=1 OMP_NUM_THREADS=1 VECLIB_MAXIMUM_THREADS=1
export DYLD_LIBRARY_PATH="$PWD/outputs/corepp_cpu_audit/runtime/libusb/1.0.30/lib"
"$cpu_python" "$study/track.py" freeze
"$cpu_python" "$study/evaluate.py" freeze
"$cpu_python" "$study/provided.py"
"$cpu_python" "$study/track.py" track --shard 0 --shards 2 &
left=$!
"$cpu_python" "$study/track.py" track --shard 1 --shards 2 &
right=$!
status=0
wait "$left" || status=$?
wait "$right" || status=$?
[ "$status" = 0 ]
"$cpu_python" "$study/track.py" collect
"$cpu_python" "$study/build.py"
"$cpu_python" "$study/evaluate.py" predict
"$cpu_python" "$study/audit.py"
"$cpu_python" "$study/evaluate.py" score
"$cpu_python" "$study/report.py"
