#!/usr/bin/env python3
"""
c2_controller.py — Central command and control server
Flask-based REST API to manage botnet accounts
"""
import sys
import os
import json
import time
import random
import sqlite3
import threading
import hashlib
from datetime import datetime
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from flask import Flask, request, jsonify, render_template_string, send_file
from instagrapi import Client
from instagrapi.exceptions import ClientError

from core.bot_behavior import BehaviorEngine, BotScheduler
from core.adb_bridge import ADBBridge, check_adb, list_devices
from core.account_pipeline import AccountPipeline, get_pipeline_accounts, get_pipeline_stats
from core.fingerprint import FingerprintManager
from core.proxy_verifier import test_proxy, batch_verify, get_ip_info

app = Flask(__name__)

DB_PATH = "botnet.db"

def init_db():
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.executescript("""
        CREATE TABLE IF NOT EXISTS bots (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            username TEXT UNIQUE NOT NULL,
            password TEXT NOT NULL,
            email TEXT,
            user_id TEXT,
            proxy TEXT,
            settings_file TEXT,
            status TEXT DEFAULT 'idle',
            last_online DATETIME,
            created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
            notes TEXT
        );
        
        CREATE TABLE IF NOT EXISTS tasks (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            bot_username TEXT,
            task_type TEXT NOT NULL,
            params TEXT,
            status TEXT DEFAULT 'pending',
            result TEXT,
            assigned_at DATETIME,
            completed_at DATETIME,
            FOREIGN KEY(bot_username) REFERENCES bots(username)
        );
        
        CREATE TABLE IF NOT EXISTS proxies (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            proxy_url TEXT UNIQUE NOT NULL,
            type TEXT DEFAULT 'mobile',
            is_active INTEGER DEFAULT 1,
            last_used DATETIME,
            fail_count INTEGER DEFAULT 0
        );
        
        CREATE TABLE IF NOT EXISTS targets (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            target_username TEXT NOT NULL,
            action TEXT NOT NULL,
            completed INTEGER DEFAULT 0,
            created_at DATETIME DEFAULT CURRENT_TIMESTAMP
        );
    """)
    conn.commit()
    conn.close()

init_db()

scheduler = BotScheduler()
scheduler.start()

adb_bridge = ADBBridge()
pipeline = AccountPipeline(adb_bridge=adb_bridge)
fingerprint = FingerprintManager()
if check_adb():
    adb_bridge.scan()
    adb_bridge.start_monitor()
    print(f"[ADB] Bridge active — {len(adb_bridge.phones)} phone(s) detected")
else:
    print("[ADB] ADB not found — phone proxy carrier disabled")

def get_db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn

def bot_login(bot):
    client = Client()
    if bot['proxy']:
        client.set_proxy(bot['proxy'])
    if os.path.exists(bot['settings_file']):
        client.load_settings(bot['settings_file'])
    client.login(bot['username'], bot['password'])
    return client

def update_bot_status(username, status):
    conn = get_db()
    conn.execute("UPDATE bots SET status=?, last_online=? WHERE username=?",
                 (status, datetime.now().isoformat(), username))
    conn.commit()
    conn.close()

@app.route('/')
def dashboard():
    conn = get_db()
    total = conn.execute("SELECT COUNT(*) FROM bots").fetchone()[0]
    online = conn.execute("SELECT COUNT(*) FROM bots WHERE status='online'").fetchone()[0]
    pending = conn.execute("SELECT COUNT(*) FROM tasks WHERE status='pending'").fetchone()[0]
    bots = conn.execute("SELECT * FROM bots ORDER BY id DESC LIMIT 20").fetchall()
    conn.close()
    
    return render_template_string("""
    <!DOCTYPE html>
    <html>
    <head><title>C2 Dashboard</title>
    <meta name="viewport" content="width=device-width,initial-scale=1">
    <style>
        body { font-family: monospace; background: #0a0a0a; color: #00ff00; margin: 20px; }
        .stat { display: inline-block; padding: 15px; margin: 10px; border: 1px solid #00ff00; border-radius: 5px; }
        .stat span { font-size: 2em; display: block; }
        table { width: 100%; border-collapse: collapse; margin-top: 20px; }
        th, td { text-align: left; padding: 8px; border-bottom: 1px solid #333; }
        th { color: #00ff00; }
        .online { color: #00ff00; } .offline { color: #ff4444; }
        a { color: #00ff00; text-decoration: none; }
        .nav a { margin: 0 10px; }
    </style></head>
    <body>
        <h1>🕸️ IG Botnet C2</h1>
        <div class="nav">
            <a href="/">Dashboard</a> | 
            <a href="/bots">Bots</a> | 
            <a href="/tasks">Tasks</a> | 
            <a href="/schedules">Schedules</a> |
            <a href="/engage">Engage</a> |
            <a href="/phones">📱 Phones</a> |
            <a href="/api/stats">API Stats</a>
        </div>
        <div class="stat">Total Bots <span>{{ total }}</span></div>
        <div class="stat">Online <span>{{ online }}</span></div>
        <div class="stat">Pending Tasks <span>{{ pending }}</span></div>
        <h2>Recent Bots</h2>
        <table>
            <tr><th>Username</th><th>Status</th><th>Last Online</th><th>Actions</th></tr>
            {% for bot in bots %}
            <tr>
                <td>{{ bot.username }}</td>
                <td class="{{ 'online' if bot.status == 'online' else 'offline' }}">{{ bot.status }}</td>
                <td>{{ bot.last_online or 'Never' }}</td>
                <td><a href="/api/bot/{{ bot.username }}/action/follow?target=test_account">Test Follow</a></td>
            </tr>
            {% endfor %}
        </table>
    </body></html>
    """, total=total, online=online, pending=pending, bots=bots)

