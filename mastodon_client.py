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
        server = server.strip().strip("'\"")
        if not server.startswith(("http://", "https://")):
            server = "https://" + server
        self.base_url = server.rstrip("/")
        
        token = token.strip().strip("'\"") if token else ""
        if token.lower().startswith("bearer "):
            token = token[7:].strip()
        self.token = token
        
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
        if res.status_code == 401:
            masked_token = (self.token[:6] + "..." + self.token[-4:]) if len(self.token) > 10 else "***"
            raise requests.exceptions.HTTPError(
                f"\n============================================================\n"
                f"【認証エラー 401 Unauthorized】\n"
                f"サーバー: {url}\n"
                f"現在のTOKEN: {masked_token}\n\n"
                f"【考えられる主な原因】\n"
                f"1. Misskey時代のトークンをそのまま使っている（Mastodon/Holloでは使えません）\n"
                f"2. ブラウザ承認後に画面に出た『認証コード（code）』を .env に貼り付けている\n"
                f"   ※ 画面に出る文字列は一時的な認証コードであり、アクセストークン本体ではありません。\n"
                f"   ※ 'python get_token.py' を実行し、ターミナル上でコードを入力すると正式な TOKEN が発行されます。\n"
                f"3. トークンの指定ミスまたは無効化\n\n"
                f"【解決策】\n"
                f"ターミナルで 'python get_token.py' を実行して、正式なアクセストークン（TOKEN）を発行してください。\n"
                f"============================================================",
                response=res
            )
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
        """リアクション (Hollo等の絵文字リアクションを試行。emoji指定時はfavouriteとの二重リアクションを防止)"""
        if emoji:
            try:
                # 1. Akkoma / Pleroma / Hollo形式 (PUT)
                url = f"{self.base_url}/api/v1/statuses/{status_id}/emoji_reactions/{emoji}"
                res = self.session.put(url, timeout=5)
                if res.status_code in (200, 201, 204):
                    return True
            except Exception:
                pass

            try:
                # 2. Misskey形式 (POST)
                url_mk = f"{self.base_url}/api/notes/reactions/create"
                res_mk = self.session.post(url_mk, json={"noteId": str(status_id), "reaction": emoji}, timeout=5)
                if res_mk.status_code in (200, 201, 204):
                    return True
            except Exception:
                pass

            # 絵文字指定時は、絵文字と星の二重リアクション付加を防ぐためfavouriteへのフォールバックを行わない
            return False
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
                data = res.json()
                if isinstance(data, dict) and "ancestors" in data:
                    if len(data.get("ancestors", [])) > 0:
                        return data
                    # ancestorsが空でも、直近親の有無を確認
                    curr_st = self.get_status(status_id)
                    if not (curr_st and curr_st.get("in_reply_to_id")):
                        return data
        except Exception as e:
            print(f"[MastodonClient] Error fetching context for {status_id}: {e}")
        
        # フォールバック: in_reply_to_id を手動で遡る
        ancestors = []
        curr_id = status_id
        depth = 0
        while curr_id and depth < 12:
            st = self.get_status(curr_id)
            if not st:
                break
            parent_id = st.get("in_reply_to_id")
            if not parent_id:
                break
            parent_st = self.get_status(str(parent_id))
            if not parent_st:
                break
            ancestors.insert(0, parent_st)
            curr_id = str(parent_id)
            depth += 1

        return {"ancestors": ancestors, "descendants": []}

    def is_mentioned(self, status: Dict[str, Any], my_id: Optional[str] = None, my_username: Optional[str] = None, note_text: Optional[str] = None) -> bool:
        """アカウントがこのステータス内でメンションされているかを高精度判定"""
        u_lower = (my_username or "").lower().strip()
        mid = str(my_id).strip() if my_id else ""
        
        # 1. mentions リスト判定
        for m in status.get("mentions", []):
            if mid and str(m.get("id")) == mid:
                return True
            if u_lower:
                m_user = m.get("username", "").lower().strip()
                m_acct = m.get("acct", "").lower().strip().split("@")[0]
                if m_user == u_lower or m_acct == u_lower:
                    return True
        
        # 2. 返信先アカウント判定
        if mid and str(status.get("in_reply_to_account_id")) == mid:
            return True
            
        # 3. 本文中のユーザー名判定
        txt = (note_text if note_text is not None else self.html_to_text(status.get("content", ""))).lower()
        if u_lower:
            if f"@{u_lower}" in txt or u_lower in txt:
                return True
                
        return False

    # --- Misskey 互換レイヤー ---
    def notes_show(self, note_id: str) -> Dict[str, Any]:
        """Misskey互換: notes/show"""
        st = self.get_status(note_id) or {}
        acc = st.get("account", {})
        mentions = st.get("mentions", [])
        return {
            "id": str(st.get("id", note_id)),
            "userId": str(acc.get("id", "")),
            "user": {
                "id": str(acc.get("id", "")),
                "username": acc.get("username", ""),
                "name": acc.get("display_name") or acc.get("username", "")
            },
            "text": self.html_to_text(st.get("content", "")),
            "replyId": st.get("in_reply_to_id"),
            "mentions": [str(m.get("id")) for m in mentions]
        }

    def notes_create(self, text: str, reply_id: Optional[str] = None, visibility: Any = "public", file_ids: Optional[List[str]] = None, **kwargs) -> Dict[str, Any]:
        """Misskey互換: notes/create"""
        vis_str = "public"
        if visibility:
            v = str(visibility).lower()
            if "home" in v or "unlisted" in v:
                vis_str = "unlisted"
            elif "followers" in v or "private" in v:
                vis_str = "private"
            elif "specified" in v or "direct" in v:
                vis_str = "direct"
        return self.post_status(text=text, in_reply_to_id=reply_id, visibility=vis_str, media_ids=file_ids)

    def drive_files_create(self, file_obj) -> Dict[str, Any]:
        """Misskey互換: drive/files/create"""
        if hasattr(file_obj, "name") and os.path.exists(file_obj.name):
            mid = self.upload_media(file_obj.name)
            return {"id": mid or ""}
        elif hasattr(file_obj, "read"):
            with tempfile.NamedTemporaryFile("wb", delete=False) as tf:
                tf.write(file_obj.read())
                tmp_name = tf.name
            try:
                mid = self.upload_media(tmp_name)
                return {"id": mid or ""}
            finally:
                if os.path.exists(tmp_name):
                    os.remove(tmp_name)
        return {"id": ""}

    def notes_reactions_create(self, note_id: str, reaction: str = "👍", **kwargs):
        """Misskey互換: notes/reactions/create"""
        return self.react(note_id, emoji=reaction)

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


class NoteVisibility:
    PUBLIC = "public"
    HOME = "unlisted"
    FOLLOWERS = "private"
    SPECIFIED = "direct"


