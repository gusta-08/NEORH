<#
Script auxiliar para criar um repositório GitHub (usando gh CLI), commitar o projeto e abrir a página do Render para conectar o repo.
Pré-requisitos:
- Git instalado
- GitHub CLI `gh` instalado e autenticado (`gh auth login`)

Uso:
> .\deploy_with_gh.ps1 -RepoName "meu-repo" -Private:$false
#>
param(
    [Parameter(Mandatory=$true)]
    [string]$RepoName,
    [bool]$Private = $false
)

function Exec {
    param($cmd)
    Write-Host "> $cmd"
    iex $cmd
}

# Verifica se gh está instalado
if (-not (Get-Command gh -ErrorAction SilentlyContinue)) {
    Write-Error "GitHub CLI (gh) não encontrado. Instale: https://cli.github.com/"
    exit 1
}

# Inicializa git se necessário
if (-not (Test-Path .git)) {
    Exec "git init"
}

# Cria .gitignore se não existir
if (-not (Test-Path .gitignore)) {
    @""" > .gitignore
__pycache__/
*.py[cod]
.venv/
.env
.env.*
instance/
.DS_Store
""" | Out-File -FilePath .gitignore -Encoding utf8
    Exec "git add .gitignore"
}

# Adiciona todos os arquivos e faz commit
Exec "git add -A"
Exec "git commit -m 'Preparar app para deploy'" 2>$null

# Cria repositório no GitHub usando gh
$visibility = $Private ? "--private" : "--public"
Exec "gh repo create $RepoName $visibility --source=. --remote=origin --push"

# Abre a página do Render para criar um novo Web Service
Write-Host "Abrindo Render para criar Web Service. Faça login, conecte o repositório e configure variáveis de ambiente conforme README.md"
Start-Process "https://dashboard.render.com/new/web-service"

Write-Host "Pronto. Após criar o serviço no Render, configure as Environment Variables (SECRET_KEY, DATABASE_URL, AWS_* se usar S3) e o Build/Start commands conforme README.md."
