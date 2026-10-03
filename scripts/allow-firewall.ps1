# Allows iPads on your *private* network to reach OpenDeck.
# Run once from an elevated PowerShell:  powershell -ExecutionPolicy Bypass -File scripts\allow-firewall.ps1
# The rule is scoped to the Private profile and the local subnet, so public Wi-Fi stays closed.

param([int]$Port = 8765)

$ErrorActionPreference = "Stop"
$name = "OpenDeck (TCP $Port)"

$principal = New-Object Security.Principal.WindowsPrincipal([Security.Principal.WindowsIdentity]::GetCurrent())
if (-not $principal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)) {
    Write-Error "Run this script from an elevated (Administrator) PowerShell."
}

Get-NetFirewallRule -DisplayName $name -ErrorAction SilentlyContinue | Remove-NetFirewallRule
New-NetFirewallRule -DisplayName $name -Direction Inbound -Action Allow -Protocol TCP `
    -LocalPort $Port -Profile Private -RemoteAddress LocalSubnet | Out-Null

Write-Host "Firewall rule '$name' created (Private networks, local subnet only)."
$profiles = Get-NetConnectionProfile | Select-Object Name, NetworkCategory
$profiles | Format-Table -AutoSize
if ($profiles.NetworkCategory -notcontains "Private") {
    Write-Warning "No network is set to Private. In Settings > Network & internet, set your home Wi-Fi to Private."
}
