"use client";

import Link from "next/link";
import { LogOut, ShieldAlert } from "lucide-react";
import { useAuth } from "@/lib/AuthContext";

export default function NavLinks() {
  const { user, logout, loading } = useAuth();

  if (loading) return null;

  if (!user) {
    return (
      <Link href="/login" className="text-slate-600 hover:text-slate-900">
        Sign In
      </Link>
    );
  }

  return (
    <>
      <span className="text-slate-500 mr-2">{user.email}</span>
      {user.role === "admin" && (
        <Link 
          href="/admin/documents" 
          className="flex items-center gap-1 px-3 py-1.5 rounded bg-indigo-50 text-indigo-700 hover:bg-indigo-100 transition-colors"
        >
          <ShieldAlert className="w-4 h-4" />
          <span>Documents</span>
        </Link>
      )}
      <button 
        onClick={logout}
        className="flex items-center gap-1 text-slate-600 hover:text-red-600 transition-colors"
      >
        <LogOut className="w-4 h-4" />
        <span>Logout</span>
      </button>
    </>
  );
}
