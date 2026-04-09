const BASE = "/api";

async function request<T>(path: string, options?: RequestInit): Promise<T> {
  const res = await fetch(`${BASE}${path}`, {
    headers: { "Content-Type": "application/json", ...options?.headers },
    ...options,
  });
  if (!res.ok) {
    const body = await res.text();
    throw new Error(`${res.status}: ${body}`);
  }
  return res.json();
}

export interface Lecture {
  id: string;
  title: string;
  status: string;
  duration_seconds: number | null;
  source_language: string;
  target_language: string;
  created_at: string;
  updated_at: string;
}

export interface Segment {
  id: string;
  lecture_id: string;
  speaker: string | null;
  start_sec: number;
  end_sec: number;
  source_text_en: string;
  ordering: number;
}

export interface Translation {
  id: string;
  segment_id: string;
  translated_text: string;
  status: string;
  qa_flags: string | null;
}

export interface TTSGeneration {
  id: string;
  segment_id: string;
  provider: string;
  duration_seconds: number | null;
  status: string;
}

export interface SegmentWithTranslation {
  segment: Segment;
  translation: Translation | null;
  tts: TTSGeneration | null;
}

export interface Job {
  id: string;
  lecture_id: string;
  job_type: string;
  status: string;
  current_step: string | null;
  progress: number;
  error_message: string | null;
}

// Lectures
export const createLecture = (title: string) =>
  request<Lecture>("/lectures", {
    method: "POST",
    body: JSON.stringify({ title }),
  });

export const listLectures = () => request<Lecture[]>("/lectures");

export const getLecture = (id: string) => request<Lecture>(`/lectures/${id}`);

export const uploadVideo = async (lectureId: string, file: File) => {
  const form = new FormData();
  form.append("file", file);
  const res = await fetch(`${BASE}/lectures/${lectureId}/upload`, {
    method: "POST",
    body: form,
  });
  if (!res.ok) throw new Error(`Upload failed: ${res.status}`);
  return res.json();
};

export const processLecture = (id: string) =>
  request(`/lectures/${id}/process`, { method: "POST" });

export const exportLecture = (id: string) =>
  request(`/lectures/${id}/export`, { method: "POST" });

// Segments
export const getSegments = (lectureId: string) =>
  request<SegmentWithTranslation[]>(`/lectures/${lectureId}/segments`);

export const updateSegment = (id: string, sourceTextEn: string) =>
  request(`/segments/${id}`, {
    method: "PATCH",
    body: JSON.stringify({ source_text_en: sourceTextEn }),
  });

export const updateTranslation = (id: string, translatedText: string) =>
  request(`/translations/${id}`, {
    method: "PATCH",
    body: JSON.stringify({ translated_text: translatedText }),
  });

export const regenerateTranslation = (segmentId: string) =>
  request(`/segments/${segmentId}/translate`, { method: "POST" });

export const regenerateTTS = (segmentId: string) =>
  request(`/segments/${segmentId}/tts`, { method: "POST" });

// Jobs
export const getJobs = (lectureId: string) =>
  request<Job[]>(`/lectures/${lectureId}/jobs`);

export const getJob = (id: string) => request<Job>(`/jobs/${id}`);

// SSE
export function subscribeToEvents(
  lectureId: string,
  onEvent: (data: Record<string, unknown>) => void,
): EventSource {
  const es = new EventSource(`${BASE}/lectures/${lectureId}/events`);
  es.onmessage = (e) => {
    if (e.data) {
      try {
        onEvent(JSON.parse(e.data));
      } catch {
        // ignore parse errors from keepalive pings
      }
    }
  };
  return es;
}
