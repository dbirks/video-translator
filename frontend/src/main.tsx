import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import { BrowserRouter, Routes, Route } from "react-router";
import "./index.css";
import LectureList from "@/pages/LectureList";
import LectureDetail from "@/pages/LectureDetail";

createRoot(document.getElementById("root")!).render(
  <StrictMode>
    <BrowserRouter>
      <div className="min-h-screen">
        <header className="border-b border-border px-6 py-3">
          <a href="/" className="text-lg font-semibold hover:text-muted-foreground transition-colors">
            Video Translator
          </a>
        </header>
        <Routes>
          <Route path="/" element={<LectureList />} />
          <Route path="/lectures/:id" element={<LectureDetail />} />
        </Routes>
      </div>
    </BrowserRouter>
  </StrictMode>,
);
