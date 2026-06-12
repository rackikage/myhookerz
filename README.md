# 🕸️ Instagram Botnet — Complete Android-C2 System

> **Authorization Required** — Use only on systems you own or have explicit permission to test.

A **mobile-first Android Instagram botnet** using the **real Instagram Private API** — bypassing the browser entirely.

## Architecture

1. **Mass Email Creator** → Temp email domains + generation (mail.tm API)
2. **Mass Instagram Account Creator** → Uses emails + proxies + SMS to create accounts
3. **ADB Phone Proxy Bridge** → Real Android phones as proxy exit nodes (cellular IP per account)
4. **SMS Gateway** → Root SMS interceptor, reads Instagram codes from device SMS database
5. **Dual-SIM Rotator** → Rotates between 2 phone numbers for SMS verification
6. **C2 Control Server** → Flask-based web dashboard to manage botnet
7. **TUI Interface** → Terminal-based control panel
8. **Humanized Behavior Engine** → Realistic engagement patterns (delays, follow-back, smart like, comment templates, profile rotation, daily scheduler)

## Directory Structure

```
myhookerz/
├── core/
│   ├── email_factory.py    # Mass temp email generator (mail.tm API)
│   ├── ig_creator.py       # Mass Instagram account creator (instagrapi)
│   ├── c2_controller.py    # Flask C2 server with REST API + web dashboard
│   ├── sms_gateway.py      # Root SMS interceptor + Dual-SIM rotator
│   ├── bot_behavior.py     # Humanized behavior engine + daily scheduler
│   └── adb_bridge.py       # ADB phone proxy carrier bridge
├── tuiclient/
│   └── tui.py              # Terminal UI control panel
├── accounts/               # Bot account sessions & exports
├── emails/                 # Generated email exports
├── proxies/                # Proxy lists & SIM config
├── logs/                   # Activity logs
└── c2_web/                 # Web assets
```

## Quick Setup

```bash
pkg update && pkg upgrade -y
pkg install python python-pip rust binutils git openssl curl jq -y
pip install instagrapi requests flask
```

## Full Account Creation Workflow

### 1. Generate Emails

Creates temporary inboxes via mail.tm API (no API key needed).

**Via TUI:** Option `[1] Mass Email Generator`

**Direct:**
```bash
python core/email_factory.py
```

Emails are saved to `emails/emails_<timestamp>.json`.

### 2. Create Instagram Accounts

Uses instagrapi to sign up with device fingerprinting and proxy rotation.

**Via TUI:** Option `[2] Mass Instagram Creator`

**Direct CLI:**
```bash
python core/ig_creator.py --count 10 --proxies proxies.txt --threads 5 --sms --phone1 "+1234567890" --phone2 "+0987654321"
```

| Flag | Default | Description |
|------|---------|-------------|
| `--count` | 1 | Number of accounts to create |
| `--proxies` | None | Proxy list file (one per line) |
| `--threads` | 3 | Concurrent worker threads |
| `--phone1` | None | SIM 1 phone number |
| `--phone2` | None | SIM 2 phone number |
| `--sms` | False | Enable SMS verification |

Creates each account by generating a random username, signing up via the Instagram Private API, polling the temp email inbox for the 6-digit verification code, and auto-confirming the email. If `--sms` is set, it also intercepts the SMS code from the phone via the SMS Gateway. On success, the account session is saved to `accounts/<username>.json` and the bot is registered with the C2 server.

### 3. Account Verification

The system handles two verification channels:

- **Email verification** (automatic): Polls the mail.tm inbox for Instagram's confirmation email, extracts the 6-digit code, and submits it via `login_by_code()`.
- **SMS verification** (optional): Requires root or Termux-API. The SMS Gateway reads the device SMS database (or uses `termux-sms-list`) to intercept Instagram verification codes in real time.

### 4. Dual-SIM Rotation

When two phone numbers are configured, `DualSIMRotator` alternates between SIMs after each successful SMS verification, spreading registrations across both numbers.

**Via TUI:** Option `[B] Dual-SIM Rotator Config`

Config saved to `proxies/sim_config.json`.

### 5. Register with C2

On account creation, the `MassCreator` automatically POSTs each new bot to `http://localhost:5000/api/bot/add` with username, password, email, settings_file, and proxy. Accounts are stored in the C2's SQLite database (`botnet.db`).

## Usage

**Terminal 1** — Start the C2 server:
```bash
python core/c2_controller.py
```

**Terminal 2** — Launch the TUI:
```bash
python tuiclient/tui.py
```

### TUI Menu Reference

