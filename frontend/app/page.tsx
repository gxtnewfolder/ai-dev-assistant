"use client";
import { useState, useRef, useEffect } from "react";
import axios from "axios";
import ReactMarkdown from "react-markdown";
import Mermaid from "../components/Mermaid";

const getApiUrl = () => {
  // 1. ลองดึงจาก Environment Variable
  const envUrl = process.env.NEXT_PUBLIC_API_URL;
  
  // 2. ถ้าไม่มี ให้ใช้ Localhost
  let url = envUrl || "http://127.0.0.1:8000";

  // 3. Fix: กรณีได้มาแต่ Domain ไม่มี https (เฉพาะ Cloud Run/Render)
  if (!url.startsWith("http")) {
    url = `https://${url}`;
  }
  
  // ลบ Slash ท้ายสุดออก (ถ้ามี)
  return url.endsWith('/') ? url.slice(0, -1) : url;
};

// --- Configuration ---
const COMMANDS = [
  { cmd: "/refactor", label: "✨ Refactor", desc: "Improve code structure & quality" },
  { cmd: "/test", label: "🧪 Gen Test", desc: "Write unit tests for code" },
  { cmd: "/security", label: "🔒 Security", desc: "Check for vulnerabilities" },
  { cmd: "/explain", label: "🎓 Explain", desc: "Explain code logic simply" },
  { cmd: "/diagram", label: "📊 Diagram", desc: "Generate Mermaid flowchart" },
];

// Types
type Message = {
  role: "user" | "ai";
  content: string;
  context?: string;
  timestamp: number;
};

type ChatSession = {
  id: string;
  title: string;
  messages: Message[];
  repoUrl: string;
};

