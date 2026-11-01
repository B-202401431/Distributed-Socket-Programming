# Screenshots & Terminal Demonstrations

This directory holds visual demonstration captures showcasing the system under real execution.

## Recommended Screenshots to Include

1. **`01_server_startup.png`**: Server startup in multi-threaded mode showing topic discovery, manifest indexing, and readiness announcement.
2. **`02_client_transfer_progress.png`**: Client terminal rendering dynamic ASCII progress bars, throughput rate, completed file counts, and byte offsets.
3. **`03_fault_injection_log.png`**: Server log demonstrating active Bernoulli fault injection (`[FAULT INJECTED]`), mid-block connection closure, and file offset metrics.
4. **`04_checkpoint_resume.png`**: Client terminal showing session detection, handshake, and seamless resume (`[RESUME]`) from confirmed byte offsets.
5. **`05_parallel_lanes.png`**: Enhanced Case 2 showing multi-threaded striped file downloads across 2+ concurrent lanes.
6. **`06_three_pc_lan_runner.png`**: Python distributed coordinator (`Tools/lan.py`) orchestrating nodes B and C across Wi-Fi.

---
*Generated plots from benchmark evaluation can also be found in `Results/local/*.png` and `docs/diagrams/`.*

