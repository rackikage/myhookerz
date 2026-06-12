#!/usr/bin/env python3
"""
email_factory.py — Mass temporary email generator
Uses mail.tm API (no API key required, completely free)
"""
import requests
import json
import random
import string
import time
import threading
from queue import Queue

API_BASE = "https://api.mail.tm"

class EmailFactory:
    """Creates and manages temporary email inboxes"""
    
    def __init__(self):
        self.domains = self._get_domains()
        self.active_inboxes = {}
        
    def _get_domains(self):
        r = requests.get(f"{API_BASE}/domains")
        return [d['domain'] for d in r.json()['hydra:member']]
    
    def _random_str(self, length=12):
        return ''.join(random.choices(string.ascii_lowercase + string.digits, k=length))
    
    def create_email(self, prefix=None):
        """Create a fresh temporary email account.
        Returns: (email_address, password, token, inbox_id)
        """
        domain = random.choice(self.domains)
        addr = prefix or self._random_str(10)
        email = f"{addr}@{domain}"
        password = self._random_str(16)
        
        r = requests.post(f"{API_BASE}/accounts", json={
            "address": email,
            "password": password
        })
        if r.status_code != 201:
            raise Exception(f"Failed to create email: {r.text}")
        
        acc_id = r.json()['@id']
        
        r = requests.post(f"{API_BASE}/token", json={
            "address": email,
            "password": password
        })
        token = r.json()['token']
        
        self.active_inboxes[email] = {
            'password': password,
            'token': token,
            'id': acc_id,
            'created': time.time()
        }
        return email, password, token, acc_id
    
    def wait_for_verification_code(self, email, token, timeout=120, poll=3):
        """Wait for Instagram verification email and extract the code.
        Returns: (code_string, full_message_body)
        """
        import re
        headers = {"Authorization": f"Bearer {token}"}
        start = time.time()
        
        while time.time() - start < timeout:
            r = requests.get(f"{API_BASE}/messages", headers=headers)
            if r.status_code == 200:
                msgs = r.json().get('hydra:member', [])
                for msg in msgs:
                    msg_id = msg['@id']
                    r2 = requests.get(f"{API_BASE}{msg_id}", headers=headers)
                    if r2.status_code == 200:
                        body = r2.json().get('text', '') or r2.json().get('html', '')
                        patterns = [
                            r'(\d{6})[^0-9]?.*Instagram',
                            r'Instagram.*?(\d{6})',
                            r'(\d{6})\s+is\s+your',
                            r'(\d{6})'
                        ]
                        for p in patterns:
                            m = re.search(p, body, re.IGNORECASE)
                            if m:
                                code = m.group(1)
                                if len(code) == 6 and code.isdigit():
                                    return code, body
            time.sleep(poll)
        return None, None
    
    def delete_email(self, email):
        """Clean up an inbox"""
        if email in self.active_inboxes:
            acc_id = self.active_inboxes[email]['id']
            token = self.active_inboxes[email]['token']
            headers = {"Authorization": f"Bearer {token}"}
            requests.delete(f"{API_BASE}{acc_id}", headers=headers)
            del self.active_inboxes[email]

# ── Multi-Provider Email ─────────────────────────────────────

class GuerrillaMailProvider:
    """guerrillamail.com — no signup required, stable API."""
    API = "https://api.guerrillamail.com/ajax.php"
    def __init__(self):
        self.sid = None
        self.email_addr = None
        self._create()
    def _create(self):
        import requests
        r = requests.get(self.API, params={"f": "get_email_address"}, timeout=10)
        data = r.json()
        self.email_addr = data["email_addr"]
        self.sid = data["sid"]
        self.alias = data.get("alias", "")
    def create_email(self, prefix=None):
        # guerrilla creates email on init, just return it
        pass
    def get_address(self):
        return self.email_addr
    def get_messages(self):
        import requests
        r = requests.get(self.API, params={
            "f": "get_email_list", "sid": self.sid, "offset": 0
        }, timeout=10)
        data = r.json()
        msgs = []
        for m in data.get("list", []):
            msgs.append({
                "id": m["mail_id"],
                "from": m.get("mail_from", ""),
                "subject": m.get("mail_subject", ""),
                "body": m.get("mail_excerpt", ""),
                "timestamp": m.get("mail_timestamp", 0),
            })
        return msgs
    def delete(self):
        pass

