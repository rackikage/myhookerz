#!/usr/bin/env python3
"""
tui.py — Terminal UI for IG Botnet C2
Controls everything: email gen, account creation, bot commands
"""
import os
import sys
import json
import time
import random
import threading
import subprocess
from datetime import datetime
from pathlib import Path

import requests

sys.path.insert(0, str(Path(__file__).parent.parent))

C2_URL = "http://localhost:5000"

def clear():
    os.system('clear' if os.name == 'posix' else 'cls')

def banner():
    print("""
    ===========================================
       IG BOTNET COMMAND CENTER
           Pentest Control TUI
    ===========================================
    """)

def check_c2():
    try:
        r = requests.get(f"{C2_URL}/api/stats", timeout=2)
        return r.json()
    except:
        return None

def print_menu():
    print("""
    -------------------------------------------
    [1]  Mass Email Generator
    [2]  Mass Instagram Creator
    [3]  Bot Fleet Dashboard
    [4]  Execute Bot Action
    [5]  Mass Follow / Like Campaign
    [6]  Proxy Manager
    [7]  C2 Server Control
    [8]  Export Accounts
    [9]  Interactive Shell
    [A]  SMS Gateway Status
    [B]  Dual-SIM Rotator Config
    [C]  Create Account w/ SMS Verify
    -------------------------------------------
    --- BEHAVIOR ENGINE ---
    [D]  Full Engagement Session
    [E]  Like Recent Posts (humanized)
    [F]  Auto Follow-Back
    [G]  Rotate Bio
    [H]  Set Profile Picture
    [I]  Schedule Bot Daily
    [J]  Mass Engage All Bots
    [K]  Mass Bio Rotate
    [L]  Mass Set Profile Pics
    [M]  View Schedules
    -------------------------------------------
    --- ADB PHONE PROXY CARRIERS ---
    [N]  Scan ADB Devices
    [O]  Phone Status Dashboard
    [P]  Provision Phone
    [Q]  Provision All Phones
    [R]  Refresh Proxy Pool from Phones
    -------------------------------------------
    --- PIPELINE & HEALTH ---
    [S]  Pipeline Status Dashboard
    [T]  Create Account (Full Pipeline)
    [U]  Batch Create Accounts
    [V]  Age Account
    [W]  Batch Age Accounts
    [X]  Health Check Account
    [Y]  Batch Health Check
    [Z]  Verify Proxy
    -------------------------------------------
    [0]  Exit
    -------------------------------------------
    """)

def mass_email_gen():
    clear()
    print("=== MASS EMAIL GENERATOR ===\n")
    try:
        from core.email_factory import BulkEmailGenerator
        count = int(input("How many emails to generate? "))
        prefix = input("Email prefix [ig_]: ") or "ig_"
        threads = int(input("Threads [10]: ") or "10")
        print(f"\n[*] Generating {count} emails with {threads} threads...\n")
        gen = BulkEmailGenerator(count, prefix, threads)
        emails = gen.generate()
        filename = f"emails/emails_{int(time.time())}.json"
        with open(filename, 'w') as f:
            json.dump(emails, f, indent=2)
        print(f"\n[+] Generated {len(emails)} emails -> {filename}")
        input("\nPress Enter to continue...")
    except Exception as e:
        print(f"[!] Error: {e}")
        input("\nPress Enter...")

def mass_ig_creator():
    clear()
    print("=== MASS INSTAGRAM CREATOR ===\n")
    count = int(input("How many accounts to create? "))
    use_adb = input("Use ADB phone proxies? (y/N): ").strip().lower() == 'y'
    proxy_file = ""
    proxies = None
    if not use_adb:
        proxy_file = input("Proxy list file (or Enter to skip): ").strip()
        if proxy_file and os.path.exists(proxy_file):
            with open(proxy_file) as f:
                proxies = [line.strip() for line in f if line.strip()]
            print(f"[*] Loaded {len(proxies)} proxies")
    else:
        print("[*] Will auto-detect ADB phone proxies")
    threads = int(input("Threads [3]: ") or "3")
    use_sms = input("Use SMS verification? (y/N): ").strip().lower() == 'y'
    if not use_adb:
        use_adb = False
    print(f"\n[*] Creating {count} Instagram accounts...")
    script = f"""
import sys, json, time
sys.path.insert(0, '{Path.cwd()}')
from core.ig_creator import MassCreator
from core.email_factory import EmailFactory

creator = MassCreator({count}, {json.dumps(proxies)}, {threads}, use_adb_proxies={'true' if use_adb else 'false'})
accounts = creator.run()

with open('accounts/batch_{int(time.time())}.json', 'w') as f:
    json.dump(accounts, f, indent=2)

print(f"[+] Created {{len(accounts)}} accounts")

import requests
for acc in accounts:
    if acc.get('success'):
        requests.post('{C2_URL}/api/bot/add', json={{'username': acc['username'], 'password': acc['password'], 'email': acc['email'], 'settings_file': acc.get('settings_file', ''), 'proxy': acc.get('proxy', '')}})
print("[+] Registered with C2")
"""
    subprocess.run([sys.executable, "-c", script])
    input("\nPress Enter to continue...")

