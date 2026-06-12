"""
bot_behavior.py — Humanized behavior engine for bot accounts
Simulates realistic Instagram usage patterns:
  - Random delays & action pacing
  - Smart engagement (like recent posts, follow-back)
  - Profile management (bio, avatar rotation)
  - Daily activity scheduler
  - Comment templates with variety
"""
import os
import re
import json
import time
import random
import string
import threading
import requests as http_requests
from datetime import datetime, timedelta
from pathlib import Path
from queue import Queue

from instagrapi import Client
from instagrapi.exceptions import ClientError

HUMAN_DELAYS = {
    'scroll': (1.5, 6),
    'between_actions': (2, 12),
    'between_posts': (8, 30),
    'session_gap': (60, 300),
    'like_view': (1, 4),
    'comment_typing': (3, 15),
    'follow_view': (2, 8),
    'story_view': (3, 12),
    'profile_view': (5, 20),
}

COMMENT_TEMPLATES = [
    "nice shot! {emoji}",
    "🔥🔥",
    "love this!",
    "amazing {emoji}",
    "so good!",
    "wow {emoji}",
    "great post!",
    "👏👏",
    "this is fire 🔥",
    "beautiful!",
    "too good {emoji}",
    "fire post 🔥",
    "straight fire!",
    "underrated post",
    "this deserves more likes",
    "quality content right here",
    "keep it up! 💪",
    "sheesh 🔥",
    "hard 🔥",
    "different breed",
]

EMOJIS = ["🔥", "💯", "👏", "💪", "✨", "🎯", "🙌", "⚡", "❤️", "💥"]

BIO_TEMPLATES = [
    "{emoji} {username} | {tagline}",
    "{username} {emoji} | {tagline}",
    "{tagline} ✦ {username}",
    "{emoji} {tagline}",
    "{tagline} | {username} {emoji}",
]

TAGLINES = [
    "living life", "dream chaser", "on a journey",
    "making moves", "no cap", "different mindset",
    "built different", "stay humble", "grind never stops",
    "free spirit", "just vibing", "my life my rules",
    "creating memories", "blessed", "focus & hustle",
    "positive vibes only", "real ones know",
]


def human_pause(category='between_actions'):
    lo, hi = HUMAN_DELAYS.get(category, (1, 5))
    time.sleep(random.uniform(lo, hi))


def random_comment():
    tmpl = random.choice(COMMENT_TEMPLATES)
    emoji = random.choice(EMOJIS)
    return tmpl.replace('{emoji}', emoji)


def random_bio(username):
    tmpl = random.choice(BIO_TEMPLATES)
    emoji = random.choice(EMOJIS)
    tagline = random.choice(TAGLINES)
    return tmpl.format(username=username, emoji=emoji, tagline=tagline)


def random_username():
    adjs = ['cool', 'neo', 'zen', 'arc', 'vox', 'pix', 'flux', 'nova',
            'cosmo', 'byte', 'echo', 'zero', 'volt', 'wave', 'sage',
            'icy', 'raw', 'lit', 'max', 'ace', 'jade', 'onyx', 'ruby']
    nums = ''.join(random.choices(string.digits, k=4))
    suffix = ''.join(random.choices(string.ascii_lowercase, k=2))
    return f"{random.choice(adjs)}{nums}{suffix}"


