import os
import streamlit as st
import pandas as pd
from datetime import datetime, timezone
import json
import re
from dotenv import load_dotenv
from ams_api import AMSApi
from ticket_filter import filter_tickets
from Module_Router import assign_module, MODULES

load_dotenv(override=True)

st.set_page_config(
    page_title="AMS Ticket Management & Assistant",
    page_icon="🎫",
    layout="wide"
)

# ---------------------------------------------------------
# Cached API Loaders
# ---------------------------------------------------------
@st.cache_data(ttl=300, show_spinner=False)
def fetch_all_tickets(username, password):
    api = AMSApi(username=username, password=password)
    return api.get_tickets()

@st.cache_data(ttl=60, show_spinner=False)
def fetch_ticket_statuses(username, password):
    api = AMSApi(username=username, password=password)
    return api.get_ticket_status()


def submit_draft_ticket(ams_api, draft):
    """Submits a confirmed ticket draft to AMS API and returns formatted result string."""
    client_name = draft["clientName"]
    
    # Auto-resolve partial client name against registered AMS clients
    tickets_pool = getattr(st.session_state, "tickets", None)
    if tickets_pool:
        known_clients = sorted(list({str(x["clientName"]) for x in tickets_pool if x.get("clientName")}), key=len, reverse=True)
        for kc in known_clients:
            if kc.lower() == client_name.lower() or client_name.lower() in kc.lower():
                client_name = kc
                break

    priority = draft["priority"]
    type_of_ticket = draft.get("typeofticket", "Incident")
    reported_by = draft["reportedby"]
    description = draft["descriptionofTicket"]
    assigned_module = draft.get("module") or assign_module(description)

    now_utc = datetime.now(timezone.utc)
    reported_on_iso = now_utc.strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"
    reported_on_time_str = datetime.now().time().strftime("%H:%M")

    ticket_payload = {
        "clientName": client_name,
        "ams": "AMS",
        "typeofticket": type_of_ticket,
        "priority": priority,
        "reportedon": reported_on_iso,
        "reportedontime": reported_on_time_str,
        "reportedby": reported_by,
        "descriptionofTicket": description,
        "screenshort": "N/A",
        "remarks": f"Created via AI Ticket Assistant (Module: {assigned_module})",
        "module": assigned_module
    }

    create_res = ams_api.create_ticket(ticket_payload)

    new_ticket_no = None
    new_txn_id = None

    if isinstance(create_res, dict):
        new_ticket_no = create_res.get("ticketNo") or create_res.get("ticketNumber") or create_res.get("TicketNo")
        new_txn_id = create_res.get("txnId") or create_res.get("transactionId") or create_res.get("TxnId")
        if not new_ticket_no and isinstance(create_res.get("data"), dict):
            new_ticket_no = create_res["data"].get("ticketNo") or create_res["data"].get("ticketNumber")
            new_txn_id = create_res["data"].get("txnId") or create_res["data"].get("transactionId")
        elif not new_ticket_no and isinstance(create_res.get("result"), dict):
            new_ticket_no = create_res["result"].get("ticketNo") or create_res["result"].get("ticketNumber")
            new_txn_id = create_res["result"].get("txnId") or create_res["result"].get("transactionId")

    try:
        fetch_all_tickets.clear()
        fetch_ticket_statuses.clear()
        fresh_tickets = fetch_all_tickets(ams_api.username, ams_api.password)
        fresh_statuses = fetch_ticket_statuses(ams_api.username, ams_api.password)
        st.session_state.tickets = fresh_tickets
        st.session_state.ticket_statuses = fresh_statuses

        if not new_ticket_no or not new_txn_id:
            candidates = []
            if fresh_statuses:
                candidates.extend([
                    x for x in fresh_statuses
                    if str(x.get("clientName", "")).lower() == client_name.lower()
                    or str(x.get("remarks", "")).lower() in ["created via ai ticket assistant", "no"]
                ])
            if fresh_tickets:
                candidates.extend([
                    x for x in fresh_tickets
                    if str(x.get("clientName", "")).lower() == client_name.lower()
                ])
            if candidates:
                candidates.sort(key=lambda item: int(item.get("txnId") or 0), reverse=True)
                newest = candidates[0]
                new_ticket_no = new_ticket_no or newest.get("ticketNo")
                new_txn_id = new_txn_id or newest.get("txnId")
    except Exception:
        pass

    ticket_no_display = f"`{new_ticket_no}`" if new_ticket_no else "*Generated in AMS*"
    txn_id_display = f"`{new_txn_id}`" if new_txn_id else "*Generated in AMS*"

    answer = (
        f"### 🎉 Ticket Created Successfully!\n\n"
        f"The ticket has been created and submitted to AMS (`POST /api/Ticket/CreateTicket`).\n\n"
        f"- **🎫 Ticket Number**: {ticket_no_display}\n"
        f"- **🔢 Transaction ID**: {txn_id_display}\n"
        f"- **🏢 Client**: `{client_name}`\n"
        f"- **⚡ Priority**: `{priority}`\n"
        f"- **📂 Type**: `{type_of_ticket}`\n"
        f"- **🏷️ Module**: `{assigned_module}` *(Assigned by AI Agent)*\n"
        f"- **👤 Reported By**: `{reported_by}`\n"
        f"- **📝 Description**: {description}\n"
        f"- **🕒 Timestamp**: `{now_utc.strftime('%Y-%m-%d %H:%M:%S UTC')}`\n\n"
    )
    if isinstance(create_res, dict) and create_res.get("message"):
        answer += f"> **API Response**: {create_res.get('message')}\n\n"

    answer += "🔄 *Ticket caches have been automatically refreshed.*"
    return answer

# ---------------------------------------------------------
# Initialize API & Session State
# ---------------------------------------------------------
if "ams_api" not in st.session_state:
    st.session_state.ams_api = AMSApi()

ams_api = st.session_state.ams_api

if "tickets" not in st.session_state:
    st.session_state.tickets = None

if "ticket_statuses" not in st.session_state:
    st.session_state.ticket_statuses = None

if "pending_ticket_draft" not in st.session_state:
    st.session_state.pending_ticket_draft = None

if "messages" not in st.session_state:
    st.session_state.messages = []

# ---------------------------------------------------------
# Sidebar
# ---------------------------------------------------------
with st.sidebar:
    st.header("⚙️ AMS Configuration")
    
    load_dotenv(override=True)
    env_user = os.getenv("AMS_USERNAME") or os.getenv("AMS_USER") or os.getenv("USERNAME") or ""
    
    username_val = ams_api.username
    password_val = ams_api.password
    
    input_username = st.text_input("Username", value=username_val, placeholder="Enter AMS Username")
    input_password = st.text_input("Password", value=password_val, type="password", placeholder="Enter AMS Password")
    
    ams_api.username = input_username
    ams_api.password = input_password

    if env_user:
        st.caption(f"💡 Default username loaded from `.env`: `{env_user}`")
    else:
        st.caption("ℹ️ You can set `AMS_USERNAME` and `AMS_PASSWORD` in `.env` for auto-login.")

    st.divider()
    st.subheader("⚡ Quick Actions")

    col_btn1, col_btn2 = st.columns(2)
    with col_btn1:
        if st.button("📑 All Tickets", use_container_width=True, help="Fetch from /api/Ticket"):
            try:
                with st.spinner("Loading tickets (/api/Ticket)..."):
                    fetch_all_tickets.clear()
                    tickets = fetch_all_tickets(ams_api.username, ams_api.password)
                    st.session_state.tickets = tickets
                st.success(f"Loaded {len(tickets)} tickets.")
            except Exception as e:
                st.error(f"Ticket load error:\n{e}")

    with col_btn2:
        if st.button("📋 Status List", use_container_width=True, help="Fetch from /api/Ticket/Status"):
            try:
                with st.spinner("Fetching statuses (/api/Ticket/Status)..."):
                    fetch_ticket_statuses.clear()
                    statuses = fetch_ticket_statuses(ams_api.username, ams_api.password)
                    st.session_state.ticket_statuses = statuses
                st.success(f"Loaded {len(statuses)} statuses.")
            except Exception as e:
                st.error(f"Status fetch error:\n{e}")

    # Auto-load initial data if credentials are present
    if st.session_state.tickets is None and ams_api.username and ams_api.password:
        try:
            st.session_state.tickets = fetch_all_tickets(ams_api.username, ams_api.password)
        except Exception:
            pass

    if st.session_state.ticket_statuses is None and ams_api.username and ams_api.password:
        try:
            st.session_state.ticket_statuses = fetch_ticket_statuses(ams_api.username, ams_api.password)
        except Exception:
            pass

    if st.session_state.tickets is not None:
        st.metric("All Tickets (/api/Ticket)", len(st.session_state.tickets))
        print()
    if st.session_state.ticket_statuses is not None:
        st.metric("Status Records (/api/Ticket/Status)", len(st.session_state.ticket_statuses))

    if st.session_state.tickets is not None or st.session_state.ticket_statuses is not None:
        if st.button("🗑️ Clear Cache & Data", use_container_width=True):
            fetch_all_tickets.clear()
            fetch_ticket_statuses.clear()
            st.session_state.tickets = None
            st.session_state.ticket_statuses = None
            st.rerun()

# ---------------------------------------------------------
# Header & Navigation
# ---------------------------------------------------------
st.title("🎫 SAP AMS Ticket Portal")
st.caption("Complete AMS management: Detailed Tickets, Real-time Status, Ticket Creation, & AI Assistant")

tab_chat, tab_all_tickets, tab_status, tab_create = st.tabs([
    "💬 AI Ticket Assistant",
    "📑 All Tickets (/api/Ticket)",
    "📋 Ticket Status View (/api/Ticket/Status)",
    "➕ Create Ticket (/api/Ticket/CreateTicket)"
])

