"use client";

import { FormEvent, ReactNode, useEffect, useMemo, useRef, useState } from "react";
import { signOut } from "next-auth/react";
import type {
  AvatarRecord,
  DocumentRecord,
  InputLanguage,
  OutputLanguage,
  PlatformTokenResponse,
  RetrievalChunk,
  SessionRecord,
  StreamEvent,
  TurnHistoryResponse,
  TurnRecord,
} from "@/lib/platform-client";
import { parseJsonResponse } from "@/lib/platform-client";

type Props = {
  userName: string;
  userEmail: string;
  isAdmin: boolean;
};

type ServiceHealth = {
  status: string;
  service: string;
  auth_required: boolean;
  storage_backend: string;
};

type TabKey = "conversation" | "admin";

type EventLogEntry = {
  type: string;
  text: string;
};

type LanguageOption<TValue extends string> = {
  value: TValue;
  label: string;
  locale?: string;
};

type ResetConversationOptions = {
  clearSession?: boolean;
  clearTurns?: boolean;
  clearTranscriptHint?: boolean;
  clearPendingTurn?: boolean;
};

type BrowserSpeechRecognitionAlternative = {
  transcript: string;
};

type BrowserSpeechRecognitionResult = {
  0?: BrowserSpeechRecognitionAlternative;
  length: number;
};

type BrowserSpeechRecognitionEvent = {
  results: ArrayLike<BrowserSpeechRecognitionResult>;
};

type BrowserSpeechRecognitionErrorEvent = {
  error: string;
};

type BrowserSpeechRecognition = {
  continuous: boolean;
  interimResults: boolean;
  lang: string;
  onresult: ((event: BrowserSpeechRecognitionEvent) => void) | null;
  onerror: ((event: BrowserSpeechRecognitionErrorEvent) => void) | null;
  onend: (() => void) | null;
  start: () => void;
  stop: () => void;
};

type SpeechRecognitionConstructor = new () => BrowserSpeechRecognition;

declare global {
  interface Window {
    SpeechRecognition?: SpeechRecognitionConstructor;
    webkitSpeechRecognition?: SpeechRecognitionConstructor;
  }
}

const INPUT_LANGUAGE_OPTIONS: LanguageOption<InputLanguage>[] = [
  { value: "en", label: "English", locale: "en-US" },
  { value: "hi", label: "Hindi", locale: "hi-IN" },
];

const OUTPUT_LANGUAGE_OPTIONS: LanguageOption<OutputLanguage>[] = [
  { value: "en", label: "English" },
  { value: "hi", label: "Hindi" },
  { value: "pa", label: "Punjabi" },
  { value: "ta", label: "Tamil" },
];

const INPUT_LANGUAGE_LABELS: Record<InputLanguage, string> = {
  en: "English",
  hi: "Hindi",
};

const OUTPUT_LANGUAGE_LABELS: Record<OutputLanguage, string> = {
  en: "English",
  hi: "Hindi",
  pa: "Punjabi",
  ta: "Tamil",
};

