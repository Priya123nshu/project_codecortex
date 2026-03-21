"use client";

import { ChangeEvent, FormEvent, useEffect, useMemo, useState } from "react";

type JobStatus = "queued" | "running" | "failed" | "completed";
type HealthState = "checking" | "ok" | "error";
type AvatarState = "idle" | "uploading" | "completed" | "failed";

type RenderResponse = {
  job_id: string;
  status: JobStatus;
  output_dir: string;
  stream_info_path: string;
  chunks_total?: number;
  chunks_completed?: number;
  chunk_video_paths?: string[];
  chunk_video_urls?: string[];
  stream_info_url?: string | null;
  output_url_prefix?: string | null;
  error?: string | null;
};

type AvatarSummary = {
  avatar_id: string;
  status: "ready" | "missing";
  avatar_data_path?: string | null;
  avatar_info_path?: string | null;
  source_video_path?: string | null;
  model_version?: string | null;
  num_frames?: number | null;
};

type AvatarListResponse = {
  avatars: AvatarSummary[];
};

type PreprocessAvatarResponse = {
  avatar_id: string;
  status: JobStatus;
  avatar_data_path: string;
  avatar_info_path: string;
};

const DEFAULT_AVATAR_ID = process.env.NEXT_PUBLIC_DEFAULT_AVATAR_ID ?? "sydneey";
const HEALTH_ENDPOINT = "/api/avatar/health";
const AVATARS_ENDPOINT = "/api/avatar/avatars";
const AVATAR_PREPROCESS_UPLOAD_ENDPOINT = "/api/avatar/preprocess-upload";
const RENDER_UPLOAD_ENDPOINT = "/api/avatar/render-upload";
const JOBS_ENDPOINT = "/api/avatar/jobs";
const MAX_RECOMMENDED_AUDIO_UPLOAD_BYTES = 4 * 1024 * 1024;