def fleet_dashboard():
    clear()
    print("=== BOT FLEET DASHBOARD ===\n")
    stats = check_c2()
    if not stats:
        print("[!] C2 Server not running! Start it first (option 7)")
        input("\nPress Enter...")
        return
    print(f"  Total Bots:    {stats['total_bots']}")
    print(f"  Online:        {stats['online_bots']}")
    print(f"  Busy:          {stats['busy_bots']}")
    print(f"  Pending Tasks: {stats['pending_tasks']}")
    print(f"  Total Tasks:   {stats['total_tasks']}")
    print(f"  Proxies:       {stats['total_proxies']}")
    print(f"  C2 Status:     {stats['status']}")
    try:
        r = requests.get(f"{C2_URL}/api/bots", timeout=5)
        bots = r.json()
        if bots:
            print(f"\n  {'USERNAME':<20} {'STATUS':<10} {'LAST ONLINE':<25} {'PROXY':<30}")
            print("  " + "-"*85)
            for b in bots[:15]:
                print(f"  {b['username']:<20} {b['status']:<10} {str(b.get('last_online','Never')):<25} {str(b.get('proxy','None'))[:28]:<30}")
    except:
        print("\n[!] Can't fetch bot list")
    input("\nPress Enter to continue...")

def bot_action():
    clear()
    print("=== EXECUTE BOT ACTION ===\n")
    username = input("Bot username: ").strip()
    print("\nActions: follow, unfollow, like, comment, dm, story_view, info")
    action = input("Action: ").strip()
    target = input("Target (username/media URL): ").strip()
    extra = {}
    if action == 'comment':
        extra['text'] = input("Comment text: ")
    elif action == 'dm':
        extra['text'] = input("DM text: ")
    try:
        r = requests.get(f"{C2_URL}/api/bot/{username}/action/{action}", params={'target': target}, json=extra)
        print(f"\n[Response] {json.dumps(r.json(), indent=2)}")
    except Exception as e:
        print(f"[!] Error: {e}")
    input("\nPress Enter to continue...")

def mass_campaign():
    clear()
    print("=== MASS CAMPAIGN ===\n")
    print("1. Mass Follow (all online bots follow a user)")
    print("2. Mass Like (all online bots like a post)")
    print("3. Mass Comment (all online bots comment on a post)")
    choice = input("\nChoice: ").strip()
    if choice == '1':
        target = input("Target username to follow: ")
        count = int(input("Number of bots to use [5]: ") or "5")
        try:
            r = requests.post(f"{C2_URL}/api/mass_follow", json={'target': target, 'count': count})
            print(f"\n[+] {r.json()}")
        except Exception as e:
            print(f"[!] Error: {e}")
    elif choice == '2':
        media = input("Media URL to like: ")
        count = int(input("Bots to use [5]: ") or "5")
        try:
            r = requests.post(f"{C2_URL}/api/mass_like", json={'media_url': media, 'count': count})
            print(f"\n[+] {r.json()}")
        except Exception as e:
            print(f"[!] Error: {e}")
    elif choice == '3':
        media = input("Media URL to comment on: ")
        text = input("Comment text: ")
        count = int(input("Bots to use [3]: ") or "3")
        try:
            r = requests.get(f"{C2_URL}/api/bots")
            bots = r.json()[:count]
            for bot in bots:
                requests.get(f"{C2_URL}/api/bot/{bot['username']}/action/comment", params={'target': media}, json={'text': text})
            print(f"[+] Dispatched comments to {len(bots)} bots")
        except Exception as e:
            print(f"[!] Error: {e}")
    input("\nPress Enter to continue...")

