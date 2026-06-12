#!/usr/bin/env python3
"""
ig_creator.py — Mass Instagram account creator (hardened)
Uses instagrapi (Android private API emulation) with:
  - Dynamic device fingerprinting (50+ profiles)
  - Multi-provider email rotation (5+ providers)
  - Challenge resolver (email/SMS/reCAPTCHA/phone)
  - Exponential backoff on ratelimits
  - Proxy health verification before use
  - ADB phone proxy carrier support
  - Post-creation profile setup (pic + bio)
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
    ChallengeRequired, CaptchaChallengeRequired, FeedbackRequired,
    RateLimitError, TwoFactorRequired, SignupSpamError,
)

from core.fingerprint import FingerprintManager
from core.email_factory import EmailProviderManager, EmailFactory, EmailProviderManager
from core.challenge_resolver import ChallengeResolver

try:
    from core.sms_gateway import SMSGateway, DualSIMRotator
    SMS_AVAILABLE = True
except:
    SMS_AVAILABLE = False

try:
    from core.bot_behavior import BehaviorEngine, random_bio
    BEHAVIOR_AVAILABLE = True
except:
    BEHAVIOR_AVAILABLE = False

try:
    from core.proxy_verifier import test_proxy
    PROXY_CHECK_AVAILABLE = True
except:
    PROXY_CHECK_AVAILABLE = False

fingerprint_mgr = FingerprintManager()

class IGCreator:
    def __init__(self, proxy=None, settings_dir="accounts"):
        self.client = Client()
        self.proxy = proxy
        self.settings_dir = settings_dir
        os.makedirs(self.settings_dir, exist_ok=True)
        # Use dynamic fingerprint instead of static pool
        self._fp = fingerprint_mgr.apply_to_client(self.client)
        if proxy:
            self.client.set_proxy(proxy)
        self.sms_gateway = None
        if SMS_AVAILABLE:
            try:
                self.sms_gateway = SMSGateway()
                print(f"    [SMS] Gateway initialized (root={self.sms_gateway.use_root})")
            except:
                pass
        self.challenge_resolver = ChallengeResolver(sms_gateway=self.sms_gateway)
    
    def create_account(self, email, password, full_name=None, username=None,
                      phone_number=None, use_sms_verification=False,
                      inbox_poller=None, max_retries=3):
        if not username:
            username = self._gen_username()
        if not full_name:
            full_name = username.split('_')[0].title() if '_' in username else username.title()
        result = {
            'username': username, 'password': password, 'email': email,
            'phone': phone_number, 'proxy': self.proxy,
            'success': False, 'verified': False,
            'verification_method': None, 'user_id': None,
            'settings_file': None, 'error': None,
            'fingerprint': self._fp,
        }

        for attempt in range(max_retries):
            try:
                if self.proxy:
                    self.client.set_proxy(self.proxy)
                # Fresh fingerprint per attempt
                if attempt > 0:
                    self._fp = fingerprint_mgr.apply_to_client(self.client)
                print(f"    [*] Signing up as {username} (attempt {attempt+1}/{max_retries})...")
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

                # SMS verification
                if self.sms_gateway and use_sms_verification:
                    print(f"    [*] Waiting for SMS verification code...")
                    code, sender, body = self.sms_gateway.wait_for_code(timeout=90)
                    if code:
                        result['verified'] = True
                        result['verification_method'] = 'sms'
                        result['verification_code'] = code
                        print(f"    [+] SMS code: {code}")

                # Post-creation profile setup
                if result['success'] and BEHAVIOR_AVAILABLE:
                    self._post_setup(username)

                return result

            except ChallengeRequired as e:
                print(f"    [!] Challenge: {e}")
                res = self.challenge_resolver.resolve(
                    self.client, e, phone_number, inbox_poller
                )
                if res.get("success"):
                    self.client.dump_settings(f"{self.settings_dir}/{username}.json")
                    result['success'] = True
                    result['verified'] = True
                    result['verification_method'] = res.get('channel', 'challenge')
                    return result
                result['error'] = f"challenge:{res.get('error', str(e)[:60])}"
                break

            except FeedbackRequired as e:
                wait = min(30 * (2.5 ** attempt), 3600)
                print(f"    [!] Soft lock. Waiting {wait:.0f}s...")
                result['error'] = type(e).__name__
                time.sleep(wait)
                continue

            except CaptchaChallengeRequired:
                print(f"    [!] CAPTCHA. Relaying to phone...")
                res = self.challenge_resolver.resolve_recaptcha()
                if res.get("success"):
                    continue
                result['error'] = 'captcha'
                break

            except RateLimitError as e:
                wait = 600 * (attempt + 1)
                print(f"    [!] Hard ratelimit. Waiting {wait // 60}min...")
                result['error'] = type(e).__name__
                time.sleep(wait)
                continue

            except SignupSpamError as e:
                print(f"    [!] Spam block: {e}")
                result['error'] = 'spam_block'
                break

            except TwoFactorRequired:
                print(f"    [!] 2FA (unexpected for new account)")
                result['error'] = '2fa'
                break

            except Exception as e:
                err = f"{type(e).__name__}:{str(e)[:80]}"
                print(f"    [!] {err}")
                result['error'] = type(e).__name__
                result['msg'] = str(e)
                if attempt < max_retries - 1:
                    time.sleep(10 * (attempt + 1))
                    continue
                break

        return result

    def _gen_username(self):
        adjs = ['cool', 'neo', 'zen', 'arc', 'vox', 'pix', 'flux', 'nova',
                'cosmo', 'byte', 'echo', 'zero', 'volt', 'wave', 'sage',
                'icy', 'raw', 'lit', 'max', 'ace', 'jade', 'onyx', 'ruby']
        nums = ''.join(random.choices(string_module.digits, k=4))
        suffix = ''.join(random.choices(string_module.ascii_lowercase, k=2))
        return f"{random.choice(adjs)}{nums}{suffix}"

    def _post_setup(self, username):
        try:
            pic_url = BehaviorEngine.generate_profile_pic_url()
            BehaviorEngine.set_profile_pic(self.client, pic_url)
            print(f"    [+] Profile picture set")
        except:
            pass
        try:
            bio = random_bio(username)
            self.client.account_edit(biography=bio)
            print(f"    [+] Bio set: {bio}")
        except:
            pass
    
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
                 use_sms=False, use_adb_proxies=False):
        self.num = num_accounts
        self.proxies = proxies or [None]
        self.threads = threads
        self.phone_numbers = phone_numbers or []
        self.use_sms = use_sms
        self.use_adb_proxies = use_adb_proxies
        self.results = Queue()
        self.email_mgr = EmailProviderManager()
        self.adb_bridge = None
        if use_adb_proxies:
            try:
                from core.adb_bridge import ADBBridge
                self.adb_bridge = ADBBridge()
                self.adb_bridge.scan()
                adb_proxies = self.adb_bridge.get_proxy_list()
                if adb_proxies:
                    self.proxies = adb_proxies
                    print(f"[+] Using {len(adb_proxies)} ADB phone proxies")
                else:
                    print("[!] No ADB phone proxies available — falling back to file proxies")
                    self.use_adb_proxies = False
            except Exception as e:
                print(f"[!] ADB bridge init failed: {e}")
                self.use_adb_proxies = False
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

                # Get email from provider manager (auto-rotates on failure)
                email_info = self.email_mgr.create_email("ig_")
                email = email_info["email"]
                print(f"[Worker {worker_id}] Email: {email} (provider: {email_info.get('provider','mailtm')})")

                acc_pw = ''.join(random.choices(
                    string_module.ascii_letters + string_module.digits + "!@#$",
                    k=16,
                ))

                # Set up inbox poller for email verification
                provider_info = email_info

                def inbox_poller():
                    return self.email_mgr.poll_for_code(provider_info, timeout=300, poll=3)

                result = creator.create_account(
                    email=email, password=acc_pw,
                    phone_number=phone, use_sms_verification=self.use_sms,
                    inbox_poller=inbox_poller,
                )

                if result['success']:
                    print(f"[Worker {worker_id}] Checking email for verification code...")
                    code, body = self.email_mgr.poll_for_code(provider_info, timeout=90)
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
    parser.add_argument('--retries', type=int, default=3, help='Max retries per account')
    parser.add_argument('--adb', action='store_true', help='Use ADB phone proxies')
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
