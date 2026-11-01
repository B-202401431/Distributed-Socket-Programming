# IT305 - Fault-Tolerant Topic-Based File Distribution

Groups 099 and 107. Final deadline: 16 October 2026.

The C implementation is corrected and locally verified. Before official upload,
perform the physical three-PC Animals10 tests and fill each member's actual
contribution in `team_members.csv`. The supplied report states which evidence
is available; no unperformed LAN result is presented as measured.

## Start here

1. Read `WIFI_WSL_GUIDE.md` (same content as `THREE_PC_TEST_GUIDE.md` and its PDF).
   It includes both-port diagnostics, Windows/WSL forwarding and hotspot isolation checks.
2. Follow the Wi-Fi preflight and run the coordinator/agent commands in that guide on PCs A, B and C.
3. Complete `team_members.csv` using a text editor, Excel or LibreOffice.
4. On PC A run `python3 Tools/finalize.py --lan Results/wifi_full_01`.
5. Upload the resulting `FinalSubmission_Group_099_107.zip` from the parent folder.

The finalizer verifies all required batches and hashes, generates figures and
the report, and packages source and results. It does not invent missing data.
`SUBMISSION_STATUS.json` records whether the supplied package is complete.

## Build - each folder is independent

Use Linux or Ubuntu/WSL with gcc, make, pthreads and Python 3.10+.
The C server and client do not require any Python package.

```bash
make -C Part1
make -C Part2_Case1
make -C Part2_Case2
make -C Part2_Case2_Enhanced
```

Each Makefile creates exactly `server` and `client` inside its folder.
Flags include `-Wall -Wextra -Wpedantic -Werror`.

## Required CLI

```text
Part1/server <port> <topics_root_dir> [single|multi]
Part2_Case1/server <port> <topics_root_dir> <failure_probability>
Part2_Case2/server <port> <topics_root_dir> <failure_probability>
Part2_Case2_Enhanced/server <port> <topics_root_dir> <failure_probability>

Part1/client <server_ip> <server_port> <topic> <output_dir>
Part2_Case1/client <server_ip> <server_port> <topic> <output_dir>
Part2_Case2/client <server_ip> <server_port> <topic> <output_dir>
Part2_Case2_Enhanced/client <server_ip> <server_port> <topic> <output_dir> [connections]
```

The same commands work as `./server` and `./client` when inside a Part folder.
Part I defaults to multi. Enhanced defaults to two persistent TCP lanes.
All downloads go under `output_dir/topic/`. Give concurrent clients separate,
fresh output directories. IPs, ports and root paths come from the CLI.

For a manual demo use two terminals, with your real dataset path and server IP:

```bash
# Terminal A
Part1/server 9000 /path/to/raw-img single > server.csv 2> server.log
# Terminal B
Part1/client 127.0.0.1 9000 cane demo_out > client.csv 2> client.log
```

For Part II run the same pattern from each case, adding the server probability:

```bash
Part2_Case2/server 9000 /path/to/raw-img 0.0001 > server.csv 2> server.log
Part2_Case2/client 127.0.0.1 9000 cane demo_case2 > client.csv 2> client.log
```

Stop a manual server before starting another case or the automatic runner.

## Topic configuration and dataset

Extract Animals10 and pass `raw-img`, whose immediate children are `cane`,
`cavallo`, `elefante`, `farfalla`, `gallina`, `gatto`, `mucca`, `pecora`, `ragno`
and `scoiattolo`. Topic names are case-sensitive. Dataset images are not bundled.

By default these directories are discovered at startup. To use the key's
configuration-file approach, copy `topics.conf.example` to
`raw-img/topics.conf`. Each line is `topic<TAB>relative_directory`; comments
start with `#`. Entries must resolve within the supplied root. The server
converts them to absolute paths and rejects invalid or duplicate entries.
Do not add an extra mandatory CLI argument for this file.

The dataset must stay unchanged during a run. Metadata changes reject old
checkpoints. SHA-256 is verified separately by the experiment/test tools.
Files are regular binary files; nested folders and symlinks are not transferred.

`Documents/Animals10_inventory.csv` records the full version-2 archive inventory:
26,179 images. Every `cane` image is below 64 KiB; use a large `gatto` image to
demonstrate a nonzero byte-offset resume within one file.

