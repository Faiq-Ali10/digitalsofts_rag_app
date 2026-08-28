import type { Metadata } from "next";
import { Inter } from "next/font/google";
import "./globals.css";
import Link from "next/link";
import { MessageSquare, LogOut, ShieldAlert } from "lucide-react";
import { AuthProvider } from "@/lib/AuthContext";
import NavLinks from "@/components/NavLinks";

const inter = Inter({ subsets: ["latin"] });

export const metadata: Metadata = {
  title: "Digitalsofts Assistant",
  description: "Enterprise AI Assistant",
};

export default function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  return (
    <html lang="en">
      <body className={`${inter.className} bg-slate-50 text-slate-900 min-h-screen flex flex-col`}>
        <AuthProvider>
          <nav className="bg-white border-b border-slate-200 sticky top-0 z-10">
            <div className="max-w-5xl mx-auto px-4 h-16 flex items-center justify-between">
              <Link href="/" className="flex items-center gap-2 text-indigo-600 font-semibold text-lg hover:text-indigo-700 transition-colors">
                <MessageSquare className="w-6 h-6" />
                <span>Digitalsofts</span>
              </Link>
              <div className="flex items-center gap-4 text-sm font-medium">
                <NavLinks />
              </div>
            </div>
          </nav>
          <main className="flex-1 max-w-5xl w-full mx-auto p-4 flex flex-col">
            {children}
          </main>
        </AuthProvider>
      </body>
    </html>
  );
}