export default function HomePage() {
  const [avatarId, setAvatarId] = useState(DEFAULT_AVATAR_ID);
  const [jobId, setJobId] = useState("");
  const [batchSize, setBatchSize] = useState("8");
  const [chunkDuration, setChunkDuration] = useState("3");
  const [audioFile, setAudioFile] = useState<File | null>(null);
  const [status, setStatus] = useState<JobStatus | "idle">("idle");
  const [error, setError] = useState<string | null>(null);
  const [job, setJob] = useState<RenderResponse | null>(null);
  const [selectedVideoUrl, setSelectedVideoUrl] = useState<string | null>(null);
  const [isSubmitting, setIsSubmitting] = useState(false);
  const [healthState, setHealthState] = useState<HealthState>("checking");
  const [healthMessage, setHealthMessage] = useState("Checking EC2 connection...");
  const [availableAvatars, setAvailableAvatars] = useState<AvatarSummary[]>([]);
  const [isAvatarLibraryLoading, setIsAvatarLibraryLoading] = useState(false);
  const [avatarLibraryMessage, setAvatarLibraryMessage] = useState("Loading avatar library...");
  const [newAvatarId, setNewAvatarId] = useState("");
  const [avatarVideoFile, setAvatarVideoFile] = useState<File | null>(null);
  const [avatarUploadState, setAvatarUploadState] = useState<AvatarState>("idle");
  const [avatarUploadMessage, setAvatarUploadMessage] = useState<string | null>(null);

  const readyAvatars = useMemo(
    () => availableAvatars.filter((avatar) => avatar.status === "ready"),
    [availableAvatars]
  );
  const chunkVideoUrls = useMemo(() => job?.chunk_video_urls ?? [], [job?.chunk_video_urls]);

  useEffect(() => {
    void refreshHealth();
    void refreshAvatarLibrary();
  }, []);

  useEffect(() => {
    if (readyAvatars.length === 0) {
      return;
    }

    const matchingAvatar = readyAvatars.find((avatar) => avatar.avatar_id === avatarId);
    if (!matchingAvatar) {
      setAvatarId(readyAvatars[0]?.avatar_id ?? DEFAULT_AVATAR_ID);
    }
  }, [avatarId, readyAvatars]);

  useEffect(() => {
    if (chunkVideoUrls.length === 0) {
      setSelectedVideoUrl(null);
      return;
    }

    setSelectedVideoUrl((current) => {
      if (current && chunkVideoUrls.includes(current)) {
        return current;
      }
      return chunkVideoUrls[0] ?? null;
    });
  }, [chunkVideoUrls]);

  useEffect(() => {
    if (!job?.job_id) {
      return;
    }

    if (job.status === "completed" || job.status === "failed") {
      return;
    }

    const timer = window.setTimeout(async () => {
      try {
        const response = await fetch(`${JOBS_ENDPOINT}/${job.job_id}`, {
          cache: "no-store"
        });
        const payload = (await response.json()) as RenderResponse | { detail?: string };

        if (!response.ok) {
          const message = "detail" in payload && payload.detail ? payload.detail : "Unable to fetch job status.";
          throw new Error(message);
        }

        const nextJob = payload as RenderResponse;
        setJob(nextJob);
        setStatus(nextJob.status);
        if (nextJob.status === "failed" && nextJob.error) {
          setError(nextJob.error);
        }
      } catch (cause) {
        setError(getErrorMessage(cause, "Unable to poll job status."));
      }
    }, 2500);

    return () => window.clearTimeout(timer);
  }, [job]);

  async function refreshHealth() {
    setHealthState("checking");
    setHealthMessage("Checking EC2 connection...");

    try {
      const response = await fetch(HEALTH_ENDPOINT, { cache: "no-store" });
      const payload = (await response.json()) as { status?: string; detail?: string };

      if (!response.ok || payload.status !== "ok") {
        throw new Error(payload.detail || "The frontend could not reach your EC2 API.");
      }

      setHealthState("ok");
      setHealthMessage("EC2 avatar API is reachable.");
    } catch (cause) {
      setHealthState("error");
      setHealthMessage(getErrorMessage(cause, "The EC2 backend is not reachable yet."));
    }
  }

  async function refreshAvatarLibrary() {
    setIsAvatarLibraryLoading(true);
    setAvatarLibraryMessage("Loading avatar library...");

    try {
      const response = await fetch(AVATARS_ENDPOINT, { cache: "no-store" });
      const payload = (await response.json()) as AvatarListResponse | { detail?: string };

      if (!response.ok) {
        const message = "detail" in payload && payload.detail ? payload.detail : "Unable to fetch avatars.";
        throw new Error(message);
      }

      const avatars = (payload as AvatarListResponse).avatars ?? [];
      setAvailableAvatars(avatars);
      if (avatars.length === 0) {
        setAvatarLibraryMessage("No avatars yet. Upload one video below to create your first avatar.");
      } else {
        setAvatarLibraryMessage(`${avatars.length} avatar${avatars.length === 1 ? "" : "s"} available.`);
      }
    } catch (cause) {
      setAvatarLibraryMessage(getErrorMessage(cause, "Unable to load the avatar library."));
    } finally {
      setIsAvatarLibraryLoading(false);
    }
  }

  async function handleAvatarUpload(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();

    if (!newAvatarId.trim()) {
      setAvatarUploadState("failed");
      setAvatarUploadMessage("Enter an avatar ID before uploading a video.");
      return;
    }

    if (!avatarVideoFile) {
      setAvatarUploadState("failed");
      setAvatarUploadMessage("Choose a source avatar video before preprocessing.");
      return;
    }

    setAvatarUploadState("uploading");
    setAvatarUploadMessage("Uploading and preprocessing avatar. This can take a little while.");

    try {
      const formData = new FormData();
      formData.set("avatar_id", newAvatarId.trim());
      formData.set("video_file", avatarVideoFile);
      formData.set("model_version", "v15");

      const response = await fetch(AVATAR_PREPROCESS_UPLOAD_ENDPOINT, {
        method: "POST",
        body: formData
      });
      const payload = (await response.json()) as PreprocessAvatarResponse | { detail?: string };

      if (!response.ok) {
        const message = "detail" in payload && payload.detail ? payload.detail : "Avatar preprocessing failed.";
        throw new Error(message);
      }

      const result = payload as PreprocessAvatarResponse;
      setAvatarUploadState("completed");
      setAvatarUploadMessage(`Avatar ${result.avatar_id} is ready.`);
      setAvatarId(result.avatar_id);
      setNewAvatarId("");
      setAvatarVideoFile(null);
      await refreshAvatarLibrary();
    } catch (cause) {
      setAvatarUploadState("failed");
      setAvatarUploadMessage(getErrorMessage(cause, "Unable to preprocess the avatar."));
    }
  }

  async function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();

    if (!avatarId.trim()) {
      setError("Choose an avatar before starting a render job.");
      return;
    }

    if (!audioFile) {
      setError("Choose an audio file before starting a render job.");
      return;
    }

    if (audioFile.size > MAX_RECOMMENDED_AUDIO_UPLOAD_BYTES) {
      setError("For this simple frontend, keep audio uploads under about 4 MB. Longer audio should go directly to EC2 or S3.");
      return;
    }

    setError(null);
    setIsSubmitting(true);
    setStatus("queued");
    setSelectedVideoUrl(null);

    try {
      const formData = new FormData();
      formData.set("avatar_id", avatarId.trim());
      formData.set("audio_file", audioFile);
      if (jobId.trim()) {
        formData.set("job_id", jobId.trim());
      }
      if (batchSize.trim()) {
        formData.set("batch_size", batchSize.trim());
      }
      if (chunkDuration.trim()) {
        formData.set("chunk_duration", chunkDuration.trim());
      }

      const response = await fetch(RENDER_UPLOAD_ENDPOINT, {
        method: "POST",
        body: formData
      });
      const payload = (await response.json()) as RenderResponse | { detail?: string };

      if (!response.ok) {
        const message = "detail" in payload && payload.detail ? payload.detail : "Render request failed.";
        throw new Error(message);
      }

      const nextJob = payload as RenderResponse;
      setJob(nextJob);
      setStatus(nextJob.status);
      setJobId(nextJob.job_id);
    } catch (cause) {
      setError(getErrorMessage(cause, "Unable to start the render job."));
      setStatus("idle");
    } finally {
      setIsSubmitting(false);
    }
  }

  function handleAudioChange(event: ChangeEvent<HTMLInputElement>) {
    const nextFile = event.target.files?.[0] ?? null;
    setAudioFile(nextFile);
  }

  function handleAvatarVideoChange(event: ChangeEvent<HTMLInputElement>) {
    const nextFile = event.target.files?.[0] ?? null;
    setAvatarVideoFile(nextFile);
  }

  return (
    <main className="page-shell">
      <section className="hero-card">
        <div className="hero-topline">
          <p className="eyebrow">Avatar Library Console</p>
          <HealthBadge state={healthState} />
        </div>
        <h1>Prepare multiple avatars once, then let users switch between them while rendering.</h1>
        <p className="lede">
          Your backend already renders by <code>avatar_id</code>. This UI adds the missing layer: preprocess a few
          avatars, keep them in an avatar library, and select any ready avatar when starting a new render job.
        </p>
        <div className="hero-actions">
          <button className="ghost-button" onClick={() => void refreshHealth()} type="button">
            Refresh backend health
          </button>
          <button className="ghost-button" onClick={() => void refreshAvatarLibrary()} type="button">
            Refresh avatar library
          </button>
          <span className="health-copy">{healthMessage}</span>
        </div>
      </section>

      <section className="step-grid">
        <article className="step-card">
          <span>01</span>
          <h2>Preprocess each avatar once</h2>
          <p>Upload Sydney Sweeney, then two more videos. Each becomes a cached avatar on EC2.</p>
        </article>
        <article className="step-card">
          <span>02</span>
          <h2>Keep a ready library</h2>
          <p>The frontend loads all prepared avatars and shows them as selectable cards.</p>
        </article>
        <article className="step-card">
          <span>03</span>
          <h2>Choose per render job</h2>
          <p>Each user render request picks one avatar from the library without reprocessing everything.</p>
        </article>
      </section>

      <section className="panel-grid library-grid">
        <section className="panel form-panel">
          <div className="section-heading">
            <h2>Upload a new avatar</h2>
            <p>Do this one time per character. After preprocessing, that avatar appears in the ready library below.</p>
          </div>

          <form className="form-grid" onSubmit={handleAvatarUpload}>
            <label className="field">
              <span>New avatar ID</span>
              <input
                onChange={(event) => setNewAvatarId(event.target.value)}
                placeholder="sydneey or avatar-02"
                value={newAvatarId}
              />
            </label>

            <label className="field file-field">
              <span>Avatar video</span>
              <input accept="video/*" onChange={handleAvatarVideoChange} type="file" />
              <small>
                {avatarVideoFile
                  ? `${avatarVideoFile.name} (${formatFileSize(avatarVideoFile.size)})`
                  : "Upload a short clean talking-head clip for the avatar."}
              </small>
            </label>

            <button className="primary-button" disabled={avatarUploadState === "uploading"} type="submit">
              {avatarUploadState === "uploading" ? "Preprocessing avatar..." : "Add avatar to library"}
            </button>
          </form>

          {avatarUploadMessage ? (
            <div className={avatarUploadState === "failed" ? "error-banner" : "success-banner"}>
              {avatarUploadMessage}
            </div>
          ) : null}
        </section>

        <section className="panel library-panel">
          <div className="section-heading">
            <h2>Ready avatars</h2>
            <p>{isAvatarLibraryLoading ? "Refreshing avatar library..." : avatarLibraryMessage}</p>
          </div>

          {availableAvatars.length > 0 ? (
            <div className="avatar-grid">
              {availableAvatars.map((avatar) => {
                const isActive = avatar.avatar_id === avatarId;
                return (
                  <button
                    className={isActive ? "avatar-card active" : "avatar-card"}
                    key={avatar.avatar_id}
                    onClick={() => setAvatarId(avatar.avatar_id)}
                    type="button"
                  >
                    <div className="avatar-card-header">
                      <strong>{avatar.avatar_id}</strong>
                      <span className={avatar.status === "ready" ? "pill pill-ready" : "pill pill-missing"}>
                        {avatar.status}
                      </span>
                    </div>
                    <p>Model: {avatar.model_version ?? "v15"}</p>
                    <p>Frames: {avatar.num_frames ?? "-"}</p>
                  </button>
                );
              })}
            </div>
          ) : (
            <div className="empty-state">No avatars have been preprocessed yet.</div>
          )}
        </section>
      </section>

      <section className="panel-grid">
        <section className="panel form-panel">
          <div className="section-heading">
            <h2>Start a render</h2>
            <p>Select any ready avatar from the library and use it for this job.</p>
          </div>

          <form className="form-grid" onSubmit={handleSubmit}>
            <div className="field-row">
              <label className="field">
                <span>Selected avatar</span>
                <select className="select-input" onChange={(event) => setAvatarId(event.target.value)} value={avatarId}>
                  {readyAvatars.length > 0 ? (
                    readyAvatars.map((avatar) => (
                      <option key={avatar.avatar_id} value={avatar.avatar_id}>
                        {avatar.avatar_id}
                      </option>
                    ))
                  ) : (
                    <option value="">No ready avatars yet</option>
                  )}
                </select>
              </label>

              <label className="field">
                <span>Job ID</span>
                <input
                  onChange={(event) => setJobId(event.target.value)}
                  placeholder="Optional"
                  value={jobId}
                />
              </label>
            </div>

            <div className="field-row compact">
              <label className="field">
                <span>Batch size</span>
                <input min="1" onChange={(event) => setBatchSize(event.target.value)} type="number" value={batchSize} />
              </label>

              <label className="field">
                <span>Chunk duration</span>
                <input min="1" max="30" onChange={(event) => setChunkDuration(event.target.value)} type="number" value={chunkDuration} />
              </label>
            </div>

            <label className="field file-field">
              <span>Audio file</span>
              <input accept="audio/*" onChange={handleAudioChange} type="file" />
              <small>
                {audioFile
                  ? `${audioFile.name} (${formatFileSize(audioFile.size)})`
                  : "Short clips work best for this simple upload flow."}
              </small>
            </label>

            <div className="note-card">
              <strong>How multi-avatar works</strong>
              <ul>
                <li>Each avatar is preprocessed one time and saved on EC2 under its own <code>avatar_id</code>.</li>
                <li>Each render job uses exactly one selected avatar.</li>
                <li>You can keep Sydney plus two or three more avatars ready and switch between them instantly.</li>
              </ul>
            </div>

            <button className="primary-button" disabled={isSubmitting || readyAvatars.length === 0} type="submit">
              {isSubmitting ? "Starting render..." : "Render audio"}
            </button>
          </form>

          {error ? <div className="error-banner">{error}</div> : null}
        </section>

        <section className="panel status-panel">
          <div className="section-heading">
            <h2>Job status</h2>
            <p>The frontend polls until the selected avatar finishes rendering all chunk videos.</p>
          </div>

          <div className="status-grid">
            <StatusCard label="Status" value={status} tone={status} />
            <StatusCard label="Job ID" value={job?.job_id ?? (jobId || "Not started")} />
            <StatusCard
              label="Chunks"
              value={job ? `${job.chunks_completed ?? 0}/${job.chunks_total ?? 0}` : "0/0"}
            />
          </div>

          <div className="json-card">
            <div className="json-card-header">
              <h3>Latest response</h3>
              {job?.stream_info_url ? (
                <a href={job.stream_info_url} rel="noreferrer" target="_blank">
                  Open stream info
                </a>
              ) : null}
            </div>
            <pre>{JSON.stringify(job, null, 2) || "No response yet."}</pre>
          </div>
        </section>
      </section>

      <section className="panel output-panel">
        <div className="section-heading">
          <h2>Rendered video</h2>
          <p>Select any returned chunk to preview the output for the currently chosen avatar.</p>
        </div>

        {chunkVideoUrls.length > 0 ? (
          <>
            <div className="chunk-list">
              {chunkVideoUrls.map((url, index) => (
                <button
                  className={url === selectedVideoUrl ? "chunk-pill active" : "chunk-pill"}
                  key={url}
                  onClick={() => setSelectedVideoUrl(url)}
                  type="button"
                >
                  Chunk {index}
                </button>
              ))}
            </div>

            <div className="video-shell">
              {selectedVideoUrl ? <video controls key={selectedVideoUrl} src={selectedVideoUrl} /> : null}
            </div>
          </>
        ) : (
          <div className="empty-state">
            No videos yet. Choose an avatar, upload audio, and the chunk preview area will populate automatically.
          </div>
        )}
      </section>
    </main>
  );
}

function HealthBadge({ state }: { state: HealthState }) {
  return (
    <span className={`health-badge health-${state}`}>
      {state === "ok" ? "Backend ready" : state === "checking" ? "Checking backend" : "Backend unavailable"}
    </span>
  );
}

function StatusCard({
  label,
  value,
  tone
}: {
  label: string;
  value: string;
  tone?: JobStatus | "idle";
}) {
  return (
    <article className={tone ? `status-card tone-${tone}` : "status-card"}>
      <p>{label}</p>
      <strong>{value}</strong>
    </article>
  );
}

function formatFileSize(size: number): string {
  if (size < 1024 * 1024) {
    return `${(size / 1024).toFixed(1)} KB`;
  }
  return `${(size / (1024 * 1024)).toFixed(2)} MB`;
}

function getErrorMessage(cause: unknown, fallback: string): string {
  if (cause instanceof Error && cause.message) {
    return cause.message;
  }

  return fallback;
}
