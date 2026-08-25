import os
import requests
from dotenv import load_dotenv

load_dotenv()


class AMSApi:
    def __init__(self, username=None, password=None):
        self.username = username or os.getenv("AMS_USERNAME", "")
        self.password = password or os.getenv("AMS_PASSWORD", "")
        self.auth_url = os.getenv("AMS_AUTH_URL", "http://172.16.32.50/api/Auth/login")
        self.ticket_url = os.getenv("AMS_TICKET_URL", "http://172.16.32.50/api/Ticket")
        self.ticket_status_url = os.getenv("AMS_TICKET_STATUS_URL", "http://172.16.32.50/api/Ticket/Status")
        self.ticket_create_url = os.getenv("AMS_TICKET_CREATE_URL", "http://172.16.32.50/api/Ticket/CreateTicket")
        self.token = None

    def authenticate(self, username=None, password=None):
        if username is not None:
            self.username = username
        if password is not None:
            self.password = password

        if not self.username or self.username == "your_username" or not self.password or self.password == "your_password":
            raise Exception(
                "Invalid credentials configured. Please enter your actual AMS Username and Password in the sidebar or update the .env file."
            )

        payload = {
            "userName": self.username,
            "password": self.password
        }
    
        headers = {
            "Accept": "*/*",
            "Content-Type": "application/json"
        }
    
        try:
            response = requests.post(
                self.auth_url,
                json=payload,
                headers=headers,
                timeout=30
            )
        except requests.exceptions.RequestException as err:
            raise Exception(f"Failed to reach AMS Authentication server at {self.auth_url}: {err}")
    
        print("STATUS:", response.status_code)
        print("RESPONSE:", response.text)
    
        if response.status_code == 401:
            raise Exception(
                f"Authentication failed (401 Unauthorized) for user '{self.username}'. Please check your username and password."
            )
        
        response.raise_for_status()
    
        data = response.json()
        token = data.get("token")
    
        if not token:
            raise Exception(
                f"Token not found in authentication response: {data}"
            )
    
        self.token = token
        return token

    def get_tickets(self):
        """Get AMS tickets using JWT."""
        if not self.token:
            self.authenticate()
        headers = {
            "Authorization": f"Bearer {self.token}",
            "Accept": "application/json"
        }
        try:
            response = requests.get(
                self.ticket_url,
                headers=headers,
                timeout=60
            )
        except requests.exceptions.RequestException as err:
            raise Exception(f"Failed to reach AMS Ticket API at {self.ticket_url}: {err}")

        # Token might have expired
        if response.status_code == 401:
            self.authenticate()
            headers["Authorization"] = f"Bearer {self.token}"
            response = requests.get(
                self.ticket_url,
                headers=headers,
                timeout=60
            )
        response.raise_for_status()
        data = response.json()
        
        if isinstance(data, list):
            return data
        if isinstance(data, dict):
            if isinstance(data.get("data"), list):
                return data["data"]
            if isinstance(data.get("result"), list):
                return data["result"]
        raise Exception(
            "Unexpected ticket API response format."
        )

    def get_ticket_status(self):
        """Get AMS ticket statuses from /api/Ticket/Status using JWT."""
        if not self.token:
            self.authenticate()
        headers = {
            "Authorization": f"Bearer {self.token}",
            "Accept": "application/json"
        }
        try:
            response = requests.get(
                self.ticket_status_url,
                headers=headers,
                timeout=60
            )
        except requests.exceptions.RequestException as err:
            raise Exception(f"Failed to reach AMS Ticket Status API at {self.ticket_status_url}: {err}")

        if response.status_code == 401:
            self.authenticate()
            headers["Authorization"] = f"Bearer {self.token}"
            response = requests.get(
                self.ticket_status_url,
                headers=headers,
                timeout=60
            )
        response.raise_for_status()
        data = response.json()

        if isinstance(data, list):
            return data
        if isinstance(data, dict):
            if isinstance(data.get("data"), list):
                return data["data"]
            if isinstance(data.get("result"), list):
                return data["result"]
        raise Exception("Unexpected ticket status API response format.")

    def create_ticket(self, ticket_data):
        """
        Create a new ticket in AMS via /api/Ticket/CreateTicket.
        Allowed priorities in AMS database:
          - 'Low'
          - 'Medium'
          - 'High (Business Impacted)'
          - 'Very High (Production Impacted)'
        """
        if not self.token:
            self.authenticate()
        
        # Clone payload and normalize priority if short form was given
        payload = dict(ticket_data)
        prio = payload.get("priority")
        if prio:
            prio_clean = str(prio).strip().lower()
            if prio_clean in ["high", "p2"]:
                payload["priority"] = "High (Business Impacted)"
            elif prio_clean in ["critical", "very high", "veryhigh", "p1"]:
                payload["priority"] = "Very High (Production Impacted)"
            elif prio_clean in ["medium", "med", "p3"]:
                payload["priority"] = "Medium"
            elif prio_clean in ["low", "p4"]:
                payload["priority"] = "Low"

        headers = {
            "Authorization": f"Bearer {self.token}",
            "Accept": "*/*",
            "Content-Type": "application/json"
        }
        try:
            response = requests.post(
                self.ticket_create_url,
                json=payload,
                headers=headers,
                timeout=60
            )
        except requests.exceptions.RequestException as err:
            raise Exception(f"Failed to reach AMS Ticket Create API at {self.ticket_create_url}: {err}")

        if response.status_code == 401:
            self.authenticate()
            headers["Authorization"] = f"Bearer {self.token}"
            response = requests.post(
                self.ticket_create_url,
                json=ticket_data,
                headers=headers,
                timeout=60
            )

        if not response.ok:
            error_msg = response.text.strip()
            try:
                err_json = response.json()
                error_msg = err_json.get("message") or err_json.get("title") or response.text.strip()
            except Exception:
                pass
            
            if response.status_code == 500:
                hint = (
                    " (Hint: Server Error 500 is typically caused by an unrecognized 'priority' value (use 'Low', 'Medium', 'High', 'Critical') "
                    "or an unregistered 'clientName' in the database.)"
                )
                raise Exception(f"Ticket creation failed (500): {error_msg if error_msg else 'Internal Server Error'}{hint}")
            
            raise Exception(f"Ticket creation failed ({response.status_code}): {error_msg}")

        try:
            return response.json()
        except Exception:
            return {"status": "success", "statusCode": response.status_code, "text": response.text}

