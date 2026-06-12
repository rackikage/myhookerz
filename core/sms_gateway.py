#!/usr/bin/env python3
"""
sms_gateway.py — Root SMS interceptor for Android
Reads Instagram verification codes directly from the SMS database
or via Termux-API. Supports dual-SIM (2 phone numbers).
"""
import os
import re
import json
import time
import sqlite3
import subprocess
import threading
from pathlib import Path

SMS_DB = "/data/data/com.android.providers.telephony/databases/mmssms.db"
SMS_DB_ALT = "/data/user_de/0/com.android.providers.telephony/databases/mmssms.db"

class SMSGateway:
    """Root-level SMS interception for Instagram verification codes"""
    
    def __init__(self, use_root=True, use_termux_api=True):
        self.use_root = use_root and os.path.exists(SMS_DB)
        self.use_termux_api = use_termux_api
        self.last_id = 0
        self.listener_running = False
        self.incoming_queue = []
        
        if self.use_root:
            self.db_path = SMS_DB if os.path.exists(SMS_DB) else SMS_DB_ALT
            print(f"[+] Root SMS DB found at: {self.db_path}")
        elif self.use_termux_api:
            self._check_termux_api()
            
    def _check_termux_api(self):
        try:
            subprocess.run(["termux-sms-list", "-n", "1"],
                         capture_output=True, timeout=5)
            print("[+] Termux-API available")
        except:
            print("[!] Termux-API not available. Install: pkg install termux-api")
            self.use_termux_api = False
    
    def read_sms_db(self, limit=10):
        if not self.use_root:
            return []
        try:
            conn = sqlite3.connect(self.db_path)
            conn.row_factory = sqlite3.Row
            c = conn.cursor()
            c.execute("""
                SELECT address, body, date, date_sent, type, _id 
                FROM sms 
                WHERE type=1 
                ORDER BY date DESC 
                LIMIT ?
            """, (limit,))
            messages = []
            for row in c.fetchall():
                msg = {
                    'id': row['_id'],
                    'sender': row['address'],
                    'body': row['body'],
                    'timestamp': row['date'],
                    'type': 'inbox'
                }
                messages.append(msg)
            conn.close()
            return messages
        except Exception as e:
            print(f"[!] DB read error: {e}")
            return []
    
    def read_sms_termux(self, limit=1):
        if not self.use_termux_api:
            return []
        try:
            result = subprocess.run(
                ["termux-sms-list", "-t", "inbox", "-n", str(limit)],
                capture_output=True, text=True, timeout=10
            )
            if result.returncode == 0 and result.stdout:
                messages = json.loads(result.stdout)
                formatted = []
                for msg in messages:
                    formatted.append({
                        'id': msg.get('_id', 0),
                        'sender': msg.get('number', msg.get('address', '')),
                        'body': msg.get('body', ''),
                        'timestamp': msg.get('received', 0),
                        'type': 'inbox'
                    })
                return formatted
        except Exception as e:
            print(f"[!] Termux SMS error: {e}")
        return []
    
    def extract_instagram_code(self, body):
        patterns = [
            r'(\d{6})\s+is\s+your\s+Instagram',
            r'Instagram.*?(\d{6})',
            r'(\d{6})[^0-9]?.*?verification',
            r'(\d{6})[^0-9]?.*?code',
            r'(\d{6})\b',
        ]
        for p in patterns:
            m = re.search(p, body, re.IGNORECASE)
            if m:
                code = m.group(1)
                if len(code) == 6 and code.isdigit():
                    return code
        return None
    
    def is_instagram_sms(self, sender, body):
        sender = sender.lower().replace(' ', '').replace('-', '')
        instagram_senders = [
            'instagram', '32665', 'ig', 'meta',
            '+132665', '19033', '326-65'
        ]
        sender_match = any(s in sender for s in instagram_senders)
        body_match = bool(re.search(r'instagram|verification.*?code|confirm.*?login', 
                                     body, re.IGNORECASE))
        return sender_match or body_match
    
    def wait_for_code(self, timeout=120, poll_interval=2, phone_number=None):
        start = time.time()
        seen_ids = set()
        print(f"[*] Listening for Instagram SMS (timeout={timeout}s)...")
        while time.time() - start < timeout:
            if self.use_root:
                messages = self.read_sms_db(limit=10)
            else:
                messages = self.read_sms_termux(limit=5)
            for msg in messages:
                msg_id = msg['id']
                if msg_id in seen_ids:
                    continue
                seen_ids.add(msg_id)
                sender = msg.get('sender', '')
                body = msg.get('body', '')
                if self.is_instagram_sms(sender, body):
                    code = self.extract_instagram_code(body)
                    if code:
                        print(f"[+] Instagram code found: {code} (from {sender})")
                        return code, sender, body
            time.sleep(poll_interval)
        print("[!] Timeout waiting for Instagram SMS")
        return None, None, None
    
    def get_sim_info(self):
        try:
            result = subprocess.run(
                ["termux-telephony-deviceinfo"],
                capture_output=True, text=True, timeout=5
            )
            if result.returncode == 0:
                info = json.loads(result.stdout)
                sim_count = 0
                for key in info:
                    if 'sim' in key.lower() or 'sub' in key.lower():
                        sim_count += 1
                return {'sim_count': max(sim_count, 1), 'data': info}
        except:
            pass
        try:
            result = subprocess.run(
                ["su", "-c", "getprop | grep -i sim"],
                capture_output=True, text=True, timeout=5
            )
            lines = result.stdout.strip().split('\n')
            sim_related = [l for l in lines if 'sim' in l.lower()]
            return {'sim_count': 2, 'raw': sim_related[:10]}
        except:
            pass
        return {'sim_count': 2}
    
    def start_background_listener(self, callback=None):
        self.listener_running = True
        def _listen():
            seen = set()
            while self.listener_running:
                try:
                    if self.use_root:
                        msgs = self.read_sms_db(limit=5)
                    else:
                        msgs = self.read_sms_termux(limit=5)
                    for msg in msgs:
                        msg_id = msg['id']
                        if msg_id in seen:
                            continue
                        seen.add(msg_id)
                        sender = msg.get('sender', '')
                        body = msg.get('body', '')
                        if self.is_instagram_sms(sender, body):
                            code = self.extract_instagram_code(body)
                            if code:
                                entry = {
                                    'code': code,
                                    'sender': sender,
                                    'body': body,
                                    'timestamp': time.time()
                                }
                                self.incoming_queue.append(entry)
                                if callback:
                                    callback(entry)
                except:
                    pass
                time.sleep(2)
        t = threading.Thread(target=_listen, daemon=True)
        t.start()
        print("[+] SMS listener started in background")
        return t
    
    def stop_listener(self):
        self.listener_running = False

