import { NextResponse } from "next/server";
import { auth } from "@/auth";
import { issuePlatformAccessToken, roleForEmail } from "@/lib/platform-access-token";
import type { PlatformTokenResponse } from "@/lib/platform-client";

export async function GET() {
  const session = await auth();

  if (!session?.user?.email) {
    return NextResponse.json({ detail: "Not authenticated." }, { status: 401 });
  }

  const platformApiBaseUrl = process.env.NEXT_PUBLIC_PLATFORM_API_BASE_URL?.trim();
  if (!platformApiBaseUrl) {
    return NextResponse.json({ detail: "NEXT_PUBLIC_PLATFORM_API_BASE_URL is not configured." }, { status: 500 });
  }

  const role = roleForEmail(session.user.email);
  const accessToken = await issuePlatformAccessToken({
    subject: session.user.email,
    email: session.user.email,
    name: session.user.name ?? session.user.email,
    role,
    orgId: process.env.PLATFORM_DEFAULT_ORG_ID ?? "pilot-org",
  });

  const payload: PlatformTokenResponse = {
    access_token: accessToken,
    platform_api_base_url: platformApiBaseUrl.replace(/\/$/, ""),
    role,
  };

  return NextResponse.json(payload);
}
