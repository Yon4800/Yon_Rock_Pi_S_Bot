import os
import re
import html
import json
import time
try:
    import requests
except ImportError:
    requests = None
import tempfile
from typing import Optional, List, Dict, Any

class ProcessedStore:
    def __init__(self, filepath: str, max_items: int = 2000):
        self.filepath = filepath
        self.max_items = max_items
        self.ids = set()
        self.load()

    def load(self):
        if os.path.exists(self.filepath):
            try:
                with open(self.filepath, "r", encoding="utf-8") as f:
                    data = json.load(f)
                    if isinstance(data, list):
                        self.ids = set(data[-self.max_items:])
            except Exception as e:
                print(f"[ProcessedStore] Error loading {self.filepath}: {e}")

    def save(self):
        dir_name = os.path.dirname(self.filepath)
        if dir_name and not os.path.exists(dir_name):
            os.makedirs(dir_name, exist_ok=True)
        try:
            items = list(self.ids)[-self.max_items:]
            with tempfile.NamedTemporaryFile("w", dir=dir_name or ".", delete=False, encoding="utf-8") as tf:
                json.dump(items, tf, ensure_ascii=False, indent=2)
                temp_name = tf.name
            os.replace(temp_name, self.filepath)
        except Exception as e:
            print(f"[ProcessedStore] Error saving {self.filepath}: {e}")

    def is_processed(self, item_id: str) -> bool:
        return str(item_id) in self.ids

    def add(self, item_id: str):
        self.ids.add(str(item_id))
        self.save()


