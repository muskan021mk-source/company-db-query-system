import { useState, useRef, useEffect, useCallback } from "react";
import {
  Network, Send, Square, Plus, X, Menu,
  PanelLeft, Sun, Moon, Trash2, Copy, Check, LogOut, UserX,
} from "lucide-react";
import { useDispatch, useSelector } from "react-redux";
import { useNavigate, Routes, Route } from "react-router-dom";
import ChartRenderer from "./ChartRenderer";
import { logout } from "./services/operations/authAPI";
import { sendDeleteAccountOtp, deleteAccount } from "./services/operations/profileAPI";
import "./App.css";


import Login from "./Pages/Login.jsx";
import Signup from "./Pages/Signup.jsx";
import VerifyEmail from "./Pages/VerifyEmail.jsx";
import ForgotPassword from "./Pages/ForgotPassword.jsx";
import UpdatePassword from "./Pages/UpdatePassword.jsx";
import PrivateRoute from "./components/core/auth/PrivateRoute.jsx";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";

const API_URL = import.meta.env.VITE_API_URL || "http://localhost:8000";
const ACTIVE_KEY = "org_assistant_active_thread";
const SIDEBAR_COLLAPSED_KEY = "org_assistant_sidebar_collapsed";
const SIDEBAR_WIDTH_KEY = "org_assistant_sidebar_width";

const DEFAULT_SIDEBAR_WIDTH = 264;
const MIN_SIDEBAR_WIDTH = 200;
const MAX_SIDEBAR_WIDTH = 420;

function newThreadId() {
  return "user-" + crypto.randomUUID();
}

function makeLocalConversation() {
  const threadId = newThreadId();
  return {
    threadId,
    title: "New chat",
    messages: [],
    messagesLoaded: true,
    persisted: false,
  };
}

const SUGGESTIONS = [
  "Show all employees in the Engineering department",
  "Who reported absent in the last 7 days?",
  "Update John Smith's department to Finance",
  "How many records are in the sales table?",
];

function initials(name) {
  if (!name) return "?";
  return name.trim().split(/\s+/).slice(0, 2).map((p) => p[0]?.toUpperCase()).join("");
}