# =========================================================
# TAB 1: AI Ticket Assistant / Chat
# =========================================================
with tab_chat:
    st.subheader("💬 AI Ticket Assistant")
    
    # Active index badge
    total_loaded = len(st.session_state.tickets) if st.session_state.tickets else 0
    if total_loaded > 0:
        st.caption(f"🟢 **{total_loaded:,} tickets loaded & indexed** from AMS database")
    else:
        st.caption("Ask questions and search through loaded AMS tickets")

    # Display chat history
    for message in st.session_state.messages:
        with st.chat_message(message["role"]):
            st.markdown(message["content"])
            if "data" in message and message["data"]:
                df = pd.DataFrame(message["data"])
                display_columns = [
                    "ticketNo", "clientName", "priority", "ticketStatus",
                    "module", "createdname", "remarks", "createddate", "closedondate", "txnId"
                ]
                available_columns = [c for c in display_columns if c in df.columns]
                if available_columns:
                    st.dataframe(df[available_columns], use_container_width=True, hide_index=True)
                else:
                    st.dataframe(df, use_container_width=True, hide_index=True)

    # Interactive draft confirmation controls if a complete draft is pending confirmation
    if st.session_state.pending_ticket_draft and st.session_state.pending_ticket_draft.get("ready_for_confirmation"):
        draft_info = st.session_state.pending_ticket_draft
        with st.container(border=True):
            st.markdown(f"📋 **Draft Ready for Confirmation**: Client: `{draft_info.get('clientName')}` | Priority: `{draft_info.get('priority')}` | Module: `{draft_info.get('module')}`")
            col_c1, col_c2 = st.columns(2)
            with col_c1:
                if st.button("✅ Confirm & Create Ticket", type="primary", use_container_width=True, key="confirm_ticket_btn"):
                    st.session_state.messages.append({"role": "user", "content": "✅ Confirmed ticket creation"})
                    try:
                        with st.spinner(f"Submitting ticket for '{draft_info.get('clientName')}' to AMS API..."):
                            res_msg = submit_draft_ticket(ams_api, draft_info)
                        st.session_state.messages.append({"role": "assistant", "content": res_msg, "data": None})
                    except Exception as ex:
                        st.session_state.messages.append({
                            "role": "assistant",
                            "content": f"### ❌ Ticket Creation Failed\n\nThe AMS API returned an error:\n> `{ex}`\n\nEnsure client name matches a valid registered client in AMS.",
                            "data": None
                        })
                    st.session_state.pending_ticket_draft = None
                    st.rerun()
            with col_c2:
                if st.button("❌ Cancel Draft", use_container_width=True, key="cancel_ticket_btn"):
                    st.session_state.pending_ticket_draft = None
                    st.session_state.messages.append({"role": "assistant", "content": "🧹 Ticket draft cancelled.", "data": None})
                    st.rerun()

    user_question = st.chat_input("Ask about tickets (e.g. 'Show P2 tickets') or create one (e.g. 'create ticket for Karamtara: Login issue, priority High')...")

    if user_question:
        st.session_state.messages.append({
            "role": "user",
            "content": user_question
        })
        with st.chat_message("user"):
            st.markdown(user_question)

        # Ensure tickets are loaded
        if st.session_state.tickets is None:
            try:
                with st.spinner("Loading ticket database from AMS API (/api/Ticket)..."):
                    st.session_state.tickets = fetch_all_tickets(ams_api.username, ams_api.password)
            except Exception as ex:
                st.warning(f"Could not load full ticket dataset: {ex}")

        pool = st.session_state.tickets or st.session_state.ticket_statuses or []
        question = user_question.lower().strip()

        # Check for Ticket Creation intent or ongoing draft
        has_active_draft = bool(st.session_state.pending_ticket_draft)
        
        # Check if the question is a general inquiry about ticket creation capabilities (e.g., "can you create ticket?")
        is_capability_question = bool(re.search(
            r'^(can you|could you|how to|how do i|is it possible to|are you able to|do you|help me)\s+(create|raise|open|log)\s+(a\s+|an\s+|the\s+)?tickets?\??$',
            question
        ))

        if is_capability_question and not has_active_draft:
            answer = (
                "### 🎫 Yes, I can create tickets for you!\n\n"
                "You can create a new AMS ticket in any of the following ways:\n\n"
                "1. **Specify details in a single message**:\n"
                "   > `create ticket for Karamtara: SAP login authentication failure, priority High`\n\n"
                "2. **Use parameter tags**:\n"
                "   > `client: Karamtara, priority: High, issue: SAP login authentication failure`\n\n"
                "3. **Start an interactive prompt**:\n"
                "   > Type `create ticket` or `create ticket for <Client>` to begin step-by-step entry.\n\n"
                "How would you like to proceed?"
            )
            filtered = None
            ticket_no = None
            count = 0
            st.session_state.messages.append({"role": "assistant", "content": answer, "data": None})
            st.rerun()

        creation_intent = False
        creation_keywords = [
            "create ticket", "create a ticket", "create new ticket", "create an ams ticket",
            "raise ticket", "raise a ticket", "raise new ticket",
            "open ticket", "open a ticket", "open new ticket",
            "log ticket", "log a ticket", "log new ticket",
            "new ticket", "generate ticket"
        ]
        for kw in creation_keywords:
            if re.search(r'\b' + re.escape(kw) + r'\b', question):
                creation_intent = True
                break

        if not creation_intent and re.search(r'\b(can you|could you|please|how to|how do i)\s+(create|raise|open|log)\s+(a\s+|an\s+|the\s+)?ticket', question):
            creation_intent = True

        if not creation_intent and (("client:" in question or "client name:" in question) and ("issue:" in question or "desc:" in question or "description:" in question)):
            creation_intent = True

        # Check if user wants to cancel an ongoing draft
        if has_active_draft and question in ["cancel", "reset", "stop", "abort", "clear"]:
            st.session_state.pending_ticket_draft = None
            answer = "🧹 Draft cancelled. You can ask ticket search questions or start a new ticket creation anytime."
            filtered = None
            ticket_no = None
            count = 0
            st.session_state.messages.append({"role": "assistant", "content": answer, "data": None})
            st.rerun()

        # If user is in an active draft and not performing an explicit search for existing tickets
        is_direct_search = bool(re.search(r'\b([A-Za-z]{2,8}\d{4,10})\b', user_question)) or ("show me" in question and not creation_intent)
        if has_active_draft and not is_direct_search:
            creation_intent = True

        if creation_intent:
            # Initialize or carry over existing draft
            draft = dict(st.session_state.pending_ticket_draft or {})

            # 0. Explicit Edit Command Detection (e.g. "edit priority to medium", "change client to ATG")
            is_edit_command = False
            edit_match = re.search(
                r'\b(?:edit|change|update|set|modify)\s+(priority|client|client\s+name|description|issue|desc|reported\s*by|reporter|type|ticket\s+type)\s*(?:to|is|=|:)?\s*(.+)',
                user_question,
                re.IGNORECASE
            )
            if edit_match:
                is_edit_command = True
                field_target = edit_match.group(1).lower().strip()
                new_val = edit_match.group(2).strip()

                if "priority" in field_target:
                    if re.search(r'\b(very high|critical|p1|production impacted)\b', new_val, re.IGNORECASE):
                        draft["priority"] = "Very High (Production Impacted)"
                    elif re.search(r'\b(high|p2|business impacted)\b', new_val, re.IGNORECASE):
                        draft["priority"] = "High (Business Impacted)"
                    elif re.search(r'\b(medium|med|p3)\b', new_val, re.IGNORECASE):
                        draft["priority"] = "Medium"
                    elif re.search(r'\b(low|p4)\b', new_val, re.IGNORECASE):
                        draft["priority"] = "Low"
                    else:
                        draft["priority"] = new_val.capitalize()

                elif "client" in field_target:
                    draft["clientName"] = new_val.strip(" .")

                elif any(k in field_target for k in ["description", "issue", "desc"]):
                    draft["descriptionofTicket"] = new_val.strip(" .")

                elif any(k in field_target for k in ["reported", "reporter", "by"]):
                    draft["reportedby"] = new_val.strip(" .")

                elif "type" in field_target:
                    draft["typeofticket"] = new_val.strip(" .")

            if not is_edit_command:
                # 1. Priority detection & extraction
                priority_match = re.search(r'\bpriority\s*(?:is|:=|=|:)?\s*([^,\.\n;]+)', user_question, re.IGNORECASE)
                if priority_match:
                    p_val = priority_match.group(1).strip()
                    if not re.search(r'^(?:issue|desc|description|client|by|reported|type)\b', p_val, re.IGNORECASE):
                        p_lower = p_val.lower()
                        if re.search(r'\b(very high|critical|p1|production impacted)\b', p_lower):
                            draft["priority"] = "Very High (Production Impacted)"
                        elif re.search(r'\b(high|p2|business impacted)\b', p_lower):
                            draft["priority"] = "High (Business Impacted)"
                        elif re.search(r'\b(medium|med|p3)\b', p_lower):
                            draft["priority"] = "Medium"
                        elif re.search(r'\b(low|p4)\b', p_lower):
                            draft["priority"] = "Low"

                if not draft.get("priority"):
                    if re.search(r'\b(very high|critical|p1|production impacted)\b', question):
                        draft["priority"] = "Very High (Production Impacted)"
                    elif re.search(r'\b(high|p2|business impacted)\b', question):
                        draft["priority"] = "High (Business Impacted)"
                    elif re.search(r'\b(medium|med|p3)\b', question):
                        draft["priority"] = "Medium"
                    elif re.search(r'\b(low|p4)\b', question):
                        draft["priority"] = "Low"

                # 2. Type of ticket detection
                for t_type in ["Service Request", "Change Request", "S PO", "Incident"]:
                    if re.search(r'\b' + re.escape(t_type.lower()) + r'\b', question):
                        draft["typeofticket"] = t_type
                        break
                if not draft.get("typeofticket"):
                    draft["typeofticket"] = "Incident"

                # 3. Client Name extraction
                client_match = re.search(r'(?:client(?:\s*name)?|organization)\s*(?:is|:=|=|:)\s*([^,\.\n;]+)', user_question, re.IGNORECASE)
                if client_match:
                    c_val = client_match.group(1).strip()
                    if not re.search(r'^(?:priority|type|issue|desc|description|by|reported)\b', c_val, re.IGNORECASE):
                        draft["clientName"] = c_val

                # Direct lookup in pool client names if not extracted yet
                if not draft.get("clientName"):
                    known_clients = sorted(list({str(x["clientName"]) for x in pool if x.get("clientName")}), key=len, reverse=True) if pool else []
                    default_clients = ["Karamtara Engineering Pvt Ltd", "AAB", "ATG", "ACSEN HyVeg Pvt Ltd", "AJAX Engineering Pvt Ltd"]
                    for dc in default_clients:
                        if dc not in known_clients:
                            known_clients.append(dc)
                    known_clients.sort(key=len, reverse=True)

                    for c_name in known_clients:
                        if len(c_name) <= 4:
                            if re.search(r'\b' + re.escape(c_name) + r'\b', user_question, re.IGNORECASE):
                                draft["clientName"] = c_name
                                break
                        else:
                            if c_name.lower() in question:
                                draft["clientName"] = c_name
                                break

                if not draft.get("clientName"):
                    for_match = re.search(r'\bfor\s+(?:client\s+)?([A-Za-z0-9\s&.]+?)(?:\s*[:,]|\s+with|\s+priority|\s+issue|\s+desc|\s+by|$|\.)', user_question, re.IGNORECASE)
                    if for_match:
                        candidate = for_match.group(1).strip()
                        if candidate.lower() not in ["ticket", "a ticket", "the ticket", "ams", "sap", "incident", "issue", "me", "us", "help"]:
                            draft["clientName"] = candidate

                # 4. Reported By extraction
                by_match = re.search(r'(?:reported\s*by|reporter|by)\s*(?:is|:=|=|:)?\s*([A-Za-z0-9\s&_.]+?)(?:\.|\,|\;|\b(?:client|priority|type|issue|desc|description)\b|$)', user_question, re.IGNORECASE)
                if by_match:
                    by_val = by_match.group(1).strip()
                    if not re.search(r'^(?:client|priority|type|issue|desc|description)\b', by_val, re.IGNORECASE):
                        draft["reportedby"] = by_val

                if not draft.get("reportedby") and ams_api.username and ams_api.username != "your_username":
                    draft["reportedby"] = ams_api.username

                # 5. Description extraction
                desc_match = re.search(r'(?:description|desc|issue|problem|summary)\s*(?:is|:=|=|:)\s*(.+)', user_question, re.IGNORECASE | re.DOTALL)
                if desc_match:
                    d_val = desc_match.group(1).strip()
                    d_val = re.split(r'[\.,]\s*(?:priority|reported\s*by|by|type|client|screenshort|remarks)\b', d_val, flags=re.IGNORECASE)[0].strip()
                    d_val = re.sub(r',?\s*priority\s+(?:p[1-4]|very high|high|medium|low|critical)\b.*$', '', d_val, flags=re.IGNORECASE).strip()
                    if d_val:
                        draft["descriptionofTicket"] = d_val

                if not draft.get("descriptionofTicket"):
                    phrase_match = re.search(r'\b(?:i\s+have|i\s+am\s+having|having|facing|got|there\s+is|there\'s|with|due\s+to)\s+(.+)', user_question, re.IGNORECASE)
                    if phrase_match:
                        p_text = phrase_match.group(1).strip()
                        p_text = re.split(r'\.|\,|\;\s*(?:please\s+)?(?:create|raise|open|log)\s+(?:a\s+)?ticket', p_text, flags=re.IGNORECASE)[0].strip()
                        p_text = re.sub(r'\s+(?:for\s+client|priority|module|reported\s+by).*$', '', p_text, flags=re.IGNORECASE).strip()
                        if p_text and len(p_text) > 3:
                            draft["descriptionofTicket"] = p_text

                if not draft.get("descriptionofTicket"):
                    colon_parts = user_question.split(":", 1)
                    if len(colon_parts) > 1 and not re.search(r'^(client|priority|type|by|reported by)', colon_parts[0].strip(), re.IGNORECASE):
                        val = colon_parts[1].strip()
                        val = re.sub(r',?\s*priority\s+(?:p[1-4]|very high|high|medium|low|critical)\b.*$', '', val, flags=re.IGNORECASE).strip()
                        if val:
                            draft["descriptionofTicket"] = val

                if not draft.get("descriptionofTicket") and has_active_draft:
                    clean_text = user_question
                    if draft.get("clientName"):
                        clean_text = re.sub(r'client\s*(?:name)?\s*(?:is|:=|=|:)?\s*' + re.escape(draft["clientName"]), '', clean_text, flags=re.IGNORECASE)
                        clean_text = re.sub(r'\b' + re.escape(draft["clientName"]) + r'\b', '', clean_text, flags=re.IGNORECASE)
                    if draft.get("reportedby"):
                        clean_text = re.sub(r'reported\s*by\s*(?:is|:=|=|:)?\s*' + re.escape(draft["reportedby"]), '', clean_text, flags=re.IGNORECASE)
                    clean_text = re.sub(r'priority\s*(?:is|:=|=|:)?\s*(?:very high|high|medium|low|critical|p[1-4])', '', clean_text, flags=re.IGNORECASE)
                    clean_text = re.sub(r'\b(create ticket|raise ticket|new ticket|ticket|incident|issue|priority|client|reported by)\b', '', clean_text, flags=re.IGNORECASE)
                    clean_text = clean_text.strip(" .,;:-")
                    if len(clean_text) > 3:
                        draft["descriptionofTicket"] = clean_text

            # Check missing required fields
            missing_fields = []
            if not draft.get("clientName"):
                missing_fields.append(("Client Name", "client: <Organization Name>", "e.g. `client: Karamtara Engineering Pvt Ltd`"))
            if not draft.get("priority"):
                missing_fields.append(("Priority", "priority: <Low | Medium | High | Critical>", "e.g. `priority: High` or `priority: P2`"))
            if not draft.get("descriptionofTicket"):
                missing_fields.append(("Issue Description", "issue: <Details of the issue>", "e.g. `issue: SAP login authentication failure`"))
            if not draft.get("reportedby"):
                missing_fields.append(("Reported By", "reported by: <Your Name>", "e.g. `reported by: Veera`"))

            registered_clients = sorted(list({str(x["clientName"]) for x in pool if x.get("clientName")})) if pool else []

            # If there are missing fields, ask for them and save the pending draft
            if missing_fields:
                st.session_state.pending_ticket_draft = draft

                status_lines = []
                # Client
                if draft.get("clientName"):
                    status_lines.append(f"- 🏢 **Client**: `{draft['clientName']}` ✅")
                else:
                    status_lines.append("- 🏢 **Client**: ❌ *Missing*")

                # Priority
                if draft.get("priority"):
                    status_lines.append(f"- ⚡ **Priority**: `{draft['priority']}` ✅")
                else:
                    status_lines.append("- ⚡ **Priority**: ❌ *Missing (Please specify: Low, Medium, High, or Critical)*")

                # Description & Module Assignment
                if draft.get("descriptionofTicket"):
                    assigned_mod = assign_module(draft["descriptionofTicket"])
                    draft["module"] = assigned_mod
                    status_lines.append(f"- 📝 **Description**: {draft['descriptionofTicket']} ✅")
                    status_lines.append(f"- 🏷️ **Assigned Module**: `{assigned_mod}` *(Assigned by AI Agent)* ✅")
                else:
                    status_lines.append("- 📝 **Description**: ❌ *Missing (Issue details)*")

                # Reported By
                if draft.get("reportedby"):
                    status_lines.append(f"- 👤 **Reported By**: `{draft['reportedby']}` ✅")
                else:
                    status_lines.append("- 👤 **Reported By**: ❌ *Missing*")

                missing_prompts = "\n".join([f"- **{m[0]}**: `{m[1]}` ({m[2]})" for m in missing_fields])
                
                clients_hint = ""
                if not draft.get("clientName") and registered_clients:
                    top_c = ", ".join([f"`{c}`" for c in registered_clients[:4]])
                    clients_hint = f"\n\n> 💡 **Known Registered Clients**: {top_c}"

                answer = (
                    "### ⚠️ Incomplete Ticket Details\n\n"
                    "I need the remaining details to create your AMS ticket:\n\n"
                    + "\n".join(status_lines) + "\n\n"
                    "#### ✍️ Please reply with the missing field(s):\n"
                    + missing_prompts
                    + clients_hint +
                    "\n\n*(Type `cancel` to reset this draft)*"
                )

            else:
                # All required fields are present
                client_name = draft["clientName"]
                priority = draft["priority"]
                type_of_ticket = draft.get("typeofticket", "Incident")
                reported_by = draft["reportedby"]
                description = draft["descriptionofTicket"]
                assigned_module = assign_module(description)
                draft["module"] = assigned_module

                # Check if user is confirming a draft that is ready for confirmation
                confirm_keywords = ["confirm", "yes", "create", "proceed", "submit", "ok", "create ticket", "go ahead", "do it", "confirm creation", "create ticket now"]
                is_confirm = draft.get("ready_for_confirmation") and (question in confirm_keywords or question.startswith("confirm") or question.startswith("yes"))

                if is_confirm:
                    try:
                        with st.spinner(f"Submitting ticket for '{client_name}' to AMS API..."):
                            answer = submit_draft_ticket(ams_api, draft)
                        st.session_state.pending_ticket_draft = None
                    except Exception as ex:
                        answer = (
                            f"### ❌ Ticket Creation Failed\n\n"
                            f"The AMS API returned an error:\n"
                            f"> `{ex}`\n\n"
                            f"**Troubleshooting Tips**:\n"
                            f"- Ensure the client name matches a valid registered client organization.\n"
                            f"- Check your credentials in the sidebar."
                        )
                else:
                    # Present complete draft preview and ask for confirmation
                    draft["ready_for_confirmation"] = True
                    st.session_state.pending_ticket_draft = draft

                    answer = (
                        "### 📝 Ticket Draft Preview (Pending Confirmation)\n\n"
                        "All ticket details have been gathered! Please review below before final submission to AMS:\n\n"
                        f"- 🏢 **Client Name**: `{client_name}`\n"
                        f"- ⚡ **Priority**: `{priority}`\n"
                        f"- 📂 **Ticket Type**: `{type_of_ticket}`\n"
                        f"- 🏷️ **Assigned Module**: `{assigned_module}` *(Assigned by AI Agent)*\n"
                        f"- 👤 **Reported By**: `{reported_by}`\n"
                        f"- 📝 **Description**: {description}\n\n"
                        "--- \n"
                        "#### 💡 Want to edit any field before submitting?\n"
                        "You can reply with edit commands like:\n"
                        "- `edit priority to High`\n"
                        "- `change client to ATG`\n"
                        "- `change description to RPA bot process stopped`\n"
                        "- `change reported by to Mani`\n\n"
                        "#### ❓ Ready to create this ticket in AMS?\n"
                        "Click **`✅ Confirm & Create Ticket`** above or reply **`confirm`** / **`yes`** to create this ticket.\n"
                        "*(Reply `cancel` to discard this draft)*"
                    )

            filtered = None
            ticket_no = None
            count = 0

        else:
            # 1. Regex match for ticket numbers like ICP2608111, Kar2608133, ATG2608209
            ticket_no = None
            ticket_match = re.search(r'\b([A-Za-z]{2,8}\d{4,10})\b', user_question)
            if ticket_match:
                candidate = ticket_match.group(1).strip()
                # Look up candidate in pool
                for item in pool:
                    t_num = str(item.get("ticketNo", ""))
                    if t_num.lower() == candidate.lower():
                        ticket_no = t_num
                        break
                if not ticket_no:
                    ticket_no = candidate
            else:
                for item in pool:
                    t_num = item.get("ticketNo")
                    if t_num and str(t_num).lower() in question:
                        ticket_no = t_num
                        break

            priority = None
            status = None
            client_name_query = None
            module_query = None

            # Only apply secondary attribute filters if NOT querying a specific ticket directly
            if not ticket_no:
                # 2. Priority match with word boundaries
                if re.search(r'\b(very high|critical|p1)\b', question):
                    priority = "Very High (Production Impacted)"
                elif re.search(r'\b(high|p2)\b', question):
                    priority = "High (Business Impacted)"
                elif re.search(r'\b(medium|med|p3)\b', question):
                    priority = "Medium"
                elif re.search(r'\b(low|p4)\b', question):
                    priority = "Low"

                # 3. Status match with word boundaries
                for s in ["created", "assigned", "in progress", "resolved", "closed"]:
                    if re.search(r'\b' + re.escape(s) + r'\b', question):
                        status = s
                        break

                # 4. Client detection
                for item in pool:
                    c_name = item.get("clientName")
                    if c_name and len(str(c_name)) > 3 and str(c_name).lower() in question:
                        client_name_query = c_name
                        break

                # 5. Module detection
                for item in pool:
                    m_name = item.get("module")
                    if m_name and len(str(m_name)) > 2 and str(m_name).lower() in question:
                        module_query = m_name
                        break

            filtered = filter_tickets(
                tickets=pool,
                ticket_no=ticket_no,
                client_name=client_name_query,
                status=status,
                priority=priority,
                module=module_query,
                search_text=None if (ticket_no or priority or status or client_name_query or module_query) else user_question
            )

            count = len(filtered)
            if not filtered:
                answer = f"I couldn't find any tickets matching your request (**'{user_question}'**)."
            else:
                if ticket_no and count == 1:
                    t = filtered[0]
                    answer = (
                        f"### 🎫 Ticket Details: **{t.get('ticketNo')}**\n\n"
                        f"- **Client**: {t.get('clientName', 'N/A')}\n"
                        f"- **Status**: `{t.get('ticketStatus', 'N/A')}`\n"
                        f"- **Priority**: `{t.get('priority', 'N/A')}`\n"
                        f"- **Module**: {t.get('module', 'N/A')}\n"
                        f"- **Created By**: {t.get('createdname', 'N/A')} ({t.get('createdEmails', '')})\n"
                        f"- **Created Date**: {t.get('createddate', 'N/A')}\n"
                        f"- **Closed Date**: {t.get('closedondate', 'N/A')}\n"
                        f"- **Remarks**: {t.get('remarks') if t.get('remarks') else 'None'}\n"
                        f"- **Transaction ID**: `{t.get('txnId', 'N/A')}`"
                    )
                else:
                    filters_used = []
                    if ticket_no:
                        filters_used.append(f"ticket **{ticket_no}**")
                    if client_name_query:
                        filters_used.append(f"client **{client_name_query}**")
                    if priority:
                        filters_used.append(f"priority **{priority.title()}**")
                    if status:
                        filters_used.append(f"status **{status.title()}**")
                    if module_query:
                        filters_used.append(f"module **{module_query}**")

                    if filters_used:
                        answer = f"Found **{count}** ticket(s) matching " + ", ".join(filters_used) + "."
                    else:
                        answer = f"Found **{count}** ticket(s) related to your search."

        st.session_state.messages.append({
            "role": "assistant",
            "content": answer,
            "data": filtered if (filtered and not (ticket_no and count == 1)) else None
        })
        st.rerun()