class DualSIMRotator:
    def __init__(self, number1, number2):
        self.numbers = [number1, number2]
        self.current_index = 0
        self.gateway = SMSGateway()
    
    def get_next_number(self):
        self.current_index = (self.current_index + 1) % len(self.numbers)
        return self.numbers[self.current_index]
    
    def get_current_number(self):
        return self.numbers[self.current_index]
    
    def wait_for_code_dual(self, timeout=120):
        code, sender, body = self.gateway.wait_for_code(timeout=timeout)
        if code:
            self.get_next_number()
        return code, sender, body

if __name__ == "__main__":
    print("=== SMS Gateway Test ===\n")
    gateway = SMSGateway()
    print("[*] Checking SIM info...")
    sim_info = gateway.get_sim_info()
    print(f"  SIM count: {sim_info.get('sim_count', 'unknown')}")
    print("\n[*] Checking for recent Instagram SMS...")
    if gateway.use_root:
        msgs = gateway.read_sms_db(limit=20)
    else:
        msgs = gateway.read_sms_termux(limit=20)
    found = False
    for msg in msgs[:10]:
        sender = msg.get('sender', '')
        body = msg.get('body', '')
        if gateway.is_instagram_sms(sender, body):
            code = gateway.extract_instagram_code(body)
            print(f"  [IG] From {sender}: {body[:80]}... Code: {code}")
            found = True
    if not found:
        print("  No recent Instagram SMS found")
        print("  Starting listener mode...")
        print("  (Send an Instagram verification SMS to your phone)")
        def on_sms(data):
            print(f"\n[!] INSTAGRAM CODE RECEIVED: {data['code']}")
        gateway.start_background_listener(callback=on_sms)
        try:
            time.sleep(120)
        except KeyboardInterrupt:
            pass
        gateway.stop_listener()
