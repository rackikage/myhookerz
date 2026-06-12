#!/usr/bin/env python3
"""
ig_creator.py — Mass Instagram account creator
Uses instagrapi (Android private API emulation)
Now with SMS verification support via rooted SMS gateway
"""
import sys
import os
import json
import time
import random
import threading
import string as string_module
from queue import Queue
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from instagrapi import Client
from instagrapi.exceptions import (
    ClientError, LoginRequired, BadPassword,
    ReloginAttempt, ChallengeRequired, RecaptchaChallengeRequired,
    FeedbackRequired, PleaseWaitFewMinutes, SentryBlock,
    RateLimitError, TwoFactorRequired
)

from core.email_factory import EmailFactory

try:
    from core.sms_gateway import SMSGateway, DualSIMRotator
    SMS_AVAILABLE = True
except:
    SMS_AVAILABLE = False

DEVICE_SETTINGS = [
    {"app_version": "219.0.0.12.117", "android_version": 28, "android_release": "9.0",
     "manufacturer": "Xiaomi", "device": "Mi 9", "model": "grus",
     "dpi": "420dpi", "resolution": "1080x1920", "chipset": "qcom"},
    {"app_version": "219.0.0.12.117", "android_version": 29, "android_release": "10.0",
     "manufacturer": "samsung", "device": "SM-G975F", "model": "beyond2",
     "dpi": "440dpi", "resolution": "1080x2340", "chipset": "exynos9820"},
    {"app_version": "219.0.0.12.117", "android_version": 30, "android_release": "11.0",
     "manufacturer": "OnePlus", "device": "KB2003", "model": "kebab",
     "dpi": "480dpi", "resolution": "1440x3040", "chipset": "sm8250"},
    {"app_version": "219.0.0.12.117", "android_version": 31, "android_release": "12.0",
     "manufacturer": "Google", "device": "Pixel 6", "model": "oriole",
     "dpi": "420dpi", "resolution": "1080x2400", "chipset": "tensor"},
    {"app_version": "219.0.0.12.117", "android_version": 32, "android_release": "12.0",
     "manufacturer": "OPPO", "device": "CPH2211", "model": "kona",
     "dpi": "440dpi", "resolution": "1080x2340", "chipset": "qcom"},
    {"app_version": "276.0.0.21.94", "android_version": 33, "android_release": "13.0",
     "manufacturer": "samsung", "device": "SM-S918B", "model": "dm1q",
     "dpi": "500dpi", "resolution": "1440x3088", "chipset": "exynos2200"},
]

USER_AGENTS = [
    "Instagram 219.0.0.12.117 Android (28/9; 420dpi; 1080x1920; Xiaomi; Mi 9; grus; qcom; en_US; 123456789)",
    "Instagram 219.0.0.12.117 Android (29/10; 440dpi; 1080x2340; samsung; SM-G975F; beyond2; exynos9820; en_GB; 987654321)",
    "Instagram 219.0.0.12.117 Android (30/11; 480dpi; 1440x3040; OnePlus; KB2003; kebab; sm8250; en_US; 456789123)",
    "Instagram 219.0.0.12.117 Android (31/12; 420dpi; 1080x2400; Google; Pixel 6; oriole; tensor; en_US; 321654987)",
    "Instagram 219.0.0.12.117 Android (32/12; 440dpi; 1080x2340; OPPO; CPH2211; kona; qcom; en_IN; 654987321)",
    "Instagram 276.0.0.21.94 Android (33/13; 500dpi; 1440x3088; samsung; SM-S918B; dm1q; exynos2200; en_US; 789123456)",
]

