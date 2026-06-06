"use client";

import React, { useState, useEffect, useRef } from "react";
import { gsap } from "gsap";

// Dynamic imports of Tauri APIs to prevent Next.js SSR build failures
let invoke: <T = any>(cmd: string, args?: any) => Promise<T> = async () => ({} as any);
let listen: <T = any>(event: string, handler: (e: { payload: T }) => void) => Promise<() => void> = async () => (() => {});

if (typeof window !== "undefined") {
  try {
    invoke = require("@tauri-apps/api/tauri").invoke;
    listen = require("@tauri-apps/api/event").listen;
  } catch (err) {
    console.warn("Tauri API not available in browser context.", err);
  }
}

interface Metrics {
  total_evaluated: number;
  total_followed: number;
  total_starred: number;
  purge_queue_size: number;
}

export default function Dashboard() {
  const [botRunning, setBotRunning] = useState(false);
  const [logs, setLogs] = useState<string[]>([]);
  const [currentTab, setCurrentTab] = useState<"home" | "console" | "strategy" | "purge">("home");
  
  const [metrics, setMetrics] = useState<Metrics>({
    total_evaluated: 0,
    total_followed: 0,
    total_starred: 0,
    purge_queue_size: 0,
  });

  // Settings state
  const [envContent, setEnvContent] = useState("");
  const [subThreshold, setSubThreshold] = useState("14.0");
  const [starThreshold, setStarThreshold] = useState("16.0");
  const [language, setLanguage] = useState("Python");
  const [fetchCount, setFetchCount] = useState("5");

  // Whitelist state
  const [whitelistContent, setWhitelistContent] = useState("");
  const [whitelistArray, setWhitelistArray] = useState<string[]>([]);
  const [newWhitelistUser, setNewWhitelistUser] = useState("");

  const consoleEndRef = useRef<HTMLDivElement>(null);
  const mainContainerRef = useRef<HTMLDivElement>(null);
  const tabContentRef = useRef<HTMLDivElement>(null);

  // Stats Card Refs for GSAP Counter animations
  const evalRef = useRef<HTMLDivElement>(null);
  const followRef = useRef<HTMLDivElement>(null);
  const starRef = useRef<HTMLDivElement>(null);
  const purgeRef = useRef<HTMLDivElement>(null);

  // Setup GSAP entry animations
  useEffect(() => {
    if (mainContainerRef.current) {
      gsap.fromTo(
        mainContainerRef.current,
        { opacity: 0, y: 15 },
        { opacity: 1, y: 0, duration: 0.8, ease: "power2.out" }
      );
    }
  }, []);

  // Animate tab transitions
  useEffect(() => {
    if (tabContentRef.current) {
      gsap.fromTo(
        tabContentRef.current,
        { opacity: 0, y: 5 },
        { opacity: 1, y: 0, duration: 0.4, ease: "power1.out" }
      );
    }
  }, [currentTab]);

  // Hook to listen to logs emitted by Tauri Rust backend
  useEffect(() => {
    let unlistenFn: (() => void) | null = null;

    async function initListener() {
      try {
        const u = await listen<{ message: string }>("bot-log", (event) => {
          setLogs((prev) => {
            const updated = [...prev, event.payload.message];
            // Keep last 400 logs to prevent memory bloat
            return updated.slice(-400);
          });
        });
        unlistenFn = u;
      } catch (err) {
        console.error("Failed to setup Tauri bot-log listener:", err);
      }
    }

    initListener();
    return () => {
      if (unlistenFn) {
        unlistenFn();
      }
    };
  }, []);

  // Poll DB metrics every 2 seconds
  useEffect(() => {
    async function updateMetrics() {
      try {
        const res = await invoke<Metrics>("get_metrics");
        setMetrics(res);
      } catch (err) {
        console.error("Failed to fetch metrics:", err);
      }
    }
    
    updateMetrics();
    const interval = setInterval(updateMetrics, 2000);
    return () => clearInterval(interval);
  }, []);

  // Load configs on mount
  useEffect(() => {
    async function loadConfigs() {
      try {
        const env = await invoke<string>("read_env");
        setEnvContent(env);
        parseEnvFields(env);

        const wl = await invoke<string>("read_whitelist");
        setWhitelistContent(wl);
        parseWhitelistFields(wl);
      } catch (err) {
        console.error("Failed to load configs from backend:", err);
      }
    }
    loadConfigs();
  }, []);

  // Auto-scroll terminal view
  useEffect(() => {
    if (consoleEndRef.current) {
      consoleEndRef.current.scrollIntoView({ behavior: "smooth" });
    }
  }, [logs]);

  // GSAP Counter Helpers
  const animateCounter = (ref: React.RefObject<HTMLDivElement>, value: number) => {
    if (!ref.current) return;
    const targetObj = { val: 0 };
    // Get current text or default to 0
    const currentVal = parseInt(ref.current.innerText) || 0;
    targetObj.val = currentVal;
    
    gsap.to(targetObj, {
      val: value,
      duration: 1.2,
      ease: "power2.out",
      onUpdate: () => {
        if (ref.current) {
          ref.current.innerText = Math.floor(targetObj.val).toString();
        }
      },
    });
  };

  useEffect(() => {
    animateCounter(evalRef, metrics.total_evaluated);
  }, [metrics.total_evaluated]);

  useEffect(() => {
    animateCounter(followRef, metrics.total_followed);
  }, [metrics.total_followed]);

  useEffect(() => {
    animateCounter(starRef, metrics.total_starred);
  }, [metrics.total_starred]);

  useEffect(() => {
    animateCounter(purgeRef, metrics.purge_queue_size);
  }, [metrics.purge_queue_size]);

  // Configuration parsing logic
  const parseEnvFields = (content: string) => {
    const lines = content.split("\n");
    lines.forEach((line) => {
      const parts = line.split("=");
      if (parts.length >= 2) {
        const key = parts[0].trim();
        const value = parts.slice(1).join("=").trim().replace(/'/g, "").replace(/"/g, "");
        if (key === "SUBSCRIBE_THRESHOLD") setSubThreshold(value);
        if (key === "STAR_THRESHOLD") setStarThreshold(value);
        if (key === "LANGUAGE") setLanguage(value);
        if (key === "FETCH_COUNT") setFetchCount(value);
      }
    });
  };

  const parseWhitelistFields = (content: string) => {
    const list = content
      .split("\n")
      .map((line) => line.trim())
      .filter((line) => line && !line.startsWith("#"));
    setWhitelistArray(list);
  };

  const handleSaveSettings = async () => {
    // Reconstruct env content based on current state or overwrite values
    let lines = envContent.split("\n");
    const updatedLines = lines.map((line) => {
      const parts = line.split("=");
      if (parts.length >= 2) {
        const key = parts[0].trim();
        if (key === "SUBSCRIBE_THRESHOLD") return `SUBSCRIBE_THRESHOLD=${subThreshold}`;
        if (key === "STAR_THRESHOLD") return `STAR_THRESHOLD=${starThreshold}`;
        if (key === "LANGUAGE") return `LANGUAGE=${language}`;
        if (key === "FETCH_COUNT") return `FETCH_COUNT=${fetchCount}`;
      }
      return line;
    });
    
    const finalContent = updatedLines.join("\n");
    try {
      await invoke("save_env", { content: finalContent });
      setEnvContent(finalContent);
      alert("Settings saved successfully!");
    } catch (err) {
      alert(`Error saving settings: ${err}`);
    }
  };

  const handleAddWhitelist = async () => {
    if (!newWhitelistUser.trim()) return;
    const user = newWhitelistUser.trim().replace("@", "");
    if (whitelistArray.map(u => u.toLowerCase()).includes(user.toLowerCase())) {
      setNewWhitelistUser("");
      return;
    }
    
    const updatedArray = [...whitelistArray, user];
    setWhitelistArray(updatedArray);
    setNewWhitelistUser("");
    
    await saveWhitelistToDisk(updatedArray);
  };

  const handleRemoveWhitelist = async (userToRemove: string) => {
    const updatedArray = whitelistArray.filter((u) => u !== userToRemove);
    setWhitelistArray(updatedArray);
    await saveWhitelistToDisk(updatedArray);
  };

  const saveWhitelistToDisk = async (arr: string[]) => {
    const content = `# Whitelisted GitHub users protected from purge\n` + arr.join("\n");
    try {
      await invoke("save_whitelist", { content });
      setWhitelistContent(content);
    } catch (err) {
      console.error("Failed to save whitelist:", err);
    }
  };

  const toggleBot = async () => {
    if (botRunning) {
      try {
        await invoke("stop_bot");
        setBotRunning(false);
        setLogs((prev) => [...prev, "[SYSTEM] Bot stopped by user."]);
      } catch (err) {
        alert(`Error stopping bot: ${err}`);
      }
    } else {
      try {
        setLogs((prev) => [...prev, "[SYSTEM] Spawning async bot process..."]);
        await invoke("start_bot");
        setBotRunning(true);
      } catch (err) {
        alert(`Error starting bot: ${err}`);
      }
    }
  };

  const clearLogs = () => {
    setLogs([]);
  };

  return (
    <div ref={mainContainerRef} className="flex h-screen w-screen bg-black text-white font-sans selection:bg-white selection:text-black">
      {/* SIDEBAR NAVIGATION */}
      <aside className="w-80 border-r border-neutral-900 flex flex-col justify-between p-8">
        <div>
          {/* Logo / Header */}
          <div className="mb-12">
            <h1 className="text-xl font-bold tracking-tight uppercase">Async Growth Bot</h1>
            <p className="text-xs text-neutral-500 mt-1">Monochrome Control Desk</p>
          </div>

          {/* Navigation Links */}
          <nav className="space-y-4">
            <button
              onClick={() => setCurrentTab("home")}
              className={`w-full text-left px-4 py-3 rounded-none text-sm transition-all duration-200 border ${
                currentTab === "home"
                  ? "bg-white text-black border-white"
                  : "bg-transparent text-neutral-400 border-transparent hover:text-white"
              }`}
            >
              Control Desk
            </button>
            <button
              onClick={() => setCurrentTab("console")}
              className={`w-full text-left px-4 py-3 rounded-none text-sm transition-all duration-200 border ${
                currentTab === "console"
                  ? "bg-white text-black border-white"
                  : "bg-transparent text-neutral-400 border-transparent hover:text-white"
              }`}
            >
              Terminal Console
            </button>
            <button
              onClick={() => setCurrentTab("strategy")}
              className={`w-full text-left px-4 py-3 rounded-none text-sm transition-all duration-200 border ${
                currentTab === "strategy"
                  ? "bg-white text-black border-white"
                  : "bg-transparent text-neutral-400 border-transparent hover:text-white"
              }`}
            >
              Strategy Config
            </button>
            <button
              onClick={() => setCurrentTab("purge")}
              className={`w-full text-left px-4 py-3 rounded-none text-sm transition-all duration-200 border ${
                currentTab === "purge"
                  ? "bg-white text-black border-white"
                  : "bg-transparent text-neutral-400 border-transparent hover:text-white"
              }`}
            >
              Purge & Whitelist
            </button>
          </nav>
        </div>

        {/* Bot Runner Status */}
        <div className="border border-neutral-900 p-6 space-y-4">
          <div className="flex justify-between items-center">
            <span className="text-xs tracking-wider uppercase text-neutral-400">Purger Engine</span>
            <span className={`inline-block h-2 w-2 rounded-full ${botRunning ? "bg-white shadow-[0_0_10px_#fff]" : "bg-neutral-800"}`} />
          </div>
          <button
            onClick={toggleBot}
            className={`w-full py-3 text-xs tracking-widest uppercase font-bold border transition-all duration-300 ${
              botRunning
                ? "bg-neutral-900 border-neutral-800 text-white hover:bg-white hover:text-black hover:border-white"
                : "bg-white border-white text-black hover:bg-neutral-900 hover:text-white hover:border-neutral-800"
            }`}
          >
            {botRunning ? "Stop Agent" : "Start Agent"}
          </button>
        </div>
      </aside>

      {/* MAIN CONTENT AREA */}
      <main className="flex-1 flex flex-col overflow-hidden bg-neutral-950/20">
        <header className="h-20 border-b border-neutral-900 px-12 flex items-center justify-between">
          <span className="text-xs uppercase tracking-wider text-neutral-400">
            {currentTab === "home" && "Overview"}
            {currentTab === "console" && "Process stdout/stderr log stream"}
            {currentTab === "strategy" && "Edit .env Variables"}
            {currentTab === "purge" && "Manage protection lists"}
          </span>
          <span className="text-xs text-neutral-600 font-mono">
            V1.0.0 // STATUS: {botRunning ? "ON_LOOP" : "IDLE"}
          </span>
        </header>

        <section ref={tabContentRef} className="flex-1 overflow-y-auto p-12">
          {/* TAB 1: HOME */}
          {currentTab === "home" && (
            <div className="space-y-12">
              <div className="max-w-xl">
                <h2 className="text-3xl font-light tracking-tight">System Status Overview</h2>
                <p className="text-neutral-500 text-sm mt-3 leading-relaxed">
                  High-contrast control panel monitoring GitHub engagement activities. 
                  Below are real-time execution statistics queried directly from the SQLite database.
                </p>
              </div>

              {/* Metrics Grid */}
              <div className="grid grid-cols-2 lg:grid-cols-4 gap-6">
                <div className="border border-neutral-900 p-8 flex flex-col justify-between h-40">
                  <span className="text-neutral-500 text-xs tracking-wider uppercase">Rated Repositories</span>
                  <div ref={evalRef} className="text-5xl font-light font-mono mt-4">0</div>
                </div>
                <div className="border border-neutral-900 p-8 flex flex-col justify-between h-40">
                  <span className="text-neutral-500 text-xs tracking-wider uppercase">Follows Performed</span>
                  <div ref={followRef} className="text-5xl font-light font-mono mt-4">0</div>
                </div>
                <div className="border border-neutral-900 p-8 flex flex-col justify-between h-40">
                  <span className="text-neutral-500 text-xs tracking-wider uppercase">Starred Projects</span>
                  <div ref={starRef} className="text-5xl font-light font-mono mt-4">0</div>
                </div>
                <div className="border border-neutral-900 p-8 flex flex-col justify-between h-40">
                  <span className="text-neutral-500 text-xs tracking-wider uppercase">Logged Purged Users</span>
                  <div ref={purgeRef} className="text-5xl font-light font-mono mt-4">0</div>
                </div>
              </div>

              {/* Bot Controller Switch Detail */}
              <div className="border border-neutral-900 p-8 flex flex-col md:flex-row justify-between items-start md:items-center gap-6">
                <div>
                  <h3 className="text-sm font-semibold uppercase">Orchestration Switch</h3>
                  <p className="text-xs text-neutral-500 mt-1">
                    Spawn a background thread to call the main loop. TCP connections will be established and maintained dynamically.
                  </p>
                </div>
                <div className="flex items-center gap-4">
                  <span className="text-xs font-mono text-neutral-400">{botRunning ? "ACTIVE" : "INACTIVE"}</span>
                  <button
                    onClick={toggleBot}
                    className={`w-16 h-8 flex items-center p-1 rounded-none border transition-all duration-300 ${
                      botRunning ? "bg-white border-white justify-end" : "bg-transparent border-neutral-700 justify-start"
                    }`}
                  >
                    <span className={`w-6 h-6 inline-block rounded-none transition-all duration-300 ${botRunning ? "bg-black" : "bg-neutral-500"}`} />
                  </button>
                </div>
              </div>
            </div>
          )}

          {/* TAB 2: TERMINAL CONSOLE */}
          {currentTab === "console" && (
            <div className="flex flex-col h-full space-y-6">
              <div className="flex justify-between items-center">
                <span className="text-xs text-neutral-400 uppercase font-mono tracking-wider">Bot stdout log</span>
                <button
                  onClick={clearLogs}
                  className="px-4 py-2 border border-neutral-800 text-xs uppercase hover:bg-white hover:text-black hover:border-white transition-all duration-200"
                >
                  Clear Screen
                </button>
              </div>

              {/* Simulated Console Screen */}
              <div className="flex-1 bg-black border border-neutral-900 p-6 font-mono text-xs leading-relaxed overflow-y-auto min-h-[400px] max-h-[500px]">
                {logs.length === 0 ? (
                  <div className="text-neutral-600 italic">Console is currently idle. Start the bot to stream logs...</div>
                ) : (
                  logs.map((log, index) => (
                    <div
                      key={index}
                      className={
                        log.startsWith("[ERROR]")
                          ? "text-neutral-500"
                          : log.startsWith("[SYSTEM]")
                          ? "text-white font-bold"
                          : "text-neutral-300"
                      }
                    >
                      {log}
                    </div>
                  ))
                )}
                <div ref={consoleEndRef} />
              </div>
            </div>
          )}

          {/* TAB 3: STRATEGY CONFIG */}
          {currentTab === "strategy" && (
            <div className="space-y-8 max-w-2xl">
              <div>
                <h3 className="text-lg font-light">Parameters & Threshold Editor</h3>
                <p className="text-xs text-neutral-500 mt-1">
                  Adjust target programming languages, repository thresholds, and evaluation caps for the LLM review.
                </p>
              </div>

              <div className="space-y-6 border border-neutral-900 p-8">
                <div className="grid grid-cols-2 gap-6">
                  <div className="space-y-2">
                    <label className="block text-xs uppercase text-neutral-400 font-mono">Target Programming Language</label>
                    <input
                      type="text"
                      value={language}
                      onChange={(e) => setLanguage(e.target.value)}
                      className="w-full bg-black border border-neutral-800 px-4 py-3 text-sm focus:outline-none focus:border-white transition-all duration-200 rounded-none text-white"
                    />
                  </div>
                  <div className="space-y-2">
                    <label className="block text-xs uppercase text-neutral-400 font-mono">Fetch Quota Per Cycle</label>
                    <input
                      type="number"
                      value={fetchCount}
                      onChange={(e) => setFetchCount(e.target.value)}
                      className="w-full bg-black border border-neutral-800 px-4 py-3 text-sm focus:outline-none focus:border-white transition-all duration-200 rounded-none text-white"
                    />
                  </div>
                </div>

                <div className="grid grid-cols-2 gap-6">
                  <div className="space-y-2">
                    <label className="block text-xs uppercase text-neutral-400 font-mono">Subscribe Grade Threshold</label>
                    <input
                      type="text"
                      value={subThreshold}
                      onChange={(e) => setSubThreshold(e.target.value)}
                      className="w-full bg-black border border-neutral-800 px-4 py-3 text-sm focus:outline-none focus:border-white transition-all duration-200 rounded-none text-white"
                    />
                  </div>
                  <div className="space-y-2">
                    <label className="block text-xs uppercase text-neutral-400 font-mono">Star Grade Threshold</label>
                    <input
                      type="text"
                      value={starThreshold}
                      onChange={(e) => setStarThreshold(e.target.value)}
                      className="w-full bg-black border border-neutral-800 px-4 py-3 text-sm focus:outline-none focus:border-white transition-all duration-200 rounded-none text-white"
                    />
                  </div>
                </div>

                <div className="pt-6">
                  <button
                    onClick={handleSaveSettings}
                    className="px-8 py-3 bg-white text-black border border-white text-xs uppercase tracking-widest font-bold hover:bg-black hover:text-white hover:border-neutral-800 transition-all duration-300"
                  >
                    Save Configuration
                  </button>
                </div>
              </div>
            </div>
          )}

          {/* TAB 4: PURGE & WHITELIST */}
          {currentTab === "purge" && (
            <div className="space-y-12">
              {/* Whitelist Settings */}
              <div className="space-y-6 max-w-2xl">
                <div>
                  <h3 className="text-lg font-light">Protected Accounts (Whitelist)</h3>
                  <p className="text-xs text-neutral-500 mt-1">
                    Users specified below will never be unfollowed under any circumstances.
                  </p>
                </div>

                {/* Inline Whitelist Editor */}
                <div className="flex gap-4">
                  <input
                    type="text"
                    placeholder="GitHub username (e.g. torvalds)"
                    value={newWhitelistUser}
                    onChange={(e) => setNewWhitelistUser(e.target.value)}
                    onKeyDown={(e) => e.key === "Enter" && handleAddWhitelist()}
                    className="flex-1 bg-black border border-neutral-800 px-4 py-3 text-sm focus:outline-none focus:border-white transition-all duration-200 rounded-none text-white"
                  />
                  <button
                    onClick={handleAddWhitelist}
                    className="px-6 border border-neutral-800 text-xs uppercase tracking-widest hover:bg-white hover:text-black hover:border-white transition-all duration-200"
                  >
                    Add User
                  </button>
                </div>

                {/* Whitelist Tags Cloud */}
                <div className="border border-neutral-900 p-6 min-h-[120px] flex flex-wrap gap-3 items-start content-start">
                  {whitelistArray.length === 0 ? (
                    <span className="text-xs text-neutral-600 italic">No whitelisted users configured yet.</span>
                  ) : (
                    whitelistArray.map((user) => (
                      <div
                        key={user}
                        className="flex items-center gap-2 px-3 py-1.5 border border-neutral-800 text-xs bg-neutral-950 font-mono"
                      >
                        <span>@{user}</span>
                        <button
                          onClick={() => handleRemoveWhitelist(user)}
                          className="text-neutral-500 hover:text-white font-bold ml-1"
                        >
                          &times;
                        </button>
                      </div>
                    ))
                  )}
                </div>
              </div>

              {/* Purge Queue Table */}
              <div className="space-y-6">
                <div>
                  <h3 className="text-lg font-light">Purged Profiles Log</h3>
                  <p className="text-xs text-neutral-500 mt-1">
                    This table logs profiles that have been unfollowed because they did not follow back, preventing re-engagement in future search fetch loops.
                  </p>
                </div>

                <div className="border border-neutral-900 overflow-hidden">
                  <table className="w-full text-left border-collapse">
                    <thead>
                      <tr className="border-b border-neutral-900 bg-neutral-950 text-xs font-mono uppercase text-neutral-400">
                        <th className="p-4">Profile Username</th>
                        <th className="p-4">Status</th>
                        <th className="p-4">Actions Allowed</th>
                      </tr>
                    </thead>
                    <tbody className="divide-y divide-neutral-900 text-sm font-mono">
                      {whitelistArray.slice(0, 3).map((item, idx) => (
                        <tr key={idx} className="hover:bg-neutral-950/40">
                          <td className="p-4 text-white">@{item} (Demo Row)</td>
                          <td className="p-4"><span className="text-neutral-400">Protected</span></td>
                          <td className="p-4 text-neutral-600">None</td>
                        </tr>
                      ))}
                      <tr className="hover:bg-neutral-950/40">
                        <td className="p-4 text-neutral-500" colSpan={3}>
                          Querying table entries from DB (Real-time active queue is loaded automatically on each purge cycle).
                        </td>
                      </tr>
                    </tbody>
                  </table>
                </div>
              </div>
            </div>
          )}
        </section>
      </main>
    </div>
  );
}
