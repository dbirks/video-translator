import { useState, useRef } from "react";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import {
  updateSegment,
  updateTranslation,
  regenerateTranslation,
  regenerateTTS,
  type SegmentWithTranslation,
} from "@/lib/api";
import { formatTimestamp } from "@/lib/utils";
import { RefreshCw, Volume2, Play, Square } from "lucide-react";

interface Props {
  segments: SegmentWithTranslation[];
  onRefresh: () => Promise<void>;
  sourceLanguage?: string;
  targetLanguage?: string;
}

export default function SegmentEditor({ segments, onRefresh, sourceLanguage = "en", targetLanguage = "es" }: Props) {
  const [editingEn, setEditingEn] = useState<string | null>(null);
  const [editingEs, setEditingEs] = useState<string | null>(null);
  const [enText, setEnText] = useState("");
  const [esText, setEsText] = useState("");
  const [busy, setBusy] = useState<Set<string>>(new Set());
  const [playingId, setPlayingId] = useState<string | null>(null);
  const audioRef = useRef<HTMLAudioElement | null>(null);

  const langNames: Record<string, string> = {
    en: "English", es: "Spanish", ja: "Japanese", fr: "French", de: "German",
    pt: "Portuguese", it: "Italian", zh: "Chinese", ko: "Korean", ar: "Arabic",
  };

  const withBusy = async (segId: string, fn: () => Promise<unknown>) => {
    setBusy((prev) => new Set(prev).add(segId));
    try {
      await fn();
      await onRefresh();
    } finally {
      setBusy((prev) => {
        const next = new Set(prev);
        next.delete(segId);
        return next;
      });
    }
  };

  const saveEn = async (segId: string) => {
    await withBusy(segId, () => updateSegment(segId, enText));
    setEditingEn(null);
  };

  const saveEs = async (transId: string, segId: string) => {
    await withBusy(segId, () => updateTranslation(transId, esText));
    setEditingEs(null);
  };

  const playTTS = (segId: string) => {
    if (playingId === segId && audioRef.current) {
      audioRef.current.pause();
      audioRef.current = null;
      setPlayingId(null);
      return;
    }
    if (audioRef.current) {
      audioRef.current.pause();
    }
    const audio = new Audio(`/api/segments/${segId}/audio`);
    audio.onended = () => setPlayingId(null);
    audio.onerror = () => setPlayingId(null);
    audio.play();
    audioRef.current = audio;
    setPlayingId(segId);
  };

  // Filter out grouped sub-segments — only show primary segments with real translations
  const visibleSegments = segments.filter(
    (s) => !s.translation?.translated_text.startsWith("[part of group")
  );

  const staleCount = visibleSegments.filter(
    (s) => s.translation?.status === "stale" || s.tts?.status === "stale",
  ).length;

  return (
    <div>
      <div className="flex items-center justify-between mb-4">
        <h2 className="text-lg font-semibold">
          Segments ({visibleSegments.length})
          {staleCount > 0 && (
            <Badge variant="warning" className="ml-2">
              {staleCount} stale
            </Badge>
          )}
        </h2>
      </div>

      <div className="border border-border rounded-lg overflow-hidden">
        {/* Header */}
        <div className="grid grid-cols-[80px_1fr_1fr_120px] gap-2 p-3 bg-secondary/50 text-xs font-medium text-muted-foreground uppercase tracking-wider">
          <div>Time</div>
          <div>{langNames[sourceLanguage] ?? sourceLanguage}</div>
          <div>{langNames[targetLanguage] ?? targetLanguage}</div>
          <div className="text-right">Actions</div>
        </div>

        {/* Rows */}
        {visibleSegments.map(({ segment: seg, translation: trans, tts }) => {
          const isBusy = busy.has(seg.id);
          const isTransStale = trans?.status === "stale";
          const isTTSStale = tts?.status === "stale";
          const hasTTS = tts?.media_object_id;

          return (
            <div
              key={seg.id}
              className="grid grid-cols-[80px_1fr_1fr_120px] gap-2 p-3 border-t border-border items-start hover:bg-secondary/20"
            >
              {/* Timestamp + speaker */}
              <div>
                <div className="text-xs text-muted-foreground font-mono">
                  {formatTimestamp(seg.start_sec)}
                </div>
                {seg.speaker && (
                  <div className="text-[10px] text-muted-foreground/60 mt-0.5">
                    {seg.speaker}
                  </div>
                )}
              </div>

              {/* Source language */}
              <div>
                {editingEn === seg.id ? (
                  <div className="space-y-1">
                    <textarea
                      value={enText}
                      onChange={(e) => setEnText(e.target.value)}
                      className="w-full bg-background border border-input rounded px-2 py-1 text-sm resize-none"
                      rows={3}
                      autoFocus
                    />
                    <div className="flex gap-1">
                      <Button size="sm" onClick={() => saveEn(seg.id)} disabled={isBusy}>
                        Save
                      </Button>
                      <Button size="sm" variant="ghost" onClick={() => setEditingEn(null)}>
                        Cancel
                      </Button>
                    </div>
                  </div>
                ) : (
                  <p
                    className="text-sm cursor-pointer hover:bg-secondary/50 rounded px-1 py-0.5 -mx-1"
                    onClick={() => {
                      setEditingEn(seg.id);
                      setEnText(seg.source_text_en);
                    }}
                  >
                    {seg.source_text_en}
                  </p>
                )}
              </div>

              {/* Target language */}
              <div>
                {trans ? (
                  <>
                    {editingEs === seg.id ? (
                      <div className="space-y-1">
                        <textarea
                          value={esText}
                          onChange={(e) => setEsText(e.target.value)}
                          className="w-full bg-background border border-input rounded px-2 py-1 text-sm resize-none"
                          rows={3}
                          autoFocus
                        />
                        <div className="flex gap-1">
                          <Button
                            size="sm"
                            onClick={() => saveEs(trans.id, seg.id)}
                            disabled={isBusy}
                          >
                            Save
                          </Button>
                          <Button size="sm" variant="ghost" onClick={() => setEditingEs(null)}>
                            Cancel
                          </Button>
                        </div>
                      </div>
                    ) : (
                      <div className="flex items-start gap-1">
                        {isTransStale && (
                          <Badge variant="warning" className="mt-0.5 shrink-0">
                            stale
                          </Badge>
                        )}
                        <p
                          className="text-sm cursor-pointer hover:bg-secondary/50 rounded px-1 py-0.5 -mx-1"
                          onClick={() => {
                            setEditingEs(seg.id);
                            setEsText(trans.translated_text);
                          }}
                        >
                          {trans.translated_text}
                        </p>
                      </div>
                    )}
                  </>
                ) : (
                  <span className="text-sm text-muted-foreground italic">Not translated</span>
                )}
              </div>

              {/* Actions */}
              <div className="flex gap-1 justify-end">
                {hasTTS && (
                  <Button
                    size="icon"
                    variant="ghost"
                    title="Play TTS audio"
                    onClick={() => playTTS(seg.id)}
                  >
                    {playingId === seg.id ? (
                      <Square className="w-3.5 h-3.5 text-primary" />
                    ) : (
                      <Play className="w-3.5 h-3.5" />
                    )}
                  </Button>
                )}
                {trans && (
                  <Button
                    size="icon"
                    variant="ghost"
                    title="Regenerate translation"
                    disabled={isBusy}
                    onClick={() => withBusy(seg.id, () => regenerateTranslation(seg.id))}
                  >
                    <RefreshCw className={`w-3.5 h-3.5 ${isTransStale ? "text-yellow-400" : ""}`} />
                  </Button>
                )}
                <Button
                  size="icon"
                  variant="ghost"
                  title="Regenerate TTS"
                  disabled={isBusy}
                  onClick={() => withBusy(seg.id, () => regenerateTTS(seg.id))}
                >
                  <Volume2 className={`w-3.5 h-3.5 ${isTTSStale ? "text-yellow-400" : ""}`} />
                </Button>
              </div>
            </div>
          );
        })}
      </div>
    </div>
  );
}
