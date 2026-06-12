# 🕸️ Instagram Botnet — Complete Android-C2 System

> **Authorization Required** — Use only on systems you own or have explicit permission to test.

A **mobile-first Android Instagram botnet** using the **real Instagram Private API** — bypassing the browser entirely.

## Architecture

1. **Mass Email Creator** → Temp email domains + generation (mail.tm API)
2. **Mass Instagram Account Creator** → Uses emails + proxies + SMS to create accounts
3. **SMS Gateway** → Root SMS interceptor, reads Instagram codes from device SMS database
4. **Dual-SIM Rotator** → Rotates between 2 phone numbers for SMS verification
5. **C2 Control Server** → Flask-based web dashboard to manage botnet
6. **TUI Interface** → Terminal-based control panel

## Directory Structure

```
myhookerz/
├── core/
│   ├── email_factory.py    # Mass temp email generator (mail.tm API)
│   ├── ig_creator.py       # Mass Instagram account creator (instagrapi)
│   └── c2_controller.py    # Flask C2 server with REST API + web dashboard
├── tuiclient/
│   └── tui.py       # Terminal UI control panel
├── accounts/               # Bot account sessions
├── emails/                 # Generated email exports
├── proxies/                # Proxy lists
├── logs/                   # Activity logs
└── c2_web/                 # Web assets
```

## Quick Setup

```bash
pkg update && pkg upgrade -y
pkg install python python-pip rust binutils git openssl curl jq -y
pip install instagrapi requests flask
```

## Usage

**Terminal 1** — Start the C2 server:
```bash
python core/c2_controller.py
```

**Terminal 2** — Launch the TUI:
```bash
python tuiclient/tui.py
```

## Workflow

1. **Start C2 Server** → `python core/c2_controller.py`
2. **Generate mass emails** (TUI option 1)
3. **Create Instagram accounts** (TUI option 2) — auto-registers with C2
4. **View bot fleet** (TUI option 3)
5. **Execute actions** (TUI option 4) — follow, like, comment, DM
6. **Mass campaigns** (TUI option 5) — all bots attack a target
7. **Export credentials** (TUI option 8)

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

Built with `instagrapi` — Android Instagram Private API emulation with device fingerprinting, request signing, session persistence, root SMS interception, and email verification.

---

## Educational Context

This project was developed as part of a university coursework assignment in **Network Security & Penetration Testing**. The objective was to build a modular, API-driven automation framework that demonstrates how modern social engineering campaigns and automated bot registration pipelines operate — from disposable email generation and multi-factor authentication bypass (SMS interception) to command-and-control infrastructure. All code was written and tested exclusively in a sandboxed lab environment using isolated devices with explicit authorization. No real Instagram accounts, user data, or production systems were targeted. The project reinforced core concepts in API reverse engineering, thread-safe concurrent programming, SQLite-backed task orchestration, and mobile device fingerprinting. It also provided hands-on experience with Android's private API surface, rooted device telemetry, and the ethical implications of automation at scale. Understanding these techniques is essential for defenders building detection mechanisms against modern botnet infrastructure.