@app.route('/bots')
def bots_page():
    conn = get_db()
    bots = conn.execute("SELECT * FROM bots ORDER BY id DESC").fetchall()
    conn.close()
    return render_template_string("""
    <!DOCTYPE html><html><head><title>Bots</title><style>
        body{font-family:monospace;background:#0a0a0a;color:#00ff00;margin:20px}
        table{width:100%;border-collapse:collapse}
        th,td{text-align:left;padding:8px;border-bottom:1px solid #333}
        .online{color:#0f0}.offline{color:#f44}.busy{color:#ff0}
    </style></head><body>
    <h1>🤖 Bot Fleet</h1>
    <table>
        <tr><th>ID</th><th>Username</th><th>Email</th><th>Status</th><th>Proxy</th><th>Last Online</th><th>Created</th></tr>
        {% for b in bots %}
        <tr>
            <td>{{ b.id }}</td>
            <td>{{ b.username }}</td>
            <td>{{ b.email }}</td>
            <td class="{{ b.status }}">{{ b.status }}</td>
            <td>{{ b.proxy[:30] if b.proxy else 'None' }}</td>
            <td>{{ b.last_online or 'Never' }}</td>
            <td>{{ b.created_at }}</td>
        </tr>
        {% endfor %}
    </table>
    <a href="/">← Back</a>
    </body></html>
    """, bots=bots)

@app.route('/tasks')
def tasks_page():
    conn = get_db()
    tasks = conn.execute("""SELECT t.*, b.username as bot_uname 
                           FROM tasks t LEFT JOIN bots b ON t.bot_username = b.username 
                           ORDER BY t.id DESC LIMIT 100""").fetchall()
    conn.close()
    return render_template_string("""
    <!DOCTYPE html><html><head><title>Tasks</title><style>
        body{font-family:monospace;background:#0a0a0a;color:#00ff00;margin:20px}
        table{width:100%;border-collapse:collapse}
        th,td{text-align:left;padding:8px;border-bottom:1px solid #333}
        .pending{color:#ff0}.running{color:#0ff}.done{color:#0f0}.failed{color:#f44}
    </style></head><body>
    <h1>📋 Task Queue</h1>
    <table>
        <tr><th>ID</th><th>Bot</th><th>Type</th><th>Params</th><th>Status</th><th>Result</th></tr>
        {% for t in tasks %}
        <tr>
            <td>{{ t.id }}</td>
            <td>{{ t.bot_uname or t.bot_username }}</td>
            <td>{{ t.task_type }}</td>
            <td>{{ t.params[:50] if t.params else '' }}</td>
            <td class="{{ t.status }}">{{ t.status }}</td>
            <td>{{ t.result[:50] if t.result else '' }}</td>
        </tr>
        {% endfor %}
    </table>
    <a href="/">← Back</a>
    </body></html>
    """, tasks=tasks)

