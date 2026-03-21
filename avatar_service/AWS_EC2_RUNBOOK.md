# AWS EC2 Runbook

This runbook is the fastest way to run the current `avatar_service` on AWS and inspect outputs.

## Recommended First AWS Path
Use `EC2 + GPU + S3` for your first cloud run.

Why this path:
- It matches the current code shape.
- You can upload the repo, run the pipeline, and inspect the results immediately.
- It avoids early SageMaker container work while you are still validating the runtime.

Move to SageMaker only after the EC2 run is stable.

## Recommended AWS Specs
Use these settings for the first successful cloud run:

- Region: choose a region where `g5.2xlarge` is available in your account.
- Instance type: `g5.2xlarge`
- GPU: `1 x NVIDIA A10G`
- GPU memory: `24 GiB`
- vCPU: `8`
- RAM: `32 GiB`
- Storage: `gp3`, `200 GiB`
- AMI: latest AWS Deep Learning GPU AMI on Ubuntu 22.04 or 24.04
- IAM role: read/write access to one S3 bucket for inputs and outputs
- Security group inbound:
  - `22` from your IP only, if you want SSH
  - `8000` from your IP only, if you want FastAPI docs
  - `8080` from your IP only, if you want direct browser preview from the instance
- Security group outbound:
  - allow `443` so the instance can download packages and model weights

Lower-cost fallback:
- `g5.xlarge` can work for single-job experiments because it still has an A10G GPU with `24 GiB` VRAM, but CPU and memory headroom are tighter.

## AWS Resources To Create
Create these resources first:

1. One S3 bucket, for example `spillr-avatar-artifacts`
2. One EC2 instance using the GPU DLAMI
3. One IAM role attached to the EC2 instance with S3 read/write access to that bucket
4. One security group with only the ports you need

Recommended S3 layout:
- `s3://your-bucket/code/spillr-avatar.zip`
- `s3://your-bucket/input/avatar.mp4`
- `s3://your-bucket/input/audio.mp3`
- `s3://your-bucket/output/`

## Minimal IAM Policy Pattern
Attach a bucket-scoped policy to the EC2 role. Replace `your-bucket-name` with your real bucket.

```json
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Effect": "Allow",
      "Action": [
        "s3:ListBucket"
      ],
      "Resource": "arn:aws:s3:::your-bucket-name"
    },
    {
      "Effect": "Allow",
      "Action": [
        "s3:GetObject",
        "s3:PutObject",
        "s3:DeleteObject"
      ],
      "Resource": "arn:aws:s3:::your-bucket-name/*"
    }
  ]
}
```

## Step-By-Step Deployment

### 1. Launch the instance
In the EC2 console:
- Choose the GPU Deep Learning AMI.
- Choose `g5.2xlarge`.
- Attach `200 GiB gp3` root volume.
- Attach the S3-enabled IAM role.
- Attach the security group.
- Launch the instance.

### 2. Upload your repo and media
You can use S3 for the cleanest flow.

Upload:
- your project zip to `s3://your-bucket/code/spillr-avatar.zip`
- your avatar video to `s3://your-bucket/input/avatar.mp4`
- your audio to `s3://your-bucket/input/audio.mp3`

### 3. Connect to the instance
Use one of these:
- EC2 Instance Connect from the AWS console
- Systems Manager Session Manager

### 4. Pull your project onto the instance
Example commands:

```bash
cd /home/ubuntu
aws s3 cp s3://your-bucket/code/spillr-avatar.zip .
unzip spillr-avatar.zip
cd spillr-avatar
```

### 5. Bootstrap the runtime
Run the AWS bootstrap script from the repo root:

```bash
bash avatar_service/bootstrap_aws_ec2.sh
```

What this does:
- installs system packages including `ffmpeg`
- creates a Python environment
- installs the avatar service dependencies
- clones the external MuseTalk repo to `/home/ubuntu/MuseTalk`
- writes `avatar_service/.env`

### 6. Download the required MuseTalk weights
Run:

```bash
bash avatar_service/download_musetalk_models.sh
```

If your network is slow, this is the longest step.

### 7. Run the first real job
Run directly from local files on the instance:

```bash
bash avatar_service/run_aws_job.sh \
  --video /home/ubuntu/input/avatar.mp4 \
  --audio /home/ubuntu/input/audio.mp3 \
  --avatar-id sydneey \
  --job-id first-run
```

Or run from S3 and upload the outputs back to S3:

```bash
bash avatar_service/run_aws_job.sh \
  --video s3://your-bucket/input/avatar.mp4 \
  --audio s3://your-bucket/input/audio.mp3 \
  --avatar-id sydneey \
  --job-id first-run \
  --s3-output-prefix s3://your-bucket/output
```

## Where To See Results
After the run finishes, inspect these files on the instance:

- `avatar_service/storage/avatars/<avatar_id>/avatar_data.pkl`
- `avatar_service/storage/jobs/<job_id>/job_status.json`
- `avatar_service/storage/outputs/<job_id>/stream_info.json`
- `avatar_service/storage/outputs/<job_id>/chunk_0000.mp4`

If you used `--s3-output-prefix`, inspect:
- `s3://your-bucket/output/<job_id>/chunk_0000.mp4`
- `s3://your-bucket/output/<job_id>/stream_info.json`

## Browser Preview Options

### Option A: S3 console
This is the easiest option.
- Open the output folder in the S3 console.
- Download the MP4 chunks or open them from the console.

### Option B: Direct preview from the EC2 instance
If you opened inbound port `8080` from your IP:

```bash
cd /home/ubuntu/spillr-avatar/avatar_service/storage/outputs/first-run
python3 -m http.server 8080
```

Then open:
- `http://<EC2_PUBLIC_IP>:8080/chunk_0000.mp4`

### Option C: API docs preview
If you opened inbound port `8000` from your IP:

```bash
cd /home/ubuntu/spillr-avatar
source .venv-avatar/bin/activate
uvicorn avatar_service.api:app --host 0.0.0.0 --port 8000
```

Then open:
- `http://<EC2_PUBLIC_IP>:8000/docs`

This lets you call:
- `POST /avatars/preprocess`
- `POST /jobs/render`
- `GET /jobs/{job_id}`

## Validation Checklist
Before you say the AWS run is successful, confirm all of these:
- `python -m avatar_service.validate_env` returns no `error`
- `avatar_data.pkl` exists for the avatar
- `job_status.json` reaches `completed`
- `stream_info.json` exists
- at least one `chunk_0000.mp4` exists and plays

## Recommended First Production Direction
After the EC2 path works, then move to this split:
- frontend on S3 + CloudFront
- app API on ECS Fargate
- MuseTalk GPU render on SageMaker or dedicated GPU EC2 workers
- outputs in S3

Do not start with SageMaker for the very first cloud run. Get one clean EC2 run working first.
