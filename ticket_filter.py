from datetime import datetime


def contains(value, search):
    if value is None:
        return False
    return search.lower() in str(value).lower()


def equals(value, search):
    if value is None:
        return False
    return str(value).strip().lower() == str(search).strip().lower()


def filter_tickets(
    tickets,
    ticket_no=None,
    client_name=None,
    status=None,
    priority=None,
    assigntogroup=None,
    created_name=None,
    created_email=None,
    txn_id=None,
    search_text=None,
    module=None
):
    """
    Filter AMS tickets locally.
    """
    target_group = assigntogroup or module
    result = tickets

    if ticket_no:
        result = [
            t for t in result
            if equals(t.get("ticketNo"), ticket_no)
        ]

    if client_name:
        result = [
            t for t in result
            if contains(t.get("clientName"), client_name)
        ]

    if status:
        result = [
            t for t in result
            if equals(t.get("ticketStatus"), status)
        ]

    if priority:
        result = [
            t for t in result
            if equals(t.get("priority"), priority)
        ]

    if target_group:
        result = [
            t for t in result
            if contains(t.get("assigntogroup") or t.get("module"), target_group)
        ]

    if created_name:
        result = [
            t for t in result
            if contains(t.get("createdname"), created_name)
        ]

    if created_email:
        result = [
            t for t in result
            if contains(t.get("createdEmails"), created_email)
        ]

    if txn_id:
        result = [
            t for t in result
            if equals(t.get("txnId"), txn_id)
        ]

    if search_text:
        searchable_fields = [
            "ticketNo",
            "clientName",
            "ticketStatus",
            "priority",
            "assigntogroup",
            "module",
            "createdname",
            "createdEmails",
            "name",
            "remarks"
        ]
        result = [
            t for t in result
            if any(
                contains(t.get(field), search_text)
                for field in searchable_fields
            )
        ]

    return result
