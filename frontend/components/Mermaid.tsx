"use client";
import React, { useEffect, useRef, useState } from "react";
import mermaid from "mermaid";

const initMermaid = () => {
  try {
    mermaid.initialize({
      startOnLoad: false,
      theme: "default",
      securityLevel: "loose",
      fontFamily: "ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, monospace",
    });
  } catch (e) {
    console.error("Mermaid init failed", e);
  }
};

const Mermaid = ({ chart }: { chart: string }) => {
  const ref = useRef<HTMLDivElement>(null);
  const [svg, setSvg] = useState("");
  const [status, setStatus] = useState<"loading" | "error" | "success" | "empty">("loading");
  
  // States for Zoom
  const [isZoomed, setIsZoomed] = useState(false);
  const [zoomLevel, setZoomLevel] = useState(1);

  useEffect(() => {
    if (!chart || chart.trim().length === 0) {
      setStatus("empty");
      return;
    }

    setStatus("loading");
    initMermaid();

    const renderChart = async () => {
      try {
        const id = `mermaid-${Math.random().toString(36).substr(2, 9)}`;

        // 🔥 CLEANUP LOGIC
        let cleanChart = chart
          .replace(/&gt;/g, ">")
          .replace(/&lt;/g, "<")
          .replace(/&quot;/g, '"')
          .replace(/```mermaid/g, "")
          .replace(/```/g, "")
          .replace(/^mermaid\s*/i, "")
          .replace(/graph TD/g, "flowchart TD")
          .replace(/;/g, "")
          .trim();

        // Fix Edge Labels
        cleanChart = cleanChart.replace(/ -- (.*?) -->/g, (match, label) => {
           const safeLabel = label.replace(/"/g, "'");
           return ` -- "${safeLabel}" -->`;
        });

        const { svg } = await mermaid.render(id, cleanChart);
        setSvg(svg);
        setStatus("success");
      } catch (err) {
        console.error("Mermaid Render Error:", err);
        setStatus("error");
      }
    };

    renderChart();
  }, [chart]);

  // Reset Zoom when closing modal
  useEffect(() => {
    if (!isZoomed) setZoomLevel(1);
  }, [isZoomed]);

  // Handle ESC key
  useEffect(() => {
    const handleEsc = (e: KeyboardEvent) => {
      if (e.key === "Escape") setIsZoomed(false);
    };
    window.addEventListener("keydown", handleEsc);
    return () => window.removeEventListener("keydown", handleEsc);
  }, []);

  // Zoom Helpers
  const handleZoomIn = () => setZoomLevel(prev => Math.min(prev + 0.25, 5)); // Max 5x
  const handleZoomOut = () => setZoomLevel(prev => Math.max(prev - 0.25, 0.5)); // Min 0.5x
  const handleResetZoom = () => setZoomLevel(1);

  if (status === "empty") return null;

  if (status === "error") {
    return (
      <div className="my-4 p-4 bg-red-50 border border-red-200 rounded-lg text-left">
        <p className="text-red-600 font-bold text-xs mb-2">⚠️ Cannot render diagram:</p>
        <pre className="text-xs text-slate-600 overflow-x-auto whitespace-pre-wrap font-mono bg-white p-2 rounded border">
          {chart}
        </pre>
      </div>
    );
  }

  if (status === "loading") {
    return (
      <div className="animate-pulse flex flex-col items-center justify-center space-y-2 my-8 p-6 border rounded-lg bg-slate-50">
        <div className="h-2 bg-slate-200 rounded w-1/3"></div>
        <div className="h-32 bg-slate-200 rounded w-full"></div>
      </div>
    );
  }

  return (
    <>
      {/* 1. Normal View (Thumbnail) */}
      <div 
        className="mermaid-chart relative group cursor-zoom-in overflow-hidden bg-white p-6 rounded-xl shadow-sm border border-slate-100 flex justify-center my-4 transition-all hover:shadow-md hover:border-indigo-200"
        ref={ref}
        onClick={() => setIsZoomed(true)}
      >
        <div className="absolute top-2 right-2 opacity-0 group-hover:opacity-100 transition-opacity bg-slate-800 text-white text-[10px] px-2 py-1 rounded shadow-sm pointer-events-none z-10">
          Click to Zoom 🔍
        </div>
        <div dangerouslySetInnerHTML={{ __html: svg }} />
      </div>

      {/* 2. Zoomed Modal (Overlay) */}
      {isZoomed && (
        <div 
          className="fixed inset-0 z-[9999] flex items-center justify-center bg-slate-900/90 backdrop-blur-sm animate-in fade-in duration-200"
          onClick={() => setIsZoomed(false)}
        >
          {/* Zoom Controls Bar */}
          <div 
            className="fixed bottom-8 left-1/2 transform -translate-x-1/2 bg-white/10 backdrop-blur-md border border-white/20 text-white px-4 py-2 rounded-full flex items-center gap-4 shadow-2xl z-[10000]"
            onClick={(e) => e.stopPropagation()}
          >
            <button onClick={handleZoomOut} className="hover:text-indigo-300 w-8 h-8 flex items-center justify-center rounded-full hover:bg-white/10 text-xl font-bold transition">－</button>
            <span className="font-mono text-sm min-w-[3rem] text-center">{Math.round(zoomLevel * 100)}%</span>
            <button onClick={handleZoomIn} className="hover:text-indigo-300 w-8 h-8 flex items-center justify-center rounded-full hover:bg-white/10 text-xl font-bold transition">＋</button>
            <div className="w-[1px] h-4 bg-white/20 mx-1"></div>
            <button onClick={handleResetZoom} className="text-xs hover:text-indigo-300 transition">Reset</button>
            <button onClick={() => setIsZoomed(false)} className="text-xs hover:text-red-400 ml-2 transition">✕ Close</button>
          </div>

          <div 
            className="relative w-full h-full overflow-auto flex items-center justify-center p-8"
            onClick={() => setIsZoomed(false)}
          >
            {/* Draggable/Scalable Container */}
            <div 
              className="transition-transform duration-200 ease-out origin-center"
              style={{ transform: `scale(${zoomLevel})` }}
              onClick={(e) => e.stopPropagation()}
              onWheel={(e) => {
                if (e.ctrlKey) {
                  e.preventDefault();
                  if (e.deltaY < 0) handleZoomIn();
                  else handleZoomOut();
                }
              }}
            >
               <div 
                 className="bg-white p-8 rounded-lg shadow-2xl min-w-[300px]"
                 dangerouslySetInnerHTML={{ __html: svg }} 
               />
            </div>
          </div>
        </div>
      )}
    </>
  );
};

export default Mermaid;