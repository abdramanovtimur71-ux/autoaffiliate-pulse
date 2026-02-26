param(
    [string]$RepoName = "autoaffiliate-pulse",
    [string]$Visibility = "public"
)

$ErrorActionPreference = "Stop"

$root = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
Set-Location $root

$ghPathCandidates = @(
    "gh",
    "C:\Program Files\GitHub CLI\gh.exe",
    "C:\Users\$env:USERNAME\AppData\Local\Programs\GitHub CLI\gh.exe"
)

$gh = $null
foreach ($candidate in $ghPathCandidates) {
    try {
        if ($candidate -eq "gh") {
            $cmd = Get-Command gh -ErrorAction SilentlyContinue
            if ($cmd) {
                $gh = $cmd.Source
                break
            }
        }
        elseif (Test-Path $candidate) {
            $gh = $candidate
            break
        }
    }
    catch {}
}

if (-not $gh) {
    throw "GitHub CLI not found. Install it with: winget install --id GitHub.cli -e"
}

& $gh auth status | Out-Null
if ($LASTEXITCODE -ne 0) {
    Write-Output "GitHub authentication required. Browser login will open..."
    & $gh auth login --web --git-protocol https
    if ($LASTEXITCODE -ne 0) {
        throw "GitHub authentication did not complete. Run the script again after login."
    }
}

$userOutput = & $gh api user --jq .login
if ($LASTEXITCODE -ne 0 -or [string]::IsNullOrWhiteSpace($userOutput)) {
    throw "Unable to detect GitHub username after authentication."
}

$user = ([string]$userOutput).Trim()

if (-not (Test-Path ".git")) {
    git init | Out-Null
}

if (-not (git config user.name)) {
    git config user.name $user
}
if (-not (git config user.email)) {
    git config user.email "$user@users.noreply.github.com"
}

if (-not (git status --porcelain)) {
    Write-Output "No changes to commit."
}
else {
    git add .
    git commit -m "feat: autonomous affiliate content engine + scheduled deploy" | Out-Null
}

$hasOrigin = $false
try {
    $origin = git remote get-url origin
    if ($origin) { $hasOrigin = $true }
}
catch {}

if (-not $hasOrigin) {
    $repo = "$user/$RepoName"
    & $gh repo create $repo --$Visibility --source . --remote origin --push
}
else {
    $currentBranch = (git branch --show-current).Trim()
    if (-not $currentBranch) {
        $currentBranch = "master"
    }
    git push -u origin $currentBranch
}

$currentBranch = (git branch --show-current).Trim()
if (-not $currentBranch) {
    $currentBranch = "master"
}

$repoFullName = "$user/$RepoName"
$workflows = & $gh api "repos/$repoFullName/actions/workflows" --jq ".workflows[].path"

if ($workflows -and ($workflows -match "github-pages-autodeploy.yml")) {
    & $gh workflow run "github-pages-autodeploy.yml" --ref $currentBranch -R $repoFullName
    Write-Output "Workflow GitHub Pages AutoDeploy started on branch: $currentBranch"
}
else {
    Write-Output "Workflow пока не зарегистрирован GitHub API. Это иногда бывает на новом репозитории."
    Write-Output "Откройте: https://github.com/$repoFullName/actions и нажмите 'Enable workflows', если кнопка есть."
}

Write-Output "Done: repository and auto-deploy are configured."
