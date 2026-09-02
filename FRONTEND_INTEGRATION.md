# 🚀 Frontend Integration Guide

This guide explains how to connect any frontend application (React, Next.js, Vue, Angular, Svelte, Mobile App, or Vanilla JS) to the **AMS Ticket Management & AI Assistant Backend**, including **User Authorization** (passing `message`, `email`, and `token` / Bearer token).

---

## 1. Quick Start Server

```bash
# 1. Install dependencies
pip install -r requirements.txt

# 2. Configure .env (Copy from .env.example)
cp .env.example .env

# 3. Start the FastAPI server
python main.py
# Or via Uvicorn:
uvicorn main:app --reload --host 0.0.0.0 --port 8000
```

- **Interactive Swagger Documentation**: `http://localhost:8000/docs`
- **ReDoc Documentation**: `http://localhost:8000/redoc`
- **Health Check**: `http://localhost:8000/health`

---

## 2. Authorization & Request Schema

Frontend developers can authorize API requests in two ways:

### Option A: Pass `email` & `token` directly in the Request Body

```json
POST /api/chat
Content-Type: application/json

{
  "message": "Create ticket for Karamtara: SAP login latency, priority High",
  "email": "developer@company.com",
  "token": "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9...",
  "history": [],
  "pending_draft": null
}
```

### Option B: Pass `Authorization: Bearer <token>` Header

```http
POST /api/chat
Authorization: Bearer eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9...
Content-Type: application/json

{
  "message": "Show all unresolved P2 tickets for ATG",
  "email": "developer@company.com",
  "history": []
}
```

---

## 3. API Endpoints Overview

| Method | Endpoint | Authorization | Description |
|---|---|---|---|
| `GET` | `/health` | Optional | Server health check and auth status |
| `GET` | `/api/info` | Optional | API metadata and cache info |
| `POST` | `/api/auth/login` | None | Log in with AMS email/password to retrieve JWT token |
| `GET` | `/api/auth/status` | Optional | Check active auth session |
| `POST` | `/api/chat` | `email`, `token` (body or header) | AI Assistant (Ticket Search, Analytics, Draft Creation) |
| `GET` | `/api/tickets` | `Bearer <token>` (header) | List tickets with filtering, search & pagination |
| `GET` | `/api/tickets/status` | `Bearer <token>` (header) | Real-time ticket statuses (`/api/Ticket/Status`) |
| `POST` | `/api/tickets` | `Bearer <token>` (header) | Create a new ticket directly in AMS |
| `GET` | `/api/tickets/summary` | Optional | Analytics & aggregations (by status, priority, client) |
| `GET` | `/api/meta/clients` | None | List of registered clients |
| `GET` | `/api/meta/groups` | None | List of valid assignment groups & SAP modules |
| `POST` | `/api/cache/clear` | None | Clear cache and force reload next time |

---

## 4. Frontend TypeScript Client Example (`apiClient.ts`)

```typescript
const BASE_URL = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";

export interface ChatMessage {
  role: "user" | "assistant";
  content: string;
  data?: any;
}

export interface TicketDraft {
  clientName?: string;
  priority?: string;
  typeofticket?: string;
  reportedby?: string;
  descriptionofTicket?: string;
  assigntogroup?: string;
  ready_for_confirmation?: boolean;
}

export interface ChatResponse {
  role: string;
  reply: string;
  data?: any[];
  draft?: TicketDraft;
  intent?: string;
}

// 1. Send Message to AI Assistant with User Email & Token
export async function sendChatMessage(params: {
  message: string;
  email?: string;
  token?: string;
  history?: ChatMessage[];
  pendingDraft?: TicketDraft;
}): Promise<ChatResponse> {
  const headers: Record<string, string> = {
    "Content-Type": "application/json",
  };
  if (params.token) {
    headers["Authorization"] = `Bearer ${params.token}`;
  }

  const res = await fetch(`${BASE_URL}/api/chat`, {
    method: "POST",
    headers,
    body: JSON.stringify({
      message: params.message,
      email: params.email,
      token: params.token,
      history: params.history || [],
      pending_draft: params.pendingDraft || null,
    }),
  });

  if (!res.ok) {
    const errText = await res.text();
    throw new Error(errText);
  }
  return res.json();
}

// 2. Fetch Tickets with User Token
export async function getTickets(params: {
  client?: string;
  status?: string;
  priority?: string;
  group?: string;
  search?: string;
  page?: number;
  pageSize?: number;
  token?: string;
  email?: string;
}) {
  const query = new URLSearchParams();
  if (params.client) query.set("client", params.client);
  if (params.status) query.set("status", params.status);
  if (params.priority) query.set("priority", params.priority);
  if (params.group) query.set("group", params.group);
  if (params.search) query.set("search", params.search);
  if (params.page) query.set("page", params.page.toString());
  if (params.pageSize) query.set("page_size", params.pageSize.toString());

  const headers: Record<string, string> = {};
  if (params.token) headers["Authorization"] = `Bearer ${params.token}`;
  if (params.email) headers["x-user-email"] = params.email;

  const res = await fetch(`${BASE_URL}/api/tickets?${query.toString()}`, { headers });
  if (!res.ok) throw new Error(await res.text());
  return res.json();
}
```

---

## 5. React Integration Example (`ChatBox.tsx`)

```tsx
import React, { useState } from "react";
import { sendChatMessage, ChatMessage, TicketDraft } from "./apiClient";

interface Props {
  userEmail: string;
  userToken: string;
}

export const ChatBox: React.FC<Props> = ({ userEmail, userToken }) => {
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [input, setInput] = useState("");
  const [loading, setLoading] = useState(false);
  const [pendingDraft, setPendingDraft] = useState<TicketDraft | undefined>();

  const handleSend = async (textToSend?: string) => {
    const text = textToSend || input;
    if (!text.trim() || loading) return;

    const userMsg: ChatMessage = { role: "user", content: text };
    const updatedHistory = [...messages, userMsg];
    setMessages(updatedHistory);
    setInput("");
    setLoading(true);

    try {
      const response = await sendChatMessage({
        message: text,
        email: userEmail,
        token: userToken,
        history: updatedHistory,
        pendingDraft,
      });

      const assistantMsg: ChatMessage = {
        role: "assistant",
        content: response.reply,
        data: response.data,
      };

      setMessages([...updatedHistory, assistantMsg]);
      setPendingDraft(response.draft || undefined);
    } catch (err: any) {
      setMessages([
        ...updatedHistory,
        { role: "assistant", content: `❌ Error: ${err.message}` },
      ]);
    } finally {
      setLoading(false);
    }
  };

  return (
    <div style={{ maxWidth: 800, margin: "0 auto", padding: 20 }}>
      <h2>💬 AMS AI Ticket Assistant</h2>
      <div style={{ fontSize: "12px", color: "#666", marginBottom: 8 }}>
        Authenticated as: <strong>{userEmail}</strong>
      </div>

      <div style={{ height: 450, overflowY: "auto", border: "1px solid #ccc", padding: 12, borderRadius: 8 }}>
        {messages.map((m, idx) => (
          <div key={idx} style={{ marginBottom: 12, textAlign: m.role === "user" ? "right" : "left" }}>
            <strong>{m.role === "user" ? "You" : "Assistant"}:</strong>
            <div style={{ whiteSpace: "pre-wrap" }}>{m.content}</div>
            {m.data && Array.isArray(m.data) && (
              <div style={{ fontSize: "12px", background: "#f1f5f9", padding: 8, marginTop: 4, borderRadius: 4 }}>
                Loaded {m.data.length} matching ticket record(s).
              </div>
            )}
          </div>
        ))}
        {loading && <div>Thinking...</div>}
      </div>

      {pendingDraft?.ready_for_confirmation && (
        <div style={{ marginTop: 10, padding: 12, background: "#e0f2fe", borderRadius: 8 }}>
          <p style={{ margin: "0 0 8px 0" }}>📋 <strong>Ticket draft is ready!</strong></p>
          <button onClick={() => handleSend("confirm")} style={{ marginRight: 8 }}>
            ✅ Confirm & Create Ticket
          </button>
          <button onClick={() => handleSend("cancel")}>❌ Cancel Draft</button>
        </div>
      )}

      <div style={{ display: "flex", marginTop: 12 }}>
        <input
          style={{ flex: 1, padding: 8 }}
          value={input}
          onChange={(e) => setInput(e.target.value)}
          onKeyDown={(e) => e.key === "Enter" && handleSend()}
          placeholder="Ask a question or type 'create ticket for Karamtara: Login issue, priority High'..."
        />
        <button onClick={() => handleSend()} style={{ marginLeft: 8, padding: "8px 16px" }}>
          Send
        </button>
      </div>
    </div>
  );
};
```
