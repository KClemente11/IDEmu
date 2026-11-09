[CmdletBinding()]
param(
    [string]$Distro = 'Ubuntu',
    [ValidateRange(1024, 65535)]
    [int]$Port = 8765,
    [switch]$NoBrowser
)

$wslArgs = @(
    '--distribution', $Distro, '--cd', $PSScriptRoot, '--exec',
    'sh', 'tools/windows-wsl.sh', '--port', $Port.ToString()
)
if ($NoBrowser) {
    $wslArgs += '--no-browser'
}

& wsl.exe @wslArgs
exit $LASTEXITCODE
