<#
.SYNOPSIS
    Automação segura de criação/publicação do repositório Nexus Vision no GitHub.
    Lê GITHUB_TOKEN exclusivamente de .env.deploy (nunca versiona .env.deploy).
#>

param(
    [string]$RepoName = "nexus-vision",
    [switch]$PrivateRepo
)

$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $Root

# 1. Validação rigorosa de segurança (.gitignore + .env.deploy)
if (-not (Test-Path ".gitignore")) {
    throw "ERRO CRÍTICO: .gitignore não encontrado. Abortando para evitar vazamento de tokens."
}
$gitignore = Get-Content ".gitignore" -Raw
if ($gitignore -notmatch "\.env\.deploy") {
    throw "ERRO CRÍTICO: .env.deploy não está bloqueado no .gitignore!"
}
if (-not (Test-Path ".env.deploy")) {
    throw "Arquivo .env.deploy não encontrado na raiz."
}

$tokenLine = Get-Content ".env.deploy" | Where-Object { $_ -match "^GITHUB_TOKEN=" } | Select-Object -First 1
if (-not $tokenLine) {
    throw "GITHUB_TOKEN não encontrado em .env.deploy."
}
$GitHubToken = ($tokenLine -split "=", 2)[1].Trim()

# 2. Descobre usuário autenticado na API do GitHub
$headers = @{
    Authorization = "Bearer $GitHubToken"
    Accept        = "application/vnd.github+json"
    "User-Agent"  = "NexusVision-Deploy"
}
$user = Invoke-RestMethod -Uri "https://api.github.com/user" -Headers $headers -Method Get
$Owner = $user.login
Write-Host "Autenticado no GitHub como: $Owner" -ForegroundColor Cyan

# 3. Cria repositório se ainda não existir
try {
    $repo = Invoke-RestMethod -Uri "https://api.github.com/repos/$Owner/$RepoName" -Headers $headers -Method Get
    Write-Host "Repositório já existe: $($repo.html_url)" -ForegroundColor Yellow
} catch {
    $body = @{
        name        = $RepoName
        description = "Nexus Vision — Sistema Desktop de Leitura Automática de Placas com IA Nativa Offline e Portal SaaS (NexuSistemas Tecnologia)"
        private     = [bool]$PrivateRepo
        auto_init   = $false
    } | ConvertTo-Json
    $repo = Invoke-RestMethod -Uri "https://api.github.com/user/repos" -Headers $headers -Method Post -Body $body -ContentType "application/json"
    Write-Host "Repositório criado: $($repo.html_url)" -ForegroundColor Green
}

# 4. Verifica se git CLI está instalado
$gitCmd = Get-Command git -ErrorAction SilentlyContinue
if (-not $gitCmd) {
    Write-Warning "Git CLI não encontrado no PATH. Instale via: winget install Git.Git"
    Write-Host "Repositório pronto em: https://github.com/$Owner/$RepoName" -ForegroundColor Cyan
    exit 0
}

if (-not (Test-Path ".git")) {
    git init -b main
}

# Confirma que .env.deploy está realmente ignorado pelo Git
$ignored = git check-ignore .env.deploy 2>$null
if (-not $ignored) {
    throw "BLOQUEIO DE SEGURANÇA: Git não marcou .env.deploy como ignorado!"
}

$remoteUrl = "https://github.com/$Owner/$RepoName.git"
$existingRemote = git remote get-url origin 2>$null
if ($existingRemote) {
    git remote set-url origin $remoteUrl
} else {
    git remote add origin $remoteUrl
}

git add .
$staged = git diff --cached --name-only
if ($staged -match "\.env") {
    git reset HEAD -- .env*
    throw "BLOQUEIO DE SEGURANÇA: Arquivo .env detectado na staging area!"
}

git commit -m "feat: release Nexus Vision v1.0.0 (Desktop ALPR, Supabase Licensing, Web Portal)" 2>$null

# Push usando header temporário sem gravar o token no .git/config
$basicAuth = [Convert]::ToBase64String([Text.Encoding]::ASCII.GetBytes("${Owner}:${GitHubToken}"))
git -c "http.extraHeader=Authorization: Basic $basicAuth" push -u origin main

Write-Host "`nDeploy no GitHub concluído com segurança: https://github.com/$Owner/$RepoName" -ForegroundColor Green
Write-Host "Configure os Secrets VITE_SUPABASE_URL e VITE_SUPABASE_ANON_KEY em Settings -> Secrets -> Actions para ativar o GitHub Pages." -ForegroundColor Cyan