@app.route('/phones')
def phones_page():
    stats = adb_bridge.get_stats()
    return render_template_string("""
    <!DOCTYPE html><html><head><title>ADB Phones</title><style>
        body{font-family:monospace;background:#0a0a0a;color:#0f0;margin:20px}
        table{width:100%;border-collapse:collapse}
        th,td{text-align:left;padding:8px;border-bottom:1px solid #333}
        .online{color:#0f0}.offline{color:#f44}
        .card{display:inline-block;padding:15px;margin:10px;border:1px solid #0f0;border-radius:5px}
        .card span{font-size:2em;display:block}
        .btn{background:#111;color:#0f0;border:1px solid #0f0;padding:8px 16px;margin:5px;cursor:pointer;border-radius:3px}
        .btn:hover{background:#0a1a0a}
    </style></head><body>
    <h1>📱 ADB Phone Proxy Carriers</h1>
    <div class="card">Total <span>{{ stats.total_phones }}</span></div>
    <div class="card">Online <span>{{ stats.online_phones }}</span></div>
    <div class="card">Proxies <span>{{ stats.proxies_active }}</span></div>
    <div>
        <button class="btn" onclick="f('scan')">🔍 Scan Devices</button>
        <button class="btn" onclick="f('provision_all')">🚀 Provision All</button>
        <button class="btn" onclick="f('refresh')">🔄 Refresh Proxies</button>
    </div>
    <h2>Connected Phones</h2>
    <table>
        <tr><th>Serial</th><th>Model</th><th>Proxy</th><th>Battery</th><th>Operator</th><th>Status</th><th>Actions</th></tr>
        {% for p in stats.phones %}
        <tr>
            <td>{{ p.serial }}</td>
            <td>{{ p.model }}</td>
            <td>{{ p.proxy_url or 'Not set' }}</td>
            <td>{{ p.battery or '?' }}%</td>
            <td>{{ p.operator or '?' }}</td>
            <td class="{{ 'online' if p.online else 'offline' }}">{{ 'Online' if p.online else 'Offline' }}</td>
            <td><button class="btn" onclick="prov('{{ p.serial }}')">Provision</button></td>
        </tr>
        {% endfor %}
    </table>
    {% if not stats.phones %}<p>No phones connected. Plug in USB debugging-enabled devices.</p>{% endif %}
    <script>
    function f(action){
        var url = '/api/adb/' + action;
        if(action=='refresh') url='/api/adb/refresh_proxies';
        fetch(url,{method:'POST'}).then(r=>r.json()).then(d=>{alert(JSON.stringify(d,null,2));location.reload()})
    }
    function prov(s){
        fetch('/api/adb/provision/'+s,{method:'POST'}).then(r=>r.json()).then(d=>{alert(JSON.stringify(d,null,2));location.reload()})
    }
    </script>
    <a href="/">← Back</a>
    </body></html>
    """, stats=stats)

@app.route('/schedules')
def schedules_page():
    scheds = scheduler.list_schedules()
    return render_template_string("""
    <!DOCTYPE html><html><head><title>Schedules</title><style>
        body{font-family:monospace;background:#0a0a0a;color:#00ff00;margin:20px}
        table{width:100%;border-collapse:collapse}
        th,td{text-align:left;padding:8px;border-bottom:1px solid #333}
        .active{color:#0f0}.paused{color:#ff0}
    </style></head><body>
    <h1>⏰ Bot Schedules</h1>
    <table>
        <tr><th>Bot</th><th>Next Run</th><th>Config</th></tr>
        {% for uname, s in scheds.items() %}
        <tr>
            <td>{{ uname }}</td>
            <td>{{ s.next_run }}</td>
            <td>{{ s.config }}</td>
        </tr>
        {% endfor %}
    </table>
    {% if not scheds %}<p>No scheduled bots.</p>{% endif %}
    <a href="/">← Back</a>
    </body></html>
    """, scheds=scheds)

