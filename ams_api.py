import os
import requests
from dotenv import load_dotenv

load_dotenv(override=True)


class AMSApi:
<<<<<<< HEAD
    def __init__(self, email=None, password=None):
        self._email = email
=======
    def __init__(self, username=None, password=None):
        self._username = username
>>>>>>> 7ed548ba8b9e79dba2b884b461997a2f3ead05d4
        self._password = password
        self._auth_url = None
        self._ticket_url = None
        self._ticket_status_url = None
        self._ticket_create_url = None
        self.token = None
        self.token_type = "Bearer"

    def reload_env(self):
        """Reload variables from .env file into os.environ."""
        load_dotenv(override=True)

    @property
<<<<<<< HEAD
    def email(self):
        if self._email and self._email != "your_email":
            return self._email
        self.reload_env()
        return (
            os.getenv("AMS_EMAIL")
            or os.getenv("EMAIL")
            or ""
        )

    @email.setter
    def email(self, value):
        if self._email != value:
            self._email = value
=======
    def username(self):
        if self._username and self._username != "your_username":
            return self._username
        self.reload_env()
        return (
            os.getenv("AMS_USERNAME")
            or os.getenv("AMS_USER")
            or os.getenv("USERNAME")
            or ""
        )

    @username.setter
    def username(self, value):
        if self._username != value:
            self._username = value
>>>>>>> 7ed548ba8b9e79dba2b884b461997a2f3ead05d4
            self.token = None

    @property
    def password(self):
        if self._password and self._password != "your_password":
            return self._password
        self.reload_env()
        return (
            os.getenv("AMS_PASSWORD")
            or os.getenv("AMS_PASS")
            or os.getenv("PASSWORD")
            or ""
        )

    @password.setter
    def password(self, value):
        if self._password != value:
            self._password = value
            self.token = None

    @property
    def auth_url(self):
        if self._auth_url:
            return self._auth_url
        self.reload_env()
        return os.getenv("AMS_AUTH_URL", "http://172.16.32.50/api/Auth/login")

    @auth_url.setter
    def auth_url(self, value):
        self._auth_url = value

    @property
    def ticket_url(self):
        if self._ticket_url:
            return self._ticket_url
        self.reload_env()
        return os.getenv("AMS_TICKET_URL", "http://172.16.32.50/api/Ticket")

    @ticket_url.setter
    def ticket_url(self, value):
        self._ticket_url = value

    @property
    def ticket_status_url(self):
        if self._ticket_status_url:
            return self._ticket_status_url
        self.reload_env()
        return os.getenv("AMS_TICKET_STATUS_URL", "http://172.16.32.50/api/Ticket/Status")

    @ticket_status_url.setter
    def ticket_status_url(self, value):
        self._ticket_status_url = value

    @property
    def ticket_create_url(self):
        if self._ticket_create_url:
            return self._ticket_create_url
        self.reload_env()
        return os.getenv("AMS_TICKET_CREATE_URL", "http://172.16.32.50/api/Ticket/CreateTicket")

    @ticket_create_url.setter
    def ticket_create_url(self, value):
        self._ticket_create_url = value

<<<<<<< HEAD
    def authenticate(self, email=None, password=None):
        if email is not None:
            self.email = email
=======
    def authenticate(self, username=None, password=None):
        if username is not None:
            self.username = username
>>>>>>> 7ed548ba8b9e79dba2b884b461997a2f3ead05d4
        if password is not None:
            self.password = password

        if not self.email or self.email == "your_email" or not self.password or self.password == "your_password":
            raise Exception(
                "Invalid credentials configured. Please enter your actual AMS Email and Password in the sidebar or update the .env file."
            )

        payload = {
            "email": self.email,
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
                f"Authentication failed (401 Unauthorized) for email '{self.email}'. Please check your email and password."
            )
        
        response.raise_for_status()
    
        data = response.json()
        token = data.get("token")
        self.token_type = data.get("tokenType", "Bearer")
        success = data.get("success")
        msg = data.get("message")
        
        if success is False:
            raise Exception(f"Authentication failed: {msg or 'Unknown error'}")

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
        
        # Clone payload and normalize priority if short form or variant was given
        payload = dict(ticket_data)
        prio = payload.get("priority")
        if prio:
            prio_clean = str(prio).strip().lower()
            if "very high" in prio_clean or "critical" in prio_clean or prio_clean in ["p1", "1"]:
                payload["priority"] = "Very High (Production Impacted)"
            elif "high" in prio_clean or prio_clean in ["p2", "2"]:
                payload["priority"] = "High (Business Impacted)"
            elif "med" in prio_clean or prio_clean in ["p3", "3"]:
                payload["priority"] = "Medium"
            elif "low" in prio_clean or prio_clean in ["p4", "4"]:
                payload["priority"] = "Low"

        # Client Name cleaning
        client_name = payload.get("clientName")
        if client_name:
            payload["clientName"] = str(client_name).strip()

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
                json=payload,
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

