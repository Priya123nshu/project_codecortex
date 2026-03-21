# Expose API

## Quick Test On EC2

From `/home/ssm-user/spillr-avatar`:

```bash
source .venv-avatar/bin/activate
export PYTHONPATH=/home/ssm-user/spillr-avatar
export CORS_ALLOW_ORIGINS=*
bash avatar_service/start_api.sh
```

Then open:
- `http://<EC2_PUBLIC_IP>:8000/docs`
- `http://<EC2_PUBLIC_IP>:8000/health`

## Frontend-Friendly Endpoints

- `POST /jobs/render-upload`
  - multipart form fields:
    - `avatar_id`
    - `audio_file`
    - optional `job_id`
    - optional `fps`
    - optional `batch_size`
    - optional `model_version`
    - optional `chunk_duration`
- `GET /jobs/{job_id}`
- `GET /outputs/{job_id}/chunk_0000.mp4`

`/jobs/{job_id}` now returns public URL paths like `chunk_video_urls` and `stream_info_url`.

## Example curl

```bash
curl -X POST http://<EC2_PUBLIC_IP>:8000/jobs/render-upload \
  -F "avatar_id=sydneey" \
  -F "audio_file=@/home/ssm-user/spillr-avatar/avatar_service/storage/inputs/audio.mp3"
```

## Keep It Running With systemd

Copy `avatar-service.service.example` to `/etc/systemd/system/avatar-service.service`, then:

```bash
sudo systemctl daemon-reload
sudo systemctl enable avatar-service
sudo systemctl start avatar-service
sudo systemctl status avatar-service
```

## Put Nginx In Front Later

Use `nginx.avatar-service.conf.example` if you want port `80` in front of Uvicorn.