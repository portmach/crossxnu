# Boot crossxnu in QEMU with an interactive serial console.
#
# The guest's /dev/console is backed by the serial UART (see bsd/dev/i386/cons.c),
# so -serial stdio connects your keyboard to the guest shell: the image's
# /etc/rc.local prints a short report and then execs /bin/sh -i.
#
# Usage:
#   pwsh -File scripts/run-console.ps1
#   pwsh -File scripts/run-console.ps1 -MemoryMB 6144 -Qemu "C:\Program Files\qemu\qemu-system-x86_64.exe"
#
# Type commands at the "sh-3.2#" prompt.  "exit" terminates pid 1, which makes
# the kernel panic with "initproc exited" - that is expected until launchd is
# the init program.

[CmdletBinding()]
param(
    [string]$Repo = (Split-Path -Parent $PSScriptRoot),
    [string]$Qemu = "C:\Program Files\qemu\qemu-system-x86_64.exe",
    [int]$MemoryMB = 4096,
    [int]$Cpus = 1,
    [string]$Cpu = "Skylake-Client"
)

$ErrorActionPreference = "Stop"

$esp = Join-Path $Repo "build\esp32.img"
$code = Join-Path $Repo "build\edk2-x86_64-code.fd"
$vars = Join-Path $Repo "build\esp-vars.fd"

foreach ($f in @($esp, $code, $vars)) {
    if (-not (Test-Path $f)) {
        throw "missing $f - build the ESP image first (see docs/boot.md)"
    }
}
if (-not (Test-Path $Qemu)) {
    throw "qemu not found at $Qemu; pass -Qemu <path>"
}

Write-Host "boot: $esp"
Write-Host "memory: $MemoryMB MB, cpu: $Cpu, cpus: $Cpus"
Write-Host "console: serial stdio (the guest shell appears after boot)"
Write-Host ""

$args = @(
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
    "-serial", "stdio",
    "-monitor", "none",
    "-no-reboot"
)

& $Qemu @args
