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
