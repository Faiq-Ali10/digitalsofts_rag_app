const API_URL = process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8000';

export function getToken() {
  if (typeof window !== 'undefined') {
    return localStorage.getItem('token');
  }
  return null;
}

export function setToken(token: string) {
  if (typeof window !== 'undefined') {
    localStorage.setItem('token', token);
  }
}

export function removeToken() {
  if (typeof window !== 'undefined') {
    localStorage.removeItem('token');
  }
}

async function fetchWithAuth(endpoint: string, options: RequestInit = {}) {
  const token = getToken();
  const headers = new Headers(options.headers || {});
  
  if (token) {
    headers.set('Authorization', `Bearer ${token}`);
  }
  if (!headers.has('Content-Type')) {
    headers.set('Content-Type', 'application/json');
  }

  const response = await fetch(`${API_URL}${endpoint}`, {
    ...options,
    headers,
  });

  if (!response.ok) {
    if (response.status === 401) {
      removeToken();
      // Only redirect if we are in the browser
      if (typeof window !== 'undefined') {
        window.location.href = '/login';
      }
    }
    const errorData = await response.json().catch(() => null);
    throw new Error(errorData?.detail || `API request failed with status ${response.status}`);
  }

  return response.json();
}

export async function login(email: string, password: string) {
  const data = await fetchWithAuth('/api/v1/auth/login', {
    method: 'POST',
    body: JSON.stringify({ email, password }),
  });
  if (data?.data?.access_token) {
    setToken(data.data.access_token);
  }
  return data;
}

export async function register(email: string, full_name: string, password: string) {
  return fetchWithAuth('/api/v1/auth/register', {
    method: 'POST',
    body: JSON.stringify({ email, full_name, password }),
  });
}

export async function getMe() {
  return fetchWithAuth('/api/v1/auth/me');
}

export async function getConversations() {
  return fetchWithAuth('/api/v1/conversations');
}

export async function getConversationMessages(id: string) {
  return fetchWithAuth(`/api/v1/conversations/${id}`);
}

export async function sendMessage(message: string, conversation_id: string | null = null) {
  return fetchWithAuth('/api/v1/chat', {
    method: 'POST',
    body: JSON.stringify({ message, conversation_id }),
  });
}

export async function confirmToolCall(tool_call_id: string, confirm: boolean) {
  return fetchWithAuth('/api/v1/chat/tool/confirm', {
    method: 'POST',
    body: JSON.stringify({ tool_call_id, confirm }),
  });
}

export async function getDocuments() {
  return fetchWithAuth('/api/v1/documents');
}

export async function uploadDocument(file: File, title?: string, product?: string, version?: string) {
  const formData = new FormData();
  formData.append('file', file);
  if (title) formData.append('title', title);
  if (product) formData.append('product', product);
  if (version) formData.append('version', version);

  const token = getToken();
  const response = await fetch(`${process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8000'}/api/v1/documents`, {
    method: 'POST',
    headers: {
      ...(token ? { 'Authorization': `Bearer ${token}` } : {})
      // Do NOT set Content-Type here; the browser will automatically set it to multipart/form-data with the correct boundary
    },
    body: formData,
  });

  if (!response.ok) {
    if (response.status === 401) {
      removeToken();
      if (typeof window !== 'undefined') window.location.href = '/login';
    }
    const errorData = await response.json().catch(() => null);
    throw new Error(errorData?.detail || `API request failed with status ${response.status}`);
  }

  return response.json();
}

export async function deleteDocument(id: string) {
  return fetchWithAuth(`/api/v1/documents/${id}`, {
    method: 'DELETE',
  });
}