class TempMailOrgProvider:
    """temp-mail.org — requires API key for production."""
    def __init__(self, api_key=None):
        self.api_key = api_key or ""
        self.token = None
        self.email_addr = None
    def available(self):
        return bool(self.api_key)
    def create_email(self, prefix=None):
        import requests
        if not self.available():
            return None, None, None, None
        r = requests.post("https://api.temp-mail.org/request/domains/format/json", timeout=10)
        domains = r.json() if r.status_code == 200 else ["temp-mail.org"]
        domain = random.choice(domains) if domains else "temp-mail.org"
        addr = f"{prefix or 'ig'}{random.randint(10000,99999)}@{domain}"
        self.email_addr = addr
        return addr, None, None, None
    def get_messages(self):
        import requests
        if not self.email_addr:
            return []
        username = self.email_addr.split("@")[0]
        domain = self.email_addr.split("@")[1]
        try:
            r = requests.get(
                f"https://api.temp-mail.org/request/mail/id/{username}/format/json",
                headers={"Authorization": self.api_key} if self.api_key else {},
                timeout=10,
            )
            if r.status_code == 200:
                msgs = []
                for m in r.json():
                    msgs.append({
                        "id": m.get("mail_id", ""),
                        "from": m.get("mail_from", ""),
                        "subject": m.get("mail_subject", ""),
                        "body": m.get("mail_text_only", "") or m.get("mail_html", ""),
                    })
                return msgs
        except:
            pass
        return []

class MailNesiaProvider:
    """mailnesia.com — no API key, simple inbox."""
    def create_email(self, prefix=None):
        addr = f"{prefix or 'ig'}{random.randint(10000,99999)}@mailnesia.com"
        return addr, None, None, None
    def get_messages(self, email_addr):
        import requests
        from bs4 import BeautifulSoup
        username = email_addr.split("@")[0]
        try:
            r = requests.get(f"https://mailnesia.com/mailbox/{username}", timeout=10)
            if r.status_code == 200:
                soup = BeautifulSoup(r.text, "html.parser")
                msgs = []
                for row in soup.select("tr.mail"):
                    cells = row.select("td")
                    if len(cells) >= 3:
                        msgs.append({
                            "id": row.get("data-id", ""),
                            "from": cells[0].get_text(strip=True),
                            "subject": cells[1].get_text(strip=True),
                            "body": cells[2].get_text(strip=True),
                        })
                return msgs
        except:
            pass
        return []

