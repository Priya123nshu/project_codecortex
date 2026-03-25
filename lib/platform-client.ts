export type InputLanguage = "en" | "hi";
export type OutputLanguage = "en" | "hi" | "pa" | "ta";

export type PlatformTokenResponse = {
  access_token: string;
  platform_api_base_url: string;
  role: "admin" | "user";
};

export type JobStatus =
  | "received"
  | "transcribing"
  | "thinking"
  | "synthesizing"
  | "rendering"
  | "completed"
  | "failed";

export type AvatarRecord = {
  avatar_id: string;
  display_name: string;
  status: "uploading" | "uploaded" | "preprocessing" | "ready" | "failed";
  approved: boolean;
  language: "en" | "hi" | "pa" | "ta" | "multilingual";
  source_object_key?: string | null;
  prepared_bundle_location?: string | null;
  persona_prompt?: string | null;
  default_voice?: string | null;
  num_frames?: number | null;
  last_error?: string | null;
  source_upload?: {
    upload_method: "PUT" | "S3_PRESIGNED_POST";
    upload_url: string;
    object_key: string;
  } | null;
};

export type DocumentRecord = {
  document_id: string;
  title: string;
  status: "uploaded" | "indexing" | "ready" | "failed";
  mime_type: string;
  source_object_key: string;
  chunk_count: number;
  last_error?: string | null;
  created_at: string;
  updated_at: string;
};

export type SessionRecord = {
  session_id: string;
  avatar_id: string;
  input_language: InputLanguage;
  output_language: OutputLanguage;
  status: "active" | "completed" | "failed";
  audience?: string | null;
  context_notes?: string | null;
  created_at: string;
  updated_at: string;
};

export type TurnRecord = {
  turn_id: string;
  session_id: string;
  user_transcript?: string | null;
  retrieval_query_text?: string | null;
  assistant_text?: string | null;
  status: JobStatus;
  render_job_id?: string | null;
  error?: string | null;
  created_at: string;
  updated_at: string;
};

export type TurnHistoryResponse = {
  session: SessionRecord;
  turns: TurnRecord[];
};

export type RetrievalChunk = {
  document_id: string;
  title: string;
  chunk_index: number;
  score: number;
  content: string;
};

export type StreamEvent =
  | {
      event: "transcript_ready";
      payload: { session_id: string; turn_id: string; transcript: string; input_language: InputLanguage };
    }
  | {
      event: "retrieval_ready";
      payload: { session_id: string; turn_id: string; query_text: string; chunks: RetrievalChunk[] };
    }
  | {
      event: "assistant_text_ready";
      payload: { session_id: string; turn_id: string; language: OutputLanguage; text: string };
    }
  | {
      event: "tts_ready";
      payload: {
        session_id: string;
        turn_id: string;
        provider: "edge-tts" | "friend-local" | "indic-parler";
        language: OutputLanguage;
        audio_object_key: string;
        cache_hit: boolean;
      };
    }
  | {
      event: "avatar_chunk_ready";
      payload: {
        session_id: string;
        turn_id: string;
        avatar_id: string;
        chunk_index: number;
        video_url: string;
        done_marker: boolean;
        text_segment?: string | null;
      };
    }
  | {
      event: "turn_completed";
      payload: { session_id: string; turn_id: string; render_job_id?: string | null; chunk_count: number };
    }
  | {
      event: "turn_failed";
      payload: { session_id: string; turn_id: string; error: string; recoverable: boolean };
    };

export async function parseJsonResponse<T>(response: Response): Promise<T | { detail?: string }> {
  const contentType = response.headers.get("content-type") ?? "";
  if (contentType.includes("application/json")) {
    return (await response.json()) as T | { detail?: string };
  }
  const detail = await response.text();
  return { detail };
}

