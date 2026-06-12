"""
account_pipeline.py — Full account lifecycle orchestration
Manages accounts through: create → verify → age → warm → ready

State machine:
  PENDING_CREATE → CREATING → NEEDS_VERIFY → VERIFYING → AGING → WARMING → READY → ACTIVE
                                                                                   ↓
                                                                              BANNED / LOCKED / DEAD

Each state has its own retry logic, timing, and health checks.
"""
import os
import re
import sys
import json
import time
import random
import string
import threading
import sqlite3
from datetime import datetime, timedelta
from pathlib import Path
from queue import Queue

sys.path.insert(0, str(Path(__file__).parent.parent))

from instagrapi import Client
from instagrapi.exceptions import (
    ClientError, LoginRequired, BadPassword,
    ChallengeRequired, CaptchaChallengeRequired,
    FeedbackRequired, RateLimitError, TwoFactorRequired,
    SignupSpamError, EmailVerificationSendError,
)

from core.fingerprint import FingerprintManager
from core.email_factory import EmailProviderManager, EmailFactory
from core.challenge_resolver import ChallengeResolver

try:
    from core.sms_gateway import SMSGateway
    SMS_AVAILABLE = True
except:
    SMS_AVAILABLE = False

try:
    from core.adb_bridge import ADBBridge
    ADB_AVAILABLE = True
except:
    ADB_AVAILABLE = False

try:
    from core.bot_behavior import BehaviorEngine, random_bio
    BEHAVIOR_AVAILABLE = True
except:
    BEHAVIOR_AVAILABLE = False

PIPELINE_DB = "pipeline.db"

STATES = [
    "PENDING_CREATE", "CREATING", "NEEDS_VERIFY", "VERIFYING",
    "AGING", "WARMING", "READY", "ACTIVE", "BANNED", "LOCKED", "DEAD",
]

BACKOFF_BASE = 30
BACKOFF_MAX = 3600
BACKOFF_MULTIPLIER = 2.5