def proxy_manager():
    clear()
    print("=== PROXY MANAGER ===\n")
    print("1. View proxies")
    print("2. Add proxies from file")
    print("3. Add single proxy")
    choice = input("\nChoice: ").strip()
    if choice == '1':
        try:
            r = requests.get(f"{C2_URL}/api/proxies")
            proxies = r.json()
            print(f"\nActive proxies: {len(proxies)}")
            for p in proxies:
                print(f"  {p['proxy_url']} ({p['type']})")
        except:
            print("[!] C2 not running")
    elif choice == '2':
        fpath = input("Proxy file path: ")
        ptype = input("Proxy type [mobile]: ") or "mobile"
        if os.path.exists(fpath):
            with open(fpath) as f:
                proxies = [l.strip() for l in f if l.strip()]
            try:
                r = requests.post(f"{C2_URL}/api/proxies", json={'proxies': proxies, 'type': ptype})
                print(f"[+] Added {r.json()}")
            except:
                print("[!] C2 not running")
        else:
            print("[!] File not found")
    elif choice == '3':
        proxy = input("Proxy URL (http://user:pass@host:port): ")
        try:
            r = requests.post(f"{C2_URL}/api/proxies", json={'proxies': [proxy], 'type': 'mobile'})
            print(f"[+] Added")
        except:
            print("[!] C2 not running")
    input("\nPress Enter to continue...")