class EmailProviderManager:
    """
    Rotates across multiple email providers automatically.
    Falls through providers on failure.
    """
    PROVIDERS = ["mailtm", "guerrillamail", "mailnesia"]

    def __init__(self, mailtm_factory=None):
        self.mailtm = mailtm_factory or EmailFactory()
        self.guerrilla = None
        self.mailnesia = None
        self.current_provider = "mailtm"
        self.rotation_count = 0

    def create_email(self, prefix=None):
        """Try providers in order. On failure, rotate to next."""
        for attempt in range(len(self.PROVIDERS) * 2):
            provider = self.PROVIDERS[self.rotation_count % len(self.PROVIDERS)]
            try:
                if provider == "mailtm":
                    email, pw, tok, aid = self.mailtm.create_email(prefix)
                    self.current_provider = "mailtm"
                    return {"email": email, "password": pw, "token": tok, "id": aid,
                            "provider": "mailtm"}
                elif provider == "guerrillamail":
                    if not self.guerrilla:
                        self.guerrilla = GuerrillaMailProvider()
                    addr = self.guerrilla.get_address()
                    self.current_provider = "guerrillamail"
                    return {"email": addr, "password": "", "token": self.guerrilla.sid,
                            "id": addr, "provider": "guerrillamail"}
                elif provider == "mailnesia":
                    addr, pw, tok, aid = MailNesiaProvider().create_email(prefix)
                    if addr:
                        self.current_provider = "mailnesia"
                        return {"email": addr, "password": pw, "token": tok,
                                "id": addr, "provider": "mailnesia"}
            except Exception as e:
                print(f"    [Email] {provider} failed: {e}")
            self.rotation_count += 1
            time.sleep(1)
        raise Exception("All email providers exhausted")

    def poll_for_code(self, email_info, timeout=120, poll=3):
        """Wait and extract verification code from whichever provider created it."""
        import re
        provider = email_info.get("provider", "mailtm")
        addr = email_info.get("email", "")
        start = time.time()

        while time.time() - start < timeout:
            try:
                messages = []
                if provider == "mailtm":
                    token = email_info.get("token", "")
                    if token:
                        import requests
                        h = {"Authorization": f"Bearer {token}"}
                        r = requests.get("https://api.mail.tm/messages", headers=h, timeout=10)
                        if r.status_code == 200:
                            msgs = r.json().get("hydra:member", [])
                            for m in msgs:
                                r2 = requests.get(f"https://api.mail.tm{m['@id']}", headers=h, timeout=10)
                                if r2.status_code == 200:
                                    messages.append(r2.json())
                elif provider == "guerrillamail":
                    if self.guerrilla:
                        messages = self.guerrilla.get_messages()
                elif provider == "mailnesia":
                    msgs = MailNesiaProvider().get_messages(addr)
                    messages = [{"body": str(m)} for m in msgs]

                for msg in messages:
                    body = msg.get("text", "") or msg.get("html", "") or str(msg)
                    patterns = [
                        r"(?:Instagram|IG).*?(\d{6})",
                        r"(\d{6}).*?(?:Instagram|IG)",
                        r"(\d{6})\s+is\s+your",
                        r"your\s+code\s+(?:is\s+)?(\d{6})",
                        r"(?:^|\D)(\d{6})(?:\D|$)",
                    ]
                    for p in patterns:
                        m = re.search(p, body, re.IGNORECASE)
                        if m:
                            code = m.group(1)
                            if len(code) == 6 and code.isdigit():
                                return code, body
            except:
                pass
            time.sleep(poll)
        return None, None

class BulkEmailGenerator:
    """Threaded bulk email generator for mass production"""
    
    def __init__(self, count, prefix="ig_", threads=10):
        self.count = count
        self.prefix = prefix
        self.threads = threads
        self.results = Queue()
        self.factory = EmailFactory()
        
    def _worker(self):
        while True:
            try:
                email, pw, tok, aid = self.factory.create_email(self.prefix)
                self.results.put(('success', {
                    'email': email, 'password': pw,
                    'token': tok, 'id': aid
                }))
            except Exception as e:
                self.results.put(('error', str(e)))
                
    def generate(self):
        threads = []
        for _ in range(self.threads):
            t = threading.Thread(target=self._worker, daemon=True)
            t.start()
            threads.append(t)
        
        emails = []
        for i in range(self.count):
            status, data = self.results.get(timeout=60)
            if status == 'success':
                emails.append(data)
                print(f"[+] Email {i+1}/{self.count}: {data['email']}")
        return emails

if __name__ == "__main__":
    factory = EmailFactory()
    email, pw, tok, aid = factory.create_email("test_account")
    print(f"Email: {email}")
    print(f"Pass: {pw}")
    print(f"Token: {tok}")
    print(f"Waiting for verification code...")
    code, body = factory.wait_for_verification_code(email, tok)
    print(f"Code: {code}")