# =========================================================
# TAB 2: All Tickets Detailed View (GET /api/Ticket)
# =========================================================
with tab_all_tickets:
    st.subheader("📑 Detailed Tickets Master List")
    st.caption("Endpoint: `GET http://172.16.32.50/api/Ticket`")

    col_t_btn, col_t_search = st.columns([1.5, 4.5])
    with col_t_btn:
        st.write("") # spacing
        if st.button("🔄 Refresh All Tickets", key="btn_refresh_all_tickets", use_container_width=True):
            try:
                with st.spinner("Refreshing tickets from /api/Ticket..."):
                    fetch_all_tickets.clear()
                    st.session_state.tickets = fetch_all_tickets(ams_api.username, ams_api.password)
                st.rerun()
            except Exception as e:
                st.error(f"Failed to refresh tickets: {e}")

    # Auto-load if empty
    if st.session_state.tickets is None and ams_api.username and ams_api.password:
        try:
            with st.spinner("Loading tickets from http://172.16.32.50/api/Ticket..."):
                st.session_state.tickets = fetch_all_tickets(ams_api.username, ams_api.password)
        except Exception as e:
            st.warning(f"Could not automatically load tickets: {e}")

    tickets_data = st.session_state.tickets or []

    if tickets_data:
        df_all = pd.DataFrame(tickets_data)

        # Filters
        unique_clients = ["All"] + sorted(list({str(x["clientName"]) for x in tickets_data if x.get("clientName")}))
        unique_statuses = ["All"] + sorted(list({str(x["ticketStatus"]) for x in tickets_data if x.get("ticketStatus")}))
        unique_priorities = ["All"] + sorted(list({str(x["priority"]) for x in tickets_data if x.get("priority")}))
        unique_modules = ["All"] + sorted(list({str(x["module"]) for x in tickets_data if x.get("module")}))

        f_col1, f_col2, f_col3, f_col4 = st.columns(4)
        with f_col1:
            sel_client = st.selectbox("Filter Client", unique_clients, key="f_client")
        with f_col2:
            sel_status = st.selectbox("Filter Status", unique_statuses, key="f_status")
        with f_col3:
            sel_prio = st.selectbox("Filter Priority", unique_priorities, key="f_prio")
        with f_col4:
            sel_mod = st.selectbox("Filter Module", unique_modules, key="f_mod")

        with col_t_search:
            t_search = st.text_input("🔍 Search Tickets (Ticket No, Description, Name, Email, Remarks)", placeholder="e.g. Kar2608133, SD, Veera...", key="t_search_box")

        # Apply filter
        filtered_all = filter_tickets(
            tickets=tickets_data,
            client_name=None if sel_client == "All" else sel_client,
            status=None if sel_status == "All" else sel_status,
            priority=None if sel_prio == "All" else sel_prio,
            module=None if sel_mod == "All" else sel_mod,
            search_text=t_search if t_search else None
        )

        # Summary Metrics
        m1, m2, m3, m4 = st.columns(4)
        with m1:
            st.metric("Total Loaded", len(tickets_data))
        with m2:
            st.metric("Filtered Records", len(filtered_all))
        with m3:
            clients_count = len({x.get("clientName") for x in tickets_data if x.get("clientName")})
            st.metric("Unique Clients", clients_count)
        with m4:
            created_count = sum(1 for x in tickets_data if str(x.get("ticketStatus", "")).lower() == "created")
            st.metric("New / Created", created_count)

        st.markdown("---")

        if filtered_all:
            df_filtered_all = pd.DataFrame(filtered_all)

            column_order = [
                "ticketNo", "clientName", "ticketStatus", "priority", "module",
                "createdname", "createdEmails", "createddate", "closedondate", "remarks"
            ]
            ordered_cols = [c for c in column_order if c in df_filtered_all.columns] + [c for c in df_filtered_all.columns if c not in column_order]

            st.dataframe(
                df_filtered_all[ordered_cols],
                use_container_width=True,
                hide_index=True
            )

            # Download CSV option
            csv_data = df_filtered_all[ordered_cols].to_csv(index=False).encode('utf-8')
            st.download_button(
                label="📥 Download Filtered Tickets (CSV)",
                data=csv_data,
                file_name=f"ams_tickets_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv",
                mime="text/csv"
            )
        else:
            st.info("No tickets match the selected filters.")
    else:
        st.info("No tickets loaded from `/api/Ticket`. Please check credentials and click **Refresh All Tickets**.")


