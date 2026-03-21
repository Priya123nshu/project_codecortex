# Vercel Frontend for the EC2 Avatar Service

This Next.js app is a simple public frontend for your EC2-hosted `avatar_service`.
The browser talks only to `/api/avatar/*` routes on the frontend. Those routes proxy requests to your EC2 FastAPI backend.

## 1. Keep the EC2 backend running
On EC2, make sure your avatar API is running on port `8000`.

Example:

```bash
cd /home/ssm-user/spillr-avatar
export PYTHONPATH=/home/ssm-user/spillr-avatar
/home/ssm-user/spillr-avatar/.venv-avatar/bin/python -m uvicorn avatar_service.api:app --host 0.0.0.0 --port 8000
```

## 2. Sync the latest avatar_service changes to EC2
This frontend now expects these backend routes/features to exist on EC2:
- `GET /avatars`
- `POST /avatars/preprocess-upload`
- `POST /jobs/render-upload`
- `GET /jobs/{job_id}`
- static outputs served from `/outputs/*`
- URL fields like `chunk_video_urls` in the JSON response

So before testing the new multi-avatar UI, re-sync your updated `avatar_service/` folder to the EC2 machine and restart the API process.

## 3. What multi-avatar means in this version
- Preprocess each avatar one time on EC2.
- Each avatar gets its own `avatar_id` and cached `avatar_data.pkl`.
- The frontend loads the ready avatar library.
- Each render job picks one selected avatar from that library.

This is the right model for keeping Sydney Sweeney plus two or three more avatars ready at once.

## 4. Local test
Create `.env.local` in the frontend root:

```env
AVATAR_API_BASE_URL=http://<EC2_PUBLIC_IP>:8000
NEXT_PUBLIC_DEFAULT_AVATAR_ID=sydneey
```

Then run:

```bash
npm install
npm run dev
```

Open [http://localhost:3000](http://localhost:3000).

## 5. Deploy on Vercel
In Vercel project settings, add these environment variables:

```env
AVATAR_API_BASE_URL=http://<EC2_PUBLIC_IP>:8000
NEXT_PUBLIC_DEFAULT_AVATAR_ID=sydneey
```

Then deploy the project normally.

## 6. Security group requirement
For Vercel to reach EC2, port `8000` cannot stay locked to only your IP address.
For a quick demo, allow inbound TCP `8000` from `0.0.0.0/0` temporarily.

Safer next step after testing:
- put Nginx in front
- move traffic to `80/443`
- add TLS and auth

## 7. Important limits for this simple demo
As of March 21, 2026, Vercel's official Functions limits page lists:
- a `4.5 MB` maximum payload for request or response bodies
- Hobby max duration configurable up to `300s`

This project keeps the upload proxy routes on the Node.js runtime and sets `maxDuration = 300` where needed.

Because your current backend preprocess/render endpoints are synchronous, this frontend is best for short demo uploads.
For larger avatar videos or longer audio, move to one of these:
- upload directly to EC2
- upload to S3 and send only metadata through the frontend
- change the backend to async jobs/queues

## 8. Routes created in this frontend
- `GET /api/avatar/health`
- `GET /api/avatar/avatars`
- `POST /api/avatar/preprocess-upload`
- `POST /api/avatar/render-upload`
- `GET /api/avatar/jobs/:jobId`
- `GET /api/avatar/output/*`

These proxy routes rewrite returned chunk URLs so the browser can play videos from the same frontend domain.

## 9. What the page does now
- uploads new avatar videos for one-time preprocessing
- loads the ready avatar library
- lets you select any ready avatar
- uploads one audio file
- starts a render job for the selected avatar
- polls job status
- shows returned chunk videos inline

## Official references
- [Vercel Functions](https://vercel.com/docs/functions/)
- [Vercel Functions limits](https://vercel.com/docs/functions/limitations)
- [Configuring maximum duration for Vercel Functions](https://vercel.com/docs/functions/configuring-functions/duration)
