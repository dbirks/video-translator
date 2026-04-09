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
  subscribeToEvents,
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

  useEffect(() => {
    if (!id || !activeJob) return;
    const es = subscribeToEvents(id, (data) => {
      if (data.status === "completed" || data.status === "failed") {
        refresh();
      } else if (data.progress !== undefined) {
        setActiveJob((prev) => (prev ? { ...prev, ...(data as Partial<Job>) } : prev));
      }
    });
    return () => es.close();
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
              {activeJob.current_step ?? "Starting..."}
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

      {/* Segment editor */}
      {hasDraft && <SegmentEditor segments={segments} onRefresh={refresh} />}

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
