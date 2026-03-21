import { NextResponse } from "next/server";

import { buildAvatarApiUrl, readJsonResponse } from "@/lib/avatar-api";

export const runtime = "nodejs";
export const dynamic = "force-dynamic";

export async function GET() {
  try {
    const upstreamResponse = await fetch(buildAvatarApiUrl("/avatars"), {
      cache: "no-store"
    });
    const payload = await readJsonResponse<Record<string, unknown>>(upstreamResponse);
    return NextResponse.json(payload, { status: upstreamResponse.status });
  } catch (cause) {
    return NextResponse.json(
      {
        detail:
          cause instanceof Error ? cause.message : "Unable to fetch the avatar library."
      },
      { status: 500 }
    );
  }
}