@app.route('/engage')
def engage_page():
    return render_template_string("""
    <!DOCTYPE html><html><head><title>Engage</title><style>
        body{font-family:monospace;background:#0a0a0a;color:#00ff00;margin:20px}
        .card{display:inline-block;padding:20px;margin:10px;border:1px solid #0f0;border-radius:5px;cursor:pointer}
        .card:hover{background:#0a1a0a}
        form{margin:20px 0} input,button{background:#111;color:#0f0;border:1px solid #0f0;padding:8px;margin:5px}
    </style></head><body>
    <h1>🤖 Behavior Controls</h1>
    <div class="card" onclick="fetch('/api/mass_engage',{method:'POST'}).then(r=>r.json()).then(alert)">
    ▶️ Mass Engage<br><small>All bots: like, comment, follow-back, stories</small>
    </div>
    <div class="card" onclick="fetch('/api/mass_bio_rotate',{method:'POST'}).then(r=>r.json()).then(alert)">
    🔄 Rotate Bios<br><small>All online bots get new bios</small>
    </div>
    <div class="card" onclick="fetch('/api/mass_set_pp',{method:'POST'}).then(r=>r.json()).then(alert)">
    🖼️ Set Profile Pics<br><small>All online bots get avatar</small>
    </div>
    <div class="card" onclick="fetch('/api/schedule/list').then(r=>r.json()).then(d=>alert(JSON.stringify(d,null,2)))">
    📋 View Schedules
    </div>
    <h2>Single Bot Actions</h2>
    <form onsubmit="e(this,'engage')"><label>Bot: <input name="bot" required></label>
    <button>Engage Session</button></form>
    <form onsubmit="e(this,'like')"><label>Bot: <input name="bot" required></label>
    <label>Target: <input name="target" required></label>
    <button>Like Recent</button></form>
    <form onsubmit="e(this,'follow_back')"><label>Bot: <input name="bot" required></label>
    <button>Follow Back</button></form>
    <form onsubmit="e(this,'rotate_bio')"><label>Bot: <input name="bot" required></label>
    <button>Rotate Bio</button></form>
    <form onsubmit="e(this,'set_pp')"><label>Bot: <input name="bot" required></label>
    <button>Set Profile Pic</button></form>
    <form onsubmit="e(this,'schedule')"><label>Bot: <input name="bot" required></label>
    <label>Delay(min): <input name="delay" value="30"></label>
    <button>Schedule Daily</button></form>
    <script>
    function e(f,action){
        f.preventDefault();
        var bot=f.bot.value;
        var target=f.target?f.target.value:'';
        var delay=f.delay?f.delay.value:'30';
        var url,body={};
        if(action=='engage'){url='/api/bot/'+bot+'/engage';body={};}
        else if(action=='like'){url='/api/bot/'+bot+'/like_recent';body={target:target};}
        else if(action=='follow_back'){url='/api/bot/'+bot+'/follow_back';body={};}
        else if(action=='rotate_bio'){url='/api/bot/'+bot+'/rotate_bio';body={};}
        else if(action=='set_pp'){url='/api/bot/'+bot+'/set_pp';body={};}
        else if(action=='schedule'){url='/api/schedule/bot/'+bot;body={delay_minutes:parseInt(delay)};}
        fetch(url,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(body)})
        .then(r=>r.json()).then(alert).catch(e=>alert(e));
    }
    </script>
    <a href="/">← Back</a>
    </body></html>
    """)

@app.route('/api/stats')
def api_stats():
    conn = get_db()
    total = conn.execute("SELECT COUNT(*) FROM bots").fetchone()[0]
    online = conn.execute("SELECT COUNT(*) FROM bots WHERE status='online'").fetchone()[0]
    busy = conn.execute("SELECT COUNT(*) FROM bots WHERE status='busy'").fetchone()[0]
    pending_tasks = conn.execute("SELECT COUNT(*) FROM tasks WHERE status='pending'").fetchone()[0]
    total_tasks = conn.execute("SELECT COUNT(*) FROM tasks").fetchone()[0]
    total_proxies = conn.execute("SELECT COUNT(*) FROM proxies").fetchone()[0]
    conn.close()
    sched_count = len(scheduler.list_schedules())
    adb = adb_bridge.get_stats()
    pipe_stats = get_pipeline_stats()
    return jsonify({
        'total_bots': total, 'online_bots': online, 'busy_bots': busy,
        'pending_tasks': pending_tasks, 'total_tasks': total_tasks,
        'total_proxies': total_proxies, 'scheduled_bots': sched_count,
        'adb_phones': adb.get('total_phones', 0),
        'adb_proxies': adb.get('proxies_active', 0),
        'pipeline_total': pipe_stats.get('total', 0),
        'pipeline_states': pipe_stats.get('by_state', {}),
        'fingerprint_profiles': fingerprint.stats().get('total_profiles', 0),
        'status': 'running'
    })

@app.route('/api/bots')
def api_list_bots():
    conn = get_db()
    bots = [dict(r) for r in conn.execute("SELECT * FROM bots ORDER BY id DESC").fetchall()]
    conn.close()
    return jsonify(bots)

@app.route('/api/bot/<username>')
def api_bot_detail(username):
    conn = get_db()
    bot = conn.execute("SELECT * FROM bots WHERE username=?", (username,)).fetchone()
    tasks = conn.execute("SELECT * FROM tasks WHERE bot_username=? ORDER BY id DESC LIMIT 20", (username,)).fetchall()
    conn.close()
    if bot:
        return jsonify({'bot': dict(bot), 'tasks': [dict(t) for t in tasks]})
    return jsonify({'error': 'not found'}), 404

@app.route('/api/bot/add', methods=['POST'])
def api_add_bot():
    data = request.json
    conn = get_db()
    try:
        conn.execute("""INSERT INTO bots (username, password, email, user_id, proxy, settings_file, status)
                        VALUES (?,?,?,?,?,?,?)""",
                     (data['username'], data['password'], data.get('email'),
                      data.get('user_id'), data.get('proxy'), data.get('settings_file'), 'idle'))
        conn.commit()
        return jsonify({'success': True, 'username': data['username']})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 400
    finally:
        conn.close()

