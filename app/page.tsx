import { auth, platformAuthProviders } from "@/auth";
import AuthScreen from "@/components/auth-screen";
import PlatformApp from "@/components/platform-app";
import { roleForEmail } from "@/lib/platform-access-token";

export default async function HomePage() {
  const session = await auth();

  if (!session?.user?.email) {
    return <AuthScreen providers={platformAuthProviders} />;
  }

  return (
    <PlatformApp
      isAdmin={roleForEmail(session.user.email) === "admin"}
      userEmail={session.user.email}
      userName={session.user.name ?? session.user.email}
    />
  );
}
