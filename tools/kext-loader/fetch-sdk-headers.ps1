# Fetch the IOKit storage headers of a macOS SDK's Kernel.framework.
#
# Why: XNU ships the core IOKit headers (IOKit/IOService.h, IORegistryEntry.h,
# ...), but the storage family (IOMedia, IOStorage, IOBlockStorageDevice) is
# closed source and lives only in the macOS SDK / KDK.  A kext that publishes a
# block device must compile against the real class declarations, because a
# subclass's vtable order and object size depend on them.
#
# The download is kept out of the repository (build/ is ignored): Apple's
# headers stay Apple's.  Only the storage subdirectory is fetched - mixing the
# SDK's base IOKit headers with the ones from the kernel tree we build would
# risk compiling against a different ABI than the running kernel.
#
# Usage:
#   pwsh -File tools/kext-loader/fetch-sdk-headers.ps1 [-Sdk MacOSX10.15.sdk] [-Proxy URL]
#
# On a machine where the shell has direct network access the proxy argument is
# not needed; behind an HTTP proxy pass it explicitly (this is how the headers
# used during bring-up were obtained).

param(
    [string]$Sdk = 'MacOSX10.15.sdk',
    [string]$Repo = 'phracker/MacOSX-SDKs',
    [string]$Branch = 'master',
    [string]$Proxy = $env:HTTPS_PROXY,
    [string]$Dest
)

$ErrorActionPreference = 'Stop'

$root = Split-Path -Parent (Split-Path -Parent $PSScriptRoot)   # repo root
if (-not $Dest) {
    $Dest = Join-Path $root 'build/sdk-ext/Kernel.framework/Versions/A/Headers/IOKit/storage'
}

$prefix = "$Sdk/System/Library/Frameworks/Kernel.framework/Versions/A/Headers/IOKit/storage"
$iwr = @{ TimeoutSec = 60; UseBasicParsing = $true }
if ($Proxy) { $iwr['Proxy'] = $Proxy }

function Get-Contents([string]$path) {
    # The repository is far too big for the recursive trees API (GitHub
    # truncates it), so walk directories one by one.
    $url = "https://api.github.com/repos/$Repo/contents/$path" + "?ref=$Branch"
    (Invoke-WebRequest -Uri $url @iwr).Content | ConvertFrom-Json
}

$dirs = [System.Collections.Generic.Queue[string]]::new()
$dirs.Enqueue($prefix)
$files = @()
while ($dirs.Count -gt 0) {
    $dir = $dirs.Dequeue()
    foreach ($e in Get-Contents $dir) {
        switch ($e.type) {
            'file' { $files += $e }
            'dir'  { $dirs.Enqueue($e.path) }
        }
    }
}
if (-not $files) { throw "no files under $prefix" }
Write-Host ("{0} headers under {1}" -f $files.Count, $prefix)

New-Item -ItemType Directory -Force -Path $Dest | Out-Null
$manifest = @()
foreach ($f in ($files | Sort-Object path)) {
    $rel = $f.path.Substring($prefix.Length + 1)
    $out = Join-Path $Dest $rel
    New-Item -ItemType Directory -Force -Path (Split-Path -Parent $out) | Out-Null
    Invoke-WebRequest -Uri $f.download_url -OutFile $out @iwr
    $hash = (Get-FileHash -Algorithm SHA256 -Path $out).Hash.ToLower()
    $manifest += "$hash  $rel"
    Write-Host ("  {0,-52} {1,7} bytes" -f $rel, (Get-Item $out).Length)
}

$sdkExt = Split-Path -Parent (Split-Path -Parent (Split-Path -Parent $Dest))
$manifestPath = Join-Path $sdkExt 'MANIFEST.sha256'
$manifest | Sort-Object | Set-Content -Path $manifestPath -Encoding ascii
Write-Host "manifest: $manifestPath"
Write-Host "headers:  $Dest"
