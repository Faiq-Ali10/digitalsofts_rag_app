"use client";

import { createContext, useContext, useEffect, useState, ReactNode } from "react";
import { getMe, removeToken, getToken } from "./api";
import { useRouter, usePathname } from "next/navigation";

export interface User {
  id: string;
  email: string;
  full_name: string;
  role: string;
}

interface AuthContextType {
  user: User | null;
  loading: boolean;
  logout: () => void;
}

const AuthContext = createContext<AuthContextType | undefined>(undefined);

export function AuthProvider({ children }: { children: ReactNode }) {
  const [user, setUser] = useState<User | null>(null);
  const [loading, setLoading] = useState(true);
  const router = useRouter();
  const pathname = usePathname();

  useEffect(() => {
    async function loadUser() {
      const token = getToken();
      if (!token) {
        setLoading(false);
        // Only redirect to login if we are not already on login or register
        if (pathname !== "/login" && pathname !== "/register") {
          router.push("/login");
        }
        return;
      }

      try {
        const response = await getMe();
        if (response?.data) {
          setUser(response.data);
        }
      } catch (error) {
        console.error("Failed to load user profile:", error);
        removeToken();
        if (pathname !== "/login" && pathname !== "/register") {
          router.push("/login");
        }
      } finally {
        setLoading(false);
      }
    }

    loadUser();
  }, [pathname, router]);

  const logout = () => {
    removeToken();
    setUser(null);
    router.push("/login");
  };

  return (
    <AuthContext.Provider value={{ user, loading, logout }}>
      {children}
    </AuthContext.Provider>
  );
}

export function useAuth() {
  const context = useContext(AuthContext);
  if (context === undefined) {
    throw new Error("useAuth must be used within an AuthProvider");
  }
  return context;
}
