import { useEffect, useState, useCallback } from "react";
import { useParams } from "react-router";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { Progress } from "@/components/ui/progress";
import {
  getLecture,
  uploadVideo,
  processLecture,
  exportLecture,
  getSegments,
  getJobs,
  type Lecture,
  type SegmentWithTranslation,
  type Job,
} from "@/lib/api";
import { Upload, Play, Download, RefreshCw } from "lucide-react";
import SegmentEditor from "@/components/SegmentEditor";

export default function LectureDetail() {
  const { id } = useParams<{ id: string }>();
  const [lecture, setLecture] = useState<Lecture | null>(null);
  const [segments, setSegments] = useState<SegmentWithTranslation[]>([]);
  const [jobs, setJobs] = useState<Job[]>([]);
  const [uploading, setUploading] = useState(false);
  const [activeJob, setActiveJob] = useState<Job | null>(null);

  const refresh = useCallback(async () => {
    if (!id) return;
    const [l, s, j] = await Promise.all([getLecture(id), getSegments(id).catch(() => []), getJobs(id).catch(() => [])]);
    setLecture(l);
    setSegments(s);
    setJobs(j);
    const running = j.find((job) => job.status === "running" || job.status === "pending");
    setActiveJob(running ?? null);
  }, [id]);

  useEffect(() => {
    refresh();
  }, [refresh]);

  // Poll for job updates while a job is active — SSE is unreliable
  useEffect(() => {
    if (!id || !activeJob) return;
    const interval = setInterval(async () => {
      try {
        const [l, j] = await Promise.all([getLecture(id), getJobs(id)]);
        setLecture(l);
        setJobs(j);
        const running = j.find((job) => job.status === "running" || job.status === "pending");
        if (running) {
          setActiveJob(running);
        } else {
          // Job finished — do a full refresh to pick up segments/media
          setActiveJob(null);
          await refresh();
        }
      } catch {
        // ignore polling errors
      }
    }, 3000);
    return () => clearInterval(interval);
  }, [id, activeJob, refresh]);

  const handleUpload = async (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0];
    if (!file || !id) return;
    setUploading(true);
    try {
      await uploadVideo(id, file);
      await refresh();
    } finally {
      setUploading(false);
    }
  };

  const handleProcess = async () => {
    if (!id) return;
    await processLecture(id);
    await refresh();
  };

  const handleExport = async () => {
    if (!id) return;
    await exportLecture(id);
    await refresh();
  };

  if (!lecture) return <div className="p-6 text-muted-foreground">Loading...</div>;

  const isProcessing = activeJob?.status === "running";
  const hasDraft = segments.length > 0;

  return (
    <div className="max-w-6xl mx-auto p-6">
      {/* Header */}
      <div className="flex items-center justify-between mb-6">
        <div>
          <h1 className="text-2xl font-bold">{lecture.title}</h1>
          <div className="flex items-center gap-3 mt-1 text-sm text-muted-foreground">
            <Badge variant="outline">{lecture.status}</Badge>
            {lecture.duration_seconds && <span>{Math.round(lecture.duration_seconds / 60)} min</span>}
            <span>{lecture.source_language} → {lecture.target_language}</span>
          </div>
        </div>
        <div className="flex gap-2">
          {lecture.status === "uploaded" && !isProcessing && (
            <Button onClick={handleProcess}>
              <Play className="w-4 h-4" />
              Process
            </Button>
          )}
          {hasDraft && !isProcessing && (
            <>
              <Button variant="outline" onClick={handleProcess}>
                <RefreshCw className="w-4 h-4" />
                Reprocess
              </Button>
              <Button onClick={handleExport}>
                <Download className="w-4 h-4" />
                Export
              </Button>
            </>
          )}
        </div>
      </div>

      {/* Active job progress */}
      {activeJob && (activeJob.status === "running" || activeJob.status === "pending") && (
        <div className="mb-6 p-4 rounded-lg border border-border bg-card">
          <div className="flex items-center justify-between mb-2">
            <span className="text-sm font-medium">
              {(() => {
                const steps: Record<string, string> = {
                  extracting: "Extracting audio...",
                  separating: "Separating vocals from background...",
                  transcribing: "Transcribing speech...",
                  translating: "Translating...",
                  dubbing: "Generating dubbed audio...",
                  done: "Complete",
                };
                return steps[activeJob.current_step ?? ""] ?? activeJob.current_step ?? "Starting...";
              })()}
            </span>
            <span className="text-sm text-muted-foreground">
              {Math.round(activeJob.progress * 100)}%
            </span>
          </div>
          <Progress value={activeJob.progress * 100} />
        </div>
      )}

      {/* Upload section */}
      {lecture.status === "uploaded" && !hasDraft && (
        <div className="border-2 border-dashed border-border rounded-lg p-12 text-center">
          <Upload className="w-12 h-12 mx-auto mb-4 text-muted-foreground" />
          <p className="text-lg mb-4">Upload a lecture video to get started</p>
          <label className="cursor-pointer">
            <Button disabled={uploading} asChild>
              <span>{uploading ? "Uploading..." : "Choose File"}</span>
            </Button>
            <input type="file" accept="video/*" onChange={handleUpload} className="hidden" />
          </label>
        </div>
      )}

      {/* Video player */}
      {lecture.status !== "uploaded" && (
        <div className="mb-6">
          <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
            <div>
              <h3 className="text-sm font-medium text-muted-foreground mb-2">Original</h3>
              <video
                controls
                className="w-full rounded-lg border border-border bg-black"
                src={`/api/lectures/${id}/media/source_video`}
              />
            </div>
            <div>
              <h3 className="text-sm font-medium text-muted-foreground mb-2">Dubbed ({lecture.target_language.toUpperCase()})</h3>
              {lecture.status === "exported" || lecture.status === "draft" ? (
                <video
                  controls
                  className="w-full rounded-lg border border-border bg-black"
                  src={`/api/lectures/${id}/media/export_mp4`}
                />
              ) : (
                <div className="w-full aspect-video rounded-lg border border-border bg-black flex items-center justify-center text-muted-foreground text-sm">
                  Export not ready yet
                </div>
              )}
            </div>
          </div>
        </div>
      )}

      {/* Segment editor */}
      {hasDraft && (
        <SegmentEditor
          segments={segments}
          onRefresh={refresh}
          sourceLanguage={lecture.source_language}
          targetLanguage={lecture.target_language}
        />
      )}

      {/* Job history */}
      {jobs.length > 0 && (
        <div className="mt-8">
          <h2 className="text-lg font-semibold mb-3">Job History</h2>
          <div className="space-y-2">
            {jobs.map((j) => (
              <div key={j.id} className="flex items-center justify-between p-3 rounded border border-border text-sm">
                <span>{j.job_type}</span>
                <div className="flex items-center gap-3">
                  {j.error_message && (
                    <span className="text-destructive text-xs">{j.error_message}</span>
                  )}
                  <Badge
                    variant={
                      j.status === "completed" ? "success" : j.status === "failed" ? "destructive" : "outline"
                    }
                  >
                    {j.status}
                  </Badge>
                </div>
              </div>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}