// ChatApp is only rendered when authenticated (PrivateRoute below handles the gate)
function ChatApp() {
  const dispatch  = useDispatch();
  const navigate  = useNavigate();
  const { token } = useSelector((state) => state.auth);
  const { user }  = useSelector((state) => state.profile);

  const [conversations, setConversations]               = useState([]);
  const [activeId, setActiveId]                         = useState(null);
  const [conversationsLoading, setConversationsLoading] = useState(true);
  const [input, setInput]                               = useState("");
  const [loading, setLoading]                           = useState(false);
  const [theme, setTheme]                               = useState("dark");
  const [sidebarOpen, setSidebarOpen]                   = useState(false);
  const [sidebarCollapsed, setSidebarCollapsed]         = useState(() => {
    try { return localStorage.getItem(SIDEBAR_COLLAPSED_KEY) === "1"; }
    catch { return false; }
  });
  const [sidebarWidth, setSidebarWidth] = useState(() => {
    try {
      const saved = parseInt(localStorage.getItem(SIDEBAR_WIDTH_KEY), 10);
      if (!Number.isNaN(saved)) {
        return Math.min(MAX_SIDEBAR_WIDTH, Math.max(MIN_SIDEBAR_WIDTH, saved));
      }
    } catch { /* ignore */ }
    return DEFAULT_SIDEBAR_WIDTH;
  });
  const [isResizing, setIsResizing]     = useState(false);
  const [copiedId, setCopiedId]         = useState(null);
  const [showLogoutConfirm, setShowLogoutConfirm] = useState(false);
  const [userMenuOpen, setUserMenuOpen] = useState(false);

  // Delete-account flow: "confirm" (are you sure?) -> "otp" (enter the
  // code just emailed to you). null means the modal is closed.
  const [deleteStep, setDeleteStep]           = useState(null); // null | "confirm" | "otp"
  const [deleteOtp, setDeleteOtp]             = useState("");
  const [deleteSubmitting, setDeleteSubmitting] = useState(false);

  const bottomRef               = useRef(null);
  const abortControllerRef      = useRef(null);
  const stopThreadIdRef         = useRef(null);
  const messageFetchInFlightRef = useRef(new Set());
  const userMenuRef             = useRef(null);

  const active = conversations.find((c) => c.threadId === activeId) ?? null;

  function authHeaders() {
    return token ? { Authorization: `Bearer ${token}` } : {};
  }

  function handleLogout() {
    setShowLogoutConfirm(false);
    dispatch(logout(navigate));
  }

  // Load conversations on mount
  useEffect(() => {
    if (!token) return;
    let cancelled = false;

    async function load() {
      setConversationsLoading(true);
      try {
        const res = await fetch(`${API_URL}/conversations`, { headers: authHeaders() });
        if (!res.ok) throw new Error(`Server error: ${res.status}`);
        const list = await res.json();
        if (cancelled) return;

        if (list.length === 0) {
          const fresh = makeLocalConversation();
          setConversations([fresh]);
          setActiveId(fresh.threadId);
          return;
        }

        const mapped = list.map((c) => ({
          threadId: c.thread_id,
          title: c.title,
          messages: [],
          messagesLoaded: false,
          persisted: true,
        }));
        setConversations(mapped);

        let savedActive = null;
        try { savedActive = localStorage.getItem(ACTIVE_KEY); } catch { /* ignore */ }
        const initial = mapped.find((c) => c.threadId === savedActive) ?? mapped[0];
        setActiveId(initial.threadId);
      } catch {
        if (!cancelled) {
          const fresh = makeLocalConversation();
          setConversations([fresh]);
          setActiveId(fresh.threadId);
        }
      } finally {
        if (!cancelled) setConversationsLoading(false);
      }
    }

    load();
    return () => { cancelled = true; };
  }, [token]);

  // Lazy load messages
  useEffect(() => {
    if (!activeId) return;
    const conv = conversations.find((c) => c.threadId === activeId);
    if (!conv || conv.messagesLoaded) return;
    if (messageFetchInFlightRef.current.has(activeId)) return;

    messageFetchInFlightRef.current.add(activeId);

    (async () => {
      try {
        const res = await fetch(`${API_URL}/conversations/${activeId}`, { headers: authHeaders() });
        if (!res.ok) throw new Error(`Server error: ${res.status}`);
        const data = await res.json();
        setConversations((prev) =>
          prev.map((c) =>
            c.threadId === activeId
              ? { ...c, messages: data.messages ?? [], messagesLoaded: true }
              : c
          )
        );
      } catch {
        setConversations((prev) =>
          prev.map((c) => c.threadId === activeId ? { ...c, messagesLoaded: true } : c)
        );
      } finally {
        messageFetchInFlightRef.current.delete(activeId);
      }
    })();
  }, [activeId]);

  useEffect(() => {
    const onKeyDown = (e) => {
      if (e.key !== "Escape") return;
      if (showLogoutConfirm) { setShowLogoutConfirm(false); return; }
      if (deleteStep) { closeDeleteModal(); return; }
      if (userMenuOpen) { setUserMenuOpen(false); return; }
      setSidebarOpen(false);
    };
    window.addEventListener("keydown", onKeyDown);
    return () => window.removeEventListener("keydown", onKeyDown);
  }, [showLogoutConfirm, deleteStep, userMenuOpen]);

  // Close the user menu popover on outside click
  useEffect(() => {
    if (!userMenuOpen) return;
    function onClickOutside(e) {
      if (userMenuRef.current && !userMenuRef.current.contains(e.target)) {
        setUserMenuOpen(false);
      }
    }
    document.addEventListener("mousedown", onClickOutside);
    return () => document.removeEventListener("mousedown", onClickOutside);
  }, [userMenuOpen]);

  useEffect(() => {
    if (activeId) {
      try { localStorage.setItem(ACTIVE_KEY, activeId); } catch { /* ignore */ }
    }
  }, [activeId]);

  useEffect(() => {
    try { localStorage.setItem(SIDEBAR_COLLAPSED_KEY, sidebarCollapsed ? "1" : "0"); }
    catch { /* ignore */ }
  }, [sidebarCollapsed]);

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [active?.messages, loading]);

  // Sidebar drag-to-resize
  useEffect(() => {
    if (!isResizing) return;

    function onMouseMove(e) {
      const next = Math.min(MAX_SIDEBAR_WIDTH, Math.max(MIN_SIDEBAR_WIDTH, e.clientX));
      setSidebarWidth(next);
    }
    function onMouseUp() {
      setIsResizing(false);
    }

    document.body.style.cursor = "col-resize";
    document.body.style.userSelect = "none";
    window.addEventListener("mousemove", onMouseMove);
    window.addEventListener("mouseup", onMouseUp);
    return () => {
      document.body.style.cursor = "";
      document.body.style.userSelect = "";
      window.removeEventListener("mousemove", onMouseMove);
      window.removeEventListener("mouseup", onMouseUp);
    };
  }, [isResizing]);

  // Persist sidebar width once a drag ends
  useEffect(() => {
    if (isResizing) return;
    try { localStorage.setItem(SIDEBAR_WIDTH_KEY, String(sidebarWidth)); }
    catch { /* ignore */ }
  }, [isResizing, sidebarWidth]);

  const updateConversation = useCallback((threadId, updater) => {
    setConversations((prev) =>
      prev.map((c) => (c.threadId === threadId ? updater(c) : c))
    );
  }, []);

  function toServerMessages(messages) {
    return messages.map((m) => ({
      role: m.role,
      text: m.text,
      visualization: m.visualization ?? null,
      isError: m.isError ?? null,
      isStopped: m.isStopped ?? null,
    }));
  }

  async function persistConversation(conv, { title, messages }) {
    const headers = { "Content-Type": "application/json", ...authHeaders() };
    try {
      if (!conv.persisted) {
        await fetch(`${API_URL}/conversations`, {
          method: "POST",
          headers,
          body: JSON.stringify({ thread_id: conv.threadId, title: title ?? conv.title }),
        });
        updateConversation(conv.threadId, (c) => ({ ...c, persisted: true }));
      }
      await fetch(`${API_URL}/conversations/${conv.threadId}`, {
        method: "PATCH",
        headers,
        body: JSON.stringify({
          ...(title !== undefined ? { title } : {}),
          ...(messages !== undefined ? { messages: toServerMessages(messages) } : {}),
        }),
      });
    } catch { /* best-effort */ }
  }

  async function sendMessage(overrideText) {
    const question = (overrideText ?? input).trim();
    if (!question || loading || !active) return;

    const conv = active;
    const threadId = conv.threadId;
    const isFirstMessage = conv.messages.length === 0;
    const title = isFirstMessage ? question.slice(0, 42) : conv.title;
    const messagesAfterUser = [...conv.messages, { role: "user", text: question }];

    updateConversation(threadId, (c) => ({ ...c, title, messages: messagesAfterUser }));
    setInput("");
    setLoading(true);

    const controller = new AbortController();
    abortControllerRef.current = controller;
    stopThreadIdRef.current = threadId;

    let finalMessages = messagesAfterUser;

    try {
      const res = await fetch(`${API_URL}/chat`, {
        method: "POST",
        headers: { "Content-Type": "application/json", ...authHeaders() },
        body: JSON.stringify({ question, thread_id: threadId }),
        signal: controller.signal,
      });

      if (res.status === 401) { handleLogout(); return; }
      if (!res.ok) throw new Error(`Server error: ${res.status}`);

      const data = await res.json();
      finalMessages = [
        ...messagesAfterUser,
        data.stopped
          ? { role: "assistant", text: "Stopped.", isStopped: true }
          : { role: "assistant", text: data.answer, visualization: data.visualization ?? null },
      ];
      updateConversation(threadId, (c) => ({ ...c, messages: finalMessages }));
    } catch (err) {
      finalMessages = [
        ...messagesAfterUser,
        err.name === "AbortError"
          ? { role: "assistant", text: "Stopped.", isStopped: true }
          : { role: "assistant", text: `Error: ${err.message}`, isError: true },
      ];
      updateConversation(threadId, (c) => ({ ...c, messages: finalMessages }));
    } finally {
      setLoading(false);
      abortControllerRef.current = null;
      stopThreadIdRef.current = null;
      persistConversation(conv, { title, messages: finalMessages });
    }
  }

  function handleStop() {
    abortControllerRef.current?.abort();
    const threadId = stopThreadIdRef.current;
    if (threadId) {
      fetch(`${API_URL}/chat/stop`, {
        method: "POST",
        headers: { "Content-Type": "application/json", ...authHeaders() },
        body: JSON.stringify({ thread_id: threadId }),
      }).catch(() => { /* best-effort */ });
    }
  }

  function handleKeyDown(e) {
    if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); sendMessage(); }
  }

  function handleNewChat() {
    const conv = makeLocalConversation();
    setConversations((prev) => [conv, ...prev]);
    setActiveId(conv.threadId);
    setInput("");
    setSidebarOpen(false);
  }

  function handleSelectChat(threadId) {
    setActiveId(threadId);
    setSidebarOpen(false);
  }

  function handleDeleteChat(threadId, e) {
    e.stopPropagation();
    const conv = conversations.find((c) => c.threadId === threadId);
    setConversations((prev) => {
      const next = prev.filter((c) => c.threadId !== threadId);
      if (next.length === 0) {
        const fresh = makeLocalConversation();
        setActiveId(fresh.threadId);
        return [fresh];
      }
      if (threadId === activeId) setActiveId(next[0].threadId);
      return next;
    });
    if (conv?.persisted) {
      fetch(`${API_URL}/conversations/${threadId}`, {
        method: "DELETE", headers: authHeaders(),
      }).catch(() => { /* best-effort */ });
    }
  }

  function handleDeleteMessage(index) {
    if (!active) return;
    const target = active.messages[index];
    const next = active.messages[index + 1];
    const alsoRemoveNext = target?.role === "user" && next?.role === "assistant";
    const toRemove = alsoRemoveNext ? [index, index + 1] : [index];
    const nextMessages = active.messages.filter((_, i) => !toRemove.includes(i));
    updateConversation(active.threadId, (c) => ({ ...c, messages: nextMessages }));
    persistConversation(active, { messages: nextMessages });
  }

  function handleClearAllHistory() {
    if (!window.confirm("Delete all query history? This can't be undone.")) return;
    const fresh = makeLocalConversation();
    setConversations([fresh]);
    setActiveId(fresh.threadId);
    setSidebarOpen(false);
    fetch(`${API_URL}/conversations`, { method: "DELETE", headers: authHeaders() })
      .catch(() => { /* best-effort */ });
  }

  async function handleCopyMessage(text, msgKey) {
    try {
      await navigator.clipboard.writeText(text);
      setCopiedId(msgKey);
      setTimeout(() => setCopiedId((prev) => (prev === msgKey ? null : prev)), 1500);
    } catch { /* clipboard permission denied */ }
  }

  function handleCopyWholeChat() {
    if (!active || active.messages.length === 0) return;
    const text = active.messages
      .map((m) => `${m.role === "user" ? "You" : "Assistant"}: ${m.text}`)
      .join("\n\n");
    handleCopyMessage(text, "whole-chat");
  }

  function toggleSidebarCollapsed() {
    setSidebarCollapsed((prev) => {
      const next = !prev;
      setSidebarOpen(next ? false : true);
      return next;
    });
  }

  function handleLogoutMenuClick() {
    setUserMenuOpen(false);
    setShowLogoutConfirm(true);
  }

  function handleDeleteAccountMenuClick() {
    setUserMenuOpen(false);
    setDeleteOtp("");
    setDeleteStep("confirm");
  }

  function closeDeleteModal() {
    setDeleteStep(null);
    setDeleteOtp("");
    setDeleteSubmitting(false);
  }

  async function handleConfirmDeleteIntent() {
    setDeleteSubmitting(true);
    const sent = await dispatch(sendDeleteAccountOtp(token));
    setDeleteSubmitting(false);
    if (sent) setDeleteStep("otp");
  }

  async function handleConfirmDeleteOtp() {
    if (!deleteOtp.trim()) return;
    setDeleteSubmitting(true);
    const ok = await dispatch(deleteAccount(deleteOtp.trim(), token, navigate));
    setDeleteSubmitting(false);
    if (ok) closeDeleteModal();
  }

  return (
    <div className={`app ${theme === "light" ? "light" : ""}`}>
      {sidebarOpen && (
        <button className="sidebar-overlay" onClick={() => setSidebarOpen(false)} aria-label="Close navigation" />
      )}

      {/* Collapsed-state rail: panel toggle stacked above a compact "New" pill,
          mirrors the reference layout (icon square + New button). */}
      <div className={`collapsed-bar ${sidebarCollapsed && !sidebarOpen ? "visible" : ""}`}>
        <button
          className="collapsed-icon-btn"
          onClick={() => { setSidebarCollapsed(false); setSidebarOpen(true); }}
          title="Open sidebar" aria-label="Open sidebar"
        >
          <PanelLeft size={17} />
        </button>
        <button className="collapsed-new-btn" onClick={handleNewChat} title="New query" aria-label="New query">
          <Plus size={15} /> New
        </button>
      </div>

      <aside
        className={`sidebar ${sidebarOpen ? "open" : ""} ${sidebarCollapsed ? "collapsed" : ""} ${isResizing ? "resizing" : ""}`}
        style={!sidebarCollapsed ? { width: sidebarWidth } : undefined}
      >
        <div className="sidebar-header">
          <div className="brand">
            <span className="brand-dot" />
            <span className="brand-name">DB Query Assistant</span>
            <button
              className="sidebar-close"
              onClick={toggleSidebarCollapsed}
              title="Collapse sidebar"
              aria-label="Collapse sidebar"
            >
              <PanelLeft size={17} />
            </button>
            <button
              className="sidebar-close mobile-only"
              onClick={() => setSidebarOpen(false)}
              aria-label="Close sidebar"
            >
              <X size={18} />
            </button>
          </div>
          <button className="new-chat-btn" onClick={handleNewChat}>
            <Plus size={15} /> New query
          </button>
        </div>

        <div className="sidebar-section-label">Query History</div>
        <div className="sidebar-list">
          {conversationsLoading ? (
            <div className="sidebar-loading">Loading history…</div>
          ) : (
            conversations.map((c) => (
              <button
                key={c.threadId}
                className={`sidebar-item ${c.threadId === activeId ? "active" : ""}`}
                onClick={() => handleSelectChat(c.threadId)}
              >
                <span className="node-rail" />
                <span className="sidebar-item-label">{c.title}</span>
                <span className="sidebar-item-delete" onClick={(e) => handleDeleteChat(c.threadId, e)} title="Delete">
                  <Trash2 size={13} />
                </span>
              </button>
            ))
          )}
        </div>

        <div className="sidebar-footer-group" ref={userMenuRef}>
          {userMenuOpen && (
            <div className="user-menu-popover" role="menu">
              <button className="user-menu-item" role="menuitem" onClick={handleLogoutMenuClick}>
                <LogOut size={15} />
                <span>Log out</span>
              </button>
              <button
                className="user-menu-item user-menu-item-danger"
                role="menuitem"
                onClick={handleDeleteAccountMenuClick}
              >
                <UserX size={15} />
                <span>Delete account</span>
              </button>
            </div>
          )}

          <button
            className="sidebar-user"
            onClick={() => setUserMenuOpen((v) => !v)}
            aria-haspopup="menu"
            aria-expanded={userMenuOpen}
          >
            <span className="sidebar-user-avatar">{initials(user?.name || user?.email)}</span>
            <div className="sidebar-user-info">
              <span className="sidebar-user-name">{user?.name || "Account"}</span>
              {user?.email && <span className="sidebar-user-email">{user.email}</span>}
              {user?.department && <span className="sidebar-user-email">{user.department}</span>}
            </div>
          </button>

          <div className="sidebar-footer">
            <button className="clear-history-btn" onClick={handleClearAllHistory}>
              <Trash2 size={13} /> Clear all
            </button>
            <button className="theme-toggle" onClick={() => setTheme((t) => (t === "dark" ? "light" : "dark"))}>
              {theme === "dark" ? <Sun size={13} /> : <Moon size={13} />}
              {theme === "dark" ? "Light" : "Dark"}
            </button>
          </div>
        </div>

        {!sidebarCollapsed && (
          <div
            className="sidebar-resizer"
            onMouseDown={(e) => { e.preventDefault(); setIsResizing(true); }}
            role="separator"
            aria-orientation="vertical"
            aria-label="Resize sidebar"
          />
        )}
      </aside>

      <div className="main">
        <div className="topbar">
          <div className="topbar-left">
            <button className="menu-btn mobile-only"
              onClick={() => { setSidebarCollapsed(false); setSidebarOpen(true); }}
              aria-label="Open sidebar"
            >
              <Menu size={19} />
            </button>
            <span className="topbar-title">{active?.title ?? "DB Query Assistant"}</span>
          </div>
          {active && active.messages.length > 0 && (
            <button className="menu-btn always-visible" onClick={handleCopyWholeChat} title="Copy whole chat">
              {copiedId === "whole-chat" ? <Check size={16} /> : <Copy size={16} />}
            </button>
          )}
        </div>

        <div className="chat-area">
          {active && active.messages.length === 0 ? (
            <div className="empty-state">
              <h1>What would you like to query?</h1>
              <p>Ask anything about your company database — read records, check data, or make updates.</p>
              <div className="chips">
                {SUGGESTIONS.map((s, i) => (
                  <button key={i} className="chip" disabled={loading} onClick={() => sendMessage(s)}>{s}</button>
                ))}
              </div>
            </div>
          ) : (
            <div className="thread">
              {active?.messages.map((m, i) => {
                const msgKey = `${active.threadId}-${i}`;
                return m.role === "user" ? (
                  <div className="message user-row" key={i}>
                    <div className="user-row-inner">
                      <div className="user-pill">{m.text}</div>
                      <div className="msg-actions user-actions">
                        <button className="msg-icon-btn" onClick={() => handleCopyMessage(m.text, msgKey)}>
                          {copiedId === msgKey ? <Check size={12} /> : <Copy size={12} />}
                        </button>
                        <button className="msg-icon-btn delete-btn" onClick={() => handleDeleteMessage(i)}>
                          <Trash2 size={12} />
                        </button>
                      </div>
                    </div>
                  </div>
                ) : (
                  <div className="message assistant-message" key={i}>
                    <span className="msg-marker"><Network size={15} className="node-glyph" /></span>
                    <div className="msg-body">
                      {m.isError ? (
                        <div className="error-note">{m.text}</div>
                      ) : m.isStopped ? (
                        <div className="stopped-note">{m.text}</div>
                      ) : (
                        <>
                          <div className="msg-text">
                            <ReactMarkdown remarkPlugins={[remarkGfm]}>{m.text}</ReactMarkdown>
                          </div>
                          {m.visualization && <ChartRenderer spec={m.visualization} />}
                        </>
                      )}
                      <div className="msg-actions">
                        <button className="msg-icon-btn" onClick={() => handleCopyMessage(m.text, msgKey)}>
                          {copiedId === msgKey ? <Check size={12} /> : <Copy size={12} />}
                        </button>
                        <button className="msg-icon-btn delete-btn" onClick={() => handleDeleteMessage(i)}>
                          <Trash2 size={12} />
                        </button>
                      </div>
                    </div>
                  </div>
                );
              })}

              {loading && (
                <div className="message assistant-message">
                  <span className="msg-marker"><Network size={15} className="node-glyph" /></span>
                  <span className="typing-dots"><span /><span /><span /></span>
                </div>
              )}
              <div ref={bottomRef} />
            </div>
          )}
        </div>

        <div className="composer">
          <div className="composer-inner">
            <input
              value={input}
              onChange={(e) => setInput(e.target.value)}
              onKeyDown={handleKeyDown}
              placeholder="Ask about your database..."
              disabled={loading}
            />
            {loading ? (
              <button className="stop-btn" onClick={handleStop}>
                <Square size={14} fill="currentColor" />
              </button>
            ) : (
              <button onClick={() => sendMessage()} disabled={!input.trim()}>
                <Send size={16} />
              </button>
            )}
          </div>
        </div>
      </div>

      {showLogoutConfirm && (
        <div className="logout-confirm-overlay" onClick={() => setShowLogoutConfirm(false)}>
          <div
            className="logout-confirm-dialog"
            role="alertdialog"
            aria-modal="true"
            aria-labelledby="logout-confirm-title"
            onClick={(e) => e.stopPropagation()}
          >
            <h2 id="logout-confirm-title">Sign out?</h2>
            <p>You'll need to sign in again to access your queries.</p>
            <div className="logout-confirm-actions">
              <button className="logout-confirm-cancel" onClick={() => setShowLogoutConfirm(false)}>
                Cancel
              </button>
              <button className="logout-confirm-ok" onClick={handleLogout}>
                Sign out
              </button>
            </div>
          </div>
        </div>
      )}

      {deleteStep === "confirm" && (
        <div className="logout-confirm-overlay" onClick={closeDeleteModal}>
          <div
            className="logout-confirm-dialog"
            role="alertdialog"
            aria-modal="true"
            aria-labelledby="delete-confirm-title"
            onClick={(e) => e.stopPropagation()}
          >
            <h2 id="delete-confirm-title">Delete your account?</h2>
            <p>
              This permanently deletes your account and can't be undone.
              We'll send a confirmation code to your email before anything happens.
            </p>
            <div className="logout-confirm-actions">
              <button className="logout-confirm-cancel" onClick={closeDeleteModal} disabled={deleteSubmitting}>
                Cancel
              </button>
              <button
                className="logout-confirm-ok logout-confirm-danger"
                onClick={handleConfirmDeleteIntent}
                disabled={deleteSubmitting}
              >
                {deleteSubmitting ? "Sending code..." : "Send confirmation code"}
              </button>
            </div>
          </div>
        </div>
      )}

      {deleteStep === "otp" && (
        <div className="logout-confirm-overlay" onClick={closeDeleteModal}>
          <div
            className="logout-confirm-dialog"
            role="alertdialog"
            aria-modal="true"
            aria-labelledby="delete-otp-title"
            onClick={(e) => e.stopPropagation()}
          >
            <h2 id="delete-otp-title">Enter confirmation code</h2>
            <p>We sent a code to your email. Enter it below to permanently delete your account.</p>
            <input
              type="text"
              inputMode="numeric"
              autoFocus
              value={deleteOtp}
              onChange={(e) => setDeleteOtp(e.target.value)}
              onKeyDown={(e) => { if (e.key === "Enter") handleConfirmDeleteOtp(); }}
              placeholder="6-digit code"
              className="delete-otp-input"
              disabled={deleteSubmitting}
            />
            <div className="logout-confirm-actions">
              <button className="logout-confirm-cancel" onClick={closeDeleteModal} disabled={deleteSubmitting}>
                Cancel
              </button>
              <button
                className="logout-confirm-ok logout-confirm-danger"
                onClick={handleConfirmDeleteOtp}
                disabled={deleteSubmitting || !deleteOtp.trim()}
              >
                {deleteSubmitting ? "Deleting..." : "Delete account"}
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}

// App now owns all routing. main.jsx should only render <App />.
export default function App() {
  return (
    <Routes>
      <Route path="/login" element={<Login />} />
      <Route path="/signup" element={<Signup />} />
      <Route path="/verify-email" element={<VerifyEmail />} />
      <Route path="/forgot-password" element={<ForgotPassword />} />
      <Route path="/update-password/:resetPasswordToken" element={<UpdatePassword />} />
      <Route
        path="/*"
        element={
          <PrivateRoute>
            <ChatApp />
          </PrivateRoute>
        }
      />
    </Routes>
  );
}