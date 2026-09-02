"""
main.py - AMS Ticket Assistant & Management REST API
High-performance FastAPI backend designed to connect with any modern frontend project (React, Next.js, Vue, Angular, Mobile).
"""

import os
import re
import time
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from fastapi import FastAPI, HTTPException, Query, Header, status
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field
from dotenv import load_dotenv

from ams_api import AMSApi
from Module_Router import assign_group, GROUPS, MODULES
from ticket_filter import filter_tickets
from query_engine import (
    process_ticket_query,
    parse_chat_intent_with_llm,
    get_dataset_metadata,
    execute_query_plan,
    generate_natural_response
)

load_dotenv(override=True)

# ---------------------------------------------------------
# FastAPI App Initialization & CORS Configuration
# ---------------------------------------------------------
app = FastAPI(
    title="AMS Ticket Management & AI Assistant API",
    description="RESTful API backend for AMS ticket querying, AI assistance, analytics, and ticket creation.",
    version="2.0.0",
    docs_url="/docs",
    redoc_url="/redoc"
)

# Allow CORS for any frontend project
cors_origins_env = os.getenv("CORS_ORIGINS", "*")
origins = [o.strip() for o in cors_origins_env.split(",") if o.strip()]

app.add_middleware(
    CORSMiddleware,
    allow_origins=origins if origins else ["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ---------------------------------------------------------
# In-Memory Cache & AMS API Client Manager
# ---------------------------------------------------------
class CacheManager:
    def __init__(self):
        self.ams_api = AMSApi()
        self.tickets: Optional[List[Dict[str, Any]]] = None
        self.ticket_statuses: Optional[List[Dict[str, Any]]] = None
        self.last_ticket_fetch_time: float = 0.0
        self.last_status_fetch_time: float = 0.0
        self.tickets_ttl: int = 300  # 5 minutes
        self.statuses_ttl: int = 60  # 1 minute

    def get_api(self) -> AMSApi:
        return self.ams_api

    def get_tickets(self, force_refresh: bool = False, fallback_empty: bool = False, token: Optional[str] = None, email: Optional[str] = None) -> List[Dict[str, Any]]:
        now = time.time()
        # If user-specific token is provided, fetch directly for that caller
        if token:
            scoped_api = AMSApi(email=email or self.ams_api.email)
            scoped_api.token = token.replace("Bearer ", "").strip() if token.startswith("Bearer ") else token.strip()
            try:
                return scoped_api.get_tickets()
            except Exception as e:
                if fallback_empty:
                    return self.tickets or []
                raise e

        if (
            force_refresh
            or self.tickets is None
            or (now - self.last_ticket_fetch_time > self.tickets_ttl)
        ):
            try:
                self.tickets = self.ams_api.get_tickets()
                self.last_ticket_fetch_time = now
            except Exception as e:
                if fallback_empty:
                    return self.tickets or []
                if self.tickets is None:
                    raise e
        return self.tickets or []

    def get_statuses(self, force_refresh: bool = False, fallback_empty: bool = False, token: Optional[str] = None, email: Optional[str] = None) -> List[Dict[str, Any]]:
        now = time.time()
        if token:
            scoped_api = AMSApi(email=email or self.ams_api.email)
            scoped_api.token = token.replace("Bearer ", "").strip() if token.startswith("Bearer ") else token.strip()
            try:
                return scoped_api.get_ticket_status()
            except Exception as e:
                if fallback_empty:
                    return self.ticket_statuses or []
                raise e

        if (
            force_refresh
            or self.ticket_statuses is None
            or (now - self.last_status_fetch_time > self.statuses_ttl)
        ):
            try:
                self.ticket_statuses = self.ams_api.get_ticket_status()
                self.last_status_fetch_time = now
            except Exception as e:
                if fallback_empty:
                    return self.ticket_statuses or []
                if self.ticket_statuses is None:
                    raise e
        return self.ticket_statuses or []

    def clear(self):
        self.tickets = None
        self.ticket_statuses = None
        self.last_ticket_fetch_time = 0.0
        self.last_status_fetch_time = 0.0


cache_mgr = CacheManager()


def get_scoped_api(email: Optional[str] = None, token: Optional[str] = None) -> AMSApi:
    """
    Returns an AMSApi client instance configured with user-provided token and email,
    falling back to server default credentials.
    """
    base_api = cache_mgr.get_api()
    if token:
        clean_token = token.replace("Bearer ", "").strip() if token.startswith("Bearer ") else token.strip()
        scoped = AMSApi(email=email or base_api.email)
        scoped.token = clean_token
        return scoped
    if email and email != base_api.email:
        scoped = AMSApi(email=email, password=base_api.password)
        return scoped
    return base_api


# ---------------------------------------------------------
# Pydantic Schemas
# ---------------------------------------------------------
class AuthCredentials(BaseModel):
    email: str = Field(..., example="user@example.com")
    password: str = Field(..., example="your_password")


class AuthResponse(BaseModel):
    success: bool
    message: str
    email: Optional[str] = None
    token: Optional[str] = None


class TicketCreatePayload(BaseModel):
    clientName: str = Field(..., example="Karamtara Engineering Pvt Ltd")
    priority: str = Field(..., example="High (Business Impacted)")
    descriptionofTicket: str = Field(..., example="SAP login error for sales module")
    reportedby: Optional[str] = Field(default=None, example="Veera")
    ams: Optional[str] = Field(default="AMS", example="AMS")
    typeofticket: Optional[str] = Field(default="Incident", example="Incident")
    assigntogroup: Optional[str] = Field(default=None, example="SAP-SD")
    screenshort: Optional[str] = Field(default="N/A", example="N/A")
    remarks: Optional[str] = Field(default="Created via AI Ticket Assistant", example="Created via API")


class TicketDraft(BaseModel):
    clientName: Optional[str] = None
    priority: Optional[str] = None
    typeofticket: Optional[str] = "Incident"
    reportedby: Optional[str] = None
    descriptionofTicket: Optional[str] = None
    assigntogroup: Optional[str] = None
    ready_for_confirmation: bool = False


class ChatMessage(BaseModel):
    role: str = Field(..., example="user")  # 'user' | 'assistant'
    content: str = Field(..., example="Show P2 tickets for Karamtara")
    data: Optional[Any] = None


class ChatRequest(BaseModel):
    message: str = Field(..., example="Show all unresolved high priority tickets")
    email: Optional[str] = Field(default=None, example="user@company.com", description="User's email for authorization & ticket attribution")
    token: Optional[str] = Field(default=None, example="eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9...", description="AMS Bearer JWT token")
    history: Optional[List[ChatMessage]] = Field(default_factory=list)
    pending_draft: Optional[TicketDraft] = None


class ChatResponse(BaseModel):
    role: str = "assistant"
    reply: str
    data: Optional[List[Dict[str, Any]]] = None
    draft: Optional[TicketDraft] = None
    intent: Optional[str] = None


class PaginatedTicketsResponse(BaseModel):
    total: int
    page: int
    page_size: int
    total_pages: int
    data: List[Dict[str, Any]]


class SummaryResponse(BaseModel):
    total_tickets: int
    total_statuses: int
    unique_clients: int
    status_counts: Dict[str, int]
    priority_counts: Dict[str, int]
    group_counts: Dict[str, int]


# ---------------------------------------------------------
# Helper Functions for AI Draft Processing
# ---------------------------------------------------------
def merge_llm_entities_into_draft(
    extracted_entities: Dict[str, Any],
    existing_draft: Optional[TicketDraft],
    edit_details: Optional[Dict[str, Any]] = None,
    default_reporter: str = ""
) -> tuple[TicketDraft, List[tuple[str, str, str]], bool]:
    draft_dict = existing_draft.dict() if existing_draft else {}

    # 1. Apply edits if specified
    if edit_details and edit_details.get("target_field") and edit_details.get("new_value"):
        field = edit_details["target_field"]
        val = edit_details["new_value"]
        if field in ["clientName", "priority", "descriptionofTicket", "reportedby", "assigntogroup", "typeofticket"]:
            draft_dict[field] = val

    # 2. Merge extracted entities if not already set or updated
    for k, v in (extracted_entities or {}).items():
        if v is not None and str(v).strip():
            draft_dict[k] = v

    # 3. Default fallback for reported by
    if not draft_dict.get("reportedby") and default_reporter:
        draft_dict["reportedby"] = default_reporter

    # 4. Auto assign group if description exists and group is not set
    if draft_dict.get("descriptionofTicket") and not draft_dict.get("assigntogroup"):
        draft_dict["assigntogroup"] = assign_group(draft_dict["descriptionofTicket"])

    # 5. Check missing required fields
    missing_fields = []
    if not draft_dict.get("clientName"):
        missing_fields.append(("Client Name", "client: <Organization Name>", "e.g. `client: Karamtara Engineering Pvt Ltd`"))
    if not draft_dict.get("priority"):
        missing_fields.append(("Priority", "priority: <Low | Medium | High | Critical>", "e.g. `priority: High`"))
    if not draft_dict.get("descriptionofTicket"):
        missing_fields.append(("Issue Description", "issue: <Details of the issue>", "e.g. `issue: SAP login authentication failure`"))
    if not draft_dict.get("reportedby"):
        missing_fields.append(("Reported By", "reported by: <Your Name>", "e.g. `reported by: Veera`"))

    is_complete = len(missing_fields) == 0
    draft_dict["ready_for_confirmation"] = is_complete

    return TicketDraft(**draft_dict), missing_fields, is_complete


def submit_draft(api: AMSApi, draft: TicketDraft) -> Dict[str, Any]:
    """Submits a confirmed ticket draft to AMS API and returns response details."""
    client_name = draft.clientName or "General"
    priority = draft.priority or "Medium"
    type_of_ticket = draft.typeofticket or "Incident"
    reported_by = draft.reportedby or "Veera"
    description = draft.descriptionofTicket or "No description provided"
    assigned_group = draft.assigntogroup or assign_group(description)

    now_utc = datetime.now(timezone.utc)
    reported_on_iso = now_utc.strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"
    reported_on_time_str = datetime.now().time().strftime("%H:%M")

    payload = {
        "clientName": client_name,
        "ams": "AMS",
        "typeofticket": type_of_ticket,
        "priority": priority,
        "reportedon": reported_on_iso,
        "reportedontime": reported_on_time_str,
        "reportedby": reported_by,
        "descriptionofTicket": description,
        "screenshort": "N/A",
        "remarks": f"Created via AI Ticket Assistant (Assign To Group: {assigned_group})",
        "assigntogroup": assigned_group
    }

    create_res = api.create_ticket(payload)
    cache_mgr.clear()  # Refresh cache next time
    return {
        "success": True,
        "payload": payload,
        "api_response": create_res,
        "created_at": now_utc.isoformat()
    }


# ---------------------------------------------------------
# API Endpoints
# ---------------------------------------------------------

@app.get("/", tags=["General"])
@app.get("/health", tags=["General"])
def health_check():
    """Health check endpoint to verify backend connectivity."""
    api = cache_mgr.get_api()
    return {
        "status": "online",
        "service": "AMS Ticket Management & AI Assistant API",
        "version": "2.0.0",
        "authenticated": bool(api.token),
        "user_email": api.email or None,
        "timestamp": datetime.now(timezone.utc).isoformat()
    }


@app.get("/api/info", tags=["General"])
def get_api_info():
    """Get metadata about loaded tickets, available groups, and API state."""
    api = cache_mgr.get_api()
    tickets_count = len(cache_mgr.tickets) if cache_mgr.tickets else 0
    statuses_count = len(cache_mgr.ticket_statuses) if cache_mgr.ticket_statuses else 0
    return {
        "tickets_cached": tickets_count,
        "statuses_cached": statuses_count,
        "groups_count": len(GROUPS),
        "ams_endpoints": {
            "auth": api.auth_url,
            "tickets": api.ticket_url,
            "status": api.ticket_status_url,
            "create": api.ticket_create_url
        }
    }


# ---------------------------------------------------------
# Auth Endpoints
# ---------------------------------------------------------
@app.post("/api/auth/login", response_model=AuthResponse, tags=["Authentication"])
def login(credentials: AuthCredentials):
    """Authenticate with AMS API using email and password."""
    api = cache_mgr.get_api()
    try:
        token = api.authenticate(email=credentials.email, password=credentials.password)
        cache_mgr.clear()
        return AuthResponse(
            success=True,
            message="Successfully authenticated with AMS",
            email=api.email,
            token=token
        )
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=f"Authentication failed: {str(e)}"
        )


@app.get("/api/auth/status", response_model=AuthResponse, tags=["Authentication"])
def auth_status():
    """Check current authentication status and active token."""
    api = cache_mgr.get_api()
    return AuthResponse(
        success=bool(api.token),
        message="Active session" if api.token else "Not authenticated",
        email=api.email or None,
        token=api.token
    )


# ---------------------------------------------------------
# Tickets Endpoints
# ---------------------------------------------------------
@app.get("/api/tickets", response_model=PaginatedTicketsResponse, tags=["Tickets"])
def get_all_tickets(
    client: Optional[str] = Query(None, description="Filter by client name"),
    status: Optional[str] = Query(None, description="Filter by ticket status"),
    priority: Optional[str] = Query(None, description="Filter by priority"),
    group: Optional[str] = Query(None, description="Filter by assignment group or module"),
    search: Optional[str] = Query(None, description="Global text search"),
    page: int = Query(1, ge=1, description="Page number"),
    page_size: int = Query(50, ge=1, le=500, description="Items per page"),
    refresh: bool = Query(False, description="Force fresh fetch from AMS API"),
    authorization: Optional[str] = Header(None, description="Bearer <token>"),
    x_user_email: Optional[str] = Header(None, description="User email")
):
    """
    Retrieve all tickets from AMS with full filtering, global search, and pagination.
    Supports user-scoped Bearer token authentication via Authorization header.
    """
    try:
        raw_tickets = cache_mgr.get_tickets(
            force_refresh=refresh,
            token=authorization,
            email=x_user_email
        )
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"Could not load tickets from AMS: {str(e)}"
        )

    # Apply filters
    filtered = filter_tickets(
        tickets=raw_tickets,
        client_name=client,
        status=status,
        priority=priority,
        assigntogroup=group,
        search_text=search
    )

    total = len(filtered)
    total_pages = max(1, (total + page_size - 1) // page_size)
    start_idx = (page - 1) * page_size
    paginated_data = filtered[start_idx : start_idx + page_size]

    return PaginatedTicketsResponse(
        total=total,
        page=page,
        page_size=page_size,
        total_pages=total_pages,
        data=paginated_data
    )


@app.get("/api/tickets/status", tags=["Tickets"])
def get_ticket_statuses(
    status: Optional[str] = Query(None, description="Filter by status (e.g. Created, Closed)"),
    priority: Optional[str] = Query(None, description="Filter by priority (e.g. P2, High)"),
    search: Optional[str] = Query(None, description="Search ticketNo, txnId, or remarks"),
    refresh: bool = Query(False, description="Force fresh fetch"),
    authorization: Optional[str] = Header(None, description="Bearer <token>"),
    x_user_email: Optional[str] = Header(None, description="User email")
):
    """
    Get real-time ticket status records from `/api/Ticket/Status`.
    """
    try:
        raw_statuses = cache_mgr.get_statuses(
            force_refresh=refresh,
            token=authorization,
            email=x_user_email
        )
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"Could not load ticket statuses from AMS: {str(e)}"
        )

    result = raw_statuses
    if status and status.lower() != "all":
        result = [x for x in result if str(x.get("ticketStatus", "")).lower() == status.lower()]
    if priority and priority.lower() != "all":
        result = [x for x in result if str(x.get("priority", "")).lower() == priority.lower()]
    if search:
        sq = search.strip().lower()
        result = [
            x for x in result
            if sq in str(x.get("ticketNo", "")).lower()
            or sq in str(x.get("txnId", "")).lower()
            or sq in str(x.get("remarks", "")).lower()
            or sq in str(x.get("ticketStatus", "")).lower()
        ]

    return {
        "total": len(result),
        "data": result
    }


@app.post("/api/tickets", tags=["Tickets"])
def create_ticket(
    payload: TicketCreatePayload,
    authorization: Optional[str] = Header(None, description="Bearer <token>"),
    x_user_email: Optional[str] = Header(None, description="User email")
):
    """
    Create a new ticket directly in AMS.
    If `assigntogroup` is omitted, it will automatically be classified using AI/heuristic module routing.
    """
    effective_reporter = payload.reportedby or x_user_email or "Veera"
    api = get_scoped_api(email=effective_reporter, token=authorization)
    assigned_group = payload.assigntogroup or assign_group(payload.descriptionofTicket)

    now_utc = datetime.now(timezone.utc)
    reported_on_iso = now_utc.strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"
    reported_on_time_str = datetime.now().time().strftime("%H:%M")

    body = {
        "clientName": payload.clientName.strip(),
        "ams": payload.ams or "AMS",
        "typeofticket": payload.typeofticket or "Incident",
        "priority": payload.priority.strip(),
        "reportedon": reported_on_iso,
        "reportedontime": reported_on_time_str,
        "reportedby": effective_reporter,
        "descriptionofTicket": payload.descriptionofTicket.strip(),
        "screenshort": payload.screenshort or "N/A",
        "remarks": payload.remarks or f"Created via API (Assigned: {assigned_group})",
        "assigntogroup": assigned_group
    }

    try:
        res = api.create_ticket(body)
        cache_mgr.clear()
        return {
            "success": True,
            "message": "Ticket created successfully",
            "assigned_group": assigned_group,
            "response": res,
            "submitted_payload": body
        }
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Failed to create ticket: {str(e)}"
        )


@app.get("/api/tickets/summary", response_model=SummaryResponse, tags=["Analytics"])
def get_tickets_summary():
    """
    Get high-level analytics and aggregations (counts by status, priority, client, assignment group).
    """
    tickets = cache_mgr.get_tickets(fallback_empty=True)
    statuses = cache_mgr.get_statuses(fallback_empty=True)

    status_counts: Dict[str, int] = {}
    priority_counts: Dict[str, int] = {}
    group_counts: Dict[str, int] = {}
    clients = set()

    for t in tickets:
        st_val = str(t.get("ticketStatus") or "Unknown")
        status_counts[st_val] = status_counts.get(st_val, 0) + 1

        pr_val = str(t.get("priority") or "Unspecified")
        priority_counts[pr_val] = priority_counts.get(pr_val, 0) + 1

        gp_val = str(t.get("assigntogroup") or t.get("module") or "Unassigned")
        group_counts[gp_val] = group_counts.get(gp_val, 0) + 1

        c_name = t.get("clientName")
        if c_name:
            clients.add(str(c_name))

    return SummaryResponse(
        total_tickets=len(tickets),
        total_statuses=len(statuses),
        unique_clients=len(clients),
        status_counts=status_counts,
        priority_counts=priority_counts,
        group_counts=group_counts
    )


