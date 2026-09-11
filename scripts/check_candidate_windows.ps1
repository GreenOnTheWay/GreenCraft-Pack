param([string]$RepoDir="$env:LOCALAPPDATA\GreenCraft\repo")
$ErrorActionPreference="SilentlyContinue"
Set-Location $RepoDir
git pull --ff-only | Out-Null
$p = Join-Path $RepoDir "candidate\greencraft-release.json"
if (!(Test-Path $p)) { exit 0 }
$c = Get-Content $p -Raw | ConvertFrom-Json
if ($c.status -eq "READY_FOR_GPU") {
    msg.exe $env:USERNAME "GreenCraft: Minecraft $($c.minecraft) czeka na test GPU. Uruchom skrót 'GreenCraft GPU Test'."
}
