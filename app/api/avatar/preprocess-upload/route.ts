import { NextResponse } from "next/server";

import { buildAvatarApiUrl, readJsonResponse } from "@/lib/avatar-api";

export const runtime = "nodejs";
export const dynamic = "force-dynamic";
export const maxDuration = 300;

export async function POST(request: Request) {
  try {
    const formData = await request.formData();
    const upstreamResponse = await fetch(buildAvatarApiUrl("/avatars/preprocess-upload"), {
      method: "POST",
      body: formData,
      cache: "no-store"
    });

    const payload = await readJsonResponse<Record<string, unknown>>(upstreamResponse);
    return NextResponse.json(payload, { status: upstreamResponse.status });
  } catch (cause) {
    return NextResponse.json(
      {
        detail:
          cause instanceof Error ? cause.message : "Unable to preprocess the uploaded avatar."
      },
      { status: 500 }
    );
  }
}