export default function Home() {
  // --- Sidebar States ---
  const [isSidebarOpen, setIsSidebarOpen] = useState(true);
  const [sessions, setSessions] = useState<ChatSession[]>([]);
  const [activeSessionId, setActiveSessionId] = useState<string | null>(null);

  // --- App States ---
  const [activeTab, setActiveTab] = useState<"story" | "code">("code"); // Default to code for Dev focus
  
  // Jira States
  const [story, setStory] = useState("");
  const [storyResult, setStoryResult] = useState("");
  const [storyLoading, setStoryLoading] = useState(false);

  // Codebase States
  const [repoUrl, setRepoUrl] = useState("");
  const [ingestStatus, setIngestStatus] = useState<"idle" | "loading" | "success" | "error">("idle");
  const [chatInput, setChatInput] = useState("");
  const [chatLoading, setChatLoading] = useState(false);
  
  // Suggestion States
  const [showSuggestions, setShowSuggestions] = useState(false);
  const [filteredCmds, setFilteredCmds] = useState(COMMANDS);

  const chatEndRef = useRef<HTMLDivElement>(null);

  // --- 1. Load History on Mount ---
  useEffect(() => {
    const saved = localStorage.getItem("chat_history");
    if (saved) {
      try {
        const parsed = JSON.parse(saved);
        setSessions(parsed);
        if (parsed.length > 0) {
          // Load latest session
          const latest = parsed[0];
          setActiveSessionId(latest.id);
          setRepoUrl(latest.repoUrl || "");
        } else {
            createNewSession(); // Auto create if empty
        }
      } catch (e) {
        console.error("Failed to parse history", e);
        createNewSession();
      }
    } else {
        createNewSession();
    }
  }, []);

  const saveSessions = (newSessions: ChatSession[]) => {
    setSessions(newSessions);
    localStorage.setItem("chat_history", JSON.stringify(newSessions));
  };

  const createNewSession = () => {
    const newSession: ChatSession = {
      id: "sess_" + Date.now().toString(),
      title: "New Chat",
      messages: [],
      repoUrl: ""
    };
    const updated = [newSession, ...sessions];
    saveSessions(updated);
    loadSession(newSession);
  };

  const loadSession = (session: ChatSession) => {
    setActiveSessionId(session.id);
    setRepoUrl(session.repoUrl || "");
    // Scroll to bottom after loading
    setTimeout(() => chatEndRef.current?.scrollIntoView(), 100);
  };

  const deleteSession = (e: React.MouseEvent, sessionId: string) => {
    e.stopPropagation();
    if (!confirm("Are you sure you want to delete this chat?")) return;
    
    const updated = sessions.filter(s => s.id !== sessionId);
    saveSessions(updated);
    
    if (activeSessionId === sessionId) {
      if (updated.length > 0) loadSession(updated[0]);
      else { 
          createNewSession(); 
      }
    }
  };

  const activeMessages = sessions.find(s => s.id === activeSessionId)?.messages || [];

  // --- Functions ---
  const handleStorySubmit = async () => {
    if (!story) return;
    setStoryLoading(true);
    try {
      const res = await axios.post(`${getApiUrl()}/analyze-story`, { story_text: story });
      setStoryResult(res.data.markdown_result);
    } catch (error) {
      alert("Backend connection failed.");
      console.error(error);
    } finally {
      setStoryLoading(false);
    }
  };

  const handleIngest = async () => {
    if (!repoUrl) return;
    
    // ✅ 1. Ensure Session Exists (สร้าง Session ใหม่ถ้ายังไม่มี)
    let currentSessionId = activeSessionId;
    let currentSessions = [...sessions];
    
    if (!currentSessionId) {
        const newSession: ChatSession = {
            id: "sess_" + Date.now().toString(),
            title: "Repo Chat",
            messages: [],
            repoUrl: repoUrl
        };
        currentSessionId = newSession.id;
        currentSessions = [newSession, ...sessions];
        setActiveSessionId(currentSessionId);
    }

    setIngestStatus("loading");
    try {
      // ✅ 2. Send session_id to Backend
      await axios.post(`${getApiUrl()}/ingest`, { 
          repo_url: repoUrl,
          session_id: currentSessionId // 🔥 Critical fix
      });
      
      setIngestStatus("success");
      
      // Update local state
      const updatedSessions = currentSessions.map(s => 
        s.id === currentSessionId ? { 
            ...s, 
            repoUrl: repoUrl,
            messages: [...s.messages, { role: "ai", content: "✅ Repo ingested successfully! I'm ready to answer questions.", timestamp: Date.now() }] as Message[]
        } : s
      );
      saveSessions(updatedSessions);

      setTimeout(() => setIngestStatus("idle"), 3000);
    } catch (error) {
      console.error(error);
      setIngestStatus("error");
      alert("Ingest failed. Check backend logs.");
    }
  };

  const handleChat = async () => {
    if (!chatInput) return;
    setShowSuggestions(false);

    // 1. Prepare Session
    let currentSessionId = activeSessionId;
    let currentSessions = [...sessions];
    
    if (!currentSessionId) {
      const newSession: ChatSession = {
        id: "sess_" + Date.now().toString(),
        title: "New Chat",
        messages: [],
        repoUrl: repoUrl
      };
      currentSessionId = newSession.id;
      currentSessions = [newSession, ...sessions];
      setActiveSessionId(currentSessionId);
    }

    const userMsg: Message = { role: "user", content: chatInput, timestamp: Date.now() };
    
    // 2. Optimistic Update (Show user message immediately)
    const updatedWithUser = currentSessions.map(s => {
      if (s.id === currentSessionId) {
        const newTitle = s.messages.length === 0 ? chatInput.slice(0, 30) + "..." : s.title;
        return { ...s, title: newTitle, messages: [...s.messages, userMsg], repoUrl: repoUrl || s.repoUrl };
      }
      return s;
    });
    
    saveSessions(updatedWithUser);
    setChatInput("");
    setChatLoading(true);

    try {
      // ✅ 3. Send session_id to Backend
      const res = await axios.post(`${getApiUrl()}/ask-codebase`, { 
          question: userMsg.content,
          session_id: currentSessionId // 🔥 Critical fix
      });

      const aiMsg: Message = { 
        role: "ai", 
        content: res.data.answer,
        context: res.data.context_used || (res.data.sources ? `Sources: ${res.data.sources.join(", ")}` : undefined),
        timestamp: Date.now()
      };

      const finalSessions = updatedWithUser.map(s => 
        s.id === currentSessionId ? { ...s, messages: [...s.messages, aiMsg] } : s
      );
      saveSessions(finalSessions);

    } catch (error) {
       console.error(error);
       const errorMsg: Message = { role: "ai", content: "❌ Error connecting to AI. Please try again.", timestamp: Date.now() };
       const errorSessions = updatedWithUser.map(s => s.id === currentSessionId ? { ...s, messages: [...s.messages, errorMsg] } : s);
       saveSessions(errorSessions);
    } finally {
      setChatLoading(false);
    }
  };

  // --- Input Change Handler ---
  const handleInputChange = (e: React.ChangeEvent<HTMLInputElement>) => {
    const val = e.target.value;
    setChatInput(val);

    if (val.startsWith("/")) {
      const searchTerm = val.toLowerCase();
      const matches = COMMANDS.filter(c => c.cmd.startsWith(searchTerm));
      setFilteredCmds(matches);
      setShowSuggestions(matches.length > 0);
    } else {
      setShowSuggestions(false);
    }
  };

  const selectCommand = (cmd: string) => {
    setChatInput(cmd + " ");
    setShowSuggestions(false);
  };
  
  useEffect(() => {
    chatEndRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [activeMessages, chatLoading]);

  return (
    <div className="flex h-screen bg-slate-50 font-sans text-slate-800 overflow-hidden">
      
      {/* Sidebar */}
      <aside className={`bg-white border-r border-slate-200 flex flex-col transition-all duration-300 ${isSidebarOpen ? "w-72" : "w-0 -ml-4 opacity-0"} overflow-hidden shadow-xl z-20`}>
        <div className="p-4 border-b border-slate-100 flex items-center justify-between bg-slate-50/50">
          <h2 className="font-bold text-slate-700 flex items-center gap-2">🗂️ History</h2>
          <button onClick={createNewSession} className="p-2 bg-indigo-600 text-white rounded-lg hover:bg-indigo-700 transition shadow-sm text-xs font-bold flex items-center gap-1"><span>+</span> New</button>
        </div>
        <div className="flex-1 overflow-y-auto p-2 space-y-1">
            {sessions.length === 0 && <div className="text-center text-slate-400 text-sm mt-10 p-4">No history yet.</div>}
            {sessions.map(s => (
                <div key={s.id} onClick={() => loadSession(s)} className={`group w-full flex items-center justify-between p-3 rounded-xl text-sm transition-all cursor-pointer border border-transparent ${activeSessionId === s.id ? "bg-indigo-50 border-indigo-100 text-indigo-700 shadow-sm font-medium" : "hover:bg-slate-100 text-slate-600"}`}>
                    <span className="truncate flex-1 pr-2">{s.title}</span>
                    <button onClick={(e) => deleteSession(e, s.id)} className={`p-1.5 rounded-lg text-slate-400 hover:text-red-500 hover:bg-red-50 transition-opacity opacity-0 group-hover:opacity-100 ${activeSessionId === s.id ? "opacity-100" : ""}`} title="Delete chat">🗑️</button>
                </div>
            ))}
        </div>
      </aside>

      {/* Main Content */}
      <div className="flex-1 flex flex-col h-full w-full bg-slate-50 relative">
        <nav className="bg-white/90 backdrop-blur-md border-b border-slate-200 px-4 md:px-6 py-3 flex items-center justify-between z-10 sticky top-0">
          <div className="flex items-center gap-3">
            <button onClick={() => setIsSidebarOpen(!isSidebarOpen)} className="p-2 text-slate-500 hover:bg-slate-100 rounded-lg transition">{isSidebarOpen ? "◀" : "▶"}</button>
            <div className="flex items-center gap-2">
                <div className="w-8 h-8 bg-gradient-to-br from-indigo-500 to-purple-600 rounded-lg flex items-center justify-center text-white font-bold shadow-md shadow-indigo-200">AI</div>
                <h1 className="font-bold text-slate-700 hidden md:block tracking-tight">Dev<span className="text-indigo-600">Assistant</span></h1>
            </div>
          </div>
          <div className="bg-slate-100 p-1 rounded-xl flex text-sm font-medium shadow-inner">
            <button onClick={() => setActiveTab("story")} className={`px-4 py-1.5 rounded-lg transition-all duration-200 ${activeTab === "story" ? "bg-white shadow-sm text-indigo-600" : "text-slate-500 hover:text-slate-600"}`}>📝 Jira</button>
            <button onClick={() => setActiveTab("code")} className={`px-4 py-1.5 rounded-lg transition-all duration-200 ${activeTab === "code" ? "bg-white shadow-sm text-indigo-600" : "text-slate-500 hover:text-slate-600"}`}>🧠 Codebase</button>
          </div>
        </nav>

        <main className="flex-1 overflow-hidden p-4 md:p-6 relative max-w-7xl mx-auto w-full">
            {activeTab === "story" && (
                 <div className="grid grid-cols-1 lg:grid-cols-2 gap-6 h-full pb-2">
                    <div className="flex flex-col gap-4 h-full">
                        <div className="bg-white p-4 rounded-2xl shadow-sm border border-slate-200 flex-1 flex flex-col">
                             <h3 className="text-xs font-bold text-slate-400 uppercase tracking-wider mb-2">Input Story</h3>
                             <textarea className="flex-1 w-full p-2 bg-slate-50 border-0 rounded-xl resize-none focus:ring-0 text-slate-700 font-mono text-sm leading-relaxed" placeholder="As a user, I want to..." value={story} onChange={(e) => setStory(e.target.value)} />
                        </div>
                        <button onClick={handleStorySubmit} disabled={storyLoading} className="py-4 bg-indigo-600 text-white rounded-xl font-bold shadow-lg hover:bg-indigo-700 disabled:opacity-50 transition-all active:scale-95">{storyLoading ? "Analyzing..." : "Generate Specs ⚡️"}</button>
                    </div>
                    <div className="bg-white p-6 rounded-2xl border border-slate-200 shadow-sm overflow-y-auto h-full custom-scrollbar">
                        <div className="prose prose-sm prose-slate max-w-none prose-headings:text-indigo-900 prose-pre:bg-slate-800 prose-pre:text-slate-100"><ReactMarkdown>{storyResult}</ReactMarkdown></div>
                    </div>
                 </div>
            )}

            {activeTab === "code" && (
                <div className="flex flex-col h-full pb-2 gap-4">
                    <div className="bg-white p-2 rounded-2xl shadow-sm border border-slate-200 flex flex-col md:flex-row gap-2">
                        <input value={repoUrl} onChange={(e) => setRepoUrl(e.target.value)} placeholder="🔗 GitHub Repo URL (e.g. https://github.com/fastapi/fastapi)" className="flex-1 px-4 py-2 bg-transparent outline-none text-slate-700 placeholder-slate-400" />
                        <button onClick={handleIngest} disabled={ingestStatus === "loading"} className={`px-6 py-2 rounded-xl font-bold text-white transition-all shadow-md ${ingestStatus === "success" ? "bg-emerald-500 shadow-emerald-200" : "bg-indigo-600 shadow-indigo-200"}`}>{ingestStatus === "loading" ? "⏳" : ingestStatus === "success" ? "✓ Ready" : "📥 Load"}</button>
                    </div>

                    <div className="flex-1 bg-white rounded-2xl border border-slate-200 shadow-sm flex flex-col overflow-hidden relative">
                        <div className="flex-1 overflow-y-auto p-4 space-y-6 bg-slate-50/50" onClick={() => setShowSuggestions(false)}>
                            {(!activeSessionId || activeMessages.length === 0) && <div className="flex flex-col items-center justify-center h-full text-slate-400 gap-4 opacity-60"><div className="text-6xl">🤖</div><p>Load a repo and start chatting!</p></div>}
                            {activeMessages.map((msg, idx) => (
                                <div key={idx} className={`flex ${msg.role === "user" ? "justify-end" : "justify-start"} animate-in fade-in slide-in-from-bottom-2`}>
                                    <div className={`max-w-[85%] rounded-2xl p-4 shadow-sm ${msg.role === "user" ? "bg-indigo-600 text-white rounded-br-none" : "bg-white border text-slate-700 rounded-bl-none"}`}>
                                        <div className={`prose prose-sm max-w-none ${msg.role === "user" ? "prose-invert" : "prose-slate"}`}>
                                            <ReactMarkdown components={{ 
                                                code({ node, inline, className, children, ...props }: any) { 
                                                    const match = /language-(\w+)/.exec(className || ""); 
                                                    const isMermaid = match && match[1] === "mermaid"; 
                                                    if (!inline && isMermaid) { 
                                                        return <Mermaid chart={String(children).replace(/\n$/, "")} />; 
                                                    } 
                                                    return !inline && match ? ( <pre className={className} {...props}><code className={className} {...props}>{children}</code></pre> ) : ( <code className={className} {...props}>{children}</code> ); 
                                                }, 
                                            }}>
                                                {msg.content}
                                            </ReactMarkdown>
                                        </div>
                                        {msg.context && (
                                            <details className="mt-2 pt-2 border-t border-white/20">
                                                <summary className="text-xs cursor-pointer opacity-70 hover:opacity-100 flex items-center gap-1">📚 Referenced Code / Context</summary>
                                                <pre className="text-[10px] mt-1 p-2 bg-black/10 rounded overflow-x-auto whitespace-pre-wrap font-mono">{msg.context}</pre>
                                            </details>
                                        )}
                                    </div>
                                </div>
                            ))}
                            {chatLoading && <div className="flex justify-start"><div className="bg-white border px-4 py-2 rounded-2xl rounded-bl-none shadow-sm flex gap-1 items-center"><span className="w-2 h-2 bg-indigo-400 rounded-full animate-bounce"></span><span className="w-2 h-2 bg-indigo-400 rounded-full animate-bounce delay-100"></span><span className="w-2 h-2 bg-indigo-400 rounded-full animate-bounce delay-200"></span></div></div>}
                            <div ref={chatEndRef} />
                        </div>
                        
                        <div className="p-4 bg-white border-t border-slate-100 relative">
                            {/* 🔥 Suggestion Box */}
                            {showSuggestions && (
                              <div className="absolute bottom-full left-4 mb-2 bg-white border border-slate-200 rounded-xl shadow-xl w-64 overflow-hidden animate-in slide-in-from-bottom-2 z-50">
                                <div className="bg-slate-50 px-3 py-2 text-xs font-bold text-slate-400 uppercase tracking-wider">Commands</div>
                                {filteredCmds.map((c) => (
                                  <button
                                    key={c.cmd}
                                    onClick={() => selectCommand(c.cmd)}
                                    className="w-full text-left px-4 py-3 hover:bg-indigo-50 hover:text-indigo-700 transition flex flex-col gap-0.5 border-b border-slate-50 last:border-0"
                                  >
                                    <span className="font-bold text-sm">{c.label} <span className="text-slate-400 font-mono text-xs font-normal">({c.cmd})</span></span>
                                    <span className="text-xs text-slate-500">{c.desc}</span>
                                  </button>
                                ))}
                                {filteredCmds.length === 0 && <div className="p-4 text-center text-sm text-slate-400">No matching commands</div>}
                              </div>
                            )}

                            {/* Command Hints (Pill) */}
                            <div className="flex gap-2 mb-2 overflow-x-auto pb-1 px-1">
                                {COMMANDS.map((item) => (
                                    <button key={item.cmd} onClick={() => selectCommand(item.cmd)} className="text-xs px-3 py-1.5 rounded-full border border-slate-200 bg-slate-50 text-slate-600 font-medium transition-all hover:bg-white hover:border-indigo-300 hover:text-indigo-600 hover:shadow-sm whitespace-nowrap">
                                        {item.label}
                                    </button>
                                ))}
                            </div>

                            <div className="flex gap-2 relative">
                                <input 
                                    value={chatInput}
                                    onChange={handleInputChange}
                                    onKeyDown={(e) => {
                                        if (e.key === "Enter") handleChat();
                                        if (e.key === "Escape") setShowSuggestions(false);
                                    }}
                                    placeholder="Type / to see commands..."
                                    className="flex-1 pl-4 pr-12 py-3 bg-slate-100 border-none rounded-xl focus:ring-2 focus:ring-indigo-500 focus:bg-white transition-all outline-none"
                                />
                                <button onClick={handleChat} disabled={!chatInput || chatLoading} className="absolute right-2 top-2 bottom-2 aspect-square bg-indigo-600 text-white rounded-lg hover:bg-indigo-700 disabled:opacity-50 transition-all flex items-center justify-center shadow-sm">➤</button>
                            </div>
                        </div>
                    </div>
                </div>
            )}
        </main>
      </div>
    </div>
  );
}