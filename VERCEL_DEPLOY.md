# Vercel Deployment for Platform V1

This repo now deploys the **web app only** on Vercel. The long-running orchestration and media services stay off Vercel:

- Web app: Next.js on Vercel
- Platform API: FastAPI on AWS CPU infrastructure
- TTS service: FastAPI sidecar on CPU infrastructure
- Avatar render service: existing `avatar_service` on AWS GPU infrastructure

The browser signs in through Auth.js, fetches a short-lived platform token from `/api/platform-token`, and then calls the platform API directly.

## 1. Keep all backend services running

You need three reachable services before the Vercel app can work:

- `avatar_service` on port `8000`
- `tts_service` on port `8200`
- `platform_service` on port `8100`

Example:

```bash
uvicorn avatar_service.api:app --host 0.0.0.0 --port 8000
uvicorn tts_service.api:app --host 0.0.0.0 --port 8200
uvicorn platform_service.api:app --host 0.0.0.0 --port 8100
```

## 2. Configure the platform service

Make sure `platform_service/.env` points to the avatar render service and the TTS sidecar, and allows the Vercel frontend origin in CORS.

At minimum:

```env
PLATFORM_PUBLIC_BASE_URL=http://<CPU_API_HOST>:8100
PLATFORM_CORS_ALLOW_ORIGINS=http://localhost:3000,https://<your-vercel-domain>
PLATFORM_JWT_SECRET=<shared-secret>
PLATFORM_ADMIN_EMAILS=you@example.com
AVATAR_RENDER_SERVICE_BASE_URL=http://<GPU_HOST>:8000
AVATAR_RENDER_PUBLIC_BASE_URL=http://<GPU_HOST>:8000
TTS_SERVICE_BASE_URL=http://<CPU_HOST>:8200
PLATFORM_AVATAR_CHUNK_DURATION_SECONDS=2
```

`PLATFORM_JWT_SECRET` must match the secret used in the Next.js app for platform token minting.

For Azure OpenAI-backed multilingual routing, also configure:

```env
AZURE_OPENAI_ENDPOINT=
AZURE_OPENAI_API_KEY=
AZURE_OPENAI_CHAT_DEPLOYMENT=
AZURE_OPENAI_EMBEDDINGS_DEPLOYMENT=
```

## 3. Local frontend test

Create `.env.local` in the repo root:

```env
NEXT_PUBLIC_PLATFORM_API_BASE_URL=http://127.0.0.1:8100
NEXTAUTH_URL=http://localhost:3000
NEXTAUTH_SECRET=<shared-secret>
PLATFORM_API_JWT_SECRET=<shared-secret>
PLATFORM_ADMIN_EMAILS=you@example.com
```

Optional login providers:

```env
GOOGLE_CLIENT_ID=
GOOGLE_CLIENT_SECRET=
MICROSOFT_CLIENT_ID=
MICROSOFT_CLIENT_SECRET=
MICROSOFT_TENANT_ID=
```

Then run:

```bash
npm install
npm run dev
```

## 4. Vercel environment variables

In the Vercel project settings, add:

```env
NEXT_PUBLIC_PLATFORM_API_BASE_URL=https://api.<your-domain>
NEXTAUTH_SECRET=<shared-secret>
PLATFORM_API_JWT_SECRET=<shared-secret>
PLATFORM_ADMIN_EMAILS=you@example.com
GOOGLE_CLIENT_ID=
GOOGLE_CLIENT_SECRET=
MICROSOFT_CLIENT_ID=
MICROSOFT_CLIENT_SECRET=
MICROSOFT_TENANT_ID=
```

If you are using a custom domain, also set:

```env
NEXTAUTH_URL=https://app.<your-domain>
```

## 5. Network rules

Vercel must be able to reach the **platform API**, and the platform API must be able to reach both the **TTS sidecar** and the **GPU avatar service**.

That means:

- Vercel -> platform service must be allowed
- platform service -> TTS service must be allowed
- platform service -> avatar render service must be allowed
- you do not need to expose the GPU avatar service publicly if the platform API can reach it privately

## 6. Current production model

For this pilot, Vercel is best used for:

- sign-in
- admin console
- avatar selection
- input and output language selection
- push-to-talk UI with transcript confirmation
- session history and streamed chunk playback

The heavy work stays off Vercel:

- avatar preprocessing
- document indexing
- Azure OpenAI orchestration
- multilingual TTS synthesis
- MuseTalk rendering

## 7. Current scope

This implementation is intentionally:

- multilingual for English, Hindi, Punjabi, and Tamil
- single organization
- one avatar and one language route per session
- admin-curated avatar library
- push-to-talk, not continuous duplex audio

## Official references

- [Vercel Environment Variables](https://vercel.com/docs/environment-variables)
- [Vercel Project Settings](https://vercel.com/docs/project-configuration/project-settings)
- [Deploying Git repositories on Vercel](https://vercel.com/docs/git)
