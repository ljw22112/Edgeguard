# EdgeGuard - self-hosted MEC Sandbox VM on Hyper-V (Windows 11 Pro / Enterprise)
# Run in an *administrator* PowerShell:
#   Set-ExecutionPolicy -Scope Process Bypass; .\create-vm.ps1 -Iso C:\path\ubuntu-22.04.5-live-server-amd64.iso
#
# Creates
#   - internal switch "EdgeGuardNet" 192.168.200.0/24 (host = .1) with NAT to the internet
#   - VM "mec-sandbox": 6 vCPU, 16 GB RAM, 120 GB disk, Ubuntu ISO attached
#   - port proxy 0.0.0.0:8088 -> 192.168.200.10:80 so Docker Desktop containers reach the Sandbox
#     at http://host.docker.internal:8088
# The VM must use the static address 192.168.200.10 (set it in the Ubuntu installer; see README.md).
param(
    [Parameter(Mandatory = $true)][string]$Iso,
    [string]$Name = "mec-sandbox",
    [int]$Cpu = 6,
    [long]$MemoryGB = 16,
    [long]$DiskGB = 120,
    [string]$Dir = "C:\HyperV"
)
$ErrorActionPreference = "Stop"

if (-not (Get-WindowsOptionalFeature -Online -FeatureName Microsoft-Hyper-V-All).State.ToString().Equals("Enabled")) {
    Enable-WindowsOptionalFeature -Online -FeatureName Microsoft-Hyper-V-All -All -NoRestart | Out-Null
    Write-Host "Hyper-V enabled. REBOOT, then run this script again." -ForegroundColor Yellow
    exit 0
}
if (-not (Test-Path $Iso)) { throw "ISO not found: $Iso" }

# 1. internal switch + NAT (fixed addresses: Kubernetes needs a stable node IP)
if (-not (Get-VMSwitch -Name EdgeGuardNet -ErrorAction SilentlyContinue)) {
    New-VMSwitch -Name EdgeGuardNet -SwitchType Internal | Out-Null
}
$if = Get-NetAdapter | Where-Object { $_.Name -eq "vEthernet (EdgeGuardNet)" }
if (-not (Get-NetIPAddress -InterfaceIndex $if.ifIndex -IPAddress 192.168.200.1 -ErrorAction SilentlyContinue)) {
    New-NetIPAddress -IPAddress 192.168.200.1 -PrefixLength 24 -InterfaceIndex $if.ifIndex | Out-Null
}
if (-not (Get-NetNat -Name EdgeGuardNat -ErrorAction SilentlyContinue)) {
    New-NetNat -Name EdgeGuardNat -InternalIPInterfaceAddressPrefix 192.168.200.0/24 | Out-Null
}

# 2. VM
if (-not (Get-VM -Name $Name -ErrorAction SilentlyContinue)) {
    New-Item -ItemType Directory -Force -Path $Dir | Out-Null
    New-VM -Name $Name -Generation 2 -MemoryStartupBytes ($MemoryGB * 1GB) -SwitchName EdgeGuardNet `
        -NewVHDPath "$Dir\$Name.vhdx" -NewVHDSizeBytes ($DiskGB * 1GB) | Out-Null
    Set-VM -Name $Name -ProcessorCount $Cpu -StaticMemory -AutomaticCheckpointsEnabled $false
    Set-VMFirmware -VMName $Name -SecureBootTemplate MicrosoftUEFICertificateAuthority
    Add-VMDvdDrive -VMName $Name -Path $Iso
    Set-VMFirmware -VMName $Name -FirstBootDevice (Get-VMDvdDrive -VMName $Name)
}

# 3. port proxy for Docker Desktop containers (+ firewall rule for it)
netsh interface portproxy delete v4tov4 listenport=8088 listenaddress=0.0.0.0 2>$null | Out-Null
netsh interface portproxy add v4tov4 listenport=8088 listenaddress=0.0.0.0 connectport=80 connectaddress=192.168.200.10 | Out-Null
if (-not (Get-NetFirewallRule -DisplayName "EdgeGuard Sandbox proxy" -ErrorAction SilentlyContinue)) {
    New-NetFirewallRule -DisplayName "EdgeGuard Sandbox proxy" -Direction Inbound -Protocol TCP -LocalPort 8088 -Action Allow | Out-Null
}

Start-VM -Name $Name
vmconnect.exe localhost $Name
Write-Host "VM '$Name' started. Install Ubuntu in the window that opened (README.md, step 3)." -ForegroundColor Green
