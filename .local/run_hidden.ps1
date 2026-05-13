param(
    [Parameter(Mandatory=$true)]
    [string]$BatchPath
)

$fullPath = Resolve-Path $BatchPath
$dir = Split-Path -Parent $fullPath

$proc = Start-Process -FilePath "cmd.exe" `
    -ArgumentList "/c `"`"$fullPath`"`"" `
    -WorkingDirectory $dir `
    -WindowStyle Hidden `
    -PassThru

$proc.WaitForExit()
