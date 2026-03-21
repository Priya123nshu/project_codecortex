$python = 'E:\project_codecortex\.conda-musetalk\python.exe'
if (-not (Test-Path $python)) {
  $python = 'python'
}

& $python -m avatar_service.validate_env
if ($LASTEXITCODE -ne 0) {
  exit $LASTEXITCODE
}

& $python -m avatar_service.smoke_test `
  --video-path 'E:\project_codecortex\sydneeyvid.mp4' `
  --audio-path 'E:\project_codecortex\audio.mp3' `
  --avatar-id 'sydneey-demo' `
  --job-id 'sydneey-demo-job'
exit $LASTEXITCODE
