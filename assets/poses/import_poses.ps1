param([string]$RepoPath = "C:\Users\van02\repos\horror-shorts")
$ErrorActionPreference = 'Stop'
if (!(Test-Path (Join-Path $RepoPath '.git'))) { throw "Git repo not found: $RepoPath" }
$root = Split-Path -Parent $MyInvocation.MyCommand.Path
$target = Join-Path $RepoPath 'assets\character\host\poses'
New-Item -Path $target -ItemType Directory -Force | Out-Null
$names = @(Get-ChildItem -LiteralPath $root -Filter '*.png' -File | Select-Object -ExpandProperty Name)
foreach ($name in $names) {
  Copy-Item -LiteralPath (Join-Path $root $name) -Destination (Join-Path $target $name) -Force
  Write-Host "Imported $name"
}
Push-Location $RepoPath
try {
  if ((git branch --show-current).Trim() -ne 'main') { throw 'Switch to main before import.' }
  foreach ($name in $names) {
    git add -- "assets/character/host/poses/$name"
    if ($LASTEXITCODE -ne 0) { throw "git add failed: $name" }
  }
  git diff --cached --quiet
  if ($LASTEXITCODE -eq 0) { Write-Host 'No changes.' }
  elseif ($LASTEXITCODE -eq 1) {
    git commit -m 'Import approved poses and counting variants without deleting originals'
    if ($LASTEXITCODE -ne 0) { throw 'Commit failed.' }
    git push origin main
    if ($LASTEXITCODE -ne 0) { throw 'Push failed. Commit remains local.' }
  } else { throw 'Git staged diff failed.' }
} finally { Pop-Location }
