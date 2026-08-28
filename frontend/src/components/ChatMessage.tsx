import ReactMarkdown from 'react-markdown';
import remarkGfm from 'remark-gfm';
import { BookOpen, User, Bot, AlertTriangle, CheckCircle, XCircle } from 'lucide-react';
import { confirmToolCall } from '@/lib/api';
import { useState } from 'react';

export interface ChatMessageProps {
  role: 'user' | 'assistant';
  content: string;
  citations?: Array<{
    index: number;
    title: string;
    source: string;
    section?: string;
  }>;
  toolCalls?: Array<{
    id?: string;
    tool_name: string;
    status: string;
    requires_confirmation: boolean;
  }>;
  onToolConfirmed?: () => void;
}

export function ChatMessage({ role, content, citations, toolCalls, onToolConfirmed }: ChatMessageProps) {
  const isUser = role === 'user';
  const [confirming, setConfirming] = useState(false);

  const pendingTool = toolCalls?.find(tc => tc.status === 'pending_confirmation' && tc.requires_confirmation);

  const handleConfirm = async (confirm: boolean) => {
    if (!pendingTool || !pendingTool.id) return;
    setConfirming(true);
    try {
      await confirmToolCall(pendingTool.id, confirm);
      onToolConfirmed?.();
    } catch (e: any) {
      alert("Error confirming tool: " + e.message);
    } finally {
      setConfirming(false);
    }
  };

  return (
    <div className={`flex gap-4 w-full ${isUser ? 'flex-row-reverse' : ''}`}>
      <div className={`w-10 h-10 rounded-full flex items-center justify-center shrink-0 ${isUser ? 'bg-indigo-600 text-white' : 'bg-emerald-500 text-white'}`}>
        {isUser ? <User className="w-5 h-5" /> : <Bot className="w-5 h-5" />}
      </div>
      
      <div className={`flex flex-col max-w-[80%] ${isUser ? 'items-end' : 'items-start'}`}>
        <div className={`px-5 py-3 rounded-2xl ${isUser ? 'bg-indigo-600 text-white rounded-tr-sm' : 'bg-white border border-slate-200 text-slate-800 rounded-tl-sm shadow-sm'}`}>
          <div className="prose prose-sm max-w-none dark:prose-invert">
            <ReactMarkdown remarkPlugins={[remarkGfm]}>{content}</ReactMarkdown>
          </div>
          
          {/* Citations */}
          {citations && citations.length > 0 && (
            <div className="mt-4 pt-3 border-t border-slate-100/20">
              <p className="text-xs font-semibold mb-2 flex items-center gap-1 opacity-80">
                <BookOpen className="w-3 h-3" /> Sources
              </p>
              <div className="flex flex-wrap gap-2">
                {citations.map((c, i) => (
                  <span key={i} className="inline-flex items-center gap-1 px-2.5 py-1 rounded-md bg-slate-100 text-slate-600 text-xs border border-slate-200">
                    <span className="font-medium text-slate-500">[{c.index}]</span>
                    {c.title}
                  </span>
                ))}
              </div>
            </div>
          )}

          {/* Tool Confirmation */}
          {pendingTool && (
            <div className="mt-4 pt-4 border-t border-slate-200">
              <div className="flex items-start gap-2 bg-amber-50 border border-amber-200 p-3 rounded-lg text-amber-800 text-sm">
                <AlertTriangle className="w-5 h-5 text-amber-600 shrink-0 mt-0.5" />
                <div>
                  <p className="font-medium mb-1">Action Requires Confirmation</p>
                  <p className="opacity-90 mb-3">The assistant wants to execute: <span className="font-mono bg-amber-100 px-1 py-0.5 rounded text-amber-900">{pendingTool.tool_name}</span></p>
                  <div className="flex gap-2">
                    <button 
                      onClick={() => handleConfirm(true)}
                      disabled={confirming}
                      className="flex items-center gap-1 px-3 py-1.5 bg-emerald-600 hover:bg-emerald-700 text-white rounded-md transition-colors font-medium text-xs disabled:opacity-50"
                    >
                      <CheckCircle className="w-3.5 h-3.5" /> Confirm
                    </button>
                    <button 
                      onClick={() => handleConfirm(false)}
                      disabled={confirming}
                      className="flex items-center gap-1 px-3 py-1.5 bg-white border border-slate-300 hover:bg-slate-50 text-slate-700 rounded-md transition-colors font-medium text-xs disabled:opacity-50"
                    >
                      <XCircle className="w-3.5 h-3.5" /> Cancel
                    </button>
                  </div>
                </div>
              </div>
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
