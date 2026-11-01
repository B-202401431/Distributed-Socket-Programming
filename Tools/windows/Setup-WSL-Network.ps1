# Run ONLY on PC A from an Administrator PowerShell.
# NAT mode: forward exactly the project's two TCP ports to the chosen WSL distro.
# No global firewall disabling, no router/internet port forwarding.
[CmdletBinding()]
param(
    [Parameter(Mandatory=$true)][string]$ServerIP,
    [string]$Distro = 'Ubuntu',
    [ValidateSet('NAT','Mirrored')][string]$Mode = 'NAT',
    [ValidateRange(1,65535)][int]$DataPort = 9000,
    [ValidateRange(1,65535)][int]$ControlPort = 9101,
    [switch]$Remove
)
$ErrorActionPreference = 'Stop'
$principal = New-Object Security.Principal.WindowsPrincipal([Security.Principal.WindowsIdentity]::GetCurrent())
if (-not $principal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)) {
    throw 'Open PowerShell using Run as administrator, then run this command again.'
}
$parsed = [System.Net.IPAddress]::Parse($ServerIP)
if ($parsed.AddressFamily -ne [System.Net.Sockets.AddressFamily]::InterNetwork) { throw 'Use the Wi-Fi IPv4 address of PC A.' }
$creator = '{40E0AC32-46A5-438A-A0B2-2B479E8F2E90}'
$ruleName = "IT305-WSL-$ServerIP"
$hyperName = "IT305-WSL-Ports"
if ($Remove) {
    foreach ($port in @($DataPort,$ControlPort)) {
        & netsh interface portproxy delete v4tov4 "listenaddress=$ServerIP" "listenport=$port"
    }
    Get-NetFirewallRule -Name $ruleName -ErrorAction SilentlyContinue | Remove-NetFirewallRule
    if (Get-Command Get-NetFirewallHyperVRule -ErrorAction SilentlyContinue) {
        Get-NetFirewallHyperVRule -Name $hyperName -ErrorAction SilentlyContinue | Remove-NetFirewallHyperVRule
    }
    Write-Host 'Removed this project forwarding and firewall rules.'
    return
}
if (-not (Get-NetIPAddress -AddressFamily IPv4 | Where-Object IPAddress -eq $ServerIP)) {
    throw 'ServerIP must be an IPv4 address assigned to this Windows PC. Check ipconfig.'
}
if ($Mode -eq 'NAT') {
    $route = (& wsl.exe -d $Distro -- ip -4 route get 1.1.1.1 | Out-String)
    if ($LASTEXITCODE -ne 0 -or $route -notmatch '\bsrc\s+(\d+\.\d+\.\d+\.\d+)') {
        throw 'Could not detect WSL IPv4. Check wsl -l -v and pass the exact -Distro name.'
    }
    $wslAddress = $Matches[1]
    if ($wslAddress -eq $ServerIP) { throw 'WSL appears mirrored. Use -Mode Mirrored instead.' }
    Start-Service iphlpsvc
    foreach ($port in @($DataPort,$ControlPort)) {
        & netsh interface portproxy add v4tov4 "listenaddress=$ServerIP" "listenport=$port" "connectaddress=$wslAddress" "connectport=$port"
        if ($LASTEXITCODE -ne 0) { throw "Port forwarding failed on $port. Check netsh interface portproxy show all." }
    }
    Write-Host "Windows $ServerIP -> WSL $wslAddress (refresh after WSL restarts)."
} else {
    if (-not (Get-Command New-NetFirewallHyperVRule -ErrorAction SilentlyContinue)) {
        throw 'Hyper-V firewall commands unavailable. Use supported WSL mirrored mode, or use NAT setup.'
    }
    Get-NetFirewallHyperVRule -Name $hyperName -ErrorAction SilentlyContinue | Remove-NetFirewallHyperVRule
    New-NetFirewallHyperVRule -Name $hyperName -DisplayName 'IT305 WSL TCP ports' -Direction Inbound -VMCreatorId $creator -Protocol TCP -LocalPorts @($DataPort,$ControlPort) | Out-Null
}
Get-NetFirewallRule -Name $ruleName -ErrorAction SilentlyContinue | Remove-NetFirewallRule
New-NetFirewallRule -Name $ruleName -DisplayName 'IT305 WSL Wi-Fi transfer and coordinator' -Direction Inbound -Action Allow -Protocol TCP -LocalAddress $ServerIP -LocalPort @($DataPort,$ControlPort) -RemoteAddress LocalSubnet -Profile Any | Out-Null
Write-Host 'Allowed the two project ports for the local subnet on all Windows network profiles.'
Write-Host 'Keep the WSL probe or coordinator running. Test from BOTH B and C next.'
Write-Host "Test-NetConnection $ServerIP -Port $ControlPort"
Write-Host "Test-NetConnection $ServerIP -Port $DataPort"