class IGCreator:
    def __init__(self, proxy=None, settings_dir="accounts"):
        self.client = Client()
        self.proxy = proxy
        self.settings_dir = settings_dir
        os.makedirs(self.settings_dir, exist_ok=True)
        dev = random.choice(DEVICE_SETTINGS)
        self.client.set_device(dev)
        self.client.set_user_agent(random.choice(USER_AGENTS))
        self.client.set_locale('en_US')
        if proxy:
            self.client.set_proxy(proxy)
        self.sms_gateway = None
        if SMS_AVAILABLE:
            try:
                self.sms_gateway = SMSGateway()
                print(f"    [SMS] Gateway initialized (root={self.sms_gateway.use_root})")
            except:
                pass
    
    def create_account(self, email, password, full_name=None, username=None,
                      phone_number=None, use_sms_verification=False):
        if not username:
            adj = random.choice(['cool', 'neo', 'zen', 'arc', 'vox', 'pix',
                                'flux', 'nova', 'cosmo', 'byte', 'echo',
                                'zero', 'volt', 'wave', 'sage'])
            num = ''.join(random.choices(string_module.digits, k=4))
            suffix = ''.join(random.choices(string_module.ascii_lowercase, k=2))
            username = f"{adj}{num}{suffix}"
        if not full_name:
            full_name = username.split('_')[0].title()
        result = {
            'username': username, 'password': password, 'email': email,
            'phone': phone_number, 'proxy': self.proxy,
            'success': False, 'verified': False,
            'verification_method': None, 'user_id': None,
            'settings_file': None, 'error': None
        }
        try:
            if self.proxy:
                self.client.set_proxy(self.proxy)
            print(f"    [*] Signing up as {username}...")
            user_id = self.client.signup(
                username=username, password=password,
                email=email, phone_number=phone_number,
                full_name=full_name
            )
            settings_file = f"{self.settings_dir}/{username}.json"
            self.client.dump_settings(settings_file)
            result['success'] = True
            result['user_id'] = user_id
            result['settings_file'] = settings_file
            if self.sms_gateway and use_sms_verification:
                print(f"    [*] Waiting for SMS verification code...")
                code, sender, body = self.sms_gateway.wait_for_code(timeout=90)
                if code:
                    result['verified'] = True
                    result['verification_method'] = 'sms'
                    result['verification_code'] = code
                    print(f"    [+] SMS code: {code}")
            return result
        except ChallengeRequired as e:
            print(f"    [!] Challenge required: {e}")
            result['error'] = 'challenge'
            result['msg'] = str(e)
            if self.sms_gateway:
                print(f"    [*] Waiting for challenge SMS code...")
                code, sender, body = self.sms_gateway.wait_for_code(timeout=120)
                if code:
                    print(f"    [+] Challenge code: {code}")
                    try:
                        self.client.challenge_resolve(self.client.last_json.get('challenge', {}))
                        self.client.dump_settings(f"{self.settings_dir}/{username}.json")
                        result['success'] = True
                        result['verified'] = True
                        result['verification_method'] = 'sms_challenge'
                    except Exception as ce:
                        print(f"    [!] Challenge resolve failed: {ce}")
        except FeedbackRequired as e:
            print(f"    [!] Feedback required: {e}")
            result['error'] = 'feedback'
            result['msg'] = str(e)
        except PleaseWaitFewMinutes as e:
            print(f"    [!] Rate limited: {e}")
            result['error'] = 'ratelimit'
            result['msg'] = str(e)
        except RecaptchaChallengeRequired:
            print(f"    [!] reCAPTCHA triggered")
            result['error'] = 'recaptcha'
        except TwoFactorRequired:
            print(f"    [!] 2FA required (unexpected for new account)")
            result['error'] = '2fa'
        except Exception as e:
            print(f"    [!] Error: {type(e).__name__}: {e}")
            result['error'] = type(e).__name__
            result['msg'] = str(e)
        return result
    
    def verify_by_email_code(self, username, code):
        settings_file = f"{self.settings_dir}/{username}.json"
        if os.path.exists(settings_file):
            try:
                self.client.load_settings(settings_file)
                self.client.login_by_code(username, code)
                self.client.dump_settings(settings_file)
                return True
            except Exception as e:
                print(f"    [!] Email verify failed: {e}")
        return False

