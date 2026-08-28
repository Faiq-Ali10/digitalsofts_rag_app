"use client";

import { useEffect, useState, useRef } from "react";
import { useRouter } from "next/navigation";
import { getToken, getConversations, getConversationMessages, sendMessage } from "@/lib/api";
import { ChatMessage, ChatMessageProps } from "@/components/ChatMessage";
import { Send, Loader2, MessageSquarePlus } from "lucide-react";

export default function Home() {
  const router = useRouter();
  const [messages, setMessages] = useState<ChatMessageProps[]>([]);
  const [input, setInput] = useState("");
  const [loading, setLoading] = useState(false);
  const [conversationId, setConversationId] = useState<string | null>(null);
  const messagesEndRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    const token = getToken();
    if (!token) {
      router.push("/login");
      return;
    }

    // Load recent conversation if exists
    getConversations().then((res) => {
      if (res.data && res.data.length > 0) {
        const latest = res.data[0];
        setConversationId(latest.id);
        getConversationMessages(latest.id).then((mRes) => {
          if (mRes.data) {
            setMessages(mRes.data.map((m: any) => ({
              role: m.role,
              content: m.content,
              citations: m.citations,
              // Backend GET /messages currently doesn't return tool_calls in message schema natively, 
              // but we handle new messages fine.
            })));
          }
        });
      } else {
        setMessages([{
          role: "assistant",
          content: "Hello! I'm your Digitalsofts Enterprise AI Assistant. How can I help you today?"
        }]);
      }
    }).catch(console.error);
  }, [router]);

  useEffect(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages]);

  const handleSend = async (e?: React.FormEvent) => {
    e?.preventDefault();
    if (!input.trim() || loading) return;

    const userMessage = input;
    setInput("");
    setMessages(prev => [...prev, { role: "user", content: userMessage }]);
    setLoading(true);

    try {
      const res = await sendMessage(userMessage, conversationId);
      if (res.data) {
        if (!conversationId) setConversationId(res.data.conversation_id);
        setMessages(prev => [
          ...prev, 
          { 
            role: "assistant", 
            content: res.data.response,
            citations: res.data.citations,
            toolCalls: res.data.tool_calls
          }
        ]);
      }
    } catch (err: any) {
      alert("Failed to send message: " + err.message);
    } finally {
      setLoading(false);
    }
  };

  const startNewChat = () => {
    setConversationId(null);
    setMessages([{
      role: "assistant",
      content: "Hello! I'm your Digitalsofts Enterprise AI Assistant. How can I help you today?"
    }]);
  };

  return (
    <div className="flex-1 flex flex-col bg-slate-50 rounded-2xl overflow-hidden border border-slate-200 shadow-sm">
      {/* Chat Header */}
      <div className="bg-white px-6 py-4 border-b border-slate-200 flex items-center justify-between">
        <div>
          <h2 className="font-semibold text-slate-800">Enterprise AI Assistant</h2>
          <p className="text-xs text-slate-500">Ask about products, request demos, or search knowledge base</p>
        </div>
        <button 
          onClick={startNewChat}
          className="flex items-center gap-1.5 px-3 py-1.5 text-sm font-medium text-indigo-600 hover:bg-indigo-50 rounded-lg transition-colors"
        >
          <MessageSquarePlus className="w-4 h-4" />
          New Chat
        </button>
      </div>

      {/* Messages */}
      <div className="flex-1 overflow-y-auto p-6 space-y-6">
        {messages.map((msg, i) => (
          <ChatMessage 
            key={i} 
            {...msg} 
            onToolConfirmed={() => {
              // After confirmation, we could optionally reload the conversation
              // For a simple UX, the user can just type again or see the confirmation success
            }} 
          />
        ))}
        {loading && (
          <div className="flex gap-4 w-full">
            <div className="w-10 h-10 rounded-full flex items-center justify-center bg-emerald-500 text-white shrink-0">
              <Loader2 className="w-5 h-5 animate-spin" />
            </div>
            <div className="flex items-center px-4 py-3 bg-white border border-slate-200 rounded-2xl rounded-tl-sm shadow-sm">
              <div className="flex gap-1">
                <div className="w-2 h-2 rounded-full bg-slate-300 animate-bounce"></div>
                <div className="w-2 h-2 rounded-full bg-slate-300 animate-bounce" style={{ animationDelay: "150ms" }}></div>
                <div className="w-2 h-2 rounded-full bg-slate-300 animate-bounce" style={{ animationDelay: "300ms" }}></div>
              </div>
            </div>
          </div>
        )}
        <div ref={messagesEndRef} />
      </div>

      {/* Input */}
      <div className="p-4 bg-white border-t border-slate-200">
        <form 
          onSubmit={handleSend}
          className="relative max-w-4xl mx-auto flex items-end gap-2"
        >
          <div className="relative flex-1">
            <textarea
              value={input}
              onChange={(e) => setInput(e.target.value)}
              onKeyDown={(e) => {
                if (e.key === "Enter" && !e.shiftKey) {
                  e.preventDefault();
                  handleSend();
                }
              }}
              placeholder="Message the assistant..."
              className="w-full pl-4 pr-12 py-3 bg-slate-50 border border-slate-300 rounded-xl focus:ring-2 focus:ring-indigo-500 focus:border-indigo-500 outline-none transition-all resize-none max-h-32 min-h-[52px]"
              rows={1}
            />
          </div>
          <button
            type="submit"
            disabled={!input.trim() || loading}
            className="mb-1 p-2.5 bg-indigo-600 text-white rounded-lg hover:bg-indigo-700 transition-colors disabled:opacity-50 disabled:cursor-not-allowed shrink-0"
          >
            <Send className="w-5 h-5" />
          </button>
        </form>
        <p className="text-center text-xs text-slate-400 mt-3">
          AI generated content may be inaccurate.
        </p>
      </div>
    </div>
  );
}