# ---------------------------------------------------------
# Metadata Endpoints
# ---------------------------------------------------------
@app.get("/api/meta/clients", tags=["Metadata"])
def get_registered_clients():
    """Get sorted list of all unique client names present in AMS tickets dataset."""
    tickets = cache_mgr.get_tickets(fallback_empty=True)
    client_set = {str(x["clientName"]).strip() for x in tickets if x.get("clientName")}
    for default_c in ["Karamtara Engineering Pvt Ltd", "AAB", "ATG", "ACSEN HyVeg Pvt Ltd", "AJAX Engineering Pvt Ltd"]:
        client_set.add(default_c)
    return {"clients": sorted(list(client_set))}


@app.get("/api/meta/groups", tags=["Metadata"])
def get_assignment_groups():
    """Get list of all supported AMS assignment groups and SAP modules."""
    return {"groups": GROUPS, "modules": MODULES}


@app.post("/api/cache/clear", tags=["Maintenance"])
def clear_caches():
    """Force clear all in-memory ticket and status caches."""
    cache_mgr.clear()
    return {"success": True, "message": "Cache cleared"}


# ---------------------------------------------------------
# AI Chat & Conversational Assistant Endpoint
# ---------------------------------------------------------
@app.post("/api/chat", response_model=ChatResponse, tags=["AI Assistant"])
def chat_assistant(
    request: ChatRequest,
    authorization: Optional[str] = Header(None, description="Bearer <token>")
):
    """
    Conversational AI Endpoint powered by LLM Intent Understanding:
    - Accepts message, email, and Bearer token in request body or Authorization header.
    - Uses LLM NLU to semantically understand intent (queries, ticket creation, edits, confirmations, cancellations, greetings, capabilities).
    - Submits tickets attributed to the authenticated user's identity.
    """
    # 1. Resolve Authorization Token & User Email
    effective_token = request.token or authorization
    effective_email = request.email
    scoped_api = get_scoped_api(email=effective_email, token=effective_token)

    user_msg = request.message.strip()
    history_list = [{"role": m.role, "content": m.content, "data": m.data} for m in (request.history or [])]

    # Fetch pool scoped to user if token provided
    pool = cache_mgr.get_tickets(fallback_empty=True, token=effective_token, email=effective_email)
    if not pool:
        pool = cache_mgr.get_statuses(fallback_empty=True, token=effective_token, email=effective_email) or []

    # Step 1: Use LLM to understand intent and extract entities semantically
    meta = get_dataset_metadata(pool)
    active_draft_dict = request.pending_draft.dict() if request.pending_draft else None

    llm_analysis = parse_chat_intent_with_llm(
        user_question=user_msg,
        meta=meta,
        active_draft=active_draft_dict,
        history=history_list
    )

    intent = llm_analysis.get("intent", "ticket_query")
    extracted = llm_analysis.get("extracted_entities", {})
    edit_info = llm_analysis.get("edit_details", {})
    query_plan = llm_analysis.get("query_plan") or {}

    # Case 1: Greeting
    if intent == "greeting":
        reply = llm_analysis.get("direct_response") or (
            "👋 **Hello! I'm your Dynamic AMS Ticket Intelligence Assistant.**\n\n"
            "I can help you search, filter, analyze tickets, and create new AMS tickets.\n\n"
            "How can I assist you today?"
        )
        return ChatResponse(reply=reply, intent="greeting")

    # Case 2: Capability inquiry / Help
    if intent == "capability_inquiry":
        reply = llm_analysis.get("direct_response") or (
            "### 🎫 How I Can Help You:\n\n"
            "1. **Ticket Intelligence & Search**:\n"
            "   - *'Show unresolved P2 tickets for ATG'*\n"
            "   - *'Which client has the most tickets?'*\n"
            "   - *'Count of open SAP-MM tickets reported this week'*\n\n"
            "2. **Create Tickets**:\n"
            "   - Specify in one message: *'Create ticket for Karamtara: SAP login failure, priority High, reported by Veera'*\n"
            "   - Or start step-by-step: *'I need to raise a ticket'*."
        )
        return ChatResponse(reply=reply, intent="capability_inquiry")

    # Case 3: Cancellation of active draft
    if intent == "ticket_cancellation":
        return ChatResponse(
            reply="🧹 Ticket draft has been cancelled. You can search tickets or start a new request anytime.",
            draft=None,
            intent="draft_cancelled"
        )

    # Case 4: Confirmation of ready draft
    if intent == "ticket_confirmation":
        if request.pending_draft and request.pending_draft.ready_for_confirmation:
            try:
                sub_res = submit_draft(scoped_api, request.pending_draft)
                d = request.pending_draft
                reply = (
                    "### 🎉 Ticket Created Successfully!\n\n"
                    f"- **🏢 Client**: `{d.clientName}`\n"
                    f"- **⚡ Priority**: `{d.priority}`\n"
                    f"- **📂 Type**: `{d.typeofticket}`\n"
                    f"- **🏷️ Assigned Group**: `{d.assigntogroup}`\n"
                    f"- **👤 Reported By**: `{d.reportedby}`\n"
                    f"- **📝 Description**: {d.descriptionofTicket}\n\n"
                    "🔄 *Ticket caches have been automatically refreshed.*"
                )
                return ChatResponse(reply=reply, draft=None, intent="ticket_submitted")
            except Exception as ex:
                return ChatResponse(
                    reply=f"### ❌ Ticket Creation Failed\n\nAMS API returned an error:\n> `{str(ex)}`",
                    draft=request.pending_draft,
                    intent="ticket_submission_failed"
                )
        else:
            return ChatResponse(
                reply="There is no completed ticket draft ready for confirmation. Please provide the ticket details to create one.",
                draft=request.pending_draft,
                intent="no_draft_to_confirm"
            )

    # Case 5: Ticket Creation or Draft Editing
    if intent in ["ticket_creation", "draft_edit"]:
        draft, missing_fields, is_complete = merge_llm_entities_into_draft(
            extracted_entities=extracted,
            existing_draft=request.pending_draft,
            edit_details=edit_info if intent == "draft_edit" else None,
            default_reporter=effective_email or scoped_api.email or "Veera"
        )

        if missing_fields:
            status_lines = []
            status_lines.append(f"- 🏢 **Client**: `{draft.clientName}` ✅" if draft.clientName else "- 🏢 **Client**: ❌ *Missing*")
            status_lines.append(f"- ⚡ **Priority**: `{draft.priority}` ✅" if draft.priority else "- ⚡ **Priority**: ❌ *Missing (Low, Medium, High, Critical)*")
            status_lines.append(f"- 📝 **Description**: {draft.descriptionofTicket} ✅ (Assigned: `{draft.assigntogroup}`)" if draft.descriptionofTicket else "- 📝 **Description**: ❌ *Missing*")
            status_lines.append(f"- 👤 **Reported By**: `{draft.reportedby}` ✅" if draft.reportedby else "- 👤 **Reported By**: ❌ *Missing*")

            missing_prompts = "\n".join([f"- **{m[0]}**: `{m[1]}` ({m[2]})" for m in missing_fields])

            reply = (
                "### ⚠️ Incomplete Ticket Details\n\n"
                "I need the following information to create your AMS ticket:\n\n"
                + "\n".join(status_lines) + "\n\n"
                "#### ✍️ Please reply with the missing field(s):\n"
                + missing_prompts + "\n\n"
                "*(Type `cancel` to reset this draft)*"
            )
            return ChatResponse(reply=reply, draft=draft, intent="draft_in_progress")
        else:
            reply = (
                "### 📝 Ticket Draft Preview (Pending Confirmation)\n\n"
                "All ticket details have been gathered! Please review below before submission:\n\n"
                f"- 🏢 **Client Name**: `{draft.clientName}`\n"
                f"- ⚡ **Priority**: `{draft.priority}`\n"
                f"- 📂 **Ticket Type**: `{draft.typeofticket}`\n"
                f"- 🏷️ **Assign To Group**: `{draft.assigntogroup}` *(Auto-assigned)*\n"
                f"- 👤 **Reported By**: `{draft.reportedby}`\n"
                f"- 📝 **Description**: {draft.descriptionofTicket}\n\n"
                "---\n"
                "#### ❓ Ready to create this ticket?\n"
                "Reply **`confirm`** / **`yes`** or click confirm to submit to AMS.\n"
                "*(Or reply with changes, e.g. `change priority to Critical`)*"
            )
            return ChatResponse(reply=reply, draft=draft, intent="draft_ready")

    # Case 6: Dynamic Ticket Query / Analytics / Search
    try:
        if not query_plan:
            query_plan = parse_query_plan_with_llm(user_msg, meta, history=history_list)

        df_filtered, summary_stats = execute_query_plan(pool, query_plan)
        natural_answer = generate_natural_response(user_msg, query_plan, summary_stats, df_filtered, history=history_list)
        records = df_filtered.to_dict(orient="records") if not df_filtered.empty else None

        return ChatResponse(
            reply=natural_answer,
            data=records,
            draft=None,
            intent="query_response"
        )
    except Exception as e:
        return ChatResponse(
            reply=f"⚠️ Query processing encountered an error: {str(e)}",
            data=None,
            draft=None,
            intent="error"
        )


# ---------------------------------------------------------
# Run server if invoked directly
# ---------------------------------------------------------
if __name__ == "__main__":
    import uvicorn
    port = int(os.getenv("PORT", 8000))
    host = os.getenv("HOST", "0.0.0.0")
    print(f"[*] Starting AMS Ticket API server at http://{host}:{port}...")
    uvicorn.run("main:app", host=host, port=port, reload=True)
