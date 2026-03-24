"use client";

import { signIn } from "next-auth/react";

type ProviderDescriptor = {
  id: string;
  label: string;
  enabled: boolean;
};

type Props = {
  providers: ProviderDescriptor[];
};

export default function AuthScreen({ providers }: Props) {
  const enabledProviders = providers.filter((provider) => provider.enabled);

  async function handleSignIn(providerId: string) {
    if (providerId === "credentials") {
      await signIn("credentials", {
        email: "demo-admin@example.com",
        name: "Demo Admin",
        redirectTo: "/",
      });
      return;
    }

    await signIn(providerId, { redirectTo: "/" });
  }

  return (
    <main className="auth-shell">
      <section className="auth-card card-surface">
        <p className="eyebrow">Multilingual pilot</p>
        <h1>Sign in to the avatar platform</h1>
        <p className="hero-copy">
          This demo supports push-to-talk conversations with admin-curated avatars, retrieval-grounded answers, Azure OpenAI language generation, and streamed avatar playback in English, Hindi, Punjabi, and Tamil.
        </p>

        <div className="auth-provider-list">
          {enabledProviders.map((provider) => (
            <button
              className="primary-button wide-button"
              key={provider.id}
              onClick={() => void handleSignIn(provider.id)}
              type="button"
            >
              Continue with {provider.label}
            </button>
          ))}
        </div>

        <div className="note-card">
          <strong>What you can do after sign-in</strong>
          <ul>
            <li>Select a ready avatar and choose the input and reply languages for the session.</li>
            <li>Use push-to-talk with browser transcript assistance and manual transcript correction when needed.</li>
            <li>Watch the answer stream back as chunked avatar video while retrieval traces stay visible.</li>
          </ul>
        </div>
      </section>
    </main>
  );
}