@app.route('/api/bot/<username>/action/<action_type>', methods=['GET', 'POST'])
def api_bot_action(username, action_type):
    conn = get_db()
    bot = conn.execute("SELECT * FROM bots WHERE username=?", (username,)).fetchone()
    if not bot:
        return jsonify({'error': 'bot not found'}), 404
    
    bot = dict(bot)
    params = request.json or {}
    target = request.args.get('target') or params.get('target')
    
    task_params = json.dumps({'target': target, 'action': action_type, **params})
    conn.execute("""INSERT INTO tasks (bot_username, task_type, params, status)
                    VALUES (?,?,?,?)""", (username, action_type, task_params, 'running'))
    task_id = conn.execute("SELECT last_insert_rowid()").fetchone()[0]
    conn.commit()
    conn.close()
    
    def execute():
        try:
            client = bot_login(bot)
            update_bot_status(username, 'busy')
            
            result = {}
            if action_type == 'follow':
                user_id = client.user_id_from_username(target)
                result = client.user_follow(user_id)
                result_text = f"Followed {target}"
            elif action_type == 'unfollow':
                user_id = client.user_id_from_username(target)
                result = client.user_unfollow(user_id)
                result_text = f"Unfollowed {target}"
            elif action_type == 'like':
                media_id = client.media_id(target)
                result = client.media_like(media_id)
                result_text = f"Liked {target}"
            elif action_type == 'comment':
                media_id = client.media_id(target)
                text = params.get('text', 'Nice post!')
                result = client.media_comment(media_id, text)
                result_text = f"Commented on {target}: {text}"
            elif action_type == 'dm':
                user_id = client.user_id_from_username(target)
                text = params.get('text', 'Hey!')
                result = client.direct_send(text, [user_id])
                result_text = f"DM sent to {target}"
            elif action_type == 'story_view':
                user_id = client.user_id_from_username(target)
                result = client.user_stories(user_id)
                result_text = f"Viewed {target}'s stories"
            elif action_type == 'info':
                info = client.user_info_by_username(target)
                result_text = json.dumps(info.dict(), indent=2)
                result = {'info': str(info)}
            else:
                result_text = f"Unknown action: {action_type}"
                result = {'error': result_text}
            
            conn2 = get_db()
            conn2.execute("UPDATE tasks SET status='done', result=?, completed_at=? WHERE id=?",
                         (result_text, datetime.now().isoformat(), task_id))
            conn2.commit()
            conn2.close()
            update_bot_status(username, 'online')
            
        except Exception as e:
            conn2 = get_db()
            conn2.execute("UPDATE tasks SET status='failed', result=?, completed_at=? WHERE id=?",
                         (str(e), datetime.now().isoformat(), task_id))
            conn2.commit()
            conn2.close()
            update_bot_status(username, 'idle')
    
    threading.Thread(target=execute, daemon=True).start()
    return jsonify({'task_id': task_id, 'status': 'running', 'action': action_type, 'target': target})

@app.route('/api/bot/<username>/login', methods=['POST'])
def api_bot_login(username):
    conn = get_db()
    bot = conn.execute("SELECT * FROM bots WHERE username=?", (username,)).fetchone()
    conn.close()
    if not bot:
        return jsonify({'error': 'not found'}), 404
    
    bot = dict(bot)
    try:
        client = bot_login(bot)
        update_bot_status(username, 'online')
        client.dump_settings(bot['settings_file'])
        return jsonify({'success': True, 'username': username, 'status': 'online'})
    except Exception as e:
        update_bot_status(username, 'offline')
        return jsonify({'success': False, 'error': str(e)})

@app.route('/api/tasks')
def api_list_tasks():
    conn = get_db()
    tasks = [dict(r) for r in conn.execute(
        "SELECT * FROM tasks ORDER BY id DESC LIMIT 100").fetchall()]
    conn.close()
    return jsonify(tasks)

@app.route('/api/proxies', methods=['GET', 'POST'])
def api_proxies():
    if request.method == 'POST':
        data = request.json
        conn = get_db()
        for proxy in data.get('proxies', []):
            try:
                conn.execute("INSERT OR IGNORE INTO proxies (proxy_url, type) VALUES (?,?)",
                           (proxy, data.get('type', 'mobile')))
            except:
                pass
        conn.commit()
        conn.close()
        return jsonify({'added': len(data.get('proxies', []))})
    
    conn = get_db()
    proxies = [dict(r) for r in conn.execute("SELECT * FROM proxies WHERE is_active=1").fetchall()]
    conn.close()
    return jsonify(proxies)

