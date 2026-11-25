<#
.SYNOPSIS
    Gerenciador Interativo de Publicação de Atualizações — Nexus Vision (NexuSistemas).
    Chamado por publicar_atualizacao.bat com -ExecutionPolicy Bypass.
#>

param(
    [string]$ProjectRoot = "",
    [string]$RepoName = "nexus-vision",
    [switch]$DryRun
)

$ErrorActionPreference = "Stop"
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8
[Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12 -bor [Net.SecurityProtocolType]::Tls13

if ([string]::IsNullOrWhiteSpace($ProjectRoot)) {
    $ProjectRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
} else {
    $ProjectRoot = (Resolve-Path $ProjectRoot).Path
}
Set-Location $ProjectRoot

# ==============================================================================
# UTILITÁRIOS VISUAIS & DE ARQUIVO
# ==============================================================================
function Write-Banner {
    Clear-Host
    Write-Host "========================================================================" -ForegroundColor Cyan
    Write-Host "   NEXUS VISION — PUBLICADOR OFICIAL DE ATUALIZACOES (NexuSistemas)    " -ForegroundColor White
    Write-Host "========================================================================" -ForegroundColor Cyan
    Write-Host ""
}

function Write-Step([string]$StepNum, [string]$Text) {
    Write-Host ""
    Write-Host "[$StepNum] $Text" -ForegroundColor Cyan
}

function Write-Utf8NoBom([string]$FilePath, [string]$Text) {
    $utf8NoBom = New-Object System.Text.UTF8Encoding($false)
    [System.IO.File]::WriteAllText($FilePath, $Text, $utf8NoBom)
}

function Resolve-GitExe {
    $cmd = Get-Command git -ErrorAction SilentlyContinue
    if ($cmd) { return $cmd.Source }
    $candidates = @(
        "C:\Program Files\Git\cmd\git.exe",
        "C:\Program Files (x86)\Git\cmd\git.exe",
        (Join-Path $env:LOCALAPPDATA "Programs\Git\cmd\git.exe")
    )
    foreach ($c in $candidates) {
        if (Test-Path $c) { return $c }
    }
    return $null
}

function Read-GitHubToken {
    $gitignorePath = Join-Path $ProjectRoot ".gitignore"
    $envDeployPath = Join-Path $ProjectRoot ".env.deploy"

    if (-not (Test-Path $gitignorePath)) {
        throw "SEGURANCA CRITICA: .gitignore nao encontrado na raiz. Abortando."
    }
    $giContent = [System.IO.File]::ReadAllText($gitignorePath, [System.Text.Encoding]::UTF8)
    if ($giContent -notmatch "\.env\.deploy") {
        throw "SEGURANCA CRITICA: .env.deploy nao esta bloqueado no .gitignore. Abortando."
    }
    if (-not (Test-Path $envDeployPath)) {
        throw "Arquivo .env.deploy nao encontrado na raiz do projeto."
    }

    $tokenLine = Get-Content -Path $envDeployPath -Encoding UTF8 |
        Where-Object { $_ -match "^\s*GITHUB_TOKEN\s*=" } |
        Select-Object -First 1
    if (-not $tokenLine) {
        throw "GITHUB_TOKEN nao encontrado dentro de .env.deploy."
    }
    $tok = ($tokenLine -split "=", 2)[1].Trim().Trim('"').Trim("'")
    if ([string]::IsNullOrWhiteSpace($tok)) {
        throw "GITHUB_TOKEN esta vazio em .env.deploy."
    }
    return $tok
}

function Upload-GitHubReleaseAsset {
    param(
        [string]$UploadUrlTemplate,
        [string]$LocalFilePath,
        [string]$AssetFileName,
        [hashtable]$Headers
    )
    $baseUploadUrl = ($UploadUrlTemplate -replace "\{\?.*\}$", "")
    $encodedName = [System.Uri]::EscapeDataString($AssetFileName)
    $targetUrl = "${baseUploadUrl}?name=${encodedName}"

    $sizeMb = [Math]::Round((Get-Item $LocalFilePath).Length / 1MB, 1)
    Write-Host "  -> Enviando asset '$AssetFileName' ($sizeMb MB) para o GitHub..." -ForegroundColor Yellow

    $uploadHeaders = @{
        Authorization = $Headers.Authorization
        Accept        = "application/vnd.github+json"
        "User-Agent"  = $Headers."User-Agent"
    }

    $resp = Invoke-RestMethod `
        -Uri $targetUrl `
        -Method Post `
        -Headers $uploadHeaders `
        -InFile $LocalFilePath `
        -ContentType "application/octet-stream" `
        -TimeoutSec 600

    Write-Host "     Upload concluido: $($resp.browser_download_url)" -ForegroundColor Green
    return $resp.browser_download_url
}

# ==============================================================================
# INÍCIO DO FLUXO INTERATIVO
# ==============================================================================
try {
    $configPyPath   = Join-Path $ProjectRoot "desktop-app\config.py"
    $supaConfigPath = Join-Path $ProjectRoot "desktop-app\supabase_config.py"
    $issPath        = Join-Path $ProjectRoot "desktop-app\installer\NexusVision.iss"
    $webPkgPath     = Join-Path $ProjectRoot "web-portal\package.json"
    $webLandingPath = Join-Path $ProjectRoot "web-portal\src\pages\LandingPage.tsx"
    $venvPython     = Join-Path $ProjectRoot ".venv\Scripts\python.exe"
    $buildScript    = Join-Path $ProjectRoot "desktop-app\build_installer.py"

    if (-not (Test-Path $configPyPath)) {
        throw "Arquivo nao encontrado: $configPyPath"
    }

    # 1. LEITURA DA VERSÃO ATUAL EM desktop-app/config.py
    $configText = [System.IO.File]::ReadAllText($configPyPath, [System.Text.Encoding]::UTF8)
    $verMatch = [regex]::Match($configText, 'APP_VERSION(?:\s*:\s*str)?\s*=\s*"(\d+)\.(\d+)\.(\d+)"')
    if (-not $verMatch.Success) {
        throw "Nao foi possivel localizar APP_VERSION no formato X.Y.Z em desktop-app/config.py."
    }

    $curMajor = [int]$verMatch.Groups[1].Value
    $curMinor = [int]$verMatch.Groups[2].Value
    $curPatch = [int]$verMatch.Groups[3].Value
    $currentVersion = "$curMajor.$curMinor.$curPatch"

    $nextPatch = "$curMajor.$curMinor.$($curPatch + 1)"
    $nextMinor = "$curMajor.$($curMinor + 1).0"
    $nextMajor = "$($curMajor + 1).0.0"

    if ($DryRun) {
        Write-Host "[DRY-RUN] Versao atual lida com sucesso: $currentVersion" -ForegroundColor Green
        Write-Host "[DRY-RUN] Sugestoes SemVer: Patch=$nextPatch | Minor=$nextMinor | Major=$nextMajor" -ForegroundColor Cyan
        exit 0
    }

    Write-Banner
    Write-Host "  Versao atual instalada no codigo: " -NoNewline
    Write-Host "v$currentVersion" -ForegroundColor Green
    Write-Host ""
    Write-Host "  Escolha o incremento da nova versao (SemVer):" -ForegroundColor White
    Write-Host "    [1] Patch (Correcao rapida)  -> v$nextPatch  (Padrao - aperte ENTER)" -ForegroundColor Cyan
    Write-Host "    [2] Minor (Nova funcao/aba)  -> v$nextMinor" -ForegroundColor Yellow
    Write-Host "    [3] Major (Grande mudanca)   -> v$nextMajor" -ForegroundColor Magenta
    Write-Host "    [4] Digitar versao manualmente (formato X.Y.Z)" -ForegroundColor Gray
    Write-Host ""

    $newVersion = $null
    while (-not $newVersion) {
        $choice = (Read-Host "  Opcao [1]").Trim()
        if ([string]::IsNullOrWhiteSpace($choice) -or $choice -eq "1") {
            $newVersion = $nextPatch
        } elseif ($choice -eq "2") {
            $newVersion = $nextMinor
        } elseif ($choice -eq "3") {
            $newVersion = $nextMajor
        } elseif ($choice -eq "4") {
            $manual = (Read-Host "  Digite a versao (ex: 1.2.3)").Trim().TrimStart("v", "V")
            if ($manual -match "^\d+\.\d+\.\d+$") {
                $newVersion = $manual
            } else {
                Write-Host "  [!] Formato invalido. Use exatamente X.Y.Z (apenas numeros)." -ForegroundColor Red
            }
        } else {
            Write-Host "  [!] Opcao invalida. Digite 1, 2, 3 ou 4." -ForegroundColor Red
        }
    }

    Write-Host ""
    $changelog = (Read-Host "  Descricao curta da atualizacao (ENTER para padrao)").Trim()
    if ([string]::IsNullOrWhiteSpace($changelog)) {
        $changelog = "Melhorias gerais de estabilidade, desempenho e seguranca."
    }

    # Valida token e descobre Owner autenticado no GitHub antes de iniciar o build
    $gitHubToken = Read-GitHubToken
    $ghHeaders = @{
        Authorization = "Bearer $gitHubToken"
        Accept        = "application/vnd.github+json"
        "User-Agent"  = "NexusVision-ReleaseManager"
    }

    Write-Host ""
    Write-Host "  Validando autenticacao na API do GitHub..." -ForegroundColor DarkGray
    $ghUser = Invoke-RestMethod -Uri "https://api.github.com/user" -Headers $ghHeaders -Method Get -TimeoutSec 20
    $owner = $ghUser.login
    $fullRepo = "$owner/$RepoName"

    Write-Host ""
    Write-Host "------------------------------------------------------------------------" -ForegroundColor DarkCyan
    Write-Host "  RESUMO DA PUBLICACAO:" -ForegroundColor White
    Write-Host "    Versao:       v$currentVersion  --->  v$newVersion" -ForegroundColor Green
    Write-Host "    Changelog:    $changelog" -ForegroundColor White
    Write-Host "    Repositorio:  https://github.com/$fullRepo" -ForegroundColor Cyan
    Write-Host "    Instalador:   Output\NexusVision_Setup_v$newVersion.exe" -ForegroundColor White
    Write-Host "------------------------------------------------------------------------" -ForegroundColor DarkCyan
    $confirm = (Read-Host "  Confirmar compilacao e publicacao? [S/n]").Trim().ToUpper()
    if ($confirm -eq "N") {
        Write-Host "  Publicacao cancelada pelo usuario." -ForegroundColor Yellow
        exit 0
    }

    # ==========================================================================
    # 2. SINCRONIZAÇÃO AUTOMÁTICA DA VERSÃO EM TODO O PROJETO
    # ==========================================================================
    Write-Step "1/5" "Sincronizando versao v$newVersion em todos os arquivos do projeto..."

    # 2a. desktop-app/config.py
    $updatedConfig = [regex]::Replace(
        $configText,
        '(APP_VERSION(?:\s*:\s*str)?\s*=\s*)"\d+\.\d+\.\d+"',
        "`$1`"$newVersion`""
    )
    Write-Utf8NoBom $configPyPath $updatedConfig
    Write-Host "  -> Atualizado: desktop-app\config.py" -ForegroundColor Gray

    # 2b. desktop-app/supabase_config.py (garante updater.py apontando para o mesmo owner/repo!)
    if (Test-Path $supaConfigPath) {
        $supaText = [System.IO.File]::ReadAllText($supaConfigPath, [System.Text.Encoding]::UTF8)
        $updatedSupa = [regex]::Replace(
            $supaText,
            '(os\.getenv\("NEXUS_GITHUB_REPO",\s*)"[^"]+"(\))',
            "`$1`"$fullRepo`"`$2"
        )
        Write-Utf8NoBom $supaConfigPath $updatedSupa
        Write-Host "  -> Verificado: desktop-app\supabase_config.py (GITHUB_REPO = $fullRepo)" -ForegroundColor Gray
    }

    # 2c. desktop-app/installer/NexusVision.iss
    if (Test-Path $issPath) {
        $issText = [System.IO.File]::ReadAllText($issPath, [System.Text.Encoding]::UTF8)
        $issText = [regex]::Replace($issText, '(#define\s+MyAppVersion\s+)"[^"]+"', "`$1`"$newVersion`"")
        $issText = [regex]::Replace($issText, '(OutputBaseFilename=)NexusVision_Setup_v[^\r\n]+', "`$1NexusVision_Setup_v$newVersion")
        $utf8Bom = New-Object System.Text.UTF8Encoding($true)
        [System.IO.File]::WriteAllText($issPath, $issText, $utf8Bom)
        Write-Host "  -> Atualizado: desktop-app\installer\NexusVision.iss" -ForegroundColor Gray
    }

    # 2d. web-portal/package.json
    if (Test-Path $webPkgPath) {
        $pkgText = [System.IO.File]::ReadAllText($webPkgPath, [System.Text.Encoding]::UTF8)
        $pkgText = [regex]::Replace($pkgText, '("version"\s*:\s*)"[^"]+"', "`$1`"$newVersion`"", 1)
        Write-Utf8NoBom $webPkgPath $pkgText
        Write-Host "  -> Atualizado: web-portal\package.json" -ForegroundColor Gray
    }

    # 2e. web-portal/src/pages/LandingPage.tsx (fallback de versao e nome do arquivo)
    if (Test-Path $webLandingPath) {
        $lpText = [System.IO.File]::ReadAllText($webLandingPath, [System.Text.Encoding]::UTF8)
        $lpText = [regex]::Replace($lpText, "(version:\s*)'v\d+\.\d+\.\d+'", "`$1'v$newVersion'")
        $lpText = [regex]::Replace($lpText, "(fileName:\s*)'NexusVision_Setup_v\d+\.\d+\.\d+\.exe'", "`$1'NexusVision_Setup_v$newVersion.exe'")
        Write-Utf8NoBom $webLandingPath $lpText
        Write-Host "  -> Atualizado: web-portal\src\pages\LandingPage.tsx" -ForegroundColor Gray
    }

    # ==========================================================================
    # 3. COMPILAÇÃO AUTOMÁTICA DO NOVO INSTALADOR (.exe)
    # ==========================================================================
    Write-Step "2/5" "Compilando novo instalador Windows (PyInstaller + Inno Setup)..."

    if (-not (Test-Path $venvPython)) {
        throw "Ambiente virtual nao encontrado em: $venvPython"
    }
    if (-not (Test-Path $buildScript)) {
        throw "Script de build nao encontrado em: $buildScript"
    }

    & $venvPython $buildScript
    if ($LASTEXITCODE -ne 0) {
        throw "Falha na compilacao (build_installer.py retornou codigo $LASTEXITCODE)."
    }

    $expectedExe = Join-Path $ProjectRoot "Output\NexusVision_Setup_v$newVersion.exe"
    if (-not (Test-Path $expectedExe)) {
        throw "Instalador esperado nao foi encontrado apos o build: $expectedExe"
    }
    $exeInfo = Get-Item $expectedExe
    if ($exeInfo.Length -lt 5MB) {
        throw "Instalador gerado parece corrompido ou incompleto ($($exeInfo.Length) bytes)."
    }
    $exeSizeMb = [Math]::Round($exeInfo.Length / 1MB, 1)
    Write-Host "  -> Instalador compilado e verificado: $expectedExe ($exeSizeMb MB)" -ForegroundColor Green

    # ==========================================================================
    # 4. GARANTIR REPOSITÓRIO NO GITHUB + GIT COMMIT, TAG E PUSH SEGURO
    # ==========================================================================
    Write-Step "3/5" "Verificando repositorio GitHub ($fullRepo)..."

    try {
        $null = Invoke-RestMethod -Uri "https://api.github.com/repos/$fullRepo" -Headers $ghHeaders -Method Get -TimeoutSec 20
        Write-Host "  -> Repositorio encontrado: https://github.com/$fullRepo" -ForegroundColor Gray
    } catch {
        Write-Host "  -> Repositorio nao existe ainda. Criando https://github.com/$fullRepo..." -ForegroundColor Yellow
        $repoBody = @{
            name        = $RepoName
            description = "Nexus Vision — Monitoramento Veicular Inteligente ALPR Offline (NexuSistemas Tecnologia)"
            private     = $false
            auto_init   = $false
        } | ConvertTo-Json
        $null = Invoke-RestMethod -Uri "https://api.github.com/user/repos" -Headers $ghHeaders -Method Post -Body $repoBody -ContentType "application/json" -TimeoutSec 20
        Write-Host "  -> Repositorio criado com sucesso!" -ForegroundColor Green
    }

    Write-Step "4/5" "Realizando Git Commit, Tag v$newVersion e Push seguro..."
    $gitExe = Resolve-GitExe
    if (-not $gitExe) {
        throw "Git CLI nao encontrado neste PC. Instale via 'winget install Git.Git' e execute publicar_atualizacao.bat novamente."
    }

    if (-not (Test-Path (Join-Path $ProjectRoot ".git"))) {
        & $gitExe init -b main | Out-Null
    }

    # Checagem dupla de segurança antes de qualquer git add / push
    $ignoredCheck = & $gitExe check-ignore ".env.deploy" 2>$null
    if (-not $ignoredCheck) {
        throw "BLOQUEIO DE SEGURANCA: o Git nao reconheceu .env.deploy como ignorado!"
    }

    $remoteUrl = "https://github.com/$fullRepo.git"
    $curOrigin = & $gitExe remote get-url origin 2>$null
    if ($curOrigin) {
        & $gitExe remote set-url origin $remoteUrl
    } else {
        & $gitExe remote add origin $remoteUrl
    }

    & $gitExe add -A
    $stagedFiles = & $gitExe diff --cached --name-only
    foreach ($sf in $stagedFiles) {
        if ($sf -match "(^|/)\.env") {
            & $gitExe reset HEAD -- $sf | Out-Null
            throw "BLOQUEIO DE SEGURANCA: arquivo sensivel '$sf' detectado na staging area!"
        }
    }

    $commitMsg = "chore(release): v$newVersion - $changelog"
    $hasChanges = & $gitExe status --porcelain
    if ($hasChanges) {
        & $gitExe commit -m $commitMsg
        if ($LASTEXITCODE -ne 0) {
            throw "Falha ao executar git commit. Verifique user.name e user.email configurados no Git."
        }
    } else {
        Write-Host "  -> Nenhuma alteracao nova pendente para commit (seguindo para tag/push)." -ForegroundColor Yellow
    }

    $tagName = "v$newVersion"
    & $gitExe tag -f -a $tagName -m "Nexus Vision $tagName - $changelog"
    if ($LASTEXITCODE -ne 0) { throw "Falha ao criar tag Git $tagName." }

    # Push autenticado via header temporario (nunca grava token no .git/config!)
    $basicAuth = [Convert]::ToBase64String([System.Text.Encoding]::ASCII.GetBytes("${owner}:${gitHubToken}"))
    & $gitExe -c "http.extraHeader=Authorization: Basic $basicAuth" push -u origin main --tags --force-with-lease
    if ($LASTEXITCODE -ne 0) {
        # Fallback caso a branch main ainda nao exista no remoto
        & $gitExe -c "http.extraHeader=Authorization: Basic $basicAuth" push -u origin main --tags
        if ($LASTEXITCODE -ne 0) { throw "Falha no git push para origin main --tags." }
    }
    Write-Host "  -> Commit e tag $tagName enviados para https://github.com/$fullRepo" -ForegroundColor Green

    # ==========================================================================
    # 5. PUBLICAÇÃO DA RELEASE + UPLOAD DOS BINÁRIOS (.exe) NA API DO GITHUB
    # ==========================================================================
    Write-Step "5/5" "Publicando Release $tagName e enviando instaladores .exe para o GitHub..."

    $releaseBodyMd = @"
## Nexus Vision $tagName — NexuSistemas Tecnologia

### O que mudou nesta versão
- $changelog

### Instalação / Atualização (Windows 10/11)
1. Baixe o instalador **`NexusVision_Setup_v$newVersion.exe`** (ou **`NexusVision_Setup.exe`**) abaixo.
2. Execute o instalador — seus dados locais (moradores, histórico e licença) em ``%LOCALAPPDATA%\NexuSistemas\NexusVision`` são preservados automaticamente.
3. PCs já instalados também podem atualizar em 1 clique pela aba **Conta & Licença → Verificar Atualizações**.
"@

    $existingRelease = $null
    try {
        $existingRelease = Invoke-RestMethod `
            -Uri "https://api.github.com/repos/$fullRepo/releases/tags/$tagName" `
            -Headers $ghHeaders `
            -Method Get `
            -TimeoutSec 20
    } catch {
        $existingRelease = $null
    }

    if ($existingRelease) {
        Write-Host "  -> Release $tagName ja existe; atualizando notas e substituindo assets..." -ForegroundColor Yellow
        $patchPayload = @{
            name = "Nexus Vision $tagName"
            body = $releaseBodyMd
        } | ConvertTo-Json
        $releaseObj = Invoke-RestMethod `
            -Uri "https://api.github.com/repos/$fullRepo/releases/$($existingRelease.id)" `
            -Headers $ghHeaders `
            -Method Patch `
            -Body ([System.Text.Encoding]::UTF8.GetBytes($patchPayload)) `
            -ContentType "application/json; charset=utf-8" `
            -TimeoutSec 30

        # Remove assets antigos com o mesmo nome antes de reenviar
        foreach ($oldAsset in ($existingRelease.assets | Where-Object {
            $_.name -eq "NexusVision_Setup_v$newVersion.exe" -or $_.name -eq "NexusVision_Setup.exe"
        })) {
            Invoke-RestMethod `
                -Uri "https://api.github.com/repos/$fullRepo/releases/assets/$($oldAsset.id)" `
                -Headers $ghHeaders `
                -Method Delete `
                -TimeoutSec 20 | Out-Null
        }
    } else {
        $createPayload = @{
            tag_name         = $tagName
            target_commitish = "main"
            name             = "Nexus Vision $tagName"
            body             = $releaseBodyMd
            draft            = $false
            prerelease       = $false
        } | ConvertTo-Json
        $releaseObj = Invoke-RestMethod `
            -Uri "https://api.github.com/repos/$fullRepo/releases" `
            -Headers $ghHeaders `
            -Method Post `
            -Body ([System.Text.Encoding]::UTF8.GetBytes($createPayload)) `
            -ContentType "application/json; charset=utf-8" `
            -TimeoutSec 30
    }

    # Upload 1: Arquivo versionado NexusVision_Setup_vX.Y.Z.exe
    $versionedUrl = Upload-GitHubReleaseAsset `
        -UploadUrlTemplate $releaseObj.upload_url `
        -LocalFilePath $expectedExe `
        -AssetFileName "NexusVision_Setup_v$newVersion.exe" `
        -Headers $ghHeaders

    # Upload 2: Asset fixo NexusVision_Setup.exe (link permanente no portal vision.nexusistemas.app.br)
    $latestDirectUrl = Upload-GitHubReleaseAsset `
        -UploadUrlTemplate $releaseObj.upload_url `
        -LocalFilePath $expectedExe `
        -AssetFileName "NexusVision_Setup.exe" `
        -Headers $ghHeaders

    # ==========================================================================
    # 6. TELA FINAL DE CONFIRMAÇÃO
    # ==========================================================================
    Write-Host ""
    Write-Host "========================================================================" -ForegroundColor Green
    Write-Host "   ATUALIZACAO NEXUS VISION $tagName PUBLICADA COM SUCESSO!             " -ForegroundColor Green
    Write-Host "========================================================================" -ForegroundColor Green
    Write-Host "  Versao Publicada:     $tagName" -ForegroundColor Green
    Write-Host "  Instalador Local:     $expectedExe ($exeSizeMb MB)" -ForegroundColor Green
    Write-Host "  Pagina da Release:    $($releaseObj.html_url)" -ForegroundColor Cyan
    Write-Host "  Download Versionado:  $versionedUrl" -ForegroundColor Cyan
    Write-Host "  Link Fixo (Portal):   https://github.com/$fullRepo/releases/latest/download/NexusVision_Setup.exe" -ForegroundColor Cyan
    Write-Host "========================================================================" -ForegroundColor Green
    Write-Host "  Os PCs das portarias ja detectam $tagName no botao 'Verificar Atualizacoes'." -ForegroundColor White
    exit 0
}
catch {
    Write-Host ""
    Write-Host "========================================================================" -ForegroundColor Red
    Write-Host "  [ERRO] $($_.Exception.Message)" -ForegroundColor Red
    Write-Host "========================================================================" -ForegroundColor Red
    exit 1
}