class MassCreator:
    def __init__(self, num_accounts, proxies=None, threads=5, phone_numbers=None,
                 use_sms=False):
        self.num = num_accounts
        self.proxies = proxies or [None]
        self.threads = threads
        self.phone_numbers = phone_numbers or []
        self.use_sms = use_sms
        self.results = Queue()
        self.email_factory = EmailFactory()
        self.sim_rotator = None
        if self.use_sms and len(self.phone_numbers) >= 2 and SMS_AVAILABLE:
            self.sim_rotator = DualSIMRotator(self.phone_numbers[0], self.phone_numbers[1])
            print(f"[+] Dual-SIM rotator initialized: {self.phone_numbers}")
    
    def _worker(self, worker_id):
        while True:
            try:
                proxy = random.choice(self.proxies) if self.proxies else None
                phone = None
                if self.use_sms and self.phone_numbers:
                    phone = random.choice(self.phone_numbers)
                creator = IGCreator(proxy=proxy, settings_dir="accounts")
                email, email_pw, token, _ = self.email_factory.create_email("ig_")
                print(f"[Worker {worker_id}] Email: {email}")
                chars = string_module.ascii_letters + string_module.digits + "!@#$%^&*"
                acc_pw = ''.join(random.choices(chars, k=16))
                result = creator.create_account(
                    email=email, password=acc_pw,
                    phone_number=phone, use_sms_verification=self.use_sms
                )
                if result['success']:
                    print(f"[Worker {worker_id}] Checking email for verification code...")
                    code, body = self.email_factory.wait_for_verification_code(email, token, timeout=60)
                    if code:
                        print(f"[Worker {worker_id}] Email code: {code}")
                        creator.verify_by_email_code(result['username'], code)
                        result['verified'] = True
                        result['verification_method'] = 'email'
                    self.results.put(('success', result))
                    print(f"[✓] Account created: {result['username']}")
                else:
                    self.results.put(('fail', result))
            except Exception as e:
                self.results.put(('error', str(e)))
    
    def run(self):
        threads = []
        for i in range(min(self.threads, self.num)):
            t = threading.Thread(target=self._worker, args=(i,), daemon=True)
            t.start()
            threads.append(t)
        accounts = []
        completed = 0
        while completed < self.num:
            status, data = self.results.get(timeout=600)
            completed += 1
            if status == 'success':
                accounts.append(data)
                created = len([a for a in accounts if a.get('success')])
                verified = len([a for a in accounts if a.get('verified')])
                print(f"\r[Progress] {completed}/{self.num} | Created: {created} | Verified: {verified}", end='')
        print()
        return accounts

if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description='Instagram Account Creator')
    parser.add_argument('--count', type=int, default=1, help='Number of accounts')
    parser.add_argument('--proxies', type=str, help='Proxy list file')
    parser.add_argument('--threads', type=int, default=3, help='Worker threads')
    parser.add_argument('--phone1', type=str, help='SIM1 phone number')
    parser.add_argument('--phone2', type=str, help='SIM2 phone number')
    parser.add_argument('--sms', action='store_true', help='Use SMS verification')
    args = parser.parse_args()
    proxies = None
    if args.proxies:
        with open(args.proxies) as f:
            proxies = [l.strip() for l in f if l.strip()]
        print(f"[*] Loaded {len(proxies)} proxies")
    phones = []
    if args.phone1:
        phones.append(args.phone1)
    if args.phone2:
        phones.append(args.phone2)
    if phones:
        print(f"[*] Using phone numbers: {phones}")
    creator = MassCreator(
        num_accounts=args.count, proxies=proxies,
        threads=args.threads, phone_numbers=phones, use_sms=args.sms
    )
    accounts = creator.run()
    timestamp = int(time.time())
    with open(f"accounts/batch_{timestamp}.json", 'w') as f:
        json.dump(accounts, f, indent=2)
    print(f"\n[✓] Saved {len(accounts)} accounts to accounts/batch_{timestamp}.json")
    try:
        import requests
        for acc in accounts:
            if acc.get('success'):
                requests.post('http://localhost:5000/api/bot/add', json={
                    'username': acc['username'], 'password': acc['password'],
                    'email': acc.get('email', ''), 'phone': acc.get('phone', ''),
                    'settings_file': str(Path(f"accounts/{acc['username']}.json").resolve()),
                    'proxy': acc.get('proxy', '')
                })
        print("[✓] Registered with C2 server")
    except:
        print("[!] C2 not running — accounts saved locally")
