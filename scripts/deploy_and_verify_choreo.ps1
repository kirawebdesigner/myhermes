param(
    [string]$Remote = "myhermes",
    [string]$Branch = "codex/hermes-operator-choreo",
    [string]$Url = "https://8de13ef8-ab04-4bef-bf86-752f49a8c6e9-dev.e1-us-east-azure.choreoapis.dev/myhermes/my-hermes/v1.0",
    [Parameter(Mandatory = $true)]
    [string]$ApiKey
)

$ErrorActionPreference = "Stop"

Write-Host "Hermes Choreo deploy helper"
Write-Host "Repo:   $(Get-Location)"
Write-Host "Remote: $Remote"
Write-Host "Branch: $Branch"
Write-Host ""

Write-Host "1. Checking local branch state..."
git status --short --branch

Write-Host ""
Write-Host "2. Pushing deploy branch..."
git push $Remote "HEAD:refs/heads/$Branch"

Write-Host ""
Write-Host "3. Waiting for Choreo auto-deploy. Watch the Choreo UI until the new build is Active."
Write-Host "   Then press Enter to run verification."
Read-Host

Write-Host ""
Write-Host "4. Verifying /health..."
curl.exe "$Url/health"

Write-Host ""
Write-Host ""
Write-Host "5. Verifying /operator/selfcheck..."
curl.exe "$Url/operator/selfcheck" -H "x-api-key: $ApiKey"

Write-Host ""
Write-Host ""
Write-Host "6. Smoke-test from Telegram:"
Write-Host "   /selfcheck"
Write-Host "   hi"
Write-Host "   remember KirzKit is my default UI kit"
Write-Host "   continue BrandBlueprint"
Write-Host "   build a SaaS landing page for BrandBlueprint"
Write-Host "   /repo index kirawebdesigner/myhermes"
Write-Host ""
Write-Host "Done."