class BehaviorEngine:
    """Packs human-like patience around every C2 action."""

    @staticmethod
    def login_and_online(bot_row):
        client = Client()
        if bot_row.get('proxy'):
            client.set_proxy(bot_row['proxy'])
        sf = bot_row.get('settings_file', '')
        if sf and os.path.exists(sf):
            client.load_settings(sf)
        client.login(bot_row['username'], bot_row['password'])
        if sf:
            client.dump_settings(sf)
        return client

    # ── Engagement Actions ──────────────────────────────────────

    @staticmethod
    def follow_with_pacing(client, target_username):
        """Follow with human-like delay."""
        human_pause('follow_view')
        uid = client.user_id_from_username(target_username)
        result = client.user_follow(uid)
        human_pause('between_actions')
        return result

    @staticmethod
    def like_recent_posts(client, target_username, max_posts=6, max_age_hours=48):
        """Like only recent posts (within max_age_hours)."""
        human_pause('profile_view')
        uid = client.user_id_from_username(target_username)
        media = client.user_medias(uid, amount=min(max_posts * 2, 24))
        liked = 0
        cutoff = datetime.now() - timedelta(hours=max_age_hours)
        for m in media:
            if m.taken_at and m.taken_at.replace(tzinfo=None) < cutoff:
                continue
            if liked >= max_posts:
                break
            try:
                human_pause('like_view')
                client.media_like(m.id)
                liked += 1
            except ClientError:
                pass
        human_pause('between_actions')
        return liked

    @staticmethod
    def comment_on_recent(client, target_username, max_posts=2):
        """Comment on the most recent posts with varied templates."""
        human_pause('profile_view')
        uid = client.user_id_from_username(target_username)
        media = client.user_medias(uid, amount=min(max_posts * 2, 12))
        commented = 0
        for m in media[:max_posts]:
            try:
                human_pause('comment_typing')
                client.media_comment(m.id, random_comment())
                commented += 1
            except ClientError:
                pass
        human_pause('between_actions')
        return commented

    @staticmethod
    def view_stories(client, target_username):
        """View a user's stories with realistic pacing."""
        human_pause('story_view')
        uid = client.user_id_from_username(target_username)
        stories = client.user_stories(uid)
        viewed = 0
        if stories:
            for story in stories:
                try:
                    human_pause('story_view')
                    client.story_seen(story.id)
                    viewed += 1
                except ClientError:
                    pass
        human_pause('between_actions')
        return viewed

    # ── Auto Follow-Back ────────────────────────────────────────

    @staticmethod
    def auto_follow_backers(client, max_follow=20):
        """Check recent followers and follow anyone not yet followed back."""
        human_pause('scroll')
        followers = client.user_followers(client.user_id)
        following = client.user_following(client.user_id)
        new_follows = 0
        for uid, info in followers.items():
            if uid in following:
                continue
            if new_follows >= max_follow:
                break
            try:
                human_pause('follow_view')
                client.user_follow(uid)
                new_follows += 1
            except ClientError:
                pass
        human_pause('between_actions')
        return new_follows

    # ── Profile Management ──────────────────────────────────────

    @staticmethod
    def set_profile_pic(client, image_path_or_url):
        """Set profile picture from a local file or URL."""
        if image_path_or_url.startswith(('http://', 'https://')):
            resp = http_requests.get(image_path_or_url, timeout=15)
            local_path = f"/tmp/pp_{random.randint(10000,99999)}.jpg"
            with open(local_path, 'wb') as f:
                f.write(resp.content)
            image_path_or_url = local_path
        if not os.path.exists(image_path_or_url):
            return False
        try:
            client.account_change_picture(image_path_or_url)
            human_pause('session_gap')
            if image_path_or_url.startswith('/tmp/pp_'):
                os.remove(image_path_or_url)
            return True
        except ClientError:
            return False

    @staticmethod
    def rotate_bio(client):
        """Set a fresh random bio."""
        bio = random_bio(client.username)
        try:
            client.account_edit(biography=bio)
            return bio
        except ClientError:
            return None

    @staticmethod
    def generate_profile_pic_url():
        """Return URL for a random AI-generated face (placeholder)."""
        seed = random.randint(1, 99999)
        return f"https://i.pravatar.cc/400?u=ig{seed}"

    # ── Full Engagement Session ─────────────────────────────────

    @staticmethod
    def full_engagement_session(bot_row, config=None):
        """Run a complete human-like session on a single bot.

        config keys:
          max_likes       — posts to like per followed user   (default 3)
          max_comments    — comments to leave                 (default 1)
          max_story_users — users whose stories to view       (default 3)
          max_follow_back  — auto follow-back limit            (default 15)
          session_targets — list of usernames to engage with  (default follows)
        """
        cfg = config or {}
        try:
            client = BehaviorEngine.login_and_online(bot_row)
        except Exception as e:
            return {'status': 'failed', 'error': str(e)}

        report = {'status': 'ok', 'username': bot_row['username']}

        # 1. Follow-back
        max_fb = cfg.get('max_follow_back', 15)
        report['followed_back'] = BehaviorEngine.auto_follow_backers(client, max_fb)

        # 2. Like recent posts from followed users
        max_likes = cfg.get('max_likes', 3)
        targets = cfg.get('session_targets', [])
        if not targets:
            following = client.user_following(client.user_id)
            targets = [u.username for u in following.values()][:8]
        total_likes = 0
        for t in targets[:6]:
            try:
                total_likes += BehaviorEngine.like_recent_posts(client, t, max_likes)
            except ClientError:
                continue
        report['likes'] = total_likes

        # 3. Comment on a few
        max_comments = cfg.get('max_comments', 1)
        total_comments = 0
        for t in targets[:3]:
            try:
                total_comments += BehaviorEngine.comment_on_recent(client, t, max_comments)
            except ClientError:
                continue
        report['comments'] = total_comments

        # 4. View stories
        max_story = cfg.get('max_story_users', 2)
        total_stories = 0
        story_targets = (targets + list(client.user_followers(client.user_id).keys()))[:max_story]
        for uid_str in story_targets:
            if isinstance(uid_str, str) and not uid_str.isdigit():
                continue
            try:
                uname = uid_str if isinstance(uid_str, str) and not uid_str.isdigit() else ''
                if uname:
                    total_stories += BehaviorEngine.view_stories(client, uname)
            except ClientError:
                continue
        report['stories_viewed'] = total_stories

        human_pause('session_gap')
        return report


