"""
このBotのフォロワー確認＆一括フォローバックスクリプト
実行方法: python sync_follow.py
"""

import os
import sys
from dotenv import load_dotenv
from mastodon_client import MastodonClient

def main():
    env_path = os.path.join(os.path.dirname(__file__), ".env")
    if os.path.exists(env_path):
        load_dotenv(env_path, override=True)
    else:
        load_dotenv(override=True)

    server = os.getenv("SERVER")
    token = os.getenv("TOKEN")

    if not server or not token:
        print("エラー: .env に SERVER または TOKEN が設定されていません。")
        return

    bot_name = os.path.basename(os.path.dirname(os.path.abspath(__file__)))
    print(f"[{bot_name}] サーバー: {server} に接続中...")
    try:
        mc = MastodonClient(server, token)
        me = mc.get_me()
        my_id = str(me.get("id"))
        my_username = me.get("username")
        print(f"[{bot_name}] アカウント確認: @{my_username} (ID: {my_id})")

        followers = mc.get_followers(my_id, limit=80)
        print(f"[{bot_name}] 現在のフォロワー数: {len(followers)} 人")
        if not followers:
            print(f"[{bot_name}] フォロワーがいません。")
            return

        followed_count = mc.auto_follow_back()
        print(f"[{bot_name}] 自動フォローバック完了: 新たに {followed_count} 人をフォローしました。")
    except Exception as e:
        print(f"[{bot_name}] エラー発生: {e}")

if __name__ == "__main__":
    main()