## Recovery and protocol

Control messages are LF-terminated. The manifest and chunks use big-endian
unsigned 64-bit length fields. The normal flow is GET, OK+manifest, START,
READY, FILE, DATA/offset ACK, zero-length file end/ACK, DONE, BYE.

Case 1 removes its downloaded files and restarts the entire topic. Case 2
retains an in-memory file/offset checkpoint; only complete written chunks
advance it. Enhanced assigns sorted file i to lane i modulo K. Each lane has
one persistent connection and an independent checkpoint. Only a failed lane
reconnects. Initial connection/manifest failures are retried too.

For each non-empty payload block of up to 65,536 bytes, the server makes an
independent random draw. With probability p it sends half the block and closes
the connection. p is per block, not per second. A high p can make Case 1 unable
to finish a large topic. `FT_MAX_ATTEMPTS` defaults to 1000 attempts per lane.
Socket I/O defaults to a 300-second inactivity timeout (optional `FT_IO_TIMEOUT=1..3600` seconds); retries wait 10 ms. p=1 cannot complete a
non-empty transfer and is used only for a bounded failure test.

The session table is protected by a mutex and limited to 4096 lane records.
State is in RAM until server exit. A valid client checkpoint is authoritative
when an ACK was lost after a successful write. This is a trusted lab protocol,
not an authentication or power-failure recovery system.

## Tests and local measurements

```bash
python3 Tools/test_correctness.py
python3 Tools/test_disconnects.py
python3 Tools/test_regressions.py
python3 Tools/test_lan_runner.py
```

The first two tests check 39 functional and 24 stream-cut conditions.
Regression tests cover dataset changes, optional configuration, pure restart,
and a high-count small-file Enhanced transfer. The LAN-runner test uses A/B/C
processes on ONE machine and is not physical LAN performance evidence.

The provided `Results/local` logs and plots were regenerated from this corrected
source using 8 generated files totalling 1 MiB over loopback. They are labelled
local synthetic validation and are not the required three-PC results.
To repeat them without overwriting supplied measurements:

```bash
python3 Tools/benchmark.py --results Results/local_repeat
python3 Tools/plot_results.py Results/local_repeat/summary.csv
```

Use `Tools/test_dataset.py --dataset /path/to/raw-img` to test every topic in
all five modes locally. This can read/write several GiB and is optional before
the physical experiment. It does not replace the three-PC tests.

## Analysis and report dependencies - PC A only

```bash
python3 -m venv .venv
source .venv/bin/activate
python3 -m pip install -r requirements-analysis.txt
```

The LAN runner and C programs use only the Python standard library / C runtime.
Only plotting and PDF regeneration require matplotlib and reportlab.

## Measurement definitions

U: bytes in complete verified client outputs. S: all server payload bytes sent.
For a fully successful batch R=S-U. T: earliest client start to latest finish,
including reconnect delays and single-server queue waits.

Goodput = U/(1048576*T) MiB/s. Redundancy = 100*R/U percent.
Protocol bytes = server application bytes sent + received - S.
These counters exclude TCP/IP headers and kernel TCP retransmissions.
Failed runs are saved and marked FAILED; their successful-transfer redundancy
is left undefined. Graphs use only successful SHA-256-verified runs.

## Files for submission

Keep the named root folder, consolidated report, README, four Part folders,
Results, Tools, team member CSV and guide in the archive. The finalizer excludes
compiled binaries, caches, virtual environments and downloaded dataset outputs.
It preserves raw client/server CSVs, diagnostics, figures and test evidence.
The exact originally submitted design is retained under Documents.

## References and attribution

Specifications: supplied IT305 assignment and model key. Dataset:
https://www.kaggle.com/datasets/alessiocorrado99/animals10
WSL LAN setup: https://learn.microsoft.com/en-us/windows/wsl/networking
ChatGPT assistance was used for revisions. Group members must review the work,
confirm real contributions and follow the course attribution rules.

## Wi-Fi revision

See `CHANGES_AND_VALIDATION.md` for fixes and limitations. The assignment-required
C command interfaces are preserved. No physical three-PC measurements were
performed in the build environment; those remain required on your PCs.