class BotScheduler:
    """Daily scheduler per bot — runs tasks at random times."""

    def __init__(self, c2_url="http://localhost:5000"):
        self.c2_url = c2_url
        self._schedules = {}
        self._running = False
        self._thread = None

    def start(self):
        if self._running:
            return
        self._running = True
        self._thread = threading.Thread(target=self._loop, daemon=True)
        self._thread.start()

    def stop(self):
        self._running = False

    def _loop(self):
        while self._running:
            now = datetime.now()
            for bot_uname, entry in list(self._schedules.items()):
                next_run = entry.get('next_run')
                if next_run and now >= next_run:
                    threading.Thread(
                        target=self._dispatch,
                        args=(bot_uname, entry['config']),
                        daemon=True,
                    ).start()
                    # schedule next run 22-26 hours from now
                    jitter = random.randint(22 * 60, 26 * 60)
                    entry['next_run'] = now + timedelta(minutes=jitter)
            time.sleep(30)

    def _dispatch(self, bot_uname, config):
        try:
            resp = http_requests.get(f"{self.c2_url}/api/bot/{bot_uname}", timeout=5)
            if resp.status_code != 200:
                return
            bot = resp.json().get('bot', {})
            if bot.get('status') != 'online':
                return
            report = BehaviorEngine.full_engagement_session(bot, config)
            http_requests.post(
                f"{self.c2_url}/api/bot/{bot_uname}/report",
                json={'report': report, 'scheduled': True},
                timeout=5,
            )
        except Exception:
            pass

    def schedule_bot(self, username, config=None, first_delay_minutes=None):
        cfg = config or {}
        if first_delay_minutes is None:
            first_delay_minutes = random.randint(5, 120)
        next_run = datetime.now() + timedelta(minutes=first_delay_minutes)
        self._schedules[username] = {'next_run': next_run, 'config': cfg}

    def unschedule_bot(self, username):
        self._schedules.pop(username, None)

    def list_schedules(self):
        return {
            u: {
                'next_run': s['next_run'].isoformat() if s.get('next_run') else None,
                'config': s.get('config', {}),
            }
            for u, s in self._schedules.items()
        }