| Option | Function |
|--------|----------|
| `[1]` | Mass Email Generator — batch create temp inboxes |
| `[2]` | Mass Instagram Creator — create accounts with email verification |
| `[3]` | Bot Fleet Dashboard — view C2 stats and bot list |
| `[4]` | Execute Bot Action — follow, like, comment, DM, etc. |
| `[5]` | Mass Follow / Like Campaign — all bots attack a target |
| `[6]` | Proxy Manager — view, add, import proxies |
| `[7]` | C2 Server Control — start, stop, check status, open dashboard |
| `[8]` | Export Accounts — JSON + CSV export from C2 |
| `[9]` | Interactive Shell — direct Python commands against C2 API |
| `[A]` | SMS Gateway Status — check root access, scan recent messages |
| `[B]` | Dual-SIM Rotator Config — configure 2 phone numbers |
| `[C]` | Create Account w/ SMS Verify — full pipeline with SMS |

## Humanized Behavior Engine

The behavior engine makes each bot act like a real person — random delays, varied comment templates, smart engagement filters, and daily scheduling.

### Engagement Actions

| Action | Description |
|--------|-------------|
| `Full Engagement Session` | Complete routine: follow-back → like recent posts → comment → view stories |
| `Like Recent Posts` | Only likes posts within 48h (configurable), with human-like pauses |
| `Auto Follow-Back` | Scans recent followers and follows anyone not yet followed back |
| `Comment On` | Leaves varied, human-like comments on recent posts |
| `View Stories` | Views stories with realistic pacing between each |

### Profile Management

| Action | Description |
|--------|-------------|
| `Rotate Bio` | Sets a fresh random bio from template pool |
| `Set Profile Pic` | Uploads profile pic from URL or generated placeholder (pravatar) |
| `Mass Bio Rotate` | Rotates bios for all online bots simultaneously |
| `Mass Set Profile Pics` | Sets profile pics for all online bots |

### Daily Scheduler

Each bot can be scheduled to run a full engagement session daily at a random time (jittered 22-26h apart).

**Schedule via API:**
```bash
POST /api/schedule/bot/<username>
{"delay_minutes": 30}
```
- Bots are automatically re-scheduled 22-26 hours after each run
- Only runs when the bot status is `online`
- Reports are saved to the bot's `notes` field in the C2 database

### Delays & Humanization

All actions include configurable human-like delays:

| Phase | Delay Range |
|-------|-------------|
| Scroll pause | 1.5 - 6s |
| Between actions | 2 - 12s |
| Between posts | 8 - 30s |
| Comment "typing" | 3 - 15s |
| Story viewing | 3 - 12s |
| Profile browsing | 5 - 20s |

### Comment Templates

50+ varied comment templates with random emoji injection, cycled to avoid repetition.

### New TUI Options

| Option | Function |
|--------|----------|
| `[D]` | Full Engagement Session — entire humanized routine on one bot |
| `[E]` | Like Recent Posts — smart like with age filter |
| `[F]` | Auto Follow-Back — reciprocate followers |
| `[G]` | Rotate Bio — set a fresh random bio |
| `[H]` | Set Profile Picture — upload or random generate |
| `[I]` | Schedule Bot Daily — enqueue for periodic engagement |
| `[J]` | Mass Engage All Bots — all bots run engagement |
| `[K]` | Mass Bio Rotate — all bots get new bios |
| `[L]` | Mass Set Profile Pics — all bots get avatars |
| `[M]` | View Schedules — see all scheduled bots |

### New Web Dashboard Pages

- `/engage` — Behavior controls (mass engage, bio rotate, set PP, schedule)
- `/schedules` — View all scheduled bots

## C2 REST API

| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/` | Web dashboard |
| GET | `/bots` | Bot fleet web page |
| GET | `/tasks` | Task queue web page |
| GET | `/api/stats` | JSON stats (bots, tasks, proxies) |
| GET | `/api/bots` | List all bots |
| GET | `/api/bot/<username>` | Bot detail + recent tasks |
| POST | `/api/bot/add` | Register a new bot |
| POST | `/api/bot/<username>/login` | Login a bot session |
| GET | `/api/bot/<username>/action/<action>` | Execute action (follow, like, comment, dm, story_view, info) |
| GET | `/api/tasks` | List recent tasks |
| GET/POST | `/api/proxies` | List or add proxies |
| POST | `/api/mass_follow` | Mass follow campaign |
| POST | `/api/mass_like` | Mass like campaign |
| GET | `/api/export` | Export all bot credentials (JSON) |
| POST | `/api/bot/<username>/engage` | Full humanized engagement session |
| POST | `/api/bot/<username>/like_recent` | Like recent posts with age filter |
| POST | `/api/bot/<username>/follow_back` | Auto follow-back followers |
| POST | `/api/bot/<username>/set_pp` | Set profile picture |
| POST | `/api/bot/<username>/rotate_bio` | Rotate biography |
| POST | `/api/bot/<username>/comment_on` | Comment on recent posts |
| POST | `/api/bot/<username>/report` | Save engagement report |
| POST | `/api/schedule/bot/<username>` | Schedule daily engagement |
| DELETE | `/api/schedule/bot/<username>` | Unschedule bot |
| GET | `/api/schedule/list` | List all schedules |
| POST | `/api/mass_engage` | Engage all online/idle bots |
| POST | `/api/mass_bio_rotate` | Rotate all bots' bios |
| POST | `/api/mass_set_pp` | Set all bots' profile pics |

### Bot Actions

Supported actions via `/api/bot/<username>/action/<action>`:
- `follow` — Follow a target user
- `unfollow` — Unfollow a target user
- `like` — Like a post by media URL
- `comment` — Comment on a post (requires `text` param)
- `dm` — Send direct message (requires `text` param)
- `story_view` — View a user's stories
- `info` — Get public user info

## SMS Verification (Root Required)

With a rooted Android and **2 phone numbers**, the SMS Gateway enables:
- Direct SMS database read (`/data/data/com.android.providers.telephony/databases/mmssms.db`)
- Real-time Instagram verification code interception
- Dual-SIM rotation between both numbers
- Termux-API fallback if root not available

### Proxy Recommendations

| Provider | Type | Cost | Best For |
|----------|------|------|----------|
| ProxyEmpire | 4G/5G Mobile Rotating | ~$75-120/mo | Instagram automation, highest trust |
| Aluvia | Real SIM-based 4G | ~$50-90/mo | No KYC, automation-friendly |
| BrightData | Residential + Mobile | ~$15/GB | Large pools, sticky sessions |
| IPRoyal | Residential Rotating | ~$3/GB | Budget-friendly |

## ADB Phone Proxy Carriers

Use real Android phones connected via USB as proxy exit nodes. Each phone's cellular data connection becomes an HTTP proxy — Instagram sees a real mobile carrier IP.

### Architecture

```
Phone 1 (Termux: proxy.py :8080)     Phone 2 (Termux: proxy.py :8080)
       ↕ adb forward tcp:21001 tcp:8080     ↕ adb forward tcp:21002 tcp:8080
Host: http://localhost:21001          Host: http://localhost:21002

→ Account creator picks a random phone proxy
→ Instagram sees that phone's carrier IP
→ Each phone = different operator/IP = distributed creation
```

### Setup

1. **Enable USB debugging** on each Android phone
2. **Install ADB** on the host machine
3. **Install Termux** on each phone with:
   ```bash
   pkg install python -y
   ```
4. Connect phones via USB — accept the debugging prompt on each
5. Use the TUI or web dashboard to **Scan**, **Provision**, and **Refresh Proxies**

### Auto-Provisioning

The ADB bridge can push a standalone Python HTTP proxy to each phone's `/data/local/tmp/` and start it automatically. The proxy runs on port 8080 and handles both HTTP and CONNECT (HTTPS) tunneling.

### TUI Options

| Option | Function |
|--------|----------|
| `[N]` | Scan ADB Devices — detect connected phones |
| `[O]` | Phone Status Dashboard — view battery, carrier, model |
| `[P]` | Provision Phone — push proxy + start on a specific device |
| `[Q]` | Provision All Phones — batch provision all detected |
| `[R]` | Refresh Proxy Pool — import phone proxies into C2 DB |

### Creation with ADB Proxies

When running Mass Instagram Creator, choose `y` for ADB phone proxies. The creator will:
1. Scan connected ADB devices
2. Use each phone's proxy URL as the proxy for account creation
3. Each account appears from a different mobile carrier IP
4. Automatically rotates across available phones

### Web Dashboard

- `/phones` — ADB phone management panel
- `/api/adb/scan` — Scan for new devices
- `/api/adb/phones` — Phone status JSON
- `/api/adb/provision/<serial>` — Provision a single phone
- `/api/adb/provision_all` — Provision all phones
- `/api/adb/refresh_proxies` — Import phone proxies into C2 DB

Built with `instagrapi` — Android Instagram Private API emulation with device fingerprinting, request signing, session persistence, root SMS interception, and email verification.

---

## Educational Context

This project was developed as part of a university coursework assignment in **Network Security & Penetration Testing**. The objective was to build a modular, API-driven automation framework that demonstrates how modern social engineering campaigns and automated bot registration pipelines operate — from disposable email generation and multi-factor authentication bypass (SMS interception) to command-and-control infrastructure. All code was written and tested exclusively in a sandboxed lab environment using isolated devices with explicit authorization. No real Instagram accounts, user data, or production systems were targeted. The project reinforced core concepts in API reverse engineering, thread-safe concurrent programming, SQLite-backed task orchestration, and mobile device fingerprinting. It also provided hands-on experience with Android's private API surface, rooted device telemetry, and the ethical implications of automation at scale. Understanding these techniques is essential for defenders building detection mechanisms against modern botnet infrastructure.
