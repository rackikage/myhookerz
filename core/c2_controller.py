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
    """, total=total, online=online, pending=pending, 
       bots=conn.execute("SELECT * FROM bots ORDER BY id DESC LIMIT 20").fetchall())

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
    return jsonify({
        'total_bots': total, 'online_bots': online, 'busy_bots': busy,
        'pending_tasks': pending_tasks, 'total_tasks': total_tasks,
        'total_proxies': total_proxies, 'status': 'running'
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