@app.route('/api/mass_follow', methods=['POST'])
def api_mass_follow():
    data = request.json
    target = data['target']
    count = data.get('count', 5)
    
    conn = get_db()
    bots = conn.execute("SELECT * FROM bots WHERE status='online' OR status='idle' LIMIT ?", (count,)).fetchall()
    conn.close()
    
    tasks_created = []
    for bot in bots:
        threading.Thread(target=lambda b=dict(bot): (
            requests.get(f"http://localhost:5000/api/bot/{b['username']}/action/follow?target={target}")
        ), daemon=True).start()
        tasks_created.append(bot['username'])
    
    return jsonify({'mass_follow': True, 'bots_used': len(tasks_created), 'target': target, 'bots': tasks_created})

@app.route('/api/mass_like', methods=['POST'])
def api_mass_like():
    data = request.json
    media_url = data['media_url']
    count = data.get('count', 10)
    
    conn = get_db()
    bots = conn.execute("SELECT * FROM bots WHERE status='online' OR status='idle' LIMIT ?", (count,)).fetchall()
    conn.close()
    
    for bot in bots:
        threading.Thread(target=lambda b=dict(bot): (
            requests.get(f"http://localhost:5000/api/bot/{b['username']}/action/like?target={media_url}")
        ), daemon=True).start()
    
    return jsonify({'mass_like': True, 'bots_used': len(bots), 'media': media_url})

@app.route('/api/export')
def api_export():
    conn = get_db()
    bots = [dict(r) for r in conn.execute("SELECT username, password, email, proxy FROM bots").fetchall()]
    conn.close()
    return jsonify(bots)

# ── Humanized Behavior Endpoints ──────────────────────────────────

@app.route('/api/bot/<username>/engage', methods=['POST'])
def api_bot_engage(username):
    """Run a full human-like engagement session on one bot."""
    conn = get_db()
    bot = conn.execute("SELECT * FROM bots WHERE username=?", (username,)).fetchone()
    conn.close()
    if not bot:
        return jsonify({'error': 'not found'}), 404
    config = request.json or {}
    threading.Thread(
        target=lambda: (
            setattr(threading.current_thread(), 'result',
                    BehaviorEngine.full_engagement_session(dict(bot), config))
        ),
        daemon=True,
    ).start()
    return jsonify({'status': 'dispatched', 'username': username})

@app.route('/api/bot/<username>/like_recent', methods=['POST'])
def api_like_recent(username):
    conn = get_db()
    bot = conn.execute("SELECT * FROM bots WHERE username=?", (username,)).fetchone()
    conn.close()
    if not bot:
        return jsonify({'error': 'not found'}), 404
    data = request.json or {}
    target = data.get('target', '')
    max_posts = data.get('max_posts', 4)
    if not target:
        return jsonify({'error': 'target required'}), 400
    def _run():
        client = BehaviorEngine.login_and_online(dict(bot))
        liked = BehaviorEngine.like_recent_posts(client, target, max_posts)
        update_bot_status(username, 'online')
        return liked
    threading.Thread(target=_run, daemon=True).start()
    return jsonify({'status': 'running', 'target': target})

@app.route('/api/bot/<username>/follow_back', methods=['POST'])
def api_follow_back(username):
    conn = get_db()
    bot = conn.execute("SELECT * FROM bots WHERE username=?", (username,)).fetchone()
    conn.close()
    if not bot:
        return jsonify({'error': 'not found'}), 404
    def _run():
        client = BehaviorEngine.login_and_online(dict(bot))
        count = BehaviorEngine.auto_follow_backers(client)
        update_bot_status(username, 'online')
        return count
    threading.Thread(target=_run, daemon=True).start()
    return jsonify({'status': 'running'})

@app.route('/api/bot/<username>/set_pp', methods=['POST'])
def api_set_pp(username):
    conn = get_db()
    bot = conn.execute("SELECT * FROM bots WHERE username=?", (username,)).fetchone()
    conn.close()
    if not bot:
        return jsonify({'error': 'not found'}), 404
    data = request.json or {}
    image = data.get('image', '')
    if not image:
        image = BehaviorEngine.generate_profile_pic_url()
    def _run():
        client = BehaviorEngine.login_and_online(dict(bot))
        ok = BehaviorEngine.set_profile_pic(client, image)
        update_bot_status(username, 'online')
        return ok
    threading.Thread(target=_run, daemon=True).start()
    return jsonify({'status': 'running', 'image': image})

@app.route('/api/bot/<username>/rotate_bio', methods=['POST'])
def api_rotate_bio(username):
    conn = get_db()
    bot = conn.execute("SELECT * FROM bots WHERE username=?", (username,)).fetchone()
    conn.close()
    if not bot:
        return jsonify({'error': 'not found'}), 404
    def _run():
        client = BehaviorEngine.login_and_online(dict(bot))
        bio = BehaviorEngine.rotate_bio(client)
        update_bot_status(username, 'online')
        return bio
    threading.Thread(target=_run, daemon=True).start()
    return jsonify({'status': 'running'})