# =========================================================
# TAB 3: Ticket Status View (GET /api/Ticket/Status)
# =========================================================
with tab_status:
    st.subheader("📋 Real-Time Ticket Status")
    st.caption("Endpoint: `GET http://172.16.32.50/api/Ticket/Status`")

    col_reload, col_filter_status, col_filter_priority, col_search = st.columns([1.5, 1.5, 1.5, 2.5])
    
    with col_reload:
        st.write("") # vertical spacing
        if st.button("🔄 Refresh Status", key="btn_refresh_status", use_container_width=True):
            try:
                with st.spinner("Refreshing ticket statuses..."):
                    fetch_ticket_statuses.clear()
                    st.session_state.ticket_statuses = fetch_ticket_statuses(ams_api.username, ams_api.password)
                st.rerun()
            except Exception as e:
                st.error(f"Error: {e}")

    # Auto-load if empty
    if st.session_state.ticket_statuses is None and ams_api.username and ams_api.password:
        try:
            with st.spinner("Fetching ticket statuses from AMS API..."):
                st.session_state.ticket_statuses = fetch_ticket_statuses(ams_api.username, ams_api.password)
        except Exception as e:
            st.warning(f"Could not automatically load ticket statuses. ({e})")

    statuses_data = st.session_state.ticket_statuses or []

    if statuses_data:
        unique_statuses = ["All"] + sorted(list({str(x["ticketStatus"]) for x in statuses_data if x.get("ticketStatus")}))
        unique_priorities = ["All"] + sorted(list({str(x["priority"]) for x in statuses_data if x.get("priority")}))

        with col_filter_status:
            selected_status = st.selectbox("Filter by Status", unique_statuses, key="filter_status_select")
        with col_filter_priority:
            selected_priority = st.selectbox("Filter by Priority", unique_priorities, key="filter_prio_select")
        with col_search:
            search_query = st.text_input("🔍 Search (Ticket No, Txn ID, Remarks)", placeholder="e.g. Kar2608133", key="filter_search_input")

        # Apply filtering
        filtered_statuses = statuses_data
        if selected_status != "All":
            filtered_statuses = [x for x in filtered_statuses if str(x.get("ticketStatus", "")).lower() == selected_status.lower()]
        if selected_priority != "All":
            filtered_statuses = [x for x in filtered_statuses if str(x.get("priority", "")).lower() == selected_priority.lower()]
        if search_query:
            sq = search_query.strip().lower()
            filtered_statuses = [
                x for x in filtered_statuses
                if sq in str(x.get("ticketNo", "")).lower()
                or sq in str(x.get("txnId", "")).lower()
                or sq in str(x.get("remarks", "")).lower()
                or sq in str(x.get("ticketStatus", "")).lower()
            ]

        # Top summary metrics
        m1, m2, m3, m4 = st.columns(4)
        with m1:
            st.metric("Total Status Records", len(statuses_data))
        with m2:
            created_count = sum(1 for x in statuses_data if str(x.get("ticketStatus", "")).lower() == "created")
            st.metric("Status: Created", created_count)
        with m3:
            p2_count = sum(1 for x in statuses_data if str(x.get("priority", "")).upper() in ["P2", "HIGH"])
            st.metric("Priority P2 / High", p2_count)
        with m4:
            st.metric("Filtered Results", len(filtered_statuses))

        st.markdown("---")

        if filtered_statuses:
            df_filtered = pd.DataFrame(filtered_statuses)
            preferred_cols = ["txnId", "ticketNo", "priority", "ticketStatus", "remarks"]
            existing_cols = [c for c in preferred_cols if c in df_filtered.columns] + [c for c in df_filtered.columns if c not in preferred_cols]
            
            st.dataframe(
                df_filtered[existing_cols],
                use_container_width=True,
                hide_index=True,
                column_config={
                    "txnId": st.column_config.NumberColumn("Transaction ID", format="%d"),
                    "ticketNo": st.column_config.TextColumn("Ticket Number"),
                    "priority": st.column_config.TextColumn("Priority"),
                    "ticketStatus": st.column_config.TextColumn("Ticket Status"),
                    "remarks": st.column_config.TextColumn("Remarks")
                }
            )
        else:
            st.info("No ticket status records match the selected filters.")
    else:
        st.info("No ticket status records loaded. Provide valid credentials and click **Refresh Status**.")


