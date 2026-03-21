param(
    [string]$MuseTalkRepo = "E:\project_codecortex\MuseTalk",
    [string]$PythonExe = "E:\project_codecortex\.conda-musetalk\python.exe",
    [string]$CacheRoot = "E:\project_codecortex\avatar_service\.hf-cache",
    [string]$HfEndpoint = "https://huggingface.co"
)

$ErrorActionPreference = 'Stop'

$repoPath = (Resolve-Path $MuseTalkRepo).Path
$modelsRoot = Join-Path $repoPath 'models'
$pythonDir = Split-Path $PythonExe -Parent
$hfCli = Join-Path $pythonDir 'Scripts\huggingface-cli.exe'
if (-not (Test-Path $hfCli)) {
    throw "huggingface-cli.exe not found at $hfCli"
}

New-Item -ItemType Directory -Force -Path $modelsRoot | Out-Null
New-Item -ItemType Directory -Force -Path $CacheRoot | Out-Null
$hubCache = Join-Path $CacheRoot 'hub'
$transformersCache = Join-Path $CacheRoot 'transformers'
New-Item -ItemType Directory -Force -Path $hubCache | Out-Null
New-Item -ItemType Directory -Force -Path $transformersCache | Out-Null

$env:HF_HOME = $CacheRoot
$env:HUGGINGFACE_HUB_CACHE = $hubCache
$env:TRANSFORMERS_CACHE = $transformersCache
$env:HF_ENDPOINT = $HfEndpoint

$downloads = @(
    @{ Repo = 'TMElyralab/MuseTalk'; LocalDir = $modelsRoot; Include = @('musetalkV15/unet.pth', 'musetalkV15/musetalk.json') },
    @{ Repo = 'stabilityai/sd-vae-ft-mse'; LocalDir = (Join-Path $modelsRoot 'sd-vae'); Include = @('config.json', 'diffusion_pytorch_model.bin') },
    @{ Repo = 'openai/whisper-tiny'; LocalDir = (Join-Path $modelsRoot 'whisper'); Include = @('config.json', 'pytorch_model.bin', 'preprocessor_config.json') },
    @{ Repo = 'yzd-v/DWPose'; LocalDir = (Join-Path $modelsRoot 'dwpose'); Include = @('dw-ll_ucoco_384.pth') },
    @{ Repo = 'ByteDance/LatentSync'; LocalDir = (Join-Path $modelsRoot 'syncnet'); Include = @('latentsync_syncnet.pt') },
    @{ Repo = 'ManyOtherFunctions/face-parse-bisent'; LocalDir = (Join-Path $modelsRoot 'face-parse-bisent'); Include = @('79999_iter.pth', 'resnet18-5c106cde.pth') }
)

foreach ($download in $downloads) {
    New-Item -ItemType Directory -Force -Path $download.LocalDir | Out-Null
    Write-Host "Downloading $($download.Repo)"
    if ($download.ContainsKey('Include')) {
        Write-Host ("  include: " + ($download.Include -join ', '))
    }
    Write-Host "  target:  $($download.LocalDir)"

    $args = @('download', $download.Repo, '--local-dir', $download.LocalDir, '--max-workers', '2')
    if ($download.ContainsKey('Include')) {
        $args += '--include'
        $args += $download.Include
    }

    & $hfCli @args
    if ($LASTEXITCODE -ne 0) {
        throw "Download failed for $($download.Repo)"
    }
}

Write-Host 'All required MuseTalk v15 model assets downloaded successfully.'