@app.route('/api/bot/<username>/report', methods=['POST'])
def api_bot_report(username):
    data = request.json or {}
    report = data.get('report', {})
    conn = get_db()
    conn.execute("UPDATE bots SET notes=? WHERE username=?",
                 (json.dumps(report), username))
    conn.commit()
    conn.close()
    return jsonify({'saved': True})

@app.route('/api/bot/<username>/comment_on', methods=['POST'])
def api_comment_on(username):
    conn = get_db()
    bot = conn.execute("SELECT * FROM bots WHERE username=?", (username,)).fetchone()
    conn.close()
    if not bot:
        return jsonify({'error': 'not found'}), 404
    data = request.json or {}
    target = data.get('target', '')
    max_posts = data.get('max_posts', 2)
    if not target:
        return jsonify({'error': 'target required'}), 400
    def _run():
        client = BehaviorEngine.login_and_online(dict(bot))
        count = BehaviorEngine.comment_on_recent(client, target, max_posts)
        update_bot_status(username, 'online')
        return count
    threading.Thread(target=_run, daemon=True).start()
    return jsonify({'status': 'running', 'target': target})

# ── Scheduler Endpoints ──────────────────────────────────────────

@app.route('/api/schedule/bot/<username>', methods=['POST'])
def api_schedule_bot(username):
    data = request.json or {}
    delay = data.get('delay_minutes', random.randint(10, 120))
    scheduler.schedule_bot(username, config=data.get('config', {}), first_delay_minutes=delay)
    return jsonify({'scheduled': True, 'username': username, 'delay_minutes': delay})

@app.route('/api/schedule/bot/<username>', methods=['DELETE'])
def api_unschedule_bot(username):
    scheduler.unschedule_bot(username)
    return jsonify({'unscheduled': True, 'username': username})

@app.route('/api/schedule/list')
def api_list_schedules():
    return jsonify(scheduler.list_schedules())

@app.route('/api/mass_engage', methods=['POST'])
def api_mass_engage():
    """Run engagement session on all online/idle bots."""
    data = request.json or {}
    config = data.get('config', {})
    max_bots = data.get('max_bots', 20)
    conn = get_db()
    bots = conn.execute(
        "SELECT * FROM bots WHERE status IN ('online','idle') LIMIT ?",
        (max_bots,),
    ).fetchall()
    conn.close()
    dispatched = []
    for bot in bots:
        threading.Thread(
            target=lambda b=dict(bot): BehaviorEngine.full_engagement_session(b, config),
            daemon=True,
        ).start()
        dispatched.append(bot['username'])
    return jsonify({'mass_engage': True, 'bots_used': len(dispatched), 'bots': dispatched})

@app.route('/api/mass_bio_rotate', methods=['POST'])
def api_mass_bio_rotate():
    conn = get_db()
    bots = conn.execute("SELECT * FROM bots WHERE status IN ('online','idle')").fetchall()
    conn.close()
    for bot in bots:
        threading.Thread(target=lambda b=dict(bot): (
            setattr(threading.Thread, '_bio',
                    BehaviorEngine.rotate_bio(BehaviorEngine.login_and_online(b)))
        ), daemon=True).start()
    return jsonify({'mass_bio': True, 'bots': len(bots)})

@app.route('/api/mass_set_pp', methods=['POST'])
def api_mass_set_pp():
    conn = get_db()
    bots = conn.execute("SELECT * FROM bots WHERE status IN ('online','idle')").fetchall()
    conn.close()
    for bot in bots:
        threading.Thread(target=lambda b=dict(bot): (
            BehaviorEngine.set_profile_pic(
                BehaviorEngine.login_and_online(b),
                BehaviorEngine.generate_profile_pic_url(),
            )
        ), daemon=True).start()
    return jsonify({'mass_pp': True, 'bots': len(bots)})

# ── ADB Phone Proxy Bridge Endpoints ──────────────────────────

@app.route('/api/adb/scan', methods=['POST'])
def api_adb_scan():
    phones = adb_bridge.scan()
    return jsonify({'phones': phones, 'count': len(phones)})

@app.route('/api/adb/phones')
def api_adb_phones():
    return jsonify(adb_bridge.get_stats())

@app.route('/api/adb/provision/<serial>', methods=['POST'])
def api_adb_provision(serial):
    ok = adb_bridge.provision_phone(serial)
    return jsonify({'serial': serial, 'success': ok})

@app.route('/api/adb/provision_all', methods=['POST'])
def api_adb_provision_all():
    results = adb_bridge.provision_all()
    return jsonify({'results': results})