def init_pipeline_db():
    conn = sqlite3.connect(PIPELINE_DB)
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS pipeline_accounts (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            username TEXT UNIQUE NOT NULL,
            password TEXT NOT NULL,
            email TEXT,
            email_provider TEXT,
            email_token TEXT,
            phone TEXT,
            proxy TEXT,
            device_fingerprint TEXT,
            state TEXT DEFAULT 'PENDING_CREATE',
            attempt_count INTEGER DEFAULT 0,
            max_attempts INTEGER DEFAULT 5,
            last_error TEXT,
            created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
            state_changed_at DATETIME DEFAULT CURRENT_TIMESTAMP,
            verified_at DATETIME,
            aged_at DATETIME,
            warmed_at DATETIME,
            ready_at DATETIME,
            banned_at DATETIME,
            notes TEXT
        );
        CREATE TABLE IF NOT EXISTS pipeline_log (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            username TEXT,
            from_state TEXT,
            to_state TEXT,
            message TEXT,
            created_at DATETIME DEFAULT CURRENT_TIMESTAMP
        );
    """)
    conn.commit()
    conn.close()

init_pipeline_db()


def log_pipeline(username, from_state, to_state, message=""):
    conn = sqlite3.connect(PIPELINE_DB)
    conn.execute(
        "INSERT INTO pipeline_log (username, from_state, to_state, message) VALUES (?,?,?,?)",
        (username, from_state, to_state, message),
    )
    conn.commit()
    conn.close()


def update_state(username, new_state, error=None):
    conn = sqlite3.connect(PIPELINE_DB)
    now = datetime.now().isoformat()
    extra = ""
    if new_state == "VERIFYING":
        extra = ", verified_at=NULL"
    elif new_state == "VERIFIED":
        extra = f", verified_at='{now}'"
    elif new_state == "AGING":
        extra = f", aged_at='{now}'"
    elif new_state == "WARMING":
        extra = f", warmed_at='{now}'"
    elif new_state == "READY":
        extra = f", ready_at='{now}'"
    elif new_state in ("BANNED", "DEAD"):
        extra = f", banned_at='{now}'"
    conn.execute(
        f"UPDATE pipeline_accounts SET state=?, state_changed_at=?, last_error=?, attempt_count=attempt_count+1{extra} WHERE username=?",
        (new_state, now, error, username),
    )
    conn.commit()
    conn.close()


def get_pipeline_accounts(state=None, limit=100):
    conn = sqlite3.connect(PIPELINE_DB)
    conn.row_factory = sqlite3.Row
    if state:
        rows = conn.execute(
            "SELECT * FROM pipeline_accounts WHERE state=? ORDER BY created_at DESC LIMIT ?",
            (state, limit),
        ).fetchall()
    else:
        rows = conn.execute(
            "SELECT * FROM pipeline_accounts ORDER BY created_at DESC LIMIT ?",
            (limit,),
        ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def get_pipeline_stats():
    conn = sqlite3.connect(PIPELINE_DB)
    total = conn.execute("SELECT COUNT(*) FROM pipeline_accounts").fetchone()[0]
    by_state = {}
    for s in STATES:
        c = conn.execute("SELECT COUNT(*) FROM pipeline_accounts WHERE state=?", (s,)).fetchone()[0]
        if c:
            by_state[s] = c
    conn.close()
    return {"total": total, "by_state": by_state}


class AccountPipeline:
    """
    Full lifecycle manager for Instagram accounts.
    Orchestrates creation, verification, aging, warming, and health monitoring.
    """

    def __init__(self, proxy_pool=None, adb_bridge=None):
        self.fingerprint = FingerprintManager()
        self.email_provider = EmailProviderManager()
        self.challenge = ChallengeResolver()
        self.proxy_pool = proxy_pool or []
        self.adb_bridge = adb_bridge
        self._running = False
        self._threads = {}
        self._lock = threading.Lock()

    # ── Account Creation ───────────────────────────────────────

    def create_account(self, config=None):
        """
        Create a single account through the full pipeline.
        Returns account dict with state.
        """
        cfg = config or {}
        use_adb = cfg.get("use_adb", bool(self.adb_bridge))
        proxies = cfg.get("proxies") or self.proxy_pool

        # Pick proxy
        proxy = random.choice(proxies) if proxies else None
        if not proxy and use_adb and self.adb_bridge:
            adb_proxies = self.adb_bridge.get_proxy_list()
            if adb_proxies:
                proxy = random.choice(adb_proxies)

        # Get email
        email_info = self.email_provider.create_email("ig_")
        email = email_info["email"]
        email_token = email_info.get("token", "")

        # Generate account details
        username = self._gen_username()
        password = self._gen_password()
        full_name = username.split("_")[0].title() if "_" in username else username.title()

        # Create client with fresh fingerprint
        client = Client()
        fp = self.fingerprint.apply_to_client(client)
        if proxy:
            client.set_proxy(proxy)

        result = {
            "username": username,
            "password": password,
            "email": email,
            "email_token": email_token,
            "email_provider": email_info.get("provider", "mailtm"),
            "proxy": proxy,
            "device_fingerprint": fp["device"],
            "state": "PENDING_CREATE",
            "success": False,
            "error": None,
        }

        # Store in pipeline DB
        self._save_account(result)

        # Attempt creation
        for attempt in range(3):
            try:
                update_state(username, "CREATING")
                log_pipeline(username, "PENDING_CREATE", "CREATING")

                user_id = client.signup(
                    username=username, password=password,
                    email=email, phone_number=cfg.get("phone"),
                    full_name=full_name,
                )

                settings_file = f"accounts/{username}.json"
                client.dump_settings(settings_file)

                result["user_id"] = user_id
                result["settings_file"] = settings_file
                result["success"] = True
                result["fingerprint_log"] = fp
                update_state(username, "NEEDS_VERIFY")

                # Set profile pic + bio if behavior engine available
                if result["success"] and BEHAVIOR_AVAILABLE:
                    self._post_create_setup(client, username)

                print(f"  ✓ Account created: {username}")
                log_pipeline(username, "CREATING", "NEEDS_VERIFY", "Created successfully")

                # Start verification
                self._verify(client, result)

                return result

            except ChallengeRequired as e:
                log_pipeline(username, "CREATING", "CHALLENGE", str(e)[:100])
                res = self.challenge.resolve(client, e, cfg.get("phone"))
                if res.get("success"):
                    continue
                result["error"] = f"challenge:{res.get('error', str(e)[:60])}"
                break

            except FeedbackRequired as e:
                log_pipeline(username, "CREATING", "BACKOFF", str(e)[:100])
                self._exponential_backoff(attempt)
                if proxies:
                    proxy = random.choice(proxies)
                    client.set_proxy(proxy)
                    result["proxy"] = proxy
                continue

            except CaptchaChallengeRequired:
                log_pipeline(username, "CREATING", "CAPTCHA", "")
                res = self.challenge.resolve_recaptcha()
                if res.get("success"):
                    continue
                result["error"] = "captcha_failed"
                break

            except RateLimitError as e:
                log_pipeline(username, "CREATING", "RATELIMIT", str(e)[:100])
                wait = 600 * (attempt + 1)
                print(f"  ⏳ Rate limited. Waiting {wait // 60}min...")
                time.sleep(wait)
                if proxies:
                    proxy = random.choice(proxies)
                    client.set_proxy(proxy)
                    result["proxy"] = proxy
                continue

            except SignupSpamError as e:
                log_pipeline(username, "CREATING", "SPAM_BLOCK", str(e)[:100])
                result["error"] = "spam_block"
                break

            except Exception as e:
                err = f"{type(e).__name__}:{str(e)[:80]}"
                log_pipeline(username, "CREATING", "ERROR", err)
                result["error"] = err
                if attempt < 2:
                    time.sleep(5 * (attempt + 1))
                    if proxies:
                        proxy = random.choice(proxies)
                        client.set_proxy(proxy)
                    continue
                break

        # If we got here, creation failed
        if result["error"]:
            update_state(username, "DEAD", result["error"])
            log_pipeline(username, "CREATING", "DEAD", result["error"])
        result["state"] = "DEAD"
        return result

    def _gen_username(self):
        adjs = ['cool', 'neo', 'zen', 'arc', 'vox', 'pix', 'flux', 'nova',
                'cosmo', 'byte', 'echo', 'zero', 'volt', 'wave', 'sage',
                'icy', 'raw', 'lit', 'max', 'ace', 'jade', 'onyx', 'ruby',
                'luna', 'sol', 'kilo', 'mega', 'giga', 'nano', 'pico',
                'bliss', 'flux', 'drift', 'surf', 'peak', 'haze', 'glow']
        nums = ''.join(random.choices(string.digits, k=4))
        suffix = ''.join(random.choices(string.ascii_lowercase, k=2))
        return f"{random.choice(adjs)}{nums}{suffix}"

    def _gen_password(self):
        chars = string.ascii_letters + string.digits + "!@#$"
        return ''.join(random.choices(chars, k=16))

    def _post_create_setup(self, client, username):
        try:
            pic_url = BehaviorEngine.generate_profile_pic_url()
            BehaviorEngine.set_profile_pic(client, pic_url)
        except:
            pass
        try:
            bio = random_bio(username)
            client.account_edit(biography=bio)
        except:
            pass

    def _save_account(self, result):
        conn = sqlite3.connect(PIPELINE_DB)
        try:
            conn.execute(
                """INSERT INTO pipeline_accounts
                   (username, password, email, email_provider, email_token, proxy, device_fingerprint, state)
                   VALUES (?,?,?,?,?,?,?,?)""",
                (result["username"], result["password"], result.get("email", ""),
                 result.get("email_provider", ""), result.get("email_token", ""),
                 result.get("proxy", ""), json.dumps(result.get("device_fingerprint", {})),
                 result.get("state", "PENDING_CREATE")),
            )
            conn.commit()
        except sqlite3.IntegrityError:
            pass
        finally:
            conn.close()

    # ── Verification ───────────────────────────────────────────

    def _verify(self, client, result):
        username = result["username"]
        email = result.get("email", "")
        email_token = result.get("email_token", "")

        update_state(username, "VERIFYING")
        log_pipeline(username, "NEEDS_VERIFY", "VERIFYING")

        # Poll email for verification code
        print(f"  [*] Polling email for verification code...")
        provider = EmailProviderManager()
        code, body = provider.poll_for_code({
            "provider": result.get("email_provider", "mailtm"),
            "token": email_token,
            "email": email,
        }, timeout=90)

        if code:
            print(f"  [+] Email verification code: {code}")
            try:
                client.login_by_code(username, code)
                settings_file = f"accounts/{username}.json"
                client.dump_settings(settings_file)
                update_state(username, "AGING")
                log_pipeline(username, "VERIFYING", "AGING", "Email verified")
                print(f"  ✓ Email verified for {username}")
                return True
            except Exception as e:
                log_pipeline(username, "VERIFYING", "ERROR", f"code_submit:{str(e)[:60]}")
                print(f"  [!] Code submit failed: {e}")

        update_state(username, "NEEDS_VERIFY")
        log_pipeline(username, "VERIFYING", "NEEDS_VERIFY", "Verification timeout")
        print(f"  [!] Verification timeout for {username}")
        return False

    # ── Aging Pipeline ─────────────────────────────────────────

    def age_account(self, username, days=3):
        """
        Age an account by gradually building its profile over days.
        Phase 1 (day 0): profile pic, bio, external URL
        Phase 2 (day 0-1): 1-2 posts with generated images
        Phase 3 (day 1-2): follow 10-20 users, like 20-30 posts
        Phase 4 (day 2-3): comment on 5-10 posts, view stories
        """
        account = self._get_account(username)
        if not account:
            return False

        client = self._login_account(account)
        if not client:
            return False

        update_state(username, "AGING")
        log_pipeline(username, "WARMING", "AGING", "Started aging")

        # Phase 1: Profile completion
        print(f"\n  [Age] {username} — Phase 1: Profile completion")
        if not account.get("aged_at"):
            self._age_phase_1(client, username)

        # Phase 2: Content
        print(f"  [Age] {username} — Phase 2: Content")
        self._age_phase_2(client, username)

        # Phase 3: Social
        print(f"  [Age] {username} — Phase 3: Social engagement")
        self._age_phase_3(client)

        # Phase 4: Interaction
        print(f"  [Age] {username} — Phase 4: Interaction")
        self._age_phase_4(client)

        update_state(username, "READY")
        log_pipeline(username, "AGING", "READY", "Aging complete")
        print(f"  ✓ {username} fully aged → READY")
        return True

    def _age_phase_1(self, client, username):
        """Profile pic, bio, external URL"""
        try:
            if BEHAVIOR_AVAILABLE:
                pic = BehaviorEngine.generate_profile_pic_url()
                BehaviorEngine.set_profile_pic(client, pic)
                BehaviorEngine.rotate_bio(client)
            time.sleep(random.uniform(5, 15))
        except:
            pass

    def _age_phase_2(self, client, username):
        """Create 1-2 simple posts"""
        for i in range(random.randint(1, 2)):
            try:
                # Upload a simple colored image as placeholder
                img_path = f"/tmp/age_post_{username}_{i}.jpg"
                self._generate_placeholder_image(img_path)
                client.photo_upload(img_path, random.choice([
                    "New beginnings", "Hello world", "First post!",
                    "Excited to be here", "Let's go!", "✨",
                ]))
                os.remove(img_path)
                time.sleep(random.uniform(60, 180))
            except:
                pass

    def _age_phase_3(self, client):
        """Follow and like"""
        from instagrapi.exceptions import ClientError
        try:
            # Follow trending/recommended users
            try:
                users = client.search_users("instagram", 5)
                for u in users[:3]:
                    try:
                        client.user_follow(u.pk)
                        time.sleep(random.uniform(30, 90))
                    except:
                        pass
            except:
                pass

            # Like some posts from feed
            try:
                feed = client.get_timeline_feed()
                for m in feed.get("feed_items", [])[:10]:
                    try:
                        mid = m.get("media_or_ad", {}).get("id", m.get("id", ""))
                        if mid:
                            client.media_like(mid)
                            time.sleep(random.uniform(10, 30))
                    except:
                        pass
            except:
                pass
        except:
            pass

    def _age_phase_4(self, client):
        """View stories, add bio link"""
        try:
            stories = client.get_timeline_feed()
            for _ in range(3):
                try:
                    user_feed = client.user_following(client.user_id)
                    if user_feed:
                        uid = random.choice(list(user_feed.keys()))
                        client.user_stories(uid)
                        time.sleep(random.uniform(20, 60))
                except:
                    pass
        except:
            pass

    def _generate_placeholder_image(self, path):
        """Generate a simple solid-color image for post placeholder."""
        try:
            from PIL import Image
            w, h = 1080, 1080
            color = tuple(random.randint(50, 200) for _ in range(3))
            img = Image.new("RGB", (w, h), color)
            img.save(path)
        except ImportError:
            # Fallback: create a minimal valid JPEG
            with open(path, "wb") as f:
                # Minimal JPEG (1x1 pixel)
                f.write(bytes([
                    0xFF, 0xD8, 0xFF, 0xE0, 0x00, 0x10, 0x4A, 0x46,
                    0x49, 0x46, 0x00, 0x01, 0x01, 0x00, 0x00, 0x01,
                    0x00, 0x01, 0x00, 0x00, 0xFF, 0xDB, 0x00, 0x43,
                    0x00, 0x08, 0x06, 0x06, 0x07, 0x06, 0x05, 0x08,
                    0x07, 0x07, 0x07, 0x09, 0x09, 0x08, 0x0A, 0x0C,
                    0x14, 0x0D, 0x0C, 0x0B, 0x0B, 0x0C, 0x19, 0x12,
                    0x13, 0x0F, 0x14, 0x1D, 0x1A, 0x1F, 0x1E, 0x1D,
                    0x1A, 0x1C, 0x1C, 0x20, 0x24, 0x2E, 0x27, 0x20,
                    0x22, 0x2C, 0x23, 0x1C, 0x1C, 0x28, 0x37, 0x29,
                    0x2C, 0x30, 0x31, 0x34, 0x34, 0x34, 0x1F, 0x27,
                    0x39, 0x3D, 0x38, 0x32, 0x3C, 0x2E, 0x33, 0x34,
                    0x32, 0xFF, 0xC0, 0x00, 0x0B, 0x08, 0x00, 0x01,
                    0x00, 0x01, 0x01, 0x01, 0x11, 0x00, 0xFF, 0xC4,
                    0x00, 0x1F, 0x00, 0x00, 0x01, 0x05, 0x01, 0x01,
                    0x01, 0x01, 0x01, 0x01, 0x00, 0x00, 0x00, 0x00,
                    0x00, 0x00, 0x00, 0x00, 0x01, 0x02, 0x03, 0x04,
                    0x05, 0x06, 0x07, 0x08, 0x09, 0x0A, 0x0B, 0xFF,
                    0xC4, 0x00, 0xB5, 0x10, 0x00, 0x02, 0x01, 0x03,
                    0x03, 0x02, 0x04, 0x03, 0x05, 0x05, 0x04, 0x04,
                    0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x01,
                    0x02, 0x03, 0x00, 0x04, 0x11, 0x05, 0x12, 0x21,
                    0x13, 0x31, 0x41, 0x06, 0x22, 0x51, 0x61, 0x07,
                    0x14, 0x71, 0x81, 0x32, 0x91, 0xA1, 0x08, 0x23,
                    0x42, 0xB1, 0xC1, 0x15, 0x52, 0xD1, 0xF0, 0x24,
                    0x33, 0x62, 0x72, 0x82, 0x09, 0x0A, 0x16, 0x17,
                    0x18, 0x19, 0x1A, 0x25, 0x26, 0x27, 0x28, 0x29,
                    0x2A, 0x34, 0x35, 0x36, 0x37, 0x38, 0x39, 0x3A,
                    0x43, 0x44, 0x45, 0x46, 0x47, 0x48, 0x49, 0x4A,
                    0x53, 0x54, 0x55, 0x56, 0x57, 0x58, 0x59, 0x5A,
                    0x63, 0x64, 0x65, 0x66, 0x67, 0x68, 0x69, 0x6A,
                    0x73, 0x74, 0x75, 0x76, 0x77, 0x78, 0x79, 0x7A,
                    0x83, 0x84, 0x85, 0x86, 0x87, 0x88, 0x89, 0x8A,
                    0x92, 0x93, 0x94, 0x95, 0x96, 0x97, 0x98, 0x99,
                    0x9A, 0xA2, 0xA3, 0xA4, 0xA5, 0xA6, 0xA7, 0xA8,
                    0xA9, 0xAA, 0xB2, 0xB3, 0xB4, 0xB5, 0xB6, 0xB7,
                    0xB8, 0xB9, 0xBA, 0xC2, 0xC3, 0xC4, 0xC5, 0xC6,
                    0xC7, 0xC8, 0xC9, 0xCA, 0xD2, 0xD3, 0xD4, 0xD5,
                    0xD6, 0xD7, 0xD8, 0xD9, 0xDA, 0xE1, 0xE2, 0xE3,
                    0xE4, 0xE5, 0xE6, 0xE7, 0xE8, 0xE9, 0xEA, 0xF1,
                    0xF2, 0xF3, 0xF4, 0xF5, 0xF6, 0xF7, 0xF8, 0xF9,
                    0xFA, 0xFF, 0xDA, 0x00, 0x08, 0x01, 0x01, 0x00,
                    0x00, 0x3F, 0x00, 0x7B, 0x94, 0x11, 0x00, 0x00,
                    0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00,
                    0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00,
                    0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00,
                    0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00,
                    0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00,
                    0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00,
                    0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00,
                    0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00,
                    0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00,
                    0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00,
                    0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00,
                    0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00,
                    0x00, 0x00, 0x00, 0xFF, 0xD9,
                ]))

    # ── Health Checks ───────────────────────────────────────────

    def health_check(self, username):
        """Verify account is still alive and usable."""
        account = self._get_account(username)
        if not account:
            return {"status": "not_found"}

        client = self._login_account(account)
        if not client:
            update_state(username, "DEAD", "login_failed")
            return {"status": "dead", "reason": "login_failed"}

        try:
            me = client.account_info()
            result = {
                "status": "alive",
                "username": username,
                "pk": me.pk,
                "full_name": me.full_name,
                "follower_count": me.follower_count,
                "following_count": me.following_count,
                "media_count": me.media_count,
                "has_profile_pic": me.has_anonymous_profile_picture == False,
                "is_private": me.is_private,
                "is_business": me.is_business,
            }

            # If it has media and followers, it's properly aged
            if me.media_count >= 1 and me.follower_count >= 1:
                update_state(username, "READY")
            elif me.media_count >= 1:
                update_state(username, "WARMING")
            else:
                update_state(username, "AGING")

            return result
        except Exception as e:
            update_state(username, "DEAD", str(e)[:100])
            return {"status": "dead", "reason": str(e)[:100]}

    # ── Batch Operations ───────────────────────────────────────

    def batch_create(self, count, config=None, threads=3):
        """Create multiple accounts in parallel."""
        results = []
        lock = threading.Lock()
        remaining = count

        def worker():
            nonlocal remaining
            while True:
                with lock:
                    if remaining <= 0:
                        return
                    remaining -= 1
                try:
                    r = self.create_account(config)
                    with lock:
                        results.append(r)
                except Exception as e:
                    with lock:
                        results.append({"error": str(e)})

        tlist = []
        for _ in range(min(threads, count)):
            t = threading.Thread(target=worker, daemon=True)
            t.start()
            tlist.append(t)
        for t in tlist:
            t.join(timeout=600)

        return results

    def batch_age(self, count=5):
        """Age the next N unaged accounts."""
        conn = sqlite3.connect(PIPELINE_DB)
        rows = conn.execute(
            "SELECT username FROM pipeline_accounts WHERE state='READY' AND aged_at IS NULL LIMIT ?",
            (count,),
        ).fetchall()
        conn.close()

        for row in rows:
            self.age_account(row["username"])
            time.sleep(random.uniform(30, 120))

    def batch_health_check(self):
        """Check all READY/ACTIVE accounts."""
        conn = sqlite3.connect(PIPELINE_DB)
        rows = conn.execute(
            "SELECT username FROM pipeline_accounts WHERE state IN ('READY','ACTIVE','WARMING','AGING')"
        ).fetchall()
        conn.close()

        results = []
        for row in rows:
            r = self.health_check(row["username"])
            results.append(r)
            time.sleep(random.uniform(5, 15))
        return results

    # ── Helpers ─────────────────────────────────────────────────

    def _get_account(self, username):
        conn = sqlite3.connect(PIPELINE_DB)
        conn.row_factory = sqlite3.Row
        row = conn.execute(
            "SELECT * FROM pipeline_accounts WHERE username=?", (username,)
        ).fetchone()
        conn.close()
        return dict(row) if row else None

    def _login_account(self, account):
        client = Client()
        fp = self.fingerprint.apply_to_client(client)
        if account.get("proxy"):
            client.set_proxy(account["proxy"])
        sf = f"accounts/{account['username']}.json"
        if os.path.exists(sf):
            try:
                client.load_settings(sf)
                client.login(account["username"], account["password"])
                return client
            except:
                pass
        try:
            client.login(account["username"], account["password"])
            client.dump_settings(sf)
            return client
        except Exception as e:
            print(f"  [!] Login failed {account['username']}: {e}")
            return None

    def _exponential_backoff(self, attempt):
        wait = min(BACKOFF_BASE * (BACKOFF_MULTIPLIER ** attempt), BACKOFF_MAX)
        print(f"  ⏳ Backoff {wait:.0f}s ({attempt+1}/3)")
        time.sleep(wait)

    def get_pipeline_state(self):
        conn = sqlite3.connect(PIPELINE_DB)
        cur = conn.execute("""
            SELECT state, COUNT(*) as count
            FROM pipeline_accounts
            GROUP BY state
        """)
        states = {row["state"]: row["count"] for row in cur.fetchall()}
        total = sum(states.values())
        conn.close()
        return {"total": total, "states": states}
