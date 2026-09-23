import os
import sys
from dotenv import load_dotenv
from mastodon_client import MastodonClient

def main():
    print("=" * 60)
    print("🤖 SBCBot Mastodon/Hollo 診断スクリプト")
    print("=" * 60)
    
    # .env の読み込み
    load_dotenv()
    server = os.getenv("SERVER")
    token = os.getenv("TOKEN")
    
    if not server or not token:
        print("❌ エラー: .env に SERVER または TOKEN が設定されていません。")
        print("  python get_token.py を実行してトークンを設定してください。")
        return

    print(f"接続先サーバー: {server}")
    masked = (token[:6] + "..." + token[-4:]) if len(token) > 10 else "***"
    print(f"トークン: {masked}")

    mc = MastodonClient(server, token)
    try:
        me = mc.get_me()
        my_id = str(me.get("id"))
        my_username = me.get("username", "")
        my_acct = me.get("acct", "")
        print(f"\n✅ 認証成功!")
        print(f"  Bot アカウント ID: {my_id}")
        print(f"  ユーザー名 (username): {my_username}")
        print(f"  アカウント識別子 (acct): {my_acct}")
    except Exception as e:
        print(f"\n❌ 認証エラー: {e}")
        return

    print("\n--- 1. 最新の通知 (Notifications) 検査 ---")
    try:
        notifs = mc.get_notifications(limit=5)
        print(f"取得できた通知数: {len(notifs)} 件")
        for i, n in enumerate(notifs, 1):
            ntype = n.get("type")
            sender = n.get("account", {}).get("acct") or n.get("account", {}).get("username")
            print(f"\n [{i}] タイプ: {ntype} | 送信者: @{sender}")
            st = n.get("status")
            if st:
                txt = MastodonClient.html_to_text(st.get("content", ""))
                is_men = mc.is_mentioned(st, my_id=my_id, my_username=my_username, note_text=txt)
                is_talk = "+TALK" in txt.upper()
                is_llm = "+LLM" in txt.upper()
                print(f"     本文: {txt[:60]}...")
                print(f"     メンション判定: {is_men} | +LLM検知: {is_llm} | +TALK検知: {is_talk}")
    except Exception as e:
        print(f"通知取得エラー: {e}")

    print("\n--- 2. ホームタイムライン (Home Timeline) 検査 ---")
    try:
        home = mc.get_home_timeline(limit=5)
        print(f"取得できたホームタイムライン投稿数: {len(home)} 件")
        for i, st in enumerate(home, 1):
            sender = st.get("account", {}).get("acct") or st.get("account", {}).get("username")
            txt = MastodonClient.html_to_text(st.get("content", ""))
            is_men = mc.is_mentioned(st, my_id=my_id, my_username=my_username, note_text=txt)
            is_talk = "+TALK" in txt.upper()
            is_llm = "+LLM" in txt.upper()
            print(f" [{i}] @{sender}: {txt[:50]}... (メンション: {is_men}, TALK: {is_talk}, LLM: {is_llm})")
    except Exception as e:
        print(f"ホームタイムライン取得エラー: {e}")

    print("\n--- 3. ローカル公開タイムライン (Public Timeline) 検査 ---")
    try:
        pub = mc.get_public_timeline(local=True, limit=5)
        print(f"取得できたローカルタイムライン投稿数: {len(pub)} 件")
        for i, st in enumerate(pub, 1):
            sender = st.get("account", {}).get("acct") or st.get("account", {}).get("username")
            txt = MastodonClient.html_to_text(st.get("content", ""))
            is_men = mc.is_mentioned(st, my_id=my_id, my_username=my_username, note_text=txt)
            is_talk = "+TALK" in txt.upper()
            is_llm = "+LLM" in txt.upper()
            print(f" [{i}] @{sender}: {txt[:50]}... (メンション: {is_men}, TALK: {is_talk}, LLM: {is_llm})")
    except Exception as e:
        print(f"ローカルタイムライン取得エラー: {e}")

    print("\n" + "=" * 60)
    print("診断が完了しました。")
    print("=" * 60)

if __name__ == "__main__":
    main()