class MastodonClient:
    def __init__(self, server: str, token: str):
        if not server:
            raise ValueError("Server URL or hostname is required.")
        server = server.strip()
        if not server.startswith(("http://", "https://")):
            server = "https://" + server
        self.base_url = server.rstrip("/")
        self.token = token.strip() if token else ""
        self.headers = {
            "Authorization": f"Bearer {self.token}",
            "User-Agent": "SBCBot/2.0 (Mastodon/Hollo compatible)"
        }
        self.session = requests.Session()
        self.session.headers.update(self.headers)
        self._me = None

    @staticmethod
    def html_to_text(html_content: str) -> str:
        """MastodonのHTMLコンテンツをプレーンテキストに変換する"""
        if not html_content:
            return ""
        text = re.sub(r'<br\s*/?>', '\n', html_content, flags=re.IGNORECASE)
        text = re.sub(r'</p>\s*<p[^>]*>', '\n\n', text, flags=re.IGNORECASE)
        text = re.sub(r'<[^>]+>', '', text)
        text = html.unescape(text)
        return text.strip()

    def get_me(self) -> Dict[str, Any]:
        """自分のアカウント情報を取得・キャッシュ"""
        if self._me:
            return self._me
        url = f"{self.base_url}/api/v1/accounts/verify_credentials"
        res = self.session.get(url, timeout=10)
        res.raise_for_status()
        self._me = res.json()
        return self._me

    def post_status(self, text: str, in_reply_to_id: Optional[str] = None, visibility: str = "public", media_ids: Optional[List[str]] = None) -> Dict[str, Any]:
        """ステータス（投稿）を作成"""
        url = f"{self.base_url}/api/v1/statuses"
        payload = {
            "status": text,
            "visibility": visibility
        }
        if in_reply_to_id:
            payload["in_reply_to_id"] = str(in_reply_to_id)
        if media_ids:
            payload["media_ids"] = [str(mid) for mid in media_ids]
        
        res = self.session.post(url, json=payload, timeout=15)
        res.raise_for_status()
        return res.json()

    def upload_media(self, file_path: str) -> Optional[str]:
        """メディアファイルをアップロードして media_id を取得"""
        url = f"{self.base_url}/api/v2/media"
        try:
            with open(file_path, "rb") as f:
                res = self.session.post(url, files={"file": f}, timeout=30)
                if res.status_code in (200, 201, 202):
                    return str(res.json().get("id"))
        except Exception as e:
            # v1 フォールバック
            try:
                url_v1 = f"{self.base_url}/api/v1/media"
                with open(file_path, "rb") as f:
                    res = self.session.post(url_v1, files={"file": f}, timeout=30)
                    if res.status_code in (200, 201, 202):
                        return str(res.json().get("id"))
            except Exception as ex:
                print(f"[MastodonClient] Error uploading media: {ex}")
        return None

    def favourite(self, status_id: str) -> bool:
        """投稿をお気に入り（ふぁぼ）する"""
        url = f"{self.base_url}/api/v1/statuses/{status_id}/favourite"
        try:
            res = self.session.post(url, timeout=10)
            return res.status_code in (200, 201)
        except Exception as e:
            print(f"[MastodonClient] Error favouriting status {status_id}: {e}")
            return False

    def react(self, status_id: str, emoji: Optional[str] = None) -> bool:
        """リアクション (Hollo等の絵文字リアクションを試行し、不可ならfavourite)"""
        if emoji:
            try:
                url = f"{self.base_url}/api/v1/statuses/{status_id}/emoji_reactions/{emoji}"
                res = self.session.put(url, timeout=5)
                if res.status_code in (200, 201, 204):
                    return True
            except Exception:
                pass
        return self.favourite(status_id)

    def get_status(self, status_id: str) -> Optional[Dict[str, Any]]:
        """特定のステータスを取得"""
        url = f"{self.base_url}/api/v1/statuses/{status_id}"
        try:
            res = self.session.get(url, timeout=10)
            if res.status_code == 200:
                return res.json()
        except Exception as e:
            print(f"[MastodonClient] Error fetching status {status_id}: {e}")
        return None

    def get_context(self, status_id: str) -> Dict[str, List[Dict[str, Any]]]:
        """会話のコンテキスト（親・祖先投稿および子投稿）を取得"""
        url = f"{self.base_url}/api/v1/statuses/{status_id}/context"
        try:
            res = self.session.get(url, timeout=10)
            if res.status_code == 200:
                return res.json()
        except Exception as e:
            print(f"[MastodonClient] Error fetching context for {status_id}: {e}")
        return {"ancestors": [], "descendants": []}

    def get_notifications(self, since_id: Optional[str] = None, limit: int = 20) -> List[Dict[str, Any]]:
        """通知（メンション等）を取得"""
        url = f"{self.base_url}/api/v1/notifications"
        params = {"limit": limit}
        if since_id:
            params["since_id"] = str(since_id)
        try:
            res = self.session.get(url, params=params, timeout=10)
            if res.status_code == 200:
                return res.json()
        except Exception as e:
            print(f"[MastodonClient] Error fetching notifications: {e}")
        return []

    def get_home_timeline(self, since_id: Optional[str] = None, limit: int = 20) -> List[Dict[str, Any]]:
        """ホームタイムラインを取得"""
        url = f"{self.base_url}/api/v1/timelines/home"
        params = {"limit": limit}
        if since_id:
            params["since_id"] = str(since_id)
        try:
            res = self.session.get(url, params=params, timeout=10)
            if res.status_code == 200:
                return res.json()
        except Exception as e:
            print(f"[MastodonClient] Error fetching home timeline: {e}")
        return []

    def get_public_timeline(self, local: bool = True, since_id: Optional[str] = None, limit: int = 20) -> List[Dict[str, Any]]:
        """パブリック/ローカルタイムラインを取得"""
        url = f"{self.base_url}/api/v1/timelines/public"
        params = {"limit": limit}
        if local:
            params["local"] = "true"
        if since_id:
            params["since_id"] = str(since_id)
        try:
            res = self.session.get(url, params=params, timeout=10)
            if res.status_code == 200:
                return res.json()
        except Exception as e:
            print(f"[MastodonClient] Error fetching public timeline: {e}")
        return []

    def search_user(self, username: str) -> Optional[Dict[str, Any]]:
        """ユーザーを検索して解決"""
        url = f"{self.base_url}/api/v1/accounts/search"
        params = {"q": username, "limit": 1, "resolve": "true"}
        try:
            res = self.session.get(url, params=params, timeout=10)
            if res.status_code == 200:
                results = res.json()
                if results and len(results) > 0:
                    return results[0]
        except Exception as e:
            print(f"[MastodonClient] Error searching user {username}: {e}")
        return None

    def follow_account(self, account_id: str) -> bool:
        """指定アカウントをフォロー（フォロバ）する"""
        url = f"{self.base_url}/api/v1/accounts/{account_id}/follow"
        try:
            res = self.session.post(url, json={"reblogs": True}, timeout=10)
            if res.status_code not in (200, 201):
                res = self.session.post(url, data={"reblogs": "true"}, timeout=10)
            if res.status_code in (200, 201):
                print(f"[MastodonClient] Successfully followed account {account_id}")
                return True
            else:
                print(f"[MastodonClient] Failed to follow account {account_id}: Status {res.status_code}, Body: {res.text}")
        except Exception as e:
            print(f"[MastodonClient] Exception following account {account_id}: {e}")
        return False

    def authorize_follow_request(self, account_id: str) -> bool:
        """フォローリクエストを承認する（鍵垢の場合）"""
        url = f"{self.base_url}/api/v1/follow_requests/{account_id}/authorize"
        try:
            res = self.session.post(url, json={}, timeout=10)
            if res.status_code in (200, 201):
                print(f"[MastodonClient] Successfully authorized follow request from {account_id}")
                return True
        except Exception as e:
            print(f"[MastodonClient] Exception authorizing follow request {account_id}: {e}")
        return False

    def get_followers(self, account_id: Optional[str] = None, limit: int = 80) -> List[Dict[str, Any]]:
        """フォロワー一覧を取得"""
        aid = account_id
        if not aid and self._me:
            aid = str(self._me.get("id"))
        if not aid:
            try:
                aid = str(self.get_me().get("id"))
            except Exception:
                return []
        url = f"{self.base_url}/api/v1/accounts/{aid}/followers"
        try:
            res = self.session.get(url, params={"limit": limit}, timeout=10)
            if res.status_code == 200:
                return res.json()
        except Exception as e:
            print(f"[MastodonClient] Error fetching followers: {e}")
        return []

    def get_relationships(self, account_ids: List[str]) -> Dict[str, Dict[str, Any]]:
        """複数アカウントとのフォロー関係を取得"""
        if not account_ids:
            return {}
        url = f"{self.base_url}/api/v1/accounts/relationships"
        params = [("id[]", str(aid)) for aid in account_ids]
        try:
            res = self.session.get(url, params=params, timeout=10)
            if res.status_code == 200:
                data = res.json()
                return {str(item["id"]): item for item in data}
        except Exception as e:
            print(f"[MastodonClient] Error fetching relationships: {e}")
        return {}

    def auto_follow_back(self) -> int:
        """自分をフォローしているが、まだ自分がフォローバックしていないユーザーを自動フォロー"""
        my_info = self.get_me()
        my_id = str(my_info.get("id"))
        followers = self.get_followers(my_id, limit=80)
        if not followers:
            return 0
        
        target_ids = [str(f["id"]) for f in followers if str(f["id"]) != my_id]
        if not target_ids:
            return 0

        relationships = self.get_relationships(target_ids)
        followed_count = 0
        for uid in target_ids:
            rel = relationships.get(uid)
            if not rel or not rel.get("following"):
                print(f"[MastodonClient] Auto-followback: following account {uid}...")
                if self.follow_account(uid):
                    followed_count += 1
        return followed_count

