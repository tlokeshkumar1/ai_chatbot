"""
query_engine.py - Dynamic AMS Ticket Intelligence Engine

Provides a dynamic, LLM-driven query understanding layer for AMS ticket management.
Interprets natural-language queries dynamically against ticket datasets and schemas
without relying on static keyword-based filtering.
"""

import os
import json
import re
import warnings
from datetime import datetime, timedelta, timezone
import pandas as pd
import requests
from dotenv import load_dotenv

load_dotenv(override=True)
warnings.filterwarnings("ignore")

# Support both new google.genai and deprecated google.generativeai as fallback
GENAI_CLIENT = None
LEGACY_GENAI = None

try:
    from google import genai
    from google.genai import types
    api_key = os.getenv("GEMINI_API_KEY") or os.getenv("GOOGLE_API_KEY")
    if api_key:
        GENAI_CLIENT = genai.Client(api_key=api_key)
except Exception:
    pass

if not GENAI_CLIENT:
    try:
        import google.generativeai as legacy_genai
        api_key = os.getenv("GEMINI_API_KEY") or os.getenv("GOOGLE_API_KEY")
        if api_key:
            legacy_genai.configure(api_key=api_key)
            LEGACY_GENAI = legacy_genai
    except Exception:
        pass


SYSTEM_PROMPT = """# Dynamic AMS Ticket Intelligence Assistant

You are an intelligent AI assistant for an AMS Ticket Management System.
Your primary responsibility is to answer user questions about AMS tickets using the actual ticket dataset available to the application.
You must understand natural-language questions dynamically. Do NOT depend on static keyword lists, hardcoded phrases, or predefined filter combinations.

---

## 1. Core Objective
The user may ask any question about the available AMS tickets.
Your job is to:
1. Understand the user's natural-language intent.
2. Inspect the available ticket data and its column structure.
3. Identify relevant entities, conditions, relationships, dates, metrics, and concepts from the question.
4. Determine which ticket fields are relevant.
5. Dynamically query/filter/aggregate the actual ticket dataset.
6. Analyze the resulting records when required.
7. Return a clear, accurate natural-language answer.
Never assume that the user will use exact database values or exact column names.

---

## 2. Never Use Static Keyword-Based Filtering
Do NOT implement logic such as: `if "open" in query: status = "Open"`.
Instead, dynamically infer the meaning of the user's question from:
* the ticket dataset
* the available column names
* the actual values in those columns
* the semantic meaning of the question
* relationships between fields
* natural-language context

---

## 3. Dynamic Schema Understanding
Detect available columns dynamically. Map the user's concept to the most relevant available field. If the required information is not present, explain that clearly.

---

## 4. Natural-Language Understanding
Users may express concepts in different ways (e.g. "open/unresolved/pending/active", "critical/urgent/high priority"). Interpret semantically according to actual values in the dataset.

---

## 5. Entity Resolution
Resolve partial client names, abbreviations, informal references against registered dataset values. If ambiguous (e.g., multiple ABC companies), clarify. If single clear match, use it.

---

## 6. Semantic Ticket Search
Search fields like Description, Short Description, Remarks, Module, Assignment Group for conceptual meaning, not just exact substring.

---

## 7. Dynamic Operations
Support Retrieval, Filtering, Counting, Aggregation, Ranking, Comparison, Trend Analysis, Distribution Analysis, Semantic Search, Summarization, and Root-Cause Analysis.

---

## 8. Dates
Map natural date expressions (today, yesterday, this week, last week, this month, last month, last 7/30 days, recent) dynamically to creation/update date fields.

---

## 9. Context Awareness
Maintain conversation context for follow-up questions (e.g. "Show tickets for ABC" followed by "Only unresolved ones").

---

## 10. Unknown & Missing Data
Never invent ticket information or missing fields. State clearly if no data matches or fields are absent.

---

## 11. Response Style
Concise, clear, business-friendly, directly answer the question first. Provide counts/summaries and top records.

---

## 12. Safety and Accuracy
Always use actual AMS ticket data as the source of truth.
"""


def _call_nvidia(prompt_text, system_instruction=None, json_response=False):
    """
    Calls NVIDIA API endpoint as the primary model.
    """
    load_dotenv(override=True)
    api_key = os.getenv("NVIDIA_API_KEY")
    base_url = os.getenv("NVIDIA_BASE_URL", "https://integrate.api.nvidia.com/v1")
    model = os.getenv("NVIDIA_MODEL", "nvidia/nemotron-3-super-120b-a12b")

    if not api_key or api_key == "your_nvidia_api_key":
        return None

    url = f"{base_url.rstrip('/')}/chat/completions"
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json"
    }

    messages = []
    if system_instruction:
        sys_msg = system_instruction
        if json_response:
            sys_msg += "\n\nCRITICAL: Respond ONLY with a valid JSON object. Do not include markdown code block formatting or additional commentary."
        messages.append({"role": "system", "content": sys_msg})
    elif json_response:
        messages.append({"role": "system", "content": "You are a JSON query engine. Output only a single valid JSON object."})

    messages.append({"role": "user", "content": prompt_text})

    payload = {
        "model": model,
        "messages": messages,
        "temperature": 0.1,
        "max_tokens": 3072
    }

    try:
        res = requests.post(url, json=payload, headers=headers, timeout=35)
        if res.ok:
            data = res.json()
            if "choices" in data and len(data["choices"]) > 0:
                msg = data["choices"][0].get("message", {})
                content = msg.get("content")
                if content and isinstance(content, str) and content.strip():
                    return content.strip()
        else:
            print(f"[LLM] NVIDIA API returned status {res.status_code}: {res.text}")
    except Exception as e:
        print(f"[LLM] NVIDIA API request failed: {e}")

    return None


def _call_gemini(prompt_text, system_instruction=None, json_response=False):
    """
    Fallback LLM handler using Google Gemini API (gemini-2.5-flash, gemini-3.6-flash).
    """
    global GENAI_CLIENT
    load_dotenv(override=True)
    api_key = os.getenv("GEMINI_API_KEY") or os.getenv("GOOGLE_API_KEY")

    if api_key and api_key != "your_gemini_api_key":
        try:
            from google import genai
            from google.genai import types

            if not GENAI_CLIENT:
                GENAI_CLIENT = genai.Client(api_key=api_key)

            config = {}
            if json_response:
                config["response_mime_type"] = "application/json"
            if system_instruction:
                config["system_instruction"] = system_instruction

            gen_config = types.GenerateContentConfig(**config) if config else None

            # Primary Gemini model gemini-2.5-flash, fallback to gemini-3.6-flash
            for m in ["gemini-2.5-flash", "gemini-3.6-flash"]:
                try:
                    response = GENAI_CLIENT.models.generate_content(
                        model=m,
                        contents=prompt_text,
                        config=gen_config
                    )
                    if response and response.text:
                        return response.text
                except Exception as ex_model:
                    print(f"[LLM] Gemini Model {m} failed: {ex_model}")
                    continue
        except Exception as ex:
            print(f"[LLM] Gemini Client error: {ex}")

    return None


def _call_llm(prompt_text, system_instruction=None, json_response=False):
    """
    Unified LLM call handler:
    1. Primary: NVIDIA API (nvidia/nemotron-3-super-120b-a12b)
    2. Fallback: Google Gemini API (gemini-2.5-flash / gemini-3.6-flash)
    """
    # 1. Try NVIDIA model as primary
    nvidia_res = _call_nvidia(prompt_text, system_instruction=system_instruction, json_response=json_response)
    if nvidia_res:
        return nvidia_res

    # 2. Fallback to Google Gemini
    print("[LLM] NVIDIA API unavailable or failed. Falling back to Google Gemini...")
    gemini_res = _call_gemini(prompt_text, system_instruction=system_instruction, json_response=json_response)
    if gemini_res:
        return gemini_res

    return None


def get_dataset_metadata(tickets):
    """
    Dynamically inspects dataset schema, column names, unique categorical values,
    and date bounds to assist LLM NLU reasoning.
    """
    if not tickets:
        return {
            "columns": [],
            "total_count": 0,
            "unique_clients": [],
            "unique_statuses": [],
            "unique_priorities": [],
            "unique_groups": [],
            "sample_rows": []
        }

    df = pd.DataFrame(tickets)
    cols = list(df.columns)

    unique_clients = sorted(list({str(x).strip() for x in df.get("clientName", pd.Series()).dropna().unique() if str(x).strip()}))
    unique_statuses = sorted(list({str(x).strip() for x in df.get("ticketStatus", pd.Series()).dropna().unique() if str(x).strip()}))
    unique_priorities = sorted(list({str(x).strip() for x in df.get("priority", pd.Series()).dropna().unique() if str(x).strip()}))
    
    group_series = df.get("assigntogroup", pd.Series())
    if "module" in df.columns:
        group_series = pd.concat([group_series, df.get("module", pd.Series())])
    unique_groups = sorted(list({str(x).strip() for x in group_series.dropna().unique() if str(x).strip()}))

    # Select sample rows (up to 3) for schema context
    sample_rows = df.head(3).to_dict(orient="records")

    return {
        "columns": cols,
        "total_count": len(df),
        "unique_clients": unique_clients,
        "unique_statuses": unique_statuses,
        "unique_priorities": unique_priorities,
        "unique_groups": unique_groups,
        "sample_rows": sample_rows
    }


def parse_query_plan_with_llm(user_question, meta, history=None):
    """
    Uses Gemini LLM to interpret user question and return a structured query plan.
    """
    history_context = ""
    if history and len(history) > 0:
        recent = history[-4:] # Last 2 turns
        history_context = "\n".join([f"{msg['role'].upper()}: {msg['content']}" for msg in recent])

    prompt = f"""You are a dynamic query planner for an AMS Ticket dataset.
Analyze the user's question, dataset metadata, and conversation context to produce a JSON query plan.

### AVAILABLE DATASET METADATA:
- Total tickets in memory: {meta['total_count']}
- Available columns: {json.dumps(meta['columns'])}
- Known Client Names in dataset: {json.dumps(meta['unique_clients'])}
- Known Ticket Statuses in dataset: {json.dumps(meta['unique_statuses'])}
- Known Priorities in dataset: {json.dumps(meta['unique_priorities'])}
- Known Assignment Groups / Modules in dataset: {json.dumps(meta['unique_groups'])}
- Sample ticket object: {json.dumps(meta['sample_rows'][:1] if meta['sample_rows'] else [])}

### CONVERSATION HISTORY:
{history_context if history_context else 'None'}

### USER QUESTION:
"{user_question}"

---
Generate a valid JSON object matching this exact structure:
{{
  "intent": "retrieval" | "filtering" | "counting" | "aggregation" | "ranking" | "comparison" | "trend_analysis" | "distribution" | "semantic_search" | "summarization" | "root_cause_analysis" | "general_inquiry" | "greeting" | "ticket_creation",
  "detected_client": string or null,
  "detected_status_semantic": "open" | "unresolved" | "pending" | "closed" | "resolved" | "created" | "all" | null,
  "detected_priority": string or null,
  "detected_group_or_module": string or null,
  "detected_reporter": string or null,
  "detected_ticket_no": string or null,
  "date_range": {{
    "type": "today" | "yesterday" | "this_week" | "last_week" | "this_month" | "last_month" | "last_7_days" | "last_30_days" | null,
    "start_date": "YYYY-MM-DD" or null,
    "end_date": "YYYY-MM-DD" or null
  }},
  "semantic_text_search": string or null,
  "group_by_field": string or null,
  "aggregation": {{
    "function": "count" | "sum",
    "field": string or null
  }},
  "comparison_clients": [string] or [],
  "sort": {{
    "field": string or null,
    "direction": "asc" | "desc"
  }},
  "limit": integer or null,
  "ambiguous_client_match": boolean,
  "clarification_question": string or null
}}

Respond ONLY with the JSON object. Do not include markdown code block syntax unless required.
"""

    raw_response = _call_llm(prompt, system_instruction=SYSTEM_PROMPT, json_response=True)
    
    if raw_response:
        try:
            cleaned = raw_response.strip()
            if cleaned.startswith("```"):
                cleaned = re.sub(r"^```(?:json)?\n?", "", cleaned)
                cleaned = re.sub(r"\n?```$", "", cleaned)
            return json.loads(cleaned)
        except Exception:
            pass

    # Heuristic fallback if LLM is unreachable or response parsing fails
    return heuristic_query_plan(user_question, meta)


def heuristic_query_plan(user_question, meta):
    """
    Smart dynamic heuristic parser used as fallback when LLM is unavailable.
    """
    q_lower = user_question.lower().strip()

    # Greetings & General Inquiries
    greetings = ["hi", "hello", "hey", "hola", "namaste", "good morning", "good afternoon", "good evening", "greetings", "help", "who are you", "what can you do"]
    if q_lower in greetings or any(q_lower == g for g in greetings):
        return {
            "intent": "greeting",
            "detected_client": None,
            "detected_status_semantic": None,
            "detected_priority": None,
            "detected_group_or_module": None,
            "detected_reporter": None,
            "detected_ticket_no": None,
            "date_range": {"type": None, "start_date": None, "end_date": None},
            "semantic_text_search": None,
            "group_by_field": None,
            "aggregation": {"function": None, "field": None},
            "comparison_clients": [],
            "sort": {"field": None, "direction": None},
            "limit": None,
            "ambiguous_client_match": False,
            "clarification_question": None
        }

    # Ticket creation detection (including typos like tickate, tikit, etc.)
    if re.search(r'\b(create|raise|open|log|make|generate|want to create|need a?)\b.*\b(ticket|tickate|tikit|tickt|tikket|tikate)\b', q_lower) or re.search(r'\b(tickate|tikit|tickt|tikket|tikate)\b', q_lower):
        detected_client = None
        for c in meta.get("unique_clients", []):
            if len(c) <= 4:
                if re.search(r'\b' + re.escape(c) + r'\b', user_question, re.IGNORECASE):
                    detected_client = c
                    break
            else:
                if c.lower() in q_lower:
                    detected_client = c
                    break

        return {
            "intent": "ticket_creation",
            "detected_client": detected_client,
            "detected_status_semantic": None,
            "detected_priority": None,
            "detected_group_or_module": None,
            "detected_reporter": None,
            "detected_ticket_no": None,
            "date_range": {"type": None, "start_date": None, "end_date": None},
            "semantic_text_search": None,
            "group_by_field": None,
            "aggregation": {"function": None, "field": None},
            "comparison_clients": [],
            "sort": {"field": None, "direction": None},
            "limit": None,
            "ambiguous_client_match": False,
            "clarification_question": None
        }

    # Intent detection
    intent = "filtering"
    if any(k in q_lower for k in ["how many", "count"]):
        intent = "counting"
    elif any(k in q_lower for k in ["top", "most", "highest", "largest", "worst"]):
        intent = "ranking"
    elif "compare" in q_lower:
        intent = "comparison"
    elif any(k in q_lower for k in ["summarize", "summary", "overview", "situation", "happening"]):
        intent = "summarization"
    elif any(k in q_lower for k in ["why", "root cause", "reason"]):
        intent = "root_cause_analysis"

    # Ticket number detection
    t_no = None
    t_match = re.search(r'\b([A-Za-z]{2,8}\d{4,10})\b', user_question)
    if t_match:
        t_no = t_match.group(1).strip()

    # Client detection against meta
    detected_client = None
    matched_clients = []
    for c in meta["unique_clients"]:
        if len(c) <= 4:
            if re.search(r'\b' + re.escape(c) + r'\b', user_question, re.IGNORECASE):
                matched_clients.append(c)
        else:
            if c.lower() in q_lower:
                matched_clients.append(c)

    if len(matched_clients) == 1:
        detected_client = matched_clients[0]
    elif len(matched_clients) > 1:
        detected_client = matched_clients[0]

    # Status semantic detection
    status_sem = None
    if any(k in q_lower for k in ["unresolved", "open", "pending", "active", "not closed", "yet to be closed"]):
        status_sem = "unresolved"
    elif any(k in q_lower for k in ["closed", "resolved", "completed", "done"]):
        status_sem = "closed"

    # Priority detection
    priority = None
    if re.search(r'\b(very high|critical|p1|urgent)\b', q_lower):
        priority = "Very High (Production Impacted)"
    elif re.search(r'\b(high|p2|important)\b', q_lower):
        priority = "High (Business Impacted)"
    elif re.search(r'\b(medium|med|p3)\b', q_lower):
        priority = "Medium"
    elif re.search(r'\b(low|p4)\b', q_lower):
        priority = "Low"

    # Assignment group / module match
    detected_group = None
    for g in meta["unique_groups"]:
        if g.lower() in q_lower:
            detected_group = g
            break

    # Date range detection
    date_type = None
    if "today" in q_lower:
        date_type = "today"
    elif "yesterday" in q_lower:
        date_type = "yesterday"
    elif "this week" in q_lower:
        date_type = "this_week"
    elif "last week" in q_lower:
        date_type = "last_week"
    elif "this month" in q_lower:
        date_type = "this_month"
    elif "last 7 days" in q_lower or "past week" in q_lower:
        date_type = "last_7_days"
    elif "last 30 days" in q_lower:
        date_type = "last_30_days"

    # Semantic text search
    semantic_text = None
    if not (t_no or detected_client or priority or status_sem or detected_group):
        semantic_text = user_question

    return {
        "intent": intent,
        "detected_client": detected_client,
        "detected_status_semantic": status_sem,
        "detected_priority": priority,
        "detected_group_or_module": detected_group,
        "detected_reporter": None,
        "detected_ticket_no": t_no,
        "date_range": {"type": date_type, "start_date": None, "end_date": None},
        "semantic_text_search": semantic_text,
        "group_by_field": "clientName" if ("client" in q_lower and intent in ["ranking", "counting", "aggregation"]) else ("assigntogroup" if "group" in q_lower or "module" in q_lower else None),
        "aggregation": {"function": "count", "field": "ticketNo"},
        "comparison_clients": [c for c in meta["unique_clients"] if c.lower() in q_lower],
        "sort": {"field": "createddate", "direction": "desc"},
        "limit": 5 if "top 5" in q_lower else (10 if "top 10" in q_lower else None),
        "ambiguous_client_match": False,
        "clarification_question": None
    }


def parse_date_range(date_info):
    """
    Parses dynamic date conditions into concrete start and end datetime bounds in UTC.
    """
    if not date_info or not isinstance(date_info, dict):
        return None, None

    date_type = date_info.get("type")
    now = datetime.now(timezone.utc)

    if date_type == "today":
        start = now.replace(hour=0, minute=0, second=0, microsecond=0)
        end = now
        return start, end

    elif date_type == "yesterday":
        y = now - timedelta(days=1)
        start = y.replace(hour=0, minute=0, second=0, microsecond=0)
        end = y.replace(hour=23, minute=59, second=59, microsecond=999999)
        return start, end

    elif date_type == "this_week":
        start = (now - timedelta(days=now.weekday())).replace(hour=0, minute=0, second=0, microsecond=0)
        end = now
        return start, end

    elif date_type == "last_week":
        end_lw = (now - timedelta(days=now.weekday() + 1)).replace(hour=23, minute=59, second=59, microsecond=999999)
        start_lw = (end_lw - timedelta(days=6)).replace(hour=0, minute=0, second=0, microsecond=0)
        return start_lw, end_lw

    elif date_type == "this_month":
        start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
        end = now
        return start, end

    elif date_type == "last_7_days":
        start = now - timedelta(days=7)
        return start, now

    elif date_type == "last_30_days":
        start = now - timedelta(days=30)
        return start, now

    elif date_info.get("start_date") or date_info.get("end_date"):
        try:
            start = datetime.strptime(date_info["start_date"], "%Y-%m-%d").replace(tzinfo=timezone.utc) if date_info.get("start_date") else None
            end = datetime.strptime(date_info["end_date"], "%Y-%m-%d").replace(tzinfo=timezone.utc) if date_info.get("end_date") else None
            return start, end
        except Exception:
            pass

    return None, None


def safe_parse_datetime(val):
    """
    Parses various date string formats present in AMS datasets safely.
    """
    if not val or pd.isna(val):
        return None
    s = str(val).strip()
    for fmt in [
        "%Y-%m-%dT%H:%M:%S.%fZ", "%Y-%m-%dT%H:%M:%S.%f", "%Y-%m-%dT%H:%M:%S",
        "%Y-%m-%d %H:%M:%S", "%Y-%m-%d", "%d/%m/%Y %H:%M:%S", "%d/%m/%Y", "%d-%m-%Y"
    ]:
        try:
            dt = datetime.strptime(s, fmt)
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            return dt
        except ValueError:
            continue
    return None


def execute_query_plan(tickets_data, plan):
    """
    Executes the JSON query plan dynamically against the ticket DataFrame.
    Returns: (df_filtered, summary_stats)
    """
    if not tickets_data:
        return pd.DataFrame(), {"count": 0, "initial_total": 0, "filtered_count": 0}

    df = pd.DataFrame(tickets_data)
    initial_count = len(df)

    intent = plan.get("intent")
    if intent in ["greeting", "general_inquiry", "ticket_creation"]:
        return pd.DataFrame(), {"count": 0, "initial_total": initial_count, "filtered_count": 0}

    result = df.copy()

    # 1. Filter by specific Ticket Number if present
    t_no = plan.get("detected_ticket_no")
    if t_no:
        mask = result.apply(
            lambda r: str(r.get("ticketNo", "")).lower() == str(t_no).lower()
            or str(r.get("ticketId", "")).lower() == str(t_no).lower()
            or str(r.get("txnId", "")).lower() == str(t_no).lower(),
            axis=1
        )
        if mask.any():
            result = result[mask]

    # 2. Filter by Client Name (Entity Resolution)
    client = plan.get("detected_client")
    if client and "clientName" in result.columns and not t_no:
        mask = result["clientName"].apply(
            lambda x: str(client).lower() == str(x).lower()
            or str(client).lower() in str(x).lower()
            or str(x).lower() in str(client).lower()
            if pd.notna(x) else False
        )
        if mask.any():
            result = result[mask]

    # 3. Filter by Status Semantics
    status_sem = plan.get("detected_status_semantic")
    if status_sem and "ticketStatus" in result.columns and not t_no:
        status_sem = str(status_sem).lower()
        if status_sem in ["unresolved", "open", "pending", "active"]:
            closed_terms = ["closed", "resolved", "completed"]
            mask = result["ticketStatus"].apply(
                lambda x: not any(ct in str(x).lower() for ct in closed_terms) if pd.notna(x) else True
            )
            result = result[mask]
        elif status_sem in ["closed", "resolved", "completed"]:
            closed_terms = ["closed", "resolved", "completed"]
            mask = result["ticketStatus"].apply(
                lambda x: any(ct in str(x).lower() for ct in closed_terms) if pd.notna(x) else False
            )
            result = result[mask]
        elif status_sem == "created":
            mask = result["ticketStatus"].apply(
                lambda x: "created" in str(x).lower() if pd.notna(x) else False
            )
            result = result[mask]

    # 4. Filter by Priority
    priority = plan.get("detected_priority")
    if priority and "priority" in result.columns and not t_no:
        p_lower = str(priority).lower()
        mask = result["priority"].apply(
            lambda x: p_lower == str(x).lower()
            or (("high" in p_lower or "p2" in p_lower) and any(k in str(x).lower() for k in ["high", "p2"]))
            or (("very high" in p_lower or "p1" in p_lower or "critical" in p_lower) and any(k in str(x).lower() for k in ["very high", "critical", "p1"]))
            or (("medium" in p_lower or "p3" in p_lower) and any(k in str(x).lower() for k in ["medium", "p3"]))
            or (("low" in p_lower or "p4" in p_lower) and any(k in str(x).lower() for k in ["low", "p4"]))
            if pd.notna(x) else False
        )
        if mask.any():
            result = result[mask]

    # 5. Filter by Assignment Group / Module
    group = plan.get("detected_group_or_module")
    if group and not t_no:
        g_lower = str(group).lower()
        mask = result.apply(
            lambda r: g_lower in str(r.get("assigntogroup", "")).lower()
            or g_lower in str(r.get("module", "")).lower()
            or g_lower in str(r.get("remarks", "")).lower(),
            axis=1
        )
        if mask.any():
            result = result[mask]

    # 6. Filter by Reporter
    reporter = plan.get("detected_reporter")
    if reporter and not t_no:
        r_lower = str(reporter).lower()
        mask = result.apply(
            lambda r: r_lower in str(r.get("createdname", "")).lower()
            or r_lower in str(r.get("createdEmails", "")).lower()
            or r_lower in str(r.get("reportedby", "")).lower(),
            axis=1
        )
        if mask.any():
            result = result[mask]

    # 7. Filter by Date Range
    date_info = plan.get("date_range")
    if date_info and date_info.get("type") and not t_no:
        start_bound, end_bound = parse_date_range(date_info)
        if start_bound or end_bound:
            date_col = "createddate" if "createddate" in result.columns else ("reportedon" if "reportedon" in result.columns else None)
            if date_col:
                def date_filter(row_val):
                    dt = safe_parse_datetime(row_val)
                    if not dt:
                        return True
                    if start_bound and dt < start_bound:
                        return False
                    if end_bound and dt > end_bound:
                        return False
                    return True

                result = result[result[date_col].apply(date_filter)]

    # 8. Semantic Text Search on Description / Remarks / Comments
    search_text = plan.get("semantic_text_search")
    if search_text and not t_no:
        st_lower = str(search_text).lower().strip()
        search_keywords = [w for w in re.findall(r'\w+', st_lower) if len(w) > 2 and w not in ["show", "find", "tickets", "list", "get", "with", "where", "about", "for", "the", "and", "are", "have"]]
        if search_keywords:
            def matches_text(row):
                text_blob = " ".join([
                    str(row.get("descriptionofTicket", "")),
                    str(row.get("remarks", "")),
                    str(row.get("name", "")),
                    str(row.get("clientName", "")),
                    str(row.get("assigntogroup", "")),
                    str(row.get("module", ""))
                ]).lower()
                return any(kw in text_blob for kw in search_keywords)

            mask = result.apply(matches_text, axis=1)
            if mask.any():
                result = result[mask]

    # Aggregation / Grouping statistics calculation
    group_by = plan.get("group_by_field")
    group_stats = None
    if group_by and group_by in result.columns:
        group_stats = result.groupby(group_by).size().reset_index(name="ticket_count")
        group_stats = group_stats.sort_values(by="ticket_count", ascending=False)

    # Sorting & Limit
    sort_info = plan.get("sort")
    if sort_info and sort_info.get("field") and sort_info["field"] in result.columns:
        ascending = (sort_info.get("direction") == "asc")
        result = result.sort_values(by=sort_info["field"], ascending=ascending)

    limit = plan.get("limit")
    if limit and isinstance(limit, int) and limit > 0:
        result = result.head(limit)

    summary_stats = {
        "initial_total": initial_count,
        "filtered_count": len(result),
        "group_stats": group_stats.to_dict(orient="records") if group_stats is not None else None,
        "unique_clients_in_result": list(result["clientName"].dropna().unique()) if "clientName" in result.columns else [],
        "unique_statuses_in_result": list(result["ticketStatus"].dropna().unique()) if "ticketStatus" in result.columns else []
    }

    return result, summary_stats


