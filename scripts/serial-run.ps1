# Boot crossxnu in QEMU with a scripted serial console.
#
# Unlike run-console.ps1 (which attaches the guest console to stdio for a human),
# this script exposes the guest UART on a TCP port, types a list of shell
# commands into the guest, and writes the whole transcript to a log file.  It is
# meant for repeatable bring-up tests of the userland.
#
# Usage:
#   pwsh -File scripts/serial-run.ps1 -Commands 'uname -a','ls /' -OutFile build/serial-test.log
#   pwsh -File scripts/serial-run.ps1 -Commands (Get-Content cmds.txt) -KeepRunning
#
# Notes:
#   * The guest shell is pid 1: after "exit" the kernel panics ("initproc
#     exited"), so this script just kills QEMU when it is done.
#   * The ESP must already contain EFI/BOOT/kernel (see docs/boot.md).

[CmdletBinding()]
param(
    [string]$Repo = (Split-Path -Parent $PSScriptRoot),
    [string]$Qemu = "C:\Program Files\qemu\qemu-system-x86_64.exe",
    [int]$MemoryMB = 4096,
    [int]$Cpus = 1,
    [string]$Cpu = "Skylake-Client",
    [int]$Port = 4444,
    [string[]]$Commands = @(),
    [string]$OutFile = "",
    [int]$BootTimeoutSeconds = 180,
    [int]$PerCommandSeconds = 20,
    [switch]$KeepRunning
)

$ErrorActionPreference = "Stop"

$esp  = Join-Path $Repo "build\esp32.img"
$code = Join-Path $Repo "build\edk2-x86_64-code.fd"
$vars = Join-Path $Repo "build\esp-vars.fd"

foreach ($f in @($esp, $code, $vars)) {
    if (-not (Test-Path $f)) { throw "missing $f" }
}
if (-not (Test-Path $Qemu)) { throw "qemu not found at $Qemu" }

# A stale instance would keep the panic screen and hold the serial port.
Get-Process qemu-system-x86_64 -ErrorAction SilentlyContinue | Stop-Process -Force
Start-Sleep -Milliseconds 500

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
    "-serial", "tcp:127.0.0.1:$Port,server=on,wait=off",
    "-monitor", "none",
    "-no-reboot"
)

Write-Host "boot: $esp (serial on tcp:$Port)"
$proc = Start-Process -FilePath $Qemu -ArgumentList $qemuArgs -PassThru
$transcript = New-Object System.Text.StringBuilder

function Read-Until {
    param([System.Net.Sockets.TcpClient]$Client, [string]$Marker, [int]$TimeoutSeconds)
    $buffer = New-Object byte[] 65536
    $deadline = (Get-Date).AddSeconds($TimeoutSeconds)
    while ((Get-Date) -lt $deadline) {
        if ($Client.Available -gt 0) {
            $n = $Client.GetStream().Read($buffer, 0, $buffer.Length)
            if ($n -gt 0) {
                $text = [System.Text.Encoding]::ASCII.GetString($buffer, 0, $n)
                [void]$transcript.Append($text)
                if ($Marker -and ($transcript.ToString() -match $Marker)) { return $true }
            }
        } else {
            Start-Sleep -Milliseconds 200
            if (-not $proc.HasExited -and $Marker -and ($transcript.ToString() -match $Marker)) { return $true }
        }
    }
    return $false
}

function Drain-For {
    param([System.Net.Sockets.TcpClient]$Client, [int]$Seconds)
    $buffer = New-Object byte[] 65536
    $deadline = (Get-Date).AddSeconds($Seconds)
    $idle = 0
    while ((Get-Date) -lt $deadline) {
        if ($Client.Available -gt 0) {
            $n = $Client.GetStream().Read($buffer, 0, $buffer.Length)
            if ($n -gt 0) {
                [void]$transcript.Append([System.Text.Encoding]::ASCII.GetString($buffer, 0, $n))
                $idle = 0
                continue
            }
        }
        Start-Sleep -Milliseconds 200
        $idle += 200
        if ($idle -ge 2000) { break }
    }
}

# Type one command and wait until the guest shell prints its prompt again.
# Returns $false if the prompt did not come back within PerCommandSeconds.
function Send-GuestCommand {
    param([System.Net.Sockets.TcpClient]$Client, [string]$Command, [int]$TimeoutSeconds)
    $buffer = New-Object byte[] 65536
    $start = $transcript.Length
    $bytes = [System.Text.Encoding]::ASCII.GetBytes($Command + "`n")
    $Client.GetStream().Write($bytes, 0, $bytes.Length)
    $Client.GetStream().Flush()
    $deadline = (Get-Date).AddSeconds($TimeoutSeconds)
    while ((Get-Date) -lt $deadline) {
        if ($Client.Available -gt 0) {
            $n = $Client.GetStream().Read($buffer, 0, $buffer.Length)
            if ($n -gt 0) {
                [void]$transcript.Append([System.Text.Encoding]::ASCII.GetString($buffer, 0, $n))
                continue
            }
        }
        Start-Sleep -Milliseconds 150
        if ($transcript.Length -gt $start) {
            $tail = $transcript.ToString($start, $transcript.Length - $start)
            if ($tail -match "sh-3\.2# ?$") { return $true }
            if ($tail -match "panic\(|initproc exited|Kernel trap") { return $false }
        }
    }
    return $false
}

$client = $null
try {
    for ($i = 0; $i -lt 60 -and -not $client; $i++) {
        try {
            $client = New-Object System.Net.Sockets.TcpClient("127.0.0.1", $Port)
        } catch {
            Start-Sleep -Milliseconds 500
        }
    }
    if (-not $client) { throw "could not connect to the guest serial port" }

    Write-Host "waiting for the guest shell prompt ..."
    if (-not (Read-Until -Client $client -Marker "sh-3\.2#" -TimeoutSeconds $BootTimeoutSeconds)) {
        Write-Host "warning: shell prompt not seen within $BootTimeoutSeconds s"
    }
    Drain-For -Client $client -Seconds 1

    foreach ($cmd in $Commands) {
        Write-Host "guest> $cmd"
        $ok = Send-GuestCommand -Client $client -Command $cmd -TimeoutSeconds $PerCommandSeconds
        if (-not $ok) {
            Write-Host "  (no prompt back within $PerCommandSeconds s; stopping)"
            break
        }
    }
} finally {
    if ($client) { $client.Close() }
    $out = if ($OutFile) { $OutFile } else { Join-Path $Repo "build\serial-run.log" }
    $dir = Split-Path -Parent $out
    if ($dir -and -not (Test-Path $dir)) { New-Item -ItemType Directory -Path $dir | Out-Null }
    $transcript.ToString() | Set-Content -Path $out -Encoding utf8
    Write-Host "transcript: $out"
    if (-not $KeepRunning) {
        Get-Process qemu-system-x86_64 -ErrorAction SilentlyContinue | Stop-Process -Force
    } else {
        Write-Host "qemu still running (pid $($proc.Id)); serial on tcp:$Port"
    }
}