export default function PlatformApp({ userName, userEmail, isAdmin }: Props) {
  const [activeTab, setActiveTab] = useState<TabKey>("conversation");
  const [tokenState, setTokenState] = useState<PlatformTokenResponse | null>(null);
  const [platformError, setPlatformError] = useState<string | null>(null);
  const [health, setHealth] = useState<ServiceHealth | null>(null);
  const [avatars, setAvatars] = useState<AvatarRecord[]>([]);
  const [documents, setDocuments] = useState<DocumentRecord[]>([]);
  const [selectedAvatarId, setSelectedAvatarId] = useState("");
  const [selectedInputLanguage, setSelectedInputLanguage] = useState<InputLanguage>("en");
  const [selectedOutputLanguage, setSelectedOutputLanguage] = useState<OutputLanguage>("en");
  const [sessionRecord, setSessionRecord] = useState<SessionRecord | null>(null);
  const [turns, setTurns] = useState<TurnRecord[]>([]);
  const [currentTranscript, setCurrentTranscript] = useState("");
  const [currentRetrievalQuery, setCurrentRetrievalQuery] = useState("");
  const [currentAnswer, setCurrentAnswer] = useState("");
  const [retrievalChunks, setRetrievalChunks] = useState<RetrievalChunk[]>([]);
  const [chunkUrls, setChunkUrls] = useState<string[]>([]);
  const [selectedChunkUrl, setSelectedChunkUrl] = useState<string | null>(null);
  const [eventLog, setEventLog] = useState<EventLogEntry[]>([]);
  const [isRecording, setIsRecording] = useState(false);
  const [isSubmittingTurn, setIsSubmittingTurn] = useState(false);
  const [recordingHint, setRecordingHint] = useState<string | null>(null);
  const [transcriptHint, setTranscriptHint] = useState("");
  const [pendingTurnBlob, setPendingTurnBlob] = useState<Blob | null>(null);
  const [conversationError, setConversationError] = useState<string | null>(null);
  const [adminError, setAdminError] = useState<string | null>(null);
  const [avatarForm, setAvatarForm] = useState({ avatarId: "", displayName: "", personaPrompt: "", voice: "en-US-JennyNeural" });
  const [avatarVideo, setAvatarVideo] = useState<File | null>(null);
  const [documentTitle, setDocumentTitle] = useState("");
  const [documentFile, setDocumentFile] = useState<File | null>(null);
  const [isSubmittingAvatar, setIsSubmittingAvatar] = useState(false);
  const [isSubmittingDocument, setIsSubmittingDocument] = useState(false);

  const recorderRef = useRef<MediaRecorder | null>(null);
  const streamRef = useRef<MediaStream | null>(null);
  const chunksRef = useRef<Blob[]>([]);
  const speechRef = useRef<BrowserSpeechRecognition | null>(null);
  const videoRef = useRef<HTMLVideoElement | null>(null);
  const autoplayIndexRef = useRef(0);

  const readyAvatars = useMemo(() => avatars.filter((avatar) => avatar.status === "ready" && avatar.approved), [avatars]);
  const selectedInputLabel = INPUT_LANGUAGE_LABELS[selectedInputLanguage];
  const selectedOutputLabel = OUTPUT_LANGUAGE_LABELS[selectedOutputLanguage];
  const isConversationBusy = isRecording || isSubmittingTurn;

  useEffect(() => {
    void fetchPlatformToken();
  }, []);

  useEffect(() => {
    if (!tokenState) {
      return;
    }
    void refreshHealth();
    void refreshAvatarLibrary();
    if (isAdmin) {
      void refreshDocuments();
    }
  }, [tokenState, isAdmin]);

  useEffect(() => {
    if (readyAvatars.length === 0) {
      return;
    }
    if (!selectedAvatarId || !readyAvatars.some((avatar) => avatar.avatar_id === selectedAvatarId)) {
      setSelectedAvatarId(readyAvatars[0].avatar_id);
    }
  }, [readyAvatars, selectedAvatarId]);

  useEffect(() => {
    if (!isAdmin || !tokenState) {
      return;
    }
    const hasProcessing = avatars.some((avatar) => avatar.status === "preprocessing" || avatar.status === "uploaded");
    if (!hasProcessing) {
      return;
    }
    const timer = window.setInterval(() => {
      void refreshAvatarLibrary();
    }, 5000);
    return () => window.clearInterval(timer);
  }, [avatars, isAdmin, tokenState]);

  useEffect(() => {
    if (chunkUrls.length === 0) {
      setSelectedChunkUrl(null);
      autoplayIndexRef.current = 0;
      return;
    }
    setSelectedChunkUrl((current) => (current && chunkUrls.includes(current) ? current : chunkUrls[0]));
  }, [chunkUrls]);

  useEffect(() => {
    autoplayIndexRef.current = selectedChunkUrl ? chunkUrls.indexOf(selectedChunkUrl) : 0;
  }, [selectedChunkUrl, chunkUrls]);

  async function fetchPlatformToken() {
    try {
      const response = await fetch("/api/platform-token", { cache: "no-store" });
      const payload = (await parseJsonResponse<PlatformTokenResponse>(response)) as PlatformTokenResponse | { detail?: string };
      if (!response.ok) {
        throw new Error("detail" in payload && payload.detail ? payload.detail : "Unable to fetch a platform access token.");
      }
      setTokenState(payload as PlatformTokenResponse);
      setPlatformError(null);
    } catch (error) {
      setPlatformError(getErrorMessage(error, "Unable to connect the frontend to the platform API."));
    }
  }

  async function authorizedFetch(path: string, init?: RequestInit) {
    if (!tokenState) {
      throw new Error("Platform API access token is missing.");
    }

    const headers = new Headers(init?.headers || {});
    headers.set("Authorization", `Bearer ${tokenState.access_token}`);
    headers.set("ngrok-skip-browser-warning", "1");
    return await fetch(`${tokenState.platform_api_base_url}${path}`, {
      ...init,
      headers,
      cache: "no-store",
    });
  }

  async function authorizedUpload(url: string, formData: FormData, method: string = "PUT") {
    if (!tokenState) {
      throw new Error("Platform API access token is missing.");
    }
    const headers = new Headers();
    headers.set("Authorization", `Bearer ${tokenState.access_token}`);
    headers.set("ngrok-skip-browser-warning", "1");
    return await fetch(url, { method, headers, body: formData });
  }

  async function refreshHealth() {
    try {
      const response = await authorizedFetch("/health");
      const payload = (await parseJsonResponse<ServiceHealth>(response)) as ServiceHealth | { detail?: string };
      if (!response.ok) {
        throw new Error("detail" in payload && payload.detail ? payload.detail : "Unable to fetch platform health.");
      }
      setHealth(payload as ServiceHealth);
    } catch (error) {
      setPlatformError(getErrorMessage(error, "Unable to reach the platform API."));
    }
  }

  async function refreshAvatarLibrary() {
    try {
      const endpoint = isAdmin ? "/admin/avatars" : "/avatars";
      const response = await authorizedFetch(endpoint);
      const payload = (await parseJsonResponse<{ avatars: AvatarRecord[] }>(response)) as { avatars: AvatarRecord[] } | { detail?: string };
      if (!response.ok) {
        throw new Error("detail" in payload && payload.detail ? payload.detail : "Unable to fetch avatars.");
      }
      setAvatars((payload as { avatars: AvatarRecord[] }).avatars ?? []);
    } catch (error) {
      setPlatformError(getErrorMessage(error, "Unable to load the avatar library."));
    }
  }

  async function refreshDocuments() {
    try {
      const response = await authorizedFetch("/admin/documents");
      const payload = (await parseJsonResponse<{ documents: DocumentRecord[] }>(response)) as { documents: DocumentRecord[] } | { detail?: string };
      if (!response.ok) {
        throw new Error("detail" in payload && payload.detail ? payload.detail : "Unable to fetch documents.");
      }
      setDocuments((payload as { documents: DocumentRecord[] }).documents ?? []);
    } catch (error) {
      setAdminError(getErrorMessage(error, "Unable to load indexed documents."));
    }
  }

  function clearLiveTurnState() {
    setCurrentTranscript("");
    setCurrentRetrievalQuery("");
    setCurrentAnswer("");
    setRetrievalChunks([]);
    setChunkUrls([]);
    setSelectedChunkUrl(null);
    setEventLog([]);
    setConversationError(null);
  }

  function resetConversationState(options: ResetConversationOptions = {}) {
    const {
      clearSession = true,
      clearTurns = true,
      clearTranscriptHint = true,
      clearPendingTurn = true,
    } = options;

    clearLiveTurnState();
    setRecordingHint(null);
    if (clearSession) {
      setSessionRecord(null);
    }
    if (clearTurns) {
      setTurns([]);
    }
    if (clearTranscriptHint) {
      setTranscriptHint("");
    }
    if (clearPendingTurn) {
      setPendingTurnBlob(null);
    }
  }

  function sessionMatchesSelection(session: SessionRecord) {
    return (
      session.avatar_id === selectedAvatarId &&
      session.input_language === selectedInputLanguage &&
      session.output_language === selectedOutputLanguage
    );
  }

  async function createSessionForSelection(avatarId: string, inputLanguage: InputLanguage, outputLanguage: OutputLanguage) {
    const response = await authorizedFetch("/sessions", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        avatar_id: avatarId,
        input_language: inputLanguage,
        output_language: outputLanguage,
      }),
    });
    const payload = (await parseJsonResponse<SessionRecord>(response)) as SessionRecord | { detail?: string };
    if (!response.ok) {
      throw new Error("detail" in payload && payload.detail ? payload.detail : "Unable to create a new session.");
    }
    const session = payload as SessionRecord;
    setSessionRecord(session);
    setTurns([]);
    return session;
  }

  async function refreshSessionHistory(sessionId: string) {
    const response = await authorizedFetch(`/sessions/${sessionId}/history`);
    const payload = (await parseJsonResponse<TurnHistoryResponse>(response)) as TurnHistoryResponse | { detail?: string };
    if (!response.ok) {
      throw new Error("detail" in payload && payload.detail ? payload.detail : "Unable to load session history.");
    }
    const history = payload as TurnHistoryResponse;
    setTurns(history.turns);
    setSessionRecord(history.session);
  }

  function handleAvatarSelectionChange(avatarId: string) {
    setSelectedAvatarId(avatarId);
    resetConversationState();
  }

  function handleInputLanguageChange(language: InputLanguage) {
    setSelectedInputLanguage(language);
    resetConversationState();
  }

  function handleOutputLanguageChange(language: OutputLanguage) {
    setSelectedOutputLanguage(language);
    resetConversationState();
  }

  async function handleAvatarSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!avatarForm.avatarId.trim() || !avatarForm.displayName.trim() || !avatarVideo) {
      setAdminError("Add an avatar ID, display name, and source video before submitting.");
      return;
    }

    try {
      setIsSubmittingAvatar(true);
      setAdminError(null);
      const createResponse = await authorizedFetch("/admin/avatars", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          avatar_id: avatarForm.avatarId.trim(),
          display_name: avatarForm.displayName.trim(),
          persona_prompt: avatarForm.personaPrompt,
          default_voice: avatarForm.voice,
          language: "multilingual",
          approved: true,
        }),
      });
      const createPayload = (await parseJsonResponse<AvatarRecord>(createResponse)) as AvatarRecord | { detail?: string };
      if (!createResponse.ok) {
        throw new Error("detail" in createPayload && createPayload.detail ? createPayload.detail : "Unable to create the avatar record.");
      }

      const avatar = createPayload as AvatarRecord;
      if (!avatar.source_upload?.upload_url) {
        throw new Error("The platform API did not return an upload target for the avatar video.");
      }
      const uploadForm = new FormData();
      uploadForm.set("video_file", avatarVideo);
      const uploadResponse = await authorizedUpload(avatar.source_upload.upload_url, uploadForm, "PUT");
      const uploadPayload = await parseJsonResponse<AvatarRecord>(uploadResponse);
      if (!uploadResponse.ok) {
        throw new Error("detail" in uploadPayload && uploadPayload.detail ? uploadPayload.detail : "Unable to upload the source avatar video.");
      }
      const preprocessResponse = await authorizedFetch(`/admin/avatars/${avatar.avatar_id}/preprocess`, { method: "POST" });
      const preprocessPayload = await parseJsonResponse<{ avatar_id: string; status: string }>(preprocessResponse);
      if (!preprocessResponse.ok) {
        throw new Error("detail" in preprocessPayload && preprocessPayload.detail ? preprocessPayload.detail : "Unable to start avatar preprocessing.");
      }
      setAvatarForm({ avatarId: "", displayName: "", personaPrompt: "", voice: "en-US-JennyNeural" });
      setAvatarVideo(null);
      await refreshAvatarLibrary();
    } catch (error) {
      setAdminError(getErrorMessage(error, "Unable to add this avatar right now."));
    } finally {
      setIsSubmittingAvatar(false);
    }
  }

  async function handleDocumentSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!documentTitle.trim() || !documentFile) {
      setAdminError("Add a document title and choose a file before uploading.");
      return;
    }

    try {
      setIsSubmittingDocument(true);
      setAdminError(null);
      const formData = new FormData();
      formData.set("title", documentTitle.trim());
      formData.set("file", documentFile);
      const response = await authorizedFetch("/admin/documents", { method: "POST", body: formData });
      const payload = await parseJsonResponse<DocumentRecord>(response);
      if (!response.ok) {
        throw new Error("detail" in payload && payload.detail ? payload.detail : "Unable to index this document.");
      }
      setDocumentTitle("");
      setDocumentFile(null);
      await refreshDocuments();
    } catch (error) {
      setAdminError(getErrorMessage(error, "Unable to upload this document."));
    } finally {
      setIsSubmittingDocument(false);
    }
  }

  function cleanupActiveMedia() {
    speechRef.current?.stop();
    speechRef.current = null;
    recorderRef.current = null;
    streamRef.current?.getTracks().forEach((track) => track.stop());
    streamRef.current = null;
  }

  function readTranscriptFromRecognition(event: BrowserSpeechRecognitionEvent): string {
    return Array.from({ length: event.results.length }, (_, index) => event.results[index])
      .map((result) => result?.[0]?.transcript ?? "")
      .join(" ")
      .trim();
  }

  async function beginRecording() {
    if (isConversationBusy || pendingTurnBlob) {
      return;
    }
    if (!selectedAvatarId) {
      setConversationError("Choose a ready avatar before starting a turn.");
      return;
    }
    if (!navigator.mediaDevices?.getUserMedia) {
      setConversationError("This browser cannot capture microphone audio for push-to-talk.");
      return;
    }

    try {
      setConversationError(null);
      setTranscriptHint("");
      setPendingTurnBlob(null);
      const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
      streamRef.current = stream;
      const recorder = new MediaRecorder(stream);
      recorderRef.current = recorder;
      chunksRef.current = [];
      recorder.ondataavailable = (event) => {
        if (event.data.size > 0) {
          chunksRef.current.push(event.data);
        }
      };
      recorder.onstop = () => {
        const blob = new Blob(chunksRef.current, { type: chunksRef.current[0]?.type || "audio/webm" });
        chunksRef.current = [];
        void handleRecordedTurn(blob);
      };
      recorder.start();
      setIsRecording(true);
      setRecordingHint(`Listening in ${selectedInputLabel}. Release to capture this turn.`);

      const SpeechRecognitionCtor = window.SpeechRecognition || window.webkitSpeechRecognition;
      if (SpeechRecognitionCtor) {
        const recognition = new SpeechRecognitionCtor();
        recognition.continuous = false;
        recognition.interimResults = true;
        recognition.lang = INPUT_LANGUAGE_OPTIONS.find((option) => option.value === selectedInputLanguage)?.locale ?? "en-US";
        recognition.onresult = (event) => {
          setTranscriptHint(readTranscriptFromRecognition(event));
        };
        recognition.onerror = () => {
          setRecordingHint("Speech recognition paused. You can still type the transcript below before sending.");
        };
        recognition.onend = () => {
          speechRef.current = null;
        };
        speechRef.current = recognition;
        recognition.start();
      } else {
        setRecordingHint(`Recording in ${selectedInputLabel}. Browser speech recognition is unavailable, so type the transcript before sending.`);
      }
    } catch (error) {
      cleanupActiveMedia();
      setIsRecording(false);
      setConversationError(getErrorMessage(error, "Microphone access is required for push-to-talk."));
    }
  }

  async function stopRecording() {
    if (!isRecording) {
      return;
    }
    setRecordingHint("Finishing the take...");
    setIsRecording(false);
    speechRef.current?.stop();
    speechRef.current = null;
    recorderRef.current?.stop();
    recorderRef.current = null;
    streamRef.current?.getTracks().forEach((track) => track.stop());
    streamRef.current = null;
  }

  async function handleRecordedTurn(blob: Blob) {
    if (blob.size === 0) {
      setConversationError("No microphone audio was captured. Try recording the turn again.");
      setRecordingHint(null);
      return;
    }

    const normalizedTranscript = transcriptHint.trim();
    if (!normalizedTranscript) {
      setPendingTurnBlob(blob);
      setRecordingHint("Transcript confirmation required before the turn can be sent.");
      setConversationError("No transcript was captured. Edit the transcript box, then send or discard the take.");
      return;
    }

    await submitTurnBlob(blob, normalizedTranscript);
  }

  async function submitTurnBlob(blob: Blob, transcript: string) {
    if (!selectedAvatarId) {
      setConversationError("Choose a ready avatar before submitting a turn.");
      return;
    }

    try {
      if (!tokenState) {
        throw new Error("Platform API access token is missing.");
      }
      setIsSubmittingTurn(true);
      setPendingTurnBlob(null);
      setConversationError(null);
      setRecordingHint("Sending the turn through retrieval, TTS, and avatar rendering...");

      const activeSession = sessionRecord && sessionMatchesSelection(sessionRecord)
        ? sessionRecord
        : await createSessionForSelection(selectedAvatarId, selectedInputLanguage, selectedOutputLanguage);

      clearLiveTurnState();
      setCurrentTranscript(transcript);

      const formData = new FormData();
      formData.set("audio_file", new File([blob], `turn-${Date.now()}.webm`, { type: blob.type || "audio/webm" }));
      formData.set("transcript_hint", transcript);

      const response = await fetch(`/api/platform/sessions/${activeSession.session_id}/turns`, {
        method: "POST",
        headers: {
          Authorization: `Bearer ${tokenState.access_token}`,
        },
        body: formData,
        cache: "no-store",
      });
      if (!response.ok || !response.body) {
        const payload = await parseJsonResponse<{ detail?: string }>(response);
        throw new Error("detail" in payload && payload.detail ? payload.detail : "Unable to submit the recorded turn.");
      }

      await consumeTurnStream(response, activeSession.session_id);
      await refreshSessionHistory(activeSession.session_id);
      setTranscriptHint("");
      setRecordingHint(null);
    } catch (error) {
      setPendingTurnBlob(blob);
      setRecordingHint("This take is still available. Adjust the transcript and retry.");
      setConversationError(getErrorMessage(error, "Unable to process this turn."));
    } finally {
      setIsSubmittingTurn(false);
    }
  }

  async function submitPendingTurn() {
    if (!pendingTurnBlob) {
      return;
    }
    const normalizedTranscript = transcriptHint.trim();
    if (!normalizedTranscript) {
      setConversationError("A transcript is required before the turn can be submitted.");
      return;
    }
    await submitTurnBlob(pendingTurnBlob, normalizedTranscript);
  }

  function discardPendingTurn() {
    setPendingTurnBlob(null);
    setTranscriptHint("");
    setRecordingHint(null);
    setConversationError(null);
  }

  async function consumeTurnStream(response: Response, sessionId: string) {
    const reader = response.body?.getReader();
    if (!reader) {
      throw new Error("The browser could not read the streamed turn response.");
    }
    const decoder = new TextDecoder();
    let buffer = "";
    while (true) {
      const { value, done } = await reader.read();
      if (done) {
        break;
      }
      buffer += decoder.decode(value, { stream: true });
      let boundary = buffer.indexOf("\n\n");
      while (boundary >= 0) {
        const block = buffer.slice(0, boundary).trim();
        buffer = buffer.slice(boundary + 2);
        if (block) {
          handleSseBlock(block, sessionId);
        }
        boundary = buffer.indexOf("\n\n");
      }
    }
  }

  function handleSseBlock(block: string, sessionId: string) {
    const lines = block.split("\n");
    let eventName = "message";
    const dataLines: string[] = [];
    for (const line of lines) {
      if (line.startsWith("event:")) {
        eventName = line.replace("event:", "").trim();
      }
      if (line.startsWith("data:")) {
        dataLines.push(line.replace("data:", "").trim());
      }
    }
    const rawData = dataLines.join("\n");
    const payload = rawData ? JSON.parse(rawData) : {};
    setEventLog((current) => [{ type: eventName, text: rawData }, ...current].slice(0, 12));

    const typedEvent = { event: eventName, payload } as StreamEvent;
    switch (typedEvent.event) {
      case "transcript_ready":
        setCurrentTranscript(typedEvent.payload.transcript);
        break;
      case "retrieval_ready":
        setCurrentRetrievalQuery(typedEvent.payload.query_text);
        setRetrievalChunks(typedEvent.payload.chunks);
        break;
      case "assistant_text_ready":
        setCurrentAnswer(typedEvent.payload.text);
        break;
      case "avatar_chunk_ready":
        setChunkUrls((current) => (current.includes(typedEvent.payload.video_url) ? current : [...current, typedEvent.payload.video_url]));
        setSelectedChunkUrl((current) => current ?? typedEvent.payload.video_url);
        break;
      case "turn_completed":
        setRecordingHint(null);
        void refreshSessionHistory(sessionId);
        break;
      case "turn_failed":
        setRecordingHint("The platform reported a turn failure.");
        setConversationError(typedEvent.payload.error);
        break;
      default:
        break;
    }
  }

  function handleVideoEnded() {
    if (!videoRef.current || chunkUrls.length === 0) {
      return;
    }
    const nextIndex = autoplayIndexRef.current + 1;
    if (nextIndex < chunkUrls.length) {
      autoplayIndexRef.current = nextIndex;
      setSelectedChunkUrl(chunkUrls[nextIndex]);
    }
  }

  return (
    <main className="platform-shell">
      <section className="card-surface platform-hero">
        <div className="hero-topline">
          <div>
            <p className="eyebrow">Multilingual avatar platform</p>
            <h1>Real-time avatar replies with retrieval, Azure OpenAI, and streamed video chunks.</h1>
            <p className="hero-copy">
              This demo keeps push-to-talk and sequential MP4 playback for v1, but now the session can listen in English or Hindi and speak back in English, Hindi, Punjabi, or Tamil. The browser captures a turn, the platform grounds it with retrieval, Azure OpenAI produces the final answer in the target language, TTS creates audio, and the avatar render service streams chunked video back.
            </p>
          </div>
          <div className="hero-sidecard">
            <span className="meta-label">Signed in</span>
            <strong>{userName}</strong>
            <p>{userEmail}</p>
            <StatusPill tone={health?.status === "ok" ? "ok" : "waiting"}>
              {health?.status === "ok" ? "Platform reachable" : "Checking platform"}
            </StatusPill>
          </div>
        </div>

        <div className="hero-actions">
          <button className="ghost-button" onClick={() => void fetchPlatformToken()} type="button">
            Refresh token
          </button>
          <button className="ghost-button" onClick={() => void refreshHealth()} type="button">
            Refresh platform health
          </button>
          <button className="ghost-button" onClick={() => void refreshAvatarLibrary()} type="button">
            Refresh avatar library
          </button>
          {isAdmin ? (
            <button className="ghost-button" onClick={() => void refreshDocuments()} type="button">
              Refresh documents
            </button>
          ) : null}
          <button className="ghost-button" onClick={() => void signOut({ redirectTo: "/" })} type="button">
            Sign out
          </button>
        </div>

        <div className="stats-row">
          <StatCard label="Ready avatars" value={String(readyAvatars.length)} />
          <StatCard label="Indexed documents" value={isAdmin ? String(documents.length) : "Admin managed"} />
          <StatCard label="Live language route" value={`${selectedInputLabel} -> ${selectedOutputLabel}`} />
          <StatCard label="Latest turn state" value={turns.at(-1)?.status ?? "idle"} />
        </div>

        {platformError ? <div className="error-banner">{platformError}</div> : null}
      </section>

      <section className="tab-strip">
        <button
          className={activeTab === "conversation" ? "tab-button active" : "tab-button"}
          onClick={() => setActiveTab("conversation")}
          type="button"
        >
          Conversation app
        </button>
        {isAdmin ? (
          <button
            className={activeTab === "admin" ? "tab-button active" : "tab-button"}
            onClick={() => setActiveTab("admin")}
            type="button"
          >
            Admin console
          </button>
        ) : null}
      </section>

      {activeTab === "conversation" ? (
        <section className="platform-grid two-column">
          <div className="stack-column">
            <section className="card-surface panel-card">
              <div className="panel-heading">
                <div>
                  <p className="eyebrow">Step 1</p>
                  <h2>Choose an avatar and language route</h2>
                </div>
                <StatusPill tone={readyAvatars.length > 0 ? "ok" : "waiting"}>
                  {readyAvatars.length > 0 ? `${readyAvatars.length} ready` : "No ready avatars"}
                </StatusPill>
              </div>

              <div className="selection-grid">
                <label className="field-block field-block-full">
                  <span>Selected avatar</span>
                  <select
                    className="input-control"
                    disabled={isConversationBusy}
                    onChange={(event) => handleAvatarSelectionChange(event.target.value)}
                    value={selectedAvatarId}
                  >
                    {readyAvatars.length > 0 ? (
                      readyAvatars.map((avatar) => (
                        <option key={avatar.avatar_id} value={avatar.avatar_id}>
                          {avatar.display_name} ({avatar.avatar_id})
                        </option>
                      ))
                    ) : (
                      <option value="">No approved avatars</option>
                    )}
                  </select>
                </label>

                <label className="field-block">
                  <span>Input language</span>
                  <select
                    className="input-control"
                    disabled={isConversationBusy}
                    onChange={(event) => handleInputLanguageChange(event.target.value as InputLanguage)}
                    value={selectedInputLanguage}
                  >
                    {INPUT_LANGUAGE_OPTIONS.map((option) => (
                      <option key={option.value} value={option.value}>
                        {option.label}
                      </option>
                    ))}
                  </select>
                </label>

                <label className="field-block">
                  <span>Avatar reply language</span>
                  <select
                    className="input-control"
                    disabled={isConversationBusy}
                    onChange={(event) => handleOutputLanguageChange(event.target.value as OutputLanguage)}
                    value={selectedOutputLanguage}
                  >
                    {OUTPUT_LANGUAGE_OPTIONS.map((option) => (
                      <option key={option.value} value={option.value}>
                        {option.label}
                      </option>
                    ))}
                  </select>
                </label>
              </div>

              <div className="avatar-grid compact-avatar-grid">
                {readyAvatars.length > 0 ? (
                  readyAvatars.map((avatar) => (
                    <button
                      className={avatar.avatar_id === selectedAvatarId ? "avatar-tile active" : "avatar-tile"}
                      disabled={isConversationBusy}
                      key={avatar.avatar_id}
                      onClick={() => handleAvatarSelectionChange(avatar.avatar_id)}
                      type="button"
                    >
                      <div className="avatar-card-header">
                        <strong>{avatar.display_name}</strong>
                        <StatusPill tone={avatar.status === "ready" ? "ok" : "waiting"}>{avatar.status}</StatusPill>
                      </div>
                      <p>ID: {avatar.avatar_id}</p>
                      <p>Frames: {avatar.num_frames ?? "-"}</p>
                    </button>
                  ))
                ) : (
                  <div className="empty-state">Admins need to preprocess at least one avatar before users can start a session.</div>
                )}
              </div>
            </section>

            <section className="card-surface panel-card">
              <div className="panel-heading">
                <div>
                  <p className="eyebrow">Step 2</p>
                  <h2>Push-to-talk turn</h2>
                </div>
                <StatusPill tone={isRecording ? "ok" : pendingTurnBlob ? "waiting" : isSubmittingTurn ? "neutral" : tokenState ? "neutral" : "waiting"}>
                  {isRecording ? "Listening" : pendingTurnBlob ? "Needs transcript" : isSubmittingTurn ? "Streaming" : "Idle"}
                </StatusPill>
              </div>

              <button
                className={isRecording ? "push-button active" : "push-button"}
                disabled={!selectedAvatarId || !tokenState || isSubmittingTurn || !!pendingTurnBlob}
                onPointerCancel={() => void stopRecording()}
                onPointerDown={() => void beginRecording()}
                onPointerLeave={() => void stopRecording()}
                onPointerUp={() => void stopRecording()}
                type="button"
              >
                {isRecording
                  ? "Release to capture this turn"
                  : pendingTurnBlob
                    ? "Transcript confirmation required"
                    : isSubmittingTurn
                      ? "Sending turn..."
                      : "Hold to talk"}
              </button>

              <p className="support-copy">
                {recordingHint ??
                  `Speak in ${selectedInputLabel}. If the browser misses the transcript, edit it below and confirm before the platform sends the turn for retrieval, TTS, and 2-second avatar chunks.`}
              </p>

              <label className="field-block">
                <span>Editable transcript</span>
                <textarea
                  className="input-control textarea-control"
                  onChange={(event) => setTranscriptHint(event.target.value)}
                  placeholder={`Speech recognition hints or manual ${selectedInputLabel.toLowerCase()} transcript text appear here`}
                  value={transcriptHint}
                />
              </label>

              {pendingTurnBlob ? (
                <div className="support-actions">
                  <div className="note-card">
                    <strong>Recorded take is waiting</strong>
                    <p>{`Audio captured: ${formatFileSize(pendingTurnBlob.size)}. Confirm or edit the transcript before sending.`}</p>
                  </div>
                  <button className="primary-button" disabled={!transcriptHint.trim() || isSubmittingTurn} onClick={() => void submitPendingTurn()} type="button">
                    Send confirmed turn
                  </button>
                  <button className="ghost-button" disabled={isSubmittingTurn} onClick={discardPendingTurn} type="button">
                    Discard take
                  </button>
                </div>
              ) : null}

              {conversationError ? <div className="error-banner">{conversationError}</div> : null}
            </section>

            <section className="card-surface panel-card">
              <div className="panel-heading">
                <div>
                  <p className="eyebrow">Turn trace</p>
                  <h2>Latest streamed events</h2>
                </div>
              </div>

              <div className="event-list">
                {eventLog.length > 0 ? (
                  eventLog.map((entry, index) => (
                    <article className="event-card" key={`${entry.type}-${index}`}>
                      <strong>{entry.type}</strong>
                      <pre>{entry.text}</pre>
                    </article>
                  ))
                ) : (
                  <div className="empty-state">The SSE event stream appears here after the first turn is submitted.</div>
                )}
              </div>
            </section>
          </div>

          <div className="stack-column">
            <section className="card-surface panel-card">
              <div className="panel-heading">
                <div>
                  <p className="eyebrow">Step 3</p>
                  <h2>Live response</h2>
                </div>
                <StatusPill tone={chunkUrls.length > 0 ? "ok" : "waiting"}>
                  {chunkUrls.length > 0 ? `${chunkUrls.length} chunks ready` : "Waiting for chunks"}
                </StatusPill>
              </div>

              <div className="summary-grid conversation-summary-grid">
                <InfoCard label="Transcript" value={currentTranscript || "Waiting for transcript..."} multiline />
                <InfoCard label="Retrieval query (English)" value={currentRetrievalQuery || "Waiting for retrieval query..."} multiline />
                <InfoCard label="Assistant reply" value={currentAnswer || `Waiting for ${selectedOutputLabel} answer...`} multiline />
              </div>

              <div className="subsection">
                <h3>Retrieved knowledge</h3>
                {retrievalChunks.length > 0 ? (
                  <div className="retrieval-list">
                    {retrievalChunks.map((chunk) => (
                      <article className="retrieval-card" key={`${chunk.document_id}-${chunk.chunk_index}`}>
                        <div className="retrieval-card-header">
                          <strong>{chunk.title}</strong>
                          <span>score {chunk.score.toFixed(3)}</span>
                        </div>
                        <p>{chunk.content}</p>
                      </article>
                    ))}
                  </div>
                ) : (
                  <div className="empty-state">Upload organization documents in the admin console to ground the avatar replies.</div>
                )}
              </div>

              <div className="subsection">
                <h3>Rendered chunk playback</h3>
                {chunkUrls.length > 0 ? (
                  <>
                    <div className="chunk-row">
                      {chunkUrls.map((url, index) => (
                        <button
                          className={selectedChunkUrl === url ? "chunk-button active" : "chunk-button"}
                          key={url}
                          onClick={() => setSelectedChunkUrl(url)}
                          type="button"
                        >
                          Chunk {index + 1}
                        </button>
                      ))}
                    </div>
                    <div className="video-shell">
                      {selectedChunkUrl ? (
                        <video autoPlay controls key={selectedChunkUrl} onEnded={handleVideoEnded} ref={videoRef} src={selectedChunkUrl} />
                      ) : null}
                    </div>
                  </>
                ) : (
                  <div className="empty-state">The first 2-second video response chunk will appear here once the avatar render service completes the first step.</div>
                )}
              </div>
            </section>

            <section className="card-surface panel-card">
              <div className="panel-heading">
                <div>
                  <p className="eyebrow">History</p>
                  <h2>Session turns</h2>
                </div>
                {sessionRecord ? (
                  <button className="ghost-button" onClick={() => void refreshSessionHistory(sessionRecord.session_id)} type="button">
                    Refresh session
                  </button>
                ) : null}
              </div>

              <div className="turn-list">
                {turns.length > 0 ? (
                  turns.map((turn) => (
                    <article className="turn-card" key={turn.turn_id}>
                      <div className="turn-meta-row">
                        <strong>{turn.turn_id}</strong>
                        <span>{turn.status}</span>
                      </div>
                      <p>
                        <span>User:</span> {turn.user_transcript || "Waiting for transcript"}
                      </p>
                      <p>
                        <span>Retrieval query:</span> {turn.retrieval_query_text || "Waiting for retrieval query"}
                      </p>
                      <p>
                        <span>Assistant:</span> {turn.assistant_text || "Waiting for reply"}
                      </p>
                    </article>
                  ))
                ) : (
                  <div className="empty-state">A fresh session is created whenever the avatar or language route changes, and saved turns will appear here after the first submission.</div>
                )}
              </div>
            </section>
          </div>
        </section>
      ) : (
        <section className="platform-grid two-column admin-layout">
          <section className="card-surface panel-card">
            <div className="panel-heading">
              <div>
                <p className="eyebrow">Admin</p>
                <h2>Create and preprocess avatars</h2>
              </div>
              <StatusPill tone={avatars.length > 0 ? "ok" : "waiting"}>{avatars.length} total avatars</StatusPill>
            </div>

            <form className="field-grid" onSubmit={handleAvatarSubmit}>
              <label className="field-block">
                <span>Avatar ID</span>
                <input
                  className="input-control"
                  onChange={(event) => setAvatarForm((current) => ({ ...current, avatarId: event.target.value }))}
                  placeholder="sydneey or avatar-02"
                  value={avatarForm.avatarId}
                />
              </label>

              <label className="field-block">
                <span>Display name</span>
                <input
                  className="input-control"
                  onChange={(event) => setAvatarForm((current) => ({ ...current, displayName: event.target.value }))}
                  placeholder="Guide avatar"
                  value={avatarForm.displayName}
                />
              </label>

              <label className="field-block field-block-full">
                <span>Persona prompt</span>
                <textarea
                  className="input-control textarea-control"
                  onChange={(event) => setAvatarForm((current) => ({ ...current, personaPrompt: event.target.value }))}
                  placeholder="Describe the tone, purpose, and answer style for this avatar"
                  value={avatarForm.personaPrompt}
                />
              </label>

              <label className="field-block">
                <span>Default voice</span>
                <input
                  className="input-control"
                  onChange={(event) => setAvatarForm((current) => ({ ...current, voice: event.target.value }))}
                  value={avatarForm.voice}
                />
              </label>

              <label className="field-block">
                <span>Source talking-head video</span>
                <input accept="video/*" className="input-control" onChange={(event) => setAvatarVideo(event.target.files?.[0] ?? null)} type="file" />
                <small>
                  {avatarVideo ? `${avatarVideo.name}` : "Upload one clean source video for the avatar cache."}
                </small>
              </label>

              <button className="primary-button wide-button" disabled={isSubmittingAvatar} type="submit">
                {isSubmittingAvatar ? "Uploading avatar..." : "Create avatar"}
              </button>
            </form>

            {adminError ? <div className="error-banner">{adminError}</div> : null}

            <div className="avatar-grid admin-avatar-grid">
              {avatars.length > 0 ? (
                avatars.map((avatar) => (
                  <article className="avatar-tile admin-avatar" key={avatar.avatar_id}>
                    <div className="avatar-card-header">
                      <strong>{avatar.display_name}</strong>
                      <StatusPill tone={avatar.status === "ready" ? "ok" : avatar.status === "failed" ? "error" : "waiting"}>
                        {avatar.status}
                      </StatusPill>
                    </div>
                    <p>ID: {avatar.avatar_id}</p>
                    <p>Voice: {avatar.default_voice}</p>
                    <p>Frames: {avatar.num_frames ?? "-"}</p>
                    {avatar.last_error ? <p className="inline-error">{avatar.last_error}</p> : null}
                  </article>
                ))
              ) : (
                <div className="empty-state">No avatars have been created yet.</div>
              )}
            </div>
          </section>

          <section className="card-surface panel-card">
            <div className="panel-heading">
              <div>
                <p className="eyebrow">Knowledge base</p>
                <h2>Upload and index documents</h2>
              </div>
              <StatusPill tone={documents.length > 0 ? "ok" : "waiting"}>{documents.length} documents</StatusPill>
            </div>

            <form className="field-grid" onSubmit={handleDocumentSubmit}>
              <label className="field-block">
                <span>Document title</span>
                <input
                  className="input-control"
                  onChange={(event) => setDocumentTitle(event.target.value)}
                  placeholder="School handbook, FAQ, policy brief"
                  value={documentTitle}
                />
              </label>

              <label className="field-block">
                <span>File</span>
                <input accept=".pdf,.txt,.md,.markdown,text/plain,application/pdf" className="input-control" onChange={(event) => setDocumentFile(event.target.files?.[0] ?? null)} type="file" />
                <small>
                  {documentFile ? `${documentFile.name}` : "PDF and text documents are embedded immediately in the pilot backend."}
                </small>
              </label>

              <button className="primary-button wide-button" disabled={isSubmittingDocument} type="submit">
                {isSubmittingDocument ? "Uploading document..." : "Upload document"}
              </button>
            </form>

            <div className="document-list">
              {documents.length > 0 ? (
                documents.map((document) => (
                  <article className="document-card" key={document.document_id}>
                    <div className="retrieval-card-header">
                      <strong>{document.title}</strong>
                      <StatusPill tone={document.status === "ready" ? "ok" : document.status === "failed" ? "error" : "waiting"}>
                        {document.status}
                      </StatusPill>
                    </div>
                    <p>{document.mime_type}</p>
                    <p>{document.chunk_count} chunks indexed</p>
                    {document.last_error ? <p className="inline-error">{document.last_error}</p> : null}
                  </article>
                ))
              ) : (
                <div className="empty-state">No documents have been indexed yet.</div>
              )}
            </div>
          </section>
        </section>
      )}
    </main>
  );
}

function StatusPill({
  children,
  tone,
}: {
  children: ReactNode;
  tone: "ok" | "waiting" | "error" | "neutral";
}) {
  return <span className={`status-pill tone-${tone}`}>{children}</span>;
}

function StatCard({ label, value }: { label: string; value: string }) {
  return (
    <article className="stat-card">
      <span>{label}</span>
      <strong>{value}</strong>
    </article>
  );
}

function InfoCard({
  label,
  value,
  multiline = false,
}: {
  label: string;
  value: string;
  multiline?: boolean;
}) {
  return (
    <article className={multiline ? "info-card multiline" : "info-card"}>
      <span>{label}</span>
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
  if (typeof cause === "string" && cause.trim()) {
    return cause;
  }
  if (cause instanceof Error && cause.message) {
    return cause.message;
  }
  if (cause && typeof cause === "object") {
    const detail = "detail" in cause && typeof cause.detail === "string" ? cause.detail : "";
    const message = "message" in cause && typeof cause.message === "string" ? cause.message : "";
    if (detail) {
      return detail;
    }
    if (message) {
      return message;
    }
  }
  return fallback;
}