@app.route('/api/adb/refresh_proxies', methods=['POST'])
def api_adb_refresh_proxies():
    proxies = adb_bridge.get_proxy_list()
    # Merge into proxy DB
    conn = get_db()
    for p in proxies:
        try:
            conn.execute(
                "INSERT OR IGNORE INTO proxies (proxy_url, type) VALUES (?,?)",
                (p, 'adb_phone'),
            )
        except:
            pass
    conn.commit()
    conn.close()
    return jsonify({'proxies_added': len(proxies), 'proxies': proxies})

@app.route('/api/adb/status')
def api_adb_status():
    return jsonify({
        'adb_available': check_adb(),
        'devices_detected': len(list_devices()),
        **adb_bridge.get_stats(),
    })

# ── Pipeline Endpoints ───────────────────────────────────────

@app.route('/api/pipeline/create', methods=['POST'])
def api_pipeline_create():
    data = request.json or {}
    count = data.get('count', 1)
    config = {
        'use_adb': data.get('use_adb', True),
        'phone': data.get('phone', ''),
        'proxies': data.get('proxies', None),
    }
    if count == 1:
        result = pipeline.create_account(config)
        return jsonify(result)
    else:
        threads = data.get('threads', min(count, 5))
        results = pipeline.batch_create(count, config, threads)
        return jsonify({'created': len(results), 'accounts': results})

@app.route('/api/pipeline/accounts')
def api_pipeline_accounts():
    state = request.args.get('state')
    limit = int(request.args.get('limit', 100))
    accounts = get_pipeline_accounts(state, limit)
    return jsonify(accounts)

@app.route('/api/pipeline/stats')
def api_pipeline_stats():
    return jsonify(get_pipeline_stats())

@app.route('/api/pipeline/age/<username>', methods=['POST'])
def api_pipeline_age(username):
    data = request.json or {}
    days = data.get('days', 3)
    threading.Thread(target=pipeline.age_account, args=(username, days), daemon=True).start()
    return jsonify({'status': 'aging', 'username': username})

@app.route('/api/pipeline/health/<username>')
def api_pipeline_health(username):
    result = pipeline.health_check(username)
    return jsonify(result)

@app.route('/api/pipeline/batch_health', methods=['POST'])
def api_pipeline_batch_health():
    results = pipeline.batch_health_check()
    return jsonify({'checked': len(results), 'results': results})

@app.route('/api/pipeline/batch_age', methods=['POST'])
def api_pipeline_batch_age():
    data = request.json or {}
    count = data.get('count', 5)
    threading.Thread(target=pipeline.batch_age, args=(count,), daemon=True).start()
    return jsonify({'aging': count})

# ── Fingerprint Endpoints ────────────────────────────────────

@app.route('/api/fingerprints')
def api_fingerprints():
    return jsonify(fingerprint.stats())

# ── Proxy Verification Endpoints ─────────────────────────────

@app.route('/api/proxy/verify', methods=['POST'])
def api_proxy_verify():
    data = request.json or {}
    proxy = data.get('proxy', '')
    if not proxy:
        return jsonify({'error': 'proxy required'}), 400
    result = test_proxy(proxy)
    return jsonify(result)

@app.route('/api/proxy/batch_verify', methods=['POST'])
def api_proxy_batch_verify():
    data = request.json or {}
    proxies = data.get('proxies', [])
    if not proxies:
        return jsonify({'error': 'proxies required'}), 400
    results = batch_verify(proxies)
    working = [r for r in results if r.get('working')]
    return jsonify({'total': len(proxies), 'working': len(working), 'results': results})

@app.route('/api/ip')
def api_my_ip():
    proxy = request.args.get('proxy', '')
    info = get_ip_info(proxy if proxy else None)
    return jsonify(info or {'error': 'could not determine IP'})

# ── Legacy ───────────────────────────────────────────────────────

def keep_bots_online():
    while True:
        try:
            conn = get_db()
            bots = conn.execute("SELECT * FROM bots ORDER BY last_online ASC LIMIT 10").fetchall()
            conn.close()
            for bot in bots:
                bot = dict(bot)
                try:
                    client = bot_login(bot)
                    update_bot_status(bot['username'], 'online')
                    client.dump_settings(bot['settings_file'])
                    print(f"[KeepAlive] {bot['username']} -> online")
                except:
                    update_bot_status(bot['username'], 'offline')
                time.sleep(random.uniform(2, 5))
        except:
            pass
        time.sleep(60)

if __name__ == "__main__":
    import requests
    
    t = threading.Thread(target=keep_bots_online, daemon=True)
    t.start()
    
    print("""
    ╔═══════════════════════════════════╗
    ║   IG Botnet C2 Server v1.0       ║
    ║   Running on http://0.0.0.0:5000  ║
    ╚═══════════════════════════════════╝
    """)
    app.run(host='0.0.0.0', port=5000, debug=False)