def c2_control():
    clear()
    print("=== C2 SERVER CONTROL ===\n")
    print("1. Start C2 Server")
    print("2. Stop C2 Server")
    print("3. Check C2 Status")
    print("4. Open Web Dashboard")
    choice = input("\nChoice: ").strip()
    if choice == '1':
        print("[*] Starting C2 server on port 5000...")
        subprocess.Popen([sys.executable, "core/c2_controller.py"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        time.sleep(2)
        if check_c2():
            print("[+] C2 Server is running!")
        else:
            print("[!] C2 failed to start")
    elif choice == '2':
        os.system("pkill -f c2_controller.py 2>/dev/null || true")
        print("[+] C2 stopped")
    elif choice == '3':
        stats = check_c2()
        if stats:
            print(f"[+] C2 Online - {stats['online_bots']}/{stats['total_bots']} bots online")
        else:
            print("[!] C2 Offline")
    elif choice == '4':
        print(f"[*] Opening {C2_URL}...")
        os.system(f"termux-open-url {C2_URL} 2>/dev/null || am start -a android.intent.action.VIEW -d {C2_URL} 2>/dev/null || echo 'Open browser to: {C2_URL}'")
    input("\nPress Enter to continue...")

def export_accounts():
    clear()
    print("=== EXPORT ACCOUNTS ===\n")
    try:
        r = requests.get(f"{C2_URL}/api/export")
        accounts = r.json()
        filename = f"accounts/export_{int(time.time())}.json"
        with open(filename, 'w') as f:
            json.dump(accounts, f, indent=2)
        csv_name = f"accounts/export_{int(time.time())}.csv"
        with open(csv_name, 'w') as f:
            f.write("username,password,email,proxy\n")
            for a in accounts:
                f.write(f"{a.get('username','')},{a.get('password','')},{a.get('email','')},{a.get('proxy','')}\n")
        print(f"[+] Exported {len(accounts)} accounts")
        print(f"    JSON: {filename}")
        print(f"    CSV:  {csv_name}")
    except Exception as e:
        print(f"[!] Error: {e}")
    input("\nPress Enter to continue...")

def interactive_shell():
    clear()
    print("=== INTERACTIVE BOT SHELL ===\n")
    print("Direct Python commands against C2 API. Type 'help' or 'exit'.\n")
    while True:
        try:
            cmd = input("botnet> ").strip()
            if cmd.lower() in ('exit', 'quit', 'q'):
                break
            if cmd.lower() == 'help':
                print("""
  Commands:
    bots              - List all bots
    online            - List online bots
    stats             - Show C2 stats
    follow <user>     - Mass follow
    login <username>  - Login a bot
    info <username>   - Get bot info
    tasks             - List tasks
    exec <bot> <action> <target> - Execute action
    export            - Export accounts
                """)
                continue
            parts = cmd.split()
            if not parts:
                continue
            if parts[0] == 'bots':
                r = requests.get(f"{C2_URL}/api/bots")
                for b in r.json():
                    print(f"  [{b['status']:>7}] {b['username']:<20} {b.get('last_online','')}")
            elif parts[0] == 'online':
                r = requests.get(f"{C2_URL}/api/bots")
                for b in r.json():
                    if b['status'] == 'online':
                        print(f"  {b['username']}")
            elif parts[0] == 'stats':
                print(check_c2())
            elif parts[0] == 'follow' and len(parts) > 1:
                r = requests.post(f"{C2_URL}/api/mass_follow", json={'target': parts[1], 'count': 10})
                print(r.json())
            elif parts[0] == 'login' and len(parts) > 1:
                r = requests.post(f"{C2_URL}/api/bot/{parts[1]}/login")
                print(r.json())
            elif parts[0] == 'exec' and len(parts) > 2:
                r = requests.get(f"{C2_URL}/api/bot/{parts[1]}/action/{parts[2]}", params={'target': parts[3] if len(parts) > 3 else ''})
                print(r.json())
            elif parts[0] == 'export':
                r = requests.get(f"{C2_URL}/api/export")
                with open(f"accounts/export_shell_{int(time.time())}.json", 'w') as f:
                    json.dump(r.json(), f, indent=2)
                print(f"[+] Exported {len(r.json())} accounts")
            else:
                if cmd.startswith('GET '):
                    r = requests.get(f"{C2_URL}{cmd[4:]}")
                    print(json.dumps(r.json(), indent=2)[:1000])
                elif cmd.startswith('POST '):
                    r = requests.post(f"{C2_URL}{cmd[5:]}")
                    print(r.json())
                else:
                    print("Unknown command. Type 'help'")
        except KeyboardInterrupt:
            break
        except Exception as e:
            print(f"[!] {e}")

def sms_gateway_status():
    clear()
    print("=== SMS GATEWAY STATUS ===\n")
    try:
        from core.sms_gateway import SMSGateway
        gw = SMSGateway()
        print(f"  Root access:    {'Yes' if gw.use_root else 'No'}")
        print(f"  Termux-API:     {'Yes' if gw.use_termux_api else 'No'}")
        if gw.use_root:
            print(f"  SMS DB:         {gw.db_path}")
        print("\n[*] Scanning recent SMS for Instagram codes...")
        if gw.use_root:
            msgs = gw.read_sms_db(limit=20)
        else:
            msgs = gw.read_sms_termux(limit=10)
        ig_found = 0
        for msg in msgs:
            sender = msg.get('sender', '')
            body = msg.get('body', '')
            if gw.is_instagram_sms(sender, body):
                code = gw.extract_instagram_code(body)
                print(f"  [IG] From {sender}: {body[:60]}... Code: {code or 'not found'}")
                ig_found += 1
        if ig_found == 0:
            print("  No Instagram SMS found in recent messages")
        print("\n[*] SIM Card Info:")
        sim_info = gw.get_sim_info()
        print(f"  SIM count:      {sim_info.get('sim_count', 'unknown')}")
    except Exception as e:
        print(f"[!] Error: {e}")
    input("\nPress Enter to continue...")

def dual_sim_config():
    clear()
    print("=== DUAL-SIM CONFIGURATION ===\n")
    phone1 = input("SIM 1 phone number (with country code): ").strip()
    phone2 = input("SIM 2 phone number (with country code): ").strip()
    if phone1 and phone2:
        config = {'sim1': phone1, 'sim2': phone2, 'last_used_sim': 1}
        with open('proxies/sim_config.json', 'w') as f:
            json.dump(config, f, indent=2)
        print(f"\n[+] SIM config saved")
        print(f"  SIM 1: {phone1}")
        print(f"  SIM 2: {phone2}")
    else:
        print("[!] Both numbers required")
    input("\nPress Enter to continue...")

# ── Behavior Engine Handlers ──────────────────────────────────

def behavior_engage():
    clear()
    print("=== FULL ENGAGEMENT SESSION ===\n")
    username = input("Bot username: ").strip()
    try:
        r = requests.post(f"{C2_URL}/api/bot/{username}/engage", json={})
        print(f"\n[Response] {json.dumps(r.json(), indent=2)}")
    except Exception as e:
        print(f"[!] Error: {e}")
    input("\nPress Enter to continue...")

def behavior_like_recent():
    clear()
    print("=== LIKE RECENT POSTS (HUMANIZED) ===\n")
    username = input("Bot username: ").strip()
    target = input("Target username: ").strip()
    max_p = input("Max posts to like [4]: ").strip() or "4"
    try:
        r = requests.post(f"{C2_URL}/api/bot/{username}/like_recent", json={'target': target, 'max_posts': int(max_p)})
        print(f"\n[Response] {json.dumps(r.json(), indent=2)}")
    except Exception as e:
        print(f"[!] Error: {e}")
    input("\nPress Enter to continue...")

def behavior_follow_back():
    clear()
    print("=== AUTO FOLLOW-BACK ===\n")
    username = input("Bot username: ").strip()
    try:
        r = requests.post(f"{C2_URL}/api/bot/{username}/follow_back", json={})
        print(f"\n[Response] {json.dumps(r.json(), indent=2)}")
    except Exception as e:
        print(f"[!] Error: {e}")
    input("\nPress Enter to continue...")

def behavior_rotate_bio():
    clear()
    print("=== ROTATE BIO ===\n")
    username = input("Bot username: ").strip()
    try:
        r = requests.post(f"{C2_URL}/api/bot/{username}/rotate_bio", json={})
        print(f"\n[Response] {json.dumps(r.json(), indent=2)}")
    except Exception as e:
        print(f"[!] Error: {e}")
    input("\nPress Enter to continue...")

def behavior_set_pp():
    clear()
    print("=== SET PROFILE PICTURE ===\n")
    username = input("Bot username: ").strip()
    image = input("Image URL (or Enter for random generated): ").strip()
    try:
        r = requests.post(f"{C2_URL}/api/bot/{username}/set_pp", json={'image': image})
        print(f"\n[Response] {json.dumps(r.json(), indent=2)}")
    except Exception as e:
        print(f"[!] Error: {e}")
    input("\nPress Enter to continue...")

def behavior_schedule():
    clear()
    print("=== SCHEDULE BOT DAILY ===\n")
    username = input("Bot username: ").strip()
    delay = input("First run delay in minutes [30]: ").strip() or "30"
    try:
        r = requests.post(f"{C2_URL}/api/schedule/bot/{username}", json={'delay_minutes': int(delay)})
        print(f"\n[Response] {json.dumps(r.json(), indent=2)}")
    except Exception as e:
        print(f"[!] Error: {e}")
    input("\nPress Enter to continue...")

def behavior_mass_engage():
    clear()
    print("=== MASS ENGAGE ALL BOTS ===\n")
    max_b = input("Max bots to engage [20]: ").strip() or "20"
    try:
        r = requests.post(f"{C2_URL}/api/mass_engage", json={'max_bots': int(max_b)})
        print(f"\n[Response] {json.dumps(r.json(), indent=2)}")
    except Exception as e:
        print(f"[!] Error: {e}")
    input("\nPress Enter to continue...")

def behavior_mass_bio():
    clear()
    print("=== MASS BIO ROTATE ===\n")
    try:
        r = requests.post(f"{C2_URL}/api/mass_bio_rotate", json={})
        print(f"\n[Response] {json.dumps(r.json(), indent=2)}")
    except Exception as e:
        print(f"[!] Error: {e}")
    input("\nPress Enter to continue...")

def behavior_mass_pp():
    clear()
    print("=== MASS SET PROFILE PICS ===\n")
    try:
        r = requests.post(f"{C2_URL}/api/mass_set_pp", json={})
        print(f"\n[Response] {json.dumps(r.json(), indent=2)}")
    except Exception as e:
        print(f"[!] Error: {e}")
    input("\nPress Enter to continue...")

# ── ADB Phone Proxy Bridge Handlers ──────────────────────────

def adb_scan():
    clear()
    print("=== SCAN ADB DEVICES ===\n")
    try:
        r = requests.post(f"{C2_URL}/api/adb/scan", json={})
        data = r.json()
        print(f"  Phones found: {data.get('count', 0)}")
        for p in data.get('phones', []):
            status = '✓' if p.get('online') else '✗'
            print(f"  [{status}] {p['serial']:20} {p.get('model','?'):20} bat:{p.get('battery','?')}%")
    except Exception as e:
        print(f"[!] Error: {e}")
    input("\nPress Enter to continue...")

def adb_phones():
    clear()
    print("=== ADB PHONE STATUS ===\n")
    try:
        r = requests.get(f"{C2_URL}/api/adb/phones")
        stats = r.json()
        print(f"  Total phones: {stats.get('total_phones', 0)}")
        print(f"  Online:       {stats.get('online_phones', 0)}")
        print(f"  Active proxies: {stats.get('proxies_active', 0)}")
        print()
        for p in stats.get('phones', []):
            status = 'ONLINE' if p.get('online') else 'OFFLINE'
            print(f"  {p['serial']:<20} {status:<8} {p.get('model','?'):<20} "
                  f"bat:{p.get('battery','?'):>3}%  {p.get('proxy_url','no proxy')}")
            if p.get('operator'):
                print(f"  {'':>20} carrier: {p['operator']}")
    except Exception as e:
        print(f"[!] Error: {e}")
    input("\nPress Enter to continue...")

def adb_provision():
    clear()
    print("=== PROVISION ADB PHONE ===\n")
    serial = input("Phone serial: ").strip()
    if not serial:
        print("[!] Serial required")
        input("\nPress Enter...")
        return
    try:
        r = requests.post(f"{C2_URL}/api/adb/provision/{serial}", json={})
        print(f"\n[Response] {json.dumps(r.json(), indent=2)}")
    except Exception as e:
        print(f"[!] Error: {e}")
    input("\nPress Enter to continue...")

def adb_provision_all():
    clear()
    print("=== PROVISION ALL PHONES ===\n")
    try:
        r = requests.post(f"{C2_URL}/api/adb/provision_all", json={})
        print(f"\n[Response] {json.dumps(r.json(), indent=2)}")
    except Exception as e:
        print(f"[!] Error: {e}")
    input("\nPress Enter to continue...")

# ── Pipeline & Health Handlers ───────────────────────────────

def pipeline_status():
    clear()
    print("=== PIPELINE STATUS ===\n")
    try:
        r = requests.get(f"{C2_URL}/api/pipeline/stats")
        stats = r.json()
        print(f"  Total accounts in pipeline: {stats.get('total', 0)}")
        print()
        print(f"  {'State':<20} {'Count':>6}")
        print(f"  {'-----':<20} {'-----':>6}")
        for state, count in sorted(stats.get('by_state', {}).items()):
            print(f"  {state:<20} {count:>6}")
    except Exception as e:
        print(f"[!] Error: {e}")
    input("\nPress Enter to continue...")

def pipeline_create():
    clear()
    print("=== CREATE ACCOUNT (FULL PIPELINE) ===\n")
    use_adb = input("Use ADB phone proxies? (Y/n): ").strip().lower() != 'n'
    phone = input("Phone number for SMS (or Enter to skip): ").strip()
    try:
        body = {'count': 1, 'use_adb': use_adb}
        if phone:
            body['phone'] = phone
        r = requests.post(f"{C2_URL}/api/pipeline/create", json=body)
        print(f"\n[Response] {json.dumps(r.json(), indent=2, default=str)}")
    except Exception as e:
        print(f"[!] Error: {e}")
    input("\nPress Enter to continue...")

def pipeline_batch_create():
    clear()
    print("=== BATCH CREATE ACCOUNTS ===\n")
    count = int(input("Number of accounts: "))
    threads = int(input("Threads (3): ") or "3")
    use_adb = input("Use ADB phone proxies? (Y/n): ").strip().lower() != 'n'
    try:
        r = requests.post(f"{C2_URL}/api/pipeline/create", json={
            'count': count, 'threads': threads, 'use_adb': use_adb,
        })
        print(f"\n[Response] {json.dumps(r.json(), indent=2, default=str)[:2000]}")
    except Exception as e:
        print(f"[!] Error: {e}")
    input("\nPress Enter to continue...")

def pipeline_age():
    clear()
    print("=== AGE ACCOUNT ===\n")
    username = input("Username: ").strip()
    days = int(input("Aging days (3): ") or "3")
    try:
        r = requests.post(f"{C2_URL}/api/pipeline/age/{username}", json={'days': days})
        print(f"\n[Response] {json.dumps(r.json(), indent=2)}")
        print("[*] Aging running in background. Check pipeline status for state changes.")
    except Exception as e:
        print(f"[!] Error: {e}")
    input("\nPress Enter to continue...")

def pipeline_batch_age():
    clear()
    print("=== BATCH AGE ACCOUNTS ===\n")
    count = int(input("Number of accounts to age (5): ") or "5")
    try:
        r = requests.post(f"{C2_URL}/api/pipeline/batch_age", json={'count': count})
        print(f"\n[Response] {json.dumps(r.json(), indent=2)}")
    except Exception as e:
        print(f"[!] Error: {e}")
    input("\nPress Enter to continue...")

def pipeline_health():
    clear()
    print("=== HEALTH CHECK ACCOUNT ===\n")
    username = input("Username: ").strip()
    try:
        r = requests.get(f"{C2_URL}/api/pipeline/health/{username}")
        print(f"\n[Response] {json.dumps(r.json(), indent=2)}")
    except Exception as e:
        print(f"[!] Error: {e}")
    input("\nPress Enter to continue...")

def pipeline_batch_health():
    clear()
    print("=== BATCH HEALTH CHECK ===\n")
    try:
        r = requests.post(f"{C2_URL}/api/pipeline/batch_health", json={})
        data = r.json()
        print(f"  Checked: {data.get('checked', 0)} accounts")
        for res in data.get('results', []):
            status = '✓' if res.get('status') == 'alive' else '✗'
            print(f"  [{status}] {res.get('username','?'):<20} {res.get('status','?'):<8} "
                  f"followers:{res.get('follower_count',0)} posts:{res.get('media_count',0)}")
    except Exception as e:
        print(f"[!] Error: {e}")
    input("\nPress Enter to continue...")

def verify_proxy():
    clear()
    print("=== VERIFY PROXY ===\n")
    proxy = input("Proxy URL (http://...): ").strip()
    if proxy:
        try:
            r = requests.post(f"{C2_URL}/api/proxy/verify", json={'proxy': proxy})
            print(f"\n[Result] {json.dumps(r.json(), indent=2)}")
        except Exception as e:
            print(f"[!] Error: {e}")
    else:
        # Check own IP
        try:
            r = requests.get(f"{C2_URL}/api/ip")
            print(f"\n[Current IP] {json.dumps(r.json(), indent=2)}")
        except Exception as e:
            print(f"[!] Error: {e}")
    input("\nPress Enter to continue...")

def adb_refresh():
    clear()
    print("=== REFRESH PROXY POOL FROM PHONES ===\n")
    try:
        r = requests.post(f"{C2_URL}/api/adb/refresh_proxies", json={})
        data = r.json()
        print(f"  Proxies added: {data.get('proxies_added', 0)}")
        for p in data.get('proxies', []):
            print(f"  ✓ {p}")
    except Exception as e:
        print(f"[!] Error: {e}")
    input("\nPress Enter to continue...")

def behavior_view_schedules():
    clear()
    print("=== SCHEDULED BOTS ===\n")
    try:
        r = requests.get(f"{C2_URL}/api/schedule/list", timeout=5)
        scheds = r.json()
        if scheds:
            for uname, s in scheds.items():
                print(f"  {uname:<20} next: {s.get('next_run','?')}")
        else:
            print("  No scheduled bots")
    except Exception as e:
        print(f"[!] Error: {e}")
    input("\nPress Enter to continue...")

def create_with_sms():
    clear()
    print("=== CREATE ACCOUNTS WITH SMS VERIFICATION ===\n")
    print("This uses your phone's SIM cards to receive Instagram verification codes.")
    sms_db = "/data/data/com.android.providers.telephony/databases/mmssms.db"
    print(f"Root SMS DB: {'Available' if os.path.exists(sms_db) else 'Not available'}")
    print()
    count = int(input("Number of accounts to create? "))
    use_adb = input("Use ADB phone proxies? (y/N): ").strip().lower() == 'y'
    proxy_file = ""
    if not use_adb:
        proxy_file = input("Proxy file (or Enter to skip): ").strip()
    else:
        print("[*] Will auto-detect ADB phone proxies")
    phones = []
    if os.path.exists('proxies/sim_config.json'):
        with open('proxies/sim_config.json') as f:
            config = json.load(f)
            phones = [config.get('sim1', ''), config.get('sim2', '')]
            phones = [p for p in phones if p]
    if not phones:
        print("\n[!] No SIM numbers configured. Set them up in Dual-SIM Config.")
        p1 = input("Enter SIM 1 number now: ").strip()
        p2 = input("Enter SIM 2 number now: ").strip()
        if p1 and p2:
            phones = [p1, p2]
    if not phones:
        print("[!] Cannot proceed without phone numbers")
        input("\nPress Enter...")
        return
    proxies = None
    if proxy_file and os.path.exists(proxy_file):
        with open(proxy_file) as f:
            proxies = [l.strip() for l in f if l.strip()]
    threads = int(input("Threads [2]: ") or "2")
    print(f"\n[*] Creating {count} accounts with SMS verification...")
    print(f"    Phones: {phones}")
    print(f"    Proxies: {len(proxies) if proxies else 0}")
    print(f"    Threads: {threads}")
    script = f"""
import sys, json, time
sys.path.insert(0, '{Path.cwd()}')
from core.ig_creator import MassCreator

creator = MassCreator(
    num_accounts={count},
    proxies={json.dumps(proxies)},
    threads={threads},
    phone_numbers={json.dumps(phones)},
    use_sms=True,
    use_adb_proxies={'true' if use_adb else 'false'}
)
accounts = creator.run()
timestamp = int(time.time())
with open(f'accounts/sms_batch_{{timestamp}}.json', 'w') as f:
    json.dump(accounts, f, indent=2)
print(f'[+] Saved {{len(accounts)}} accounts')

import requests
for acc in accounts:
    if acc.get('success'):
        requests.post('http://localhost:5000/api/bot/add', json={{
            'username': acc['username'],
            'password': acc['password'],
            'email': acc.get('email', ''),
            'phone': acc.get('phone', ''),
            'settings_file': f'accounts/{acc["username"]}.json',
            'proxy': acc.get('proxy', '')
        }})
print('[+] Registered with C2')
"""
    subprocess.run([sys.executable, "-c", script])
    input("\nPress Enter to continue...")

def main():
    for d in ['accounts', 'emails', 'proxies', 'logs']:
        os.makedirs(d, exist_ok=True)
    while True:
        clear()
        banner()
        stats = check_c2()
        if stats:
            adb_str = f" | 📱Phones: {stats.get('adb_phones',0)}" if stats.get('adb_phones', 0) > 0 else ""
            pipe_str = f" | Pipeline: {stats.get('pipeline_total', 0)}" if stats.get('pipeline_total', 0) > 0 else ""
            fp_str = f" | FP: {stats.get('fingerprint_profiles', 0)}" if stats.get('fingerprint_profiles', 0) > 0 else ""
            print(f"  C2: Online | Bots: {stats['online_bots']}/{stats['total_bots']} online | Tasks: {stats['pending_tasks']} pending{adb_str}{pipe_str}{fp_str}")
        else:
            print("  C2: OFFLINE (start with option 7)")
        print_menu()
        try:
            choice = input("  Select option: ").strip()
        except KeyboardInterrupt:
            print("\n  Exiting...")
            break
        choice_lower = choice.lower()
        if choice == '1': mass_email_gen()
        elif choice == '2': mass_ig_creator()
        elif choice == '3': fleet_dashboard()
        elif choice == '4': bot_action()
        elif choice == '5': mass_campaign()
        elif choice == '6': proxy_manager()
        elif choice == '7': c2_control()
        elif choice == '8': export_accounts()
        elif choice == '9': interactive_shell()
        elif choice_lower == 'a': sms_gateway_status()
        elif choice_lower == 'b': dual_sim_config()
        elif choice_lower == 'c': create_with_sms()
        elif choice_lower == 'd': behavior_engage()
        elif choice_lower == 'e': behavior_like_recent()
        elif choice_lower == 'f': behavior_follow_back()
        elif choice_lower == 'g': behavior_rotate_bio()
        elif choice_lower == 'h': behavior_set_pp()
        elif choice_lower == 'i': behavior_schedule()
        elif choice_lower == 'j': behavior_mass_engage()
        elif choice_lower == 'k': behavior_mass_bio()
        elif choice_lower == 'l': behavior_mass_pp()
        elif choice_lower == 'm': behavior_view_schedules()
        elif choice_lower == 'n': adb_scan()
        elif choice_lower == 'o': adb_phones()
        elif choice_lower == 'p': adb_provision()
        elif choice_lower == 'q': adb_provision_all()
        elif choice_lower == 'r': adb_refresh()
        elif choice_lower == 's': pipeline_status()
        elif choice_lower == 't': pipeline_create()
        elif choice_lower == 'u': pipeline_batch_create()
        elif choice_lower == 'v': pipeline_age()
        elif choice_lower == 'w': pipeline_batch_age()
        elif choice_lower == 'x': pipeline_health()
        elif choice_lower == 'y': pipeline_batch_health()
        elif choice_lower == 'z': verify_proxy()
        elif choice == '0':
            print("\n  Goodbye.")
            break
        else:
            print("\n  Invalid option")
            time.sleep(1)

if __name__ == "__main__":
    main()
