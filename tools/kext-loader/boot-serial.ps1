# Boot whatever sits at ESP /EFI/BOOT/kernel and capture the serial console.
#
# Usage:
#   pwsh -File build/dis/boot-serial.ps1 -Log build/serial-kc.log -Seconds 90
#
# The script does not touch the ESP; use mcopy to stage the kernel image first.

[CmdletBinding()]
param(
    [string]$Repo = (Split-Path -Parent (Split-Path -Parent $PSScriptRoot)),
    [string]$Qemu = "C:\Program Files\qemu\qemu-system-x86_64.exe",
    [int]$MemoryMB = 4096,
    [int]$Cpus = 1,
    [string]$Cpu = "Skylake-Client",
    [string]$Log = "build/serial-kc.log",
    [int]$Seconds = 90
)

$ErrorActionPreference = "Stop"

$esp = Join-Path $Repo "build\esp32.img"
$code = Join-Path $Repo "build\edk2-x86_64-code.fd"
$vars = Join-Path $Repo "build\esp-vars.fd"
$logPath = Join-Path $Repo $Log

foreach ($f in @($esp, $code, $vars)) {
    if (-not (Test-Path $f)) { throw "missing $f" }
}
if (-not (Test-Path $Qemu)) { throw "qemu not found at $Qemu" }

Get-Process qemu-system-x86_64 -ErrorAction SilentlyContinue | Stop-Process -Force
Start-Sleep -Milliseconds 500

if (Test-Path $logPath) { Remove-Item $logPath -Force }

$qemuArgs = @(
    "-machine", "q35",
    "-cpu", $Cpu,
    "-m", "$MemoryMB",
    "-smp", "$Cpus",
    "-drive", "if=pflash,format=raw,readonly=on,file=$code",
    "-drive", "if=pflash,format=raw,file=$vars",
    "-drive", "file=$esp,format=raw,if=ide",
    "-boot", "order=c",
    "-display", "none",
    "-vga", "std",
    "-serial", "file:$logPath",
    "-monitor", "none",
    "-no-reboot"
)

Write-Host "booting ESP for $Seconds s, serial -> $logPath"
$p = Start-Process -FilePath $Qemu -ArgumentList $qemuArgs -PassThru -WindowStyle Hidden
Start-Sleep -Seconds $Seconds
if (-not $p.HasExited) {
    $p.Kill()
    Start-Sleep -Milliseconds 500
}
Write-Host ("log size: {0} bytes" -f (Get-Item $logPath).Length)
