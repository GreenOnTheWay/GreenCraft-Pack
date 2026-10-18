# Compare actual installed payloads, not just a version label or a GPU_PASS flag.
function Test-PublishedCandidate {
    param([string]$RepoDir)
    $candidate = Join-Path $RepoDir 'candidate'
    $stable = Join-Path $RepoDir 'stable'
    $candidateJson = Join-Path $candidate 'greencraft-release.json'
    $stableJson = Join-Path $stable 'greencraft-release.json'
    if (!(Test-Path $candidateJson) -or !(Test-Path $stableJson)) { return $false }
    $cand = Get-Content $candidateJson -Raw | ConvertFrom-Json
    $published = Get-Content $stableJson -Raw | ConvertFrom-Json
    if ($cand.status -ne 'GPU_PASS' -or $published.status -ne 'STABLE') { return $false }
    foreach ($field in @('schema', 'pack', 'release', 'greencraft_version', 'minecraft', 'fabric', 'graphics', 'content', 'warnings')) {
        if (($cand.$field | ConvertTo-Json -Depth 50 -Compress) -cne
            ($published.$field | ConvertTo-Json -Depth 50 -Compress)) { return $false }
    }
    # Lifecycle metadata differs after promotion; every other file must match.
    $files = @(Get-ChildItem $candidate -File -Recurse -Force | Where-Object {
        $_.FullName -notin @($candidateJson, (Join-Path $candidate 'status.json'))
    })
    $stableFiles = @(Get-ChildItem $stable -File -Recurse -Force | Where-Object {
        $_.FullName -notin @($stableJson, (Join-Path $stable 'status.json'))
    })
    if ($files.Count -ne $stableFiles.Count) { return $false }
    foreach ($file in $files) {
        $relative = $file.FullName.Substring($candidate.Length).TrimStart('\', '/')
        $other = Join-Path $stable $relative
        if (!(Test-Path $other -PathType Leaf)) { return $false }
        $sha = [System.Security.Cryptography.SHA256]::Create()
        try {
            $first = [Convert]::ToBase64String($sha.ComputeHash([IO.File]::ReadAllBytes($file.FullName)))
            $second = [Convert]::ToBase64String($sha.ComputeHash([IO.File]::ReadAllBytes($other)))
            if ($first -cne $second) { return $false }
        } finally { $sha.Dispose() }
    }
    return $true
}