def generate_natural_response(user_question, plan, summary_stats, df_filtered, history=None):
    """
    Synthesizes a natural-language answer incorporating actual ticket data and query statistics.
    Follows rule #24: Answer the user's question directly first.
    """
    count = summary_stats["filtered_count"]
    sample_records = df_filtered.head(5).to_dict(orient="records") if not df_filtered.empty else []

    # Prompt LLM to synthesize natural response based on concrete data results
    prompt = f"""You are the Dynamic AMS Ticket Intelligence Assistant.
Formulate a clear, business-friendly natural language response to the user's question based strictly on the actual execution results below.

### RULES:
1. ALWAYS answer the user's question directly in the FIRST sentence (e.g. "There are 24 unresolved tickets for ABC...").
2. Never expose internal database filter syntax or technical code implementation unless requested.
3. If counts or statistics were requested, summarize them clearly with bullet points or markdown tables.
4. If no tickets matched, state clearly that no matching tickets were found. Never invent ticket IDs or records.
5. If the request was analytical (e.g. "which client has the most tickets?"), state the conclusion clearly first.

### USER QUESTION:
"{user_question}"

### EXECUTED PLAN INTENT:
{json.dumps(plan)}

### CONCRETE EXECUTION METRICS:
- Total matching records: {count}
- Initial total in database: {summary_stats['initial_total']}
- Group aggregation breakdown: {json.dumps(summary_stats.get('group_stats'))}
- Top 5 matching records sample: {json.dumps(sample_records)}

Write the natural language response:
"""

    natural_res = _call_llm(prompt, system_instruction=SYSTEM_PROMPT)

    if natural_res:
        return natural_res.strip()

    # Heuristic fallback response generation if LLM is unavailable
    intent = plan.get("intent")
    client = plan.get("detected_client")
    priority = plan.get("detected_priority")
    status_sem = plan.get("detected_status_semantic")
    t_no = plan.get("detected_ticket_no")

    if intent in ["greeting", "general_inquiry"]:
        return (
            "👋 **Hello! I'm your Dynamic AMS Ticket Intelligence Assistant.**\n\n"
            "I can help you dynamically query, search, and manage your AMS tickets. Here is what you can do:\n\n"
            "- **Search & Filter**: *'Show unresolved P2 tickets for ATG'* or *'Tickets reported this week'*\n"
            "- **Analyze Metrics**: *'Which client has the most tickets?'* or *'Count of open SAP-MM tickets'*\n"
            "- **Ticket Details**: Enter any Ticket No (e.g. `ATG2608234` or `Kar2608133`)\n"
            "- **Create Tickets**: *'Create ticket for Karamtara: SAP login error, priority High'*\n\n"
            "How can I assist you today?"
        )

    if intent == "ticket_creation":
        client_str = f" for **{client}**" if client else ""
        return (
            f"### 🎫 Create AMS Ticket{client_str}\n\n"
            "I can help you create this ticket! Please specify details such as:\n"
            "- **Client Name** (e.g. `client: Karamtara` or `ATG`)\n"
            "- **Priority** (`Low`, `Medium`, `High`, `Critical`)\n"
            "- **Description** (e.g. `issue: SAP login authentication failed`)\n"
            "- **Reported By** (e.g. `reported by: Jaswanth`)\n\n"
            "Or reply with the missing fields to complete your ticket draft."
        )

    if t_no and count == 1:
        row = df_filtered.iloc[0]
        return (
            f"### 🎫 Ticket Details: **{row.get('ticketNo') or row.get('ticketId') or t_no}**\n\n"
            f"- **Client Name**: `{row.get('clientName', 'N/A')}`\n"
            f"- **Status**: `{row.get('ticketStatus', 'N/A')}`\n"
            f"- **Priority**: `{row.get('priority', 'N/A')}`\n"
            f"- **Assign To Group**: `{row.get('assigntogroup') or row.get('module', 'N/A')}`\n"
            f"- **Created By**: {row.get('createdname', 'N/A')} ({row.get('createdEmails', '')})\n"
            f"- **Description**: {row.get('descriptionofTicket') or row.get('remarks', 'N/A')}\n"
            f"- **Transaction ID**: `{row.get('txnId', 'N/A')}`"
        )

    if count == 0:
        target_str = f" for client **{client}**" if client else ""
        return f"I couldn't find any tickets matching your request (**'{user_question}'**){target_str} in the current dataset."

    if intent in ["ranking", "counting", "aggregation"] and summary_stats.get("group_stats"):
        top_group = summary_stats["group_stats"][0]
        field_name = plan.get("group_by_field") or "category"
        top_name = top_group.get(field_name) or top_group.get("clientName") or top_group.get("assigntogroup")
        top_val = top_group.get("ticket_count", 0)
        
        res = f"**{top_name}** has the highest ticket count with **{top_val}** ticket(s).\n\n"
        res += "### Breakdown:\n"
        for g in summary_stats["group_stats"][:5]:
            name = g.get(field_name) or g.get("clientName") or g.get("assigntogroup") or "Other"
            res += f"- **{name}**: {g.get('ticket_count')} tickets\n"
        return res

    filter_desc = []
    if client: filter_desc.append(f"client **{client}**")
    if status_sem: filter_desc.append(f"status **{status_sem}**")
    if priority: filter_desc.append(f"priority **{priority}**")

    matching_desc = " (" + ", ".join(filter_desc) + ")" if filter_desc else ""
    return f"There are **{count}** ticket(s) matching your request{matching_desc}."


def process_ticket_query(tickets_data, user_question, history=None):
    """
    Main entry point for processing conversational ticket queries dynamically.
    Returns: (answer_markdown_text, filtered_tickets_list_or_df)
    """
    if not tickets_data:
        return "No ticket data is currently loaded. Please ensure credentials are correct and refresh ticket data.", None

    # Step 1: Inspect schema & dataset metadata dynamically
    meta = get_dataset_metadata(tickets_data)

    # Step 2: Formulate dynamic Query Plan using LLM / NLU
    plan = parse_query_plan_with_llm(user_question, meta, history=history)

    # Check for clarification request if client is ambiguous
    if plan.get("ambiguous_client_match") and plan.get("clarification_question"):
        return plan["clarification_question"], None

    # Step 3: Execute query plan dynamically against pandas DataFrame
    df_filtered, summary_stats = execute_query_plan(tickets_data, plan)

    # Step 4: Generate natural language response backed by concrete results
    natural_answer = generate_natural_response(user_question, plan, summary_stats, df_filtered, history=history)

    # Return records as list of dicts for Streamlit table display
    records_out = df_filtered.to_dict(orient="records") if not df_filtered.empty else None

    return natural_answer, records_out
