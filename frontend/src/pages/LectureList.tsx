import { useEffect, useState } from "react";
import { useNavigate } from "react-router";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { listLectures, createLecture, type Lecture } from "@/lib/api";
import { Plus } from "lucide-react";

const statusVariant = (s: string) => {
  if (s === "exported") return "success" as const;
  if (s === "draft") return "secondary" as const;
  if (s === "failed") return "destructive" as const;
  return "outline" as const;
};

export default function LectureList() {
  const [lectures, setLectures] = useState<Lecture[]>([]);
  const [loading, setLoading] = useState(true);
  const navigate = useNavigate();

  useEffect(() => {
    listLectures()
      .then(setLectures)
      .finally(() => setLoading(false));
  }, []);

  const handleCreate = async () => {
    const title = prompt("Lecture title:");
    if (!title) return;
    const lecture = await createLecture(title);
    navigate(`/lectures/${lecture.id}`);
  };

  return (
    <div className="max-w-4xl mx-auto p-6">
      <div className="flex items-center justify-between mb-8">
        <h1 className="text-2xl font-bold">Lectures</h1>
        <Button onClick={handleCreate}>
          <Plus className="w-4 h-4" />
          New Lecture
        </Button>
      </div>

      {loading ? (
        <p className="text-muted-foreground">Loading...</p>
      ) : lectures.length === 0 ? (
        <div className="text-center py-16 text-muted-foreground">
          <p className="text-lg mb-2">No lectures yet</p>
          <p>Create one to get started</p>
        </div>
      ) : (
        <div className="space-y-3">
          {lectures.map((l) => (
            <button
              key={l.id}
              onClick={() => navigate(`/lectures/${l.id}`)}
              className="w-full text-left p-4 rounded-lg border border-border hover:bg-secondary/50 transition-colors cursor-pointer"
            >
              <div className="flex items-center justify-between">
                <span className="font-medium">{l.title}</span>
                <Badge variant={statusVariant(l.status)}>{l.status}</Badge>
              </div>
              <div className="text-sm text-muted-foreground mt-1">
                {l.duration_seconds
                  ? `${Math.round(l.duration_seconds / 60)} min`
                  : "No video uploaded"}
                {" · "}
                {new Date(l.created_at).toLocaleDateString()}
              </div>
            </button>
          ))}
        </div>
      )}
    </div>
  );
}
