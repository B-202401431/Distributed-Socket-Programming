# Three-PC test using Wi-Fi and Windows WSL

## 1. What this setup does

PC A runs the C server and Python coordinator. PCs B and C each run multiple C client processes. No Ethernet cable, SSH or public internet address is required. Wi-Fi provides the local network. The Jio SIM supplies internet to the hotspot; the file transfer uses the PCs' local IPv4 addresses.

All PCs must be able to communicate directly. A hotspot can allow internet access while blocking communication between connected devices. Code cannot remove that restriction. First try the existing hotspot. If direct connectivity still fails after the checks below, disable AP/client isolation if that setting exists, use another phone hotspot/router, or try PC A's Windows Mobile hotspot with B and C joined to it. Recheck connectivity and use PC A's address on the NEW network. Do not use Jio's public IP, the hotspot gateway IP, or a WSL 172.x address as PC A's address on B/C.

Part I explicitly requires three physical computers. The full runner also tests all Part II cases on that topology for a consistent comparison. One-PC rehearsal is a software check and cannot replace the physical experiment.

## 2. Prepare all three PCs

Extract this same ZIP on all three PCs. Keep its root folder name. In Ubuntu/WSL on EACH PC install the tools:

```bash
sudo apt update
sudo apt install -y build-essential python3 python3-venv
```

Open WSL in the extracted project folder. Example for Nirav's Windows extraction location (change the username/location on B and C):

```bash
cd /mnt/c/Users/nirav/Downloads/p/FinalSubmission_Group_099_107
make -C Part1
make -C Part2_Case1
make -C Part2_Case2
make -C Part2_Case2_Enhanced
```

For better disk performance you may copy the project to your Linux home and work there instead. Keep the same chosen copy for running, editing contributions and finalizing. Use Linux paths inside WSL; C:\Users\... becomes /mnt/c/Users/... . Python 3.10 or later is required. Do not run the C Makefiles in native Windows PowerShell.

Only PC A needs the extracted Animals10 dataset. Its dataset root must contain cane/, gatto/ and the other topic directories directly. Example: /mnt/c/Users/nirav/Downloads/raw-img . The project folder itself is NOT the dataset root unless it actually contains these ten folders. The dataset is not included in this ZIP.

## 3. Find PC A's Windows Wi-Fi IPv4

On PC A in Windows PowerShell:

```powershell
ipconfig
wsl -l -v
```

Read IPv4 under the adapter connected to your hotspot (normally Wireless LAN adapter Wi-Fi). Record the WSL distribution's exact name, for example Ubuntu or Ubuntu-24.04. The examples below use 192.168.43.100; REPLACE it everywhere with PC A's current address. It is an example, not a required IP.

## 4. Start diagnostic listeners on A in WSL

From the project root on PC A:

```bash
python3 Tools/network_check.py serve
```

Keep this terminal running. It opens TCP 9000 (data) and 9101 (control). These are temporary diagnostic listeners, not the actual file server. In another WSL terminal on A:

```bash
python3 Tools/network_check.py check --server-ip 127.0.0.1
```

Both lines must say PASS. If a port is already in use, stop the old manual server/coordinator first. Use ss -ltnp to inspect listeners.

## 5. Configure Windows-to-WSL access on A

Open Windows PowerShell with Run as administrator on PC A. Go to the Windows extraction folder:

```powershell
cd C:\Users\nirav\Downloads\p\FinalSubmission_Group_099_107
powershell -NoProfile -ExecutionPolicy Bypass -File `
  .\Tools\windows\Setup-WSL-Network.ps1 `
  -ServerIP 192.168.43.100 -Distro Ubuntu -Mode NAT
```

Replace ServerIP and Distro. NAT is the normal WSL 2 setup. The script detects the selected distribution's current IPv4, adds forwarding for exactly ports 9000 and 9101, starts IP Helper, and permits these ports from the local subnet even if Windows classifies the hotspot as Public. It does not disable your firewall. Re-run it after WSL restarts or the network/IP changes.

If you already deliberately enabled WSL mirrored networking, use -Mode Mirrored instead. Do not change .wslconfig as part of this NAT setup. The mirrored option adds the two Hyper-V inbound ports and Windows firewall rule; it does not enable mirrored mode itself. WSL 1 does not need the WSL 2 NAT proxy; use WSL 2 for these instructions.

If the project lives only in Linux home, the script is accessible in Windows through \\wsl.localhost\Ubuntu\home\YOUR_USER\... or copy this one .ps1 to a Windows folder before running it.

## 6. Check from B and C before the experiment

In Windows PowerShell on BOTH B and C while A's diagnostic listener is still running:

```powershell
Test-NetConnection 192.168.43.100 -Port 9101
Test-NetConnection 192.168.43.100 -Port 9000
```

Both must show TcpTestSucceeded : True. Then check from Ubuntu/WSL on BOTH B and C, from their project roots:

```bash
python3 Tools/network_check.py check --server-ip 192.168.43.100
```

Both must say PASS here too. B and C need outbound access only; no port forwarding is needed on them.

If this fails, test on A in Windows PowerShell as well. If A's WSL loopback test fails, fix the listener. If WSL loopback passes but A's Windows test fails, check the exact distro/IP, forwarding, firewall and listener. If A's Windows test passes but both remote PCs fail, check hotspot isolation, wrong network/interface/IP and local firewall restrictions. A successful local Windows test alone does not prove remote access. If Windows on B/C passes but their WSL checks fail, inspect their WSL routing/VPN/firewall. Disconnect an interfering VPN only if appropriate for your setup. Do not assume a failed ping proves TCP is blocked.

Useful checks on A in Administrator PowerShell:

```powershell
netsh interface portproxy show all
Get-Service iphlpsvc
Get-NetFirewallRule -DisplayName 'IT305*'
```

Changing application code cannot make isolated hotspot devices reachable. Use a hotspot/router that permits local device traffic. Do not configure Jio public/internet router port forwarding for this local test.

## 7. Start the full experiment on A

Stop A's diagnostic serve command with Ctrl+C. Do not leave any manual C server running. From the project root in WSL on PC A, verify your dataset path:

```bash
ls /mnt/c/Users/nirav/Downloads/raw-img/cane
```

Then run (replace dataset path and Wi-Fi IPv4):

```bash
python3 Tools/lan.py server \
  --dataset /mnt/c/Users/nirav/Downloads/raw-img \
  --ip 192.168.43.100 --topic cane \
  --results Results/wifi_full_01 \
  --timeout 1800 --start-delay 5 \
  --network-note 'Jio hotspot; WSL2 NAT; Wi-Fi'
```

Keep A running until it says Measurements saved. The coordinator opens 9101 and keeps an actual temporary C listener on 9000 while waiting for agents. Agents check both before joining. It then restarts the appropriate C server for each measured batch. Forwarding is persistent across these server restarts.

The default schedule is 60 batches: Part I single/multi with 1, 2, 4 and 8 total clients; all three Part II cases with four fault probabilities and four clients. Every setting repeats three times. The one-client baseline uses B; at four/eight clients both B and C run multiple client processes. The runner verifies every received file using SHA-256. Allow adequate disk space for all repeated downloads, potentially tens of GB, and keep all PCs awake/on power.

## 8. Start the agents on B and C

In WSL on PC B, from its project root:

```bash
python3 Tools/lan.py agent \
  --server http://192.168.43.100:9101 --node B \
  --results Results/wifi_B_01 --output downloads/wifi_B_01
```

In WSL on PC C, from its project root:

```bash
python3 Tools/lan.py agent \
  --server http://192.168.43.100:9101 --node C \
  --results Results/wifi_C_01 --output downloads/wifi_C_01
```

Do not use --node B on both PCs. Give each rerun fresh results/download suffixes such as _02. Do not delete earlier evidence to reuse an output path. You do not start C servers manually on B or C.

If you want a shorter Part I check first, add --only Part1 --repeats 1 to A's command and use Results/wifi_part1_smoke_01 plus fresh agent directories. That checks eight batches. It is not the complete 60-batch report dataset: afterwards run the full command above using fresh directories. The finalizer intentionally rejects an incomplete schedule.

## 9. Generate your submission after the run

Check that A reports SUCCESS for every batch and that Results/wifi_full_01/environment.json records real_three_pc: true and completed_utc. Edit team_members.csv to enter each member's ACTUAL one-line contribution; names and roll numbers are already supplied. Do not invent contributions.

On PC A in WSL, create the analysis environment and finalize:

```bash
python3 -m venv .venv
source .venv/bin/activate
python3 -m pip install -r requirements-analysis.txt
python3 Tools/finalize.py --lan Results/wifi_full_01
```

The generated ZIP is ../FinalSubmission_Group_099_107.zip relative to the project root. This is the file to upload. It contains the regenerated consolidated PDF, four independent source folders/Makefiles, README, raw measurements and graphs. The full Animals10 dataset and all downloaded copies are excluded.

If the command reports missing physical evidence, failed batches or contributions, resolve the named items and rerun. The delivered package is runnable, but its included measurements are local checks: your physical hotspot test must supply the three-PC results. Never relabel a rehearsal as a physical test.

## 10. Cleanup and references

After testing, stop the coordinator and agents. To remove the project's Windows networking rules on A, use Administrator PowerShell with the same ServerIP and distro:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File `
  .\Tools\windows\Setup-WSL-Network.ps1 `
  -ServerIP 192.168.43.100 -Distro Ubuntu -Remove
```

Microsoft's WSL networking reference explains NAT portproxy, mirrored mode and Hyper-V firewall: https://learn.microsoft.com/en-us/windows/wsl/networking . Hotspot isolation is a network property to test; no claim is made that every Jio device has the same isolation setting.
