# Installs the UTP loader into Fusion's add-ins folder. One machine, one run.
#
#   irm https://raw.githubusercontent.com/vystal/universal-tool-presets/main/tools/install.ps1 | iex
#
# What it puts there is three small files that never change: they fetch the
# add-in itself from the latest release and keep it up to date, so updating the
# shop afterwards means publishing a release rather than visiting every
# computer. Re-running this is safe and is how you pick up a change to the
# loader, which is the only part that does not update itself.
#
# Nothing here needs admin rights, and nothing is written outside the user's own
# Fusion add-ins folder.

$ErrorActionPreference = "Stop"

$repo    = "vystal/universal-tool-presets"
$branch  = "main"
$files   = @("UTP.py", "UTP.manifest", "source.json")
$addins  = Join-Path $env:APPDATA "Autodesk\Autodesk Fusion 360\API\AddIns"
$target  = Join-Path $addins "UTP"

# Older PowerShell defaults to TLS 1.0, which GitHub refuses.
try {
    [Net.ServicePointManager]::SecurityProtocol =
        [Net.SecurityProtocolType]::Tls12 -bor [Net.ServicePointManager]::SecurityProtocol
} catch { }

Write-Host "Universal Tool Presets - installing the loader"
Write-Host ""

if (-not (Test-Path $addins)) {
    throw ("Fusion's add-ins folder is not there:`n  $addins`n" +
           "Install Fusion and start it once, then run this again.")
}

# Downloaded whole, checked, and only then written. A half-written loader is a
# Fusion that reports a broken add-in on every start, and the person who ran
# this is not the person who would know why.
$fetched = @{}
foreach ($name in $files) {
    $url = "https://raw.githubusercontent.com/$repo/$branch/addin/loader/UTP/$name"
    Write-Host ("  fetching {0}" -f $name)
    try {
        $fetched[$name] = (Invoke-WebRequest -Uri $url -UseBasicParsing).Content
    } catch {
        throw ("could not fetch $name from $url`n  $($_.Exception.Message)")
    }
}

if ($fetched["UTP.py"] -notmatch "def run\(" -or
    $fetched["UTP.py"] -notmatch "SHA256") {
    throw "what came back does not look like the loader; nothing was written."
}
if ($fetched["source.json"] -notmatch '"repo"') {
    throw ("the loader's source.json does not name a repository, so it would " +
           "have nothing to fetch the add-in from. Nothing was written.")
}

$running = Get-Process Fusion360 -ErrorAction SilentlyContinue
if ($running) {
    Write-Host ""
    Write-Host "  Fusion is running. The files will be written anyway; close and" -ForegroundColor Yellow
    Write-Host "  reopen Fusion for them to take effect." -ForegroundColor Yellow
}

New-Item -ItemType Directory -Force -Path $target | Out-Null
foreach ($name in $files) {
    $to = Join-Path $target $name
    [IO.File]::WriteAllText($to, $fetched[$name], [Text.UTF8Encoding]::new($false))
}

Write-Host ""
Write-Host "  installed to $target" -ForegroundColor Green
Write-Host ""
Write-Host "Next: start Fusion. The loader fetches the add-in from the latest"
Write-Host "release, checks it against the SHA256 published beside it, and runs"
Write-Host "from a local copy afterwards - so a machine with no connection runs"
Write-Host "the copy it already has."
Write-Host ""
Write-Host "UTP appears in the Utilities tab of the Manufacture workspace."
Write-Host "If it does not, check Scripts and Add-Ins and that UTP is set to"
Write-Host "run on startup."