# =========================================================
# TAB 4: Create Ticket (POST /api/Ticket/CreateTicket)
# =========================================================
with tab_create:
    st.subheader("➕ Create a New AMS Ticket")
    st.caption("Endpoint: `POST http://172.16.32.50/api/Ticket/CreateTicket`")

    with st.form("create_ticket_form", clear_on_submit=False):
        col_c1, col_c2 = st.columns(2)
        
        with col_c1:
            client_options = ["Karamtara Engineering Pvt Ltd"]
            if st.session_state.tickets:
                fetched_clients = sorted(list({str(x["clientName"]) for x in st.session_state.tickets if x.get("clientName")}))
                if fetched_clients:
                    client_options = sorted(list(set(client_options + fetched_clients)))

            client_options.append("Other (Specify manually)")

            client_name_sel = st.selectbox(
                "Client Name *",
                options=client_options,
                index=0,
                help="Must match a registered client organization name in AMS"
            )

            if client_name_sel == "Other (Specify manually)":
                client_name = st.text_input("Specify Client Name *", placeholder="Enter client organization name")
            else:
                client_name = client_name_sel

            ams_val = st.text_input(
                "AMS *",
                value="AMS",
                help="AMS type or service classification"
            )
            type_of_ticket = st.selectbox(
                "Type of Ticket *",
                options=["S PO", "Incident", "Service Request", "Change Request"],
                index=0
            )
            priority_val = st.selectbox(
                "Priority *",
                options=[
                    "Low",
                    "Medium",
                    "High (Business Impacted)",
                    "Very High (Production Impacted)"
                ],
                index=0,
                help="Allowed AMS priority levels in database"
            )
            reported_by = st.text_input(
                "Reported By *",
                value="Veera",
                placeholder="Name of the reporter"
            )

        with col_c2:
            now_utc = datetime.now(timezone.utc)
            reported_date = st.date_input(
                "Reported On Date",
                value=now_utc.date()
            )
            reported_time = st.time_input(
                "Reported On Time",
                value=datetime.now().time()
            )
            screenshort_val = st.text_input(
                "Screenshot / Attachment Ref",
                value="N/A",
                help="Path, URL, or identifier for screenshot (nullable)"
            )
            remarks_val = st.text_input(
                "Remarks",
                value="NO",
                help="Any additional remarks"
            )
            module_val = st.selectbox(
                "Module *",
                options=MODULES,
                index=MODULES.index("SAP") if "SAP" in MODULES else 0,
                help="Select ticket module"
            )

        description_val = st.text_area(
            "Description of Ticket *",
            value="Dummy",
            placeholder="Provide a clear description of the issue or request...",
            height=120
        )

        combined_dt = datetime.combine(reported_date, reported_time).replace(tzinfo=timezone.utc)
        reported_on_iso = combined_dt.strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"
        reported_on_time_str = reported_time.strftime("%H:%M")

        ticket_payload = {
            "clientName": client_name.strip() if client_name else None,
            "ams": ams_val.strip() if ams_val else None,
            "typeofticket": type_of_ticket.strip() if type_of_ticket else None,
            "priority": priority_val.strip() if priority_val else None,
            "reportedon": reported_on_iso,
            "reportedontime": reported_on_time_str,
            "reportedby": reported_by.strip() if reported_by else None,
            "descriptionofTicket": description_val.strip() if description_val else None,
            "screenshort": screenshort_val.strip() if screenshort_val else None,
            "remarks": remarks_val.strip() if remarks_val else None,
            "module": module_val.strip() if module_val else None
        }

        with st.expander("🔍 Preview JSON Request Payload (TicketCreateRequest)"):
            st.json(ticket_payload)

        submitted = st.form_submit_button("Submit Ticket", use_container_width=True, type="primary")

    if submitted:
        if not client_name or not description_val:
            st.error("Please fill in the required fields: Client Name and Description of Ticket.")
        else:
            try:
                with st.spinner("Submitting ticket to AMS API..."):
                    res = ams_api.create_ticket(ticket_payload)
                st.success("🎉 Ticket created successfully!")
                st.json(res)
                
                # Invalidate caches and auto refresh
                try:
                    fetch_all_tickets.clear()
                    fetch_ticket_statuses.clear()
                    st.session_state.ticket_statuses = fetch_ticket_statuses(ams_api.username, ams_api.password)
                    st.session_state.tickets = fetch_all_tickets(ams_api.username, ams_api.password)
                except Exception:
                    pass

            except Exception as ex:
                st.error(f"❌ Failed to create ticket:\n\n{ex}")
