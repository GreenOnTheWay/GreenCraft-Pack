param(
    [string]$RepoDir = "$env:LOCALAPPDATA\GreenCraft\repo",
    [int]$ObserveSeconds = 90
)
$ErrorActionPreference = "Stop"
[Console]::OutputEncoding = [Text.Encoding]::UTF8

function Say($m,$c="Gray"){ Write-Host $m -ForegroundColor $c }

Set-Location $RepoDir
git pull --ff-only | Out-Host

$candidateJson = Join-Path $RepoDir "candidate\greencraft-release.json"
if (!(Test-Path $candidateJson)) {
    throw "Brak Candidate do testu."
}
$cand = Get-Content $candidateJson -Raw | ConvertFrom-Json
if ($cand.status -notin @("READY_FOR_GPU","GPU_RETRY")) {
    throw "Candidate ma status '$($cand.status)', a nie READY_FOR_GPU."
}

$ghUser = (& gh api user --jq .login).Trim()
$packUrl = "https://raw.githubusercontent.com/$ghUser/GreenCraft-Pack/main/candidate/pack.toml"

$prism = @(
 "$env:LOCALAPPDATA\Programs\PrismLauncher\prismlauncher.exe",
 "$env:ProgramFiles\PrismLauncher\prismlauncher.exe",
 "${env:ProgramFiles(x86)}\PrismLauncher\prismlauncher.exe"
) | Where-Object { $_ -and (Test-Path $_) } | Select-Object -First 1
if (!$prism) {
    $cmd = Get-Command prismlauncher.exe -ErrorAction SilentlyContinue
    if ($cmd) { $prism = $cmd.Source }
}
if (!$prism) { throw "Nie znaleziono Prism Launcher." }

$prismRoot = Join-Path $env:APPDATA "PrismLauncher"
$testId = "GreenCraft-GPU-Test"
$instance = Join-Path $prismRoot "instances\$testId"
$mc = Join-Path $instance ".minecraft"
New-Item -ItemType Directory -Force -Path $mc | Out-Null

$stableInstance = Join-Path $prismRoot "instances\GreenCraft"
$bootstrap = Join-Path $stableInstance ".minecraft\packwiz-installer-bootstrap.jar"
if (!(Test-Path $bootstrap)) { throw "Brak packwiz-installer-bootstrap.jar w głównej instancji." }
Copy-Item $bootstrap (Join-Path $mc "packwiz-installer-bootstrap.jar") -Force

# Initial component values are only a seed. packwiz-installer updates mmc-pack.json
# from candidate/pack.toml before launch.
$mmc = @{
  formatVersion = 1
  components = @(
    @{ uid="net.minecraft"; version=[string]$cand.minecraft; important=$true },
    @{ uid="net.fabricmc.fabric-loader"; version=[string]$cand.fabric }
  )
} | ConvertTo-Json -Depth 5
Set-Content (Join-Path $instance "mmc-pack.json") $mmc -Encoding UTF8

# Quotes are escaped for Prism/QSettings.
$pre = '\"$INST_JAVA\" -jar packwiz-installer-bootstrap.jar -s client ' + $packUrl
$cfg = @"
name=GreenCraft GPU Test
InstanceType=OneSix
MCLaunchMethod=LauncherPart
OverrideCommands=true
PreLaunchCommand=$pre
OverrideMemory=true
MinMemAlloc=2048
MaxMemAlloc=8192
AutomaticJava=true
"@
Set-Content (Join-Path $instance "instance.cfg") $cfg -Encoding UTF8

$log = Join-Path $mc "logs\latest.log"
if (Test-Path $log) { Remove-Item $log -Force }

Say ""
Say "GREENCRAFT GPU VALIDATOR" "Cyan"
Say "Candidate: Minecraft $($cand.minecraft)" "Green"
Say ""
Say "Prism uruchomi osobną instancję testową." "Yellow"
Say "Wejdź do dowolnego świata testowego i zostań w nim z shaderem przez około $ObserveSeconds s." "Yellow"
Say "Walidator sam sprawdzi log Iris/Sodium i wykryje typowe crashe shadera." "Yellow"
Say ""

Start-Process -FilePath $prism -ArgumentList @("--launch",$testId)

$deadline = (Get-Date).AddMinutes(5)
while (!(Test-Path $log) -and (Get-Date) -lt $deadline) { Start-Sleep -Seconds 2 }
if (!(Test-Path $log)) { throw "Minecraft nie utworzył latest.log." }

$shaderSeen = $false
$pipelineSeen = $false
$bad = $false
$badPatterns = @(
 "Failed to create shader rendering pipeline",
 "Shader compilation failed",
 "Could not compile shader",
 "Mixin apply failed",
 "Mod resolution encountered an incompatible mod set",
 "The game crashed whilst",
 "java.lang.OutOfMemoryError"
)

$started = Get-Date
while ((Get-Date) -lt $started.AddSeconds($ObserveSeconds)) {
    $txt = Get-Content $log -Raw -ErrorAction SilentlyContinue
    if ($txt -match "Using shaderpack:") { $shaderSeen = $true }
    if ($txt -match "Creating pipeline for dimension") { $pipelineSeen = $true }
    foreach($p in $badPatterns) {
        if ($txt -match [regex]::Escape($p)) {
            Say "Wykryto błąd: $p" "Red"
            $bad = $true
        }
    }
    if ($bad) { break }
    Start-Sleep -Seconds 3
}

if ($bad -or !$shaderSeen -or !$pipelineSeen) {
    Say ""
    Say "GPU TEST: FAIL" "Red"
    if (!$shaderSeen) { Say "- brak potwierdzenia 'Using shaderpack:'" "Yellow" }
    if (!$pipelineSeen) { Say "- brak potwierdzenia pipeline Iris" "Yellow" }
    python scripts\set_status.py GPU_RETRY --folder candidate
    git add candidate
    git commit -m "GreenCraft: GPU validation failed/retry $($cand.minecraft)" 2>$null
    git push
    exit 2
}

Say ""
Say "GPU TEST: PASS" "Green"
python scripts\set_status.py GPU_PASS --folder candidate
python scripts\promote.py
git add candidate stable releases
git commit -m "GreenCraft: promote $($cand.minecraft) after RTX 4070 Ti GPU validation"
git push

Say ""
Say "GreenCraft $($cand.minecraft) został promowany do STABLE." "Green"
