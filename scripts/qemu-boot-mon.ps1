param(
    [int]$Seconds = 200,
    [string]$OutFile = 'build\serial-mon1.log',
    [int]$MonPort = 4478
)

# Boot crossxnu and, after $Seconds of serial capture, ask QEMU's HMP monitor
# where the vCPU actually is.  The guest hangs without any serial output, so
# the monitor (RIP/RFLAGS/LAPIC) is the only view into what it is doing.
$ErrorActionPreference = 'Stop'
$Repo = 'C:\Users\username000101\Workspaces\MachOS-crossxnu'
$Qemu = 'C:\Program Files\qemu\qemu-system-x86_64.exe'
$Port = 4477

Get-Process qemu-system-x86_64 -ErrorAction SilentlyContinue | Stop-Process -Force
Start-Sleep -Milliseconds 500

$qemuArgs = @(
    "-machine", "q35", "-cpu", "Skylake-Client", "-m", "4096", "-smp", "1",
    "-drive", "if=pflash,format=raw,readonly=on,file=$Repo\build\edk2-x86_64-code.fd",
    "-drive", "if=pflash,format=raw,file=$Repo\build\esp-vars.fd",
    "-drive", "file=$Repo\build\esp32.img,format=raw,if=ide",
    "-boot", "order=c", "-display", "none", "-vga", "std",
    "-serial", "tcp:127.0.0.1:$Port,server=on,wait=off",
    "-monitor", "tcp:127.0.0.1:$MonPort,server=on,wait=off",
    "-no-reboot"
)
$proc = Start-Process -FilePath $Qemu -ArgumentList $qemuArgs -PassThru

$client = $null
for ($i = 0; $i -lt 60 -and -not $client; $i++) {
    try { $client = New-Object System.Net.Sockets.TcpClient("127.0.0.1", $Port) }
    catch { Start-Sleep -Milliseconds 500 }
}
if (-not $client) { throw 'no serial connection' }

$sb = New-Object System.Text.StringBuilder
$buf = New-Object byte[] 65536
$cpu = @()

$start = Get-Date
$nextSample = $start.AddSeconds(30)
$lastBytes = 0
$lastChange = $start
while (((Get-Date) - $start).TotalSeconds -lt $Seconds) {
    if ($client.Available -gt 0) {
        $n = $client.GetStream().Read($buf, 0, $buf.Length)
        if ($n -gt 0) {
            [void]$sb.Append([System.Text.Encoding]::ASCII.GetString($buf, 0, $n))
            $lastChange = Get-Date
        }
    } else {
        Start-Sleep -Milliseconds 100
    }
    if ($sb.Length -ne $lastBytes) {
        $lastBytes = $sb.Length
        $lastChange = Get-Date
    }
    if ((Get-Date) -ge $nextSample) {
        $p = Get-Process -Id $proc.Id -ErrorAction SilentlyContinue
        if ($p) { $cpu += [pscustomobject]@{ t = [int]((Get-Date) - $start).TotalSeconds; cpu = [math]::Round($p.CPU, 1); bytes = $sb.Length } }
        $nextSample = $nextSample.AddSeconds(30)
    }
}

# drain whatever is still buffered
for ($i = 0; $i -lt 20 -and $client.Available -gt 0; $i++) {
    $n = $client.GetStream().Read($buf, 0, $buf.Length)
    if ($n -gt 0) { [void]$sb.Append([System.Text.Encoding]::ASCII.GetString($buf, 0, $n)) }
    Start-Sleep -Milliseconds 100
}

function Invoke-Hmp {
    param([string]$Command)
    $mon = $null
    for ($i = 0; $i -lt 30 -and -not $mon; $i++) {
        try { $mon = New-Object System.Net.Sockets.TcpClient("127.0.0.1", $MonPort) }
        catch { Start-Sleep -Milliseconds 300 }
    }
    if (-not $mon) { return "<no monitor connection>" }
    $stream = $mon.GetStream()
    $stream.ReadTimeout = 2000
    $readBuf = New-Object byte[] 65536
    $text = New-Object System.Text.StringBuilder
    Start-Sleep -Milliseconds 300
    # drain banner
    while ($stream.DataAvailable) {
        $n = $stream.Read($readBuf, 0, $readBuf.Length)
        if ($n -le 0) { break }
        [void]$text.Append([System.Text.Encoding]::ASCII.GetString($readBuf, 0, $n))
    }
    $cmd = [System.Text.Encoding]::ASCII.GetBytes("$Command`n")
    $stream.Write($cmd, 0, $cmd.Length)
    $stream.Flush()
    $deadline = (Get-Date).AddSeconds(3)
    while ((Get-Date) -lt $deadline) {
        Start-Sleep -Milliseconds 200
        try {
            while ($stream.DataAvailable) {
                $n = $stream.Read($readBuf, 0, $readBuf.Length)
                if ($n -le 0) { break }
                [void]$text.Append([System.Text.Encoding]::ASCII.GetString($readBuf, 0, $n))
            }
        } catch { break }
    }
    $mon.Close()
    return $text.ToString()
}

$monOut = New-Object System.Text.StringBuilder
[void]$monOut.AppendLine()
[void]$monOut.AppendLine("=== qemu monitor dump ===")
[void]$monOut.AppendLine((Invoke-Hmp 'info status'))
[void]$monOut.AppendLine((Invoke-Hmp 'info registers'))
[void]$monOut.AppendLine((Invoke-Hmp 'x/24i $pc-32'))
[void]$monOut.AppendLine((Invoke-Hmp 'info lapic'))
[void]$monOut.AppendLine((Invoke-Hmp 'info pic'))

$out = Join-Path $Repo $OutFile
[System.IO.File]::WriteAllText($out, $sb.ToString() + $monOut.ToString())
Write-Host "log: $out  bytes=$($sb.Length)"
Write-Host 'cpu samples (seconds wall, seconds cpu, serial bytes):'
foreach ($s in $cpu) { Write-Host ("  {0} -> cpu={1} bytes={2}" -f $s.t, $s.cpu, $s.bytes) }
Write-Host ("last serial growth (s before end): {0}" -f [int](((Get-Date) - $lastChange).TotalSeconds))
Write-Host "qemu alive: $(-not $proc.HasExited)"
Get-Process qemu-system-x86_64 -ErrorAction SilentlyContinue | Stop-Process -Force
