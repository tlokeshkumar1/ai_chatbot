"""
test_api.py - Verification script for AMS FastAPI Backend Endpoints with Frontend Authorization
"""

import sys
from fastapi.testclient import TestClient
from main import app

client = TestClient(app)

def run_tests():
    print("[*] Running AMS FastAPI Endpoint Tests with Frontend Authorization...")
    
    # 1. Health Check
    res_health = client.get("/health")
    print(f"1. GET /health -> Status: {res_health.status_code}")
    assert res_health.status_code == 200, "Health check failed"

    # 2. API Info
    res_info = client.get("/api/info")
    print(f"2. GET /api/info -> Status: {res_info.status_code}")
    assert res_info.status_code == 200, "API info failed"

    # 3. Metadata Endpoints
    res_clients = client.get("/api/meta/clients")
    print(f"3. GET /api/meta/clients -> Found {len(res_clients.json().get('clients', []))} client(s)")
    assert res_clients.status_code == 200

    res_groups = client.get("/api/meta/groups")
    print(f"4. GET /api/meta/groups -> Found {len(res_groups.json().get('groups', []))} group(s)")
    assert res_groups.status_code == 200

    # 5. Auth Status
    res_auth = client.get("/api/auth/status")
    print(f"5. GET /api/auth/status -> Status: {res_auth.status_code}")
    assert res_auth.status_code == 200

    # 6. Test LLM Intent: Greeting
    res_greet = client.post("/api/chat", json={"message": "Good morning! How are you?"})
    print(f"6. POST /api/chat (Greeting) -> Intent: {res_greet.json().get('intent')}")
    assert res_greet.status_code == 200

    # 7. Test Frontend Authorization in Body: email + token
    test_email = "developer@acme.corp"
    test_token = "mock_jwt_token_12345"
    res_auth_body = client.post(
        "/api/chat",
        json={
            "message": "Create ticket for Karamtara: Database timeout on cluster 2, priority Critical",
            "email": test_email,
            "token": test_token
        }
    )
    data_auth_body = res_auth_body.json()
    print(f"7. POST /api/chat (Auth via body email+token) -> Intent: {data_auth_body.get('intent')}, ReportedBy: {data_auth_body.get('draft', {}).get('reportedby')}")
    assert res_auth_body.status_code == 200
    assert data_auth_body.get("draft", {}).get("reportedby") == test_email

    # 8. Test Frontend Authorization in Header: Authorization: Bearer <token>
    res_auth_header = client.post(
        "/api/chat",
        json={
            "message": "What can you do?",
            "email": "header_user@example.com"
        },
        headers={"Authorization": f"Bearer {test_token}"}
    )
    print(f"8. POST /api/chat (Auth via Header) -> Status: {res_auth_header.status_code}, Intent: {res_auth_header.json().get('intent')}")
    assert res_auth_header.status_code == 200

    print("\n[+] All endpoint & frontend authorization tests passed successfully!")

if __name__ == "__main__":
    run_tests()
