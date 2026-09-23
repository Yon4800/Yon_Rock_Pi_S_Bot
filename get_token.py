"""
Hollo / Mastodon アクセストークン取得スクリプト
実行方法: python get_token.py
"""

import sys
import json
import urllib.parse
try:
    import requests
except ImportError:
    print("エラー: requests ライブラリが必要です。'pip install requests' を実行してください。")
    sys.exit(1)

def main():
    print("=" * 60)
    print("  Hollo / Mastodon Bot用アクセストークン取得ツール")
    print("=" * 60)
    
    server_input = input("\n1. HolloサーバーのドメインまたはURLを入力してください\n(例: hollo.example.com または https://hollo.example.com): ").strip()
    if not server_input:
        print("サーバーが指定されませんでした。終了します。")
        return

    if not server_input.startswith(("http://", "https://")):
        server_url = "https://" + server_input.rstrip("/")
    else:
        server_url = server_input.rstrip("/")

    client_name = input("\n2. アプリ名/Bot名を入力してください (デフォルト: SBCBot): ").strip() or "SBCBot"

    # Step 1: クライアント登録 (/api/v1/apps)
    print(f"\n[{server_url}] にアプリケーションを登録中...")
    apps_url = f"{server_url}/api/v1/apps"
    payload = {
        "client_name": client_name,
        "redirect_uris": "urn:ietf:wg:oauth:2.0:oob",
        "scopes": "read write follow push",
        "website": "https://github.com/Yon4800"
    }

    try:
        res = requests.post(apps_url, json=payload, timeout=15)
        if res.status_code not in (200, 201):
            print(f"エラー: アプリ登録に失敗しました (Status: {res.status_code})")
            print(res.text)
            return
        app_data = res.json()
    except Exception as e:
        print(f"エラー: サーバーとの通信に失敗しました: {e}")
        return

    client_id = app_data.get("client_id")
    client_secret = app_data.get("client_secret")

    if not client_id or not client_secret:
        print("エラー: client_id または client_secret の取得に失敗しました。")
        return

    # Step 2: 認可URLの生成
    params = {
        "client_id": client_id,
        "redirect_uri": "urn:ietf:wg:oauth:2.0:oob",
        "response_type": "code",
        "scope": "read write follow push"
    }
    auth_url = f"{server_url}/oauth/authorize?{urllib.parse.urlencode(params)}"

    print("\n" + "-" * 60)
    print("【認証手順】")
    print("以下のURLをブラウザで開いて、Holloにログインし、「承認（Authorize）」をクリックしてください:\n")
    print(auth_url)
    print("-" * 60)

    auth_code = input("\n承認後に画面に表示された「認証コード（Authorization code）」をここに貼り付けてEnterを押してください:\n> ").strip()
    if not auth_code:
        print("認証コードが入力されませんでした。")
        return

    # Step 3: トークンの交換 (/oauth/token)
    token_url = f"{server_url}/oauth/token"
    token_payload = {
        "client_id": client_id,
        "client_secret": client_secret,
        "grant_type": "authorization_code",
        "code": auth_code,
        "redirect_uri": "urn:ietf:wg:oauth:2.0:oob",
        "scope": "read write follow push"
    }

    try:
        # Mastodon OAuth仕様: application/x-www-form-urlencoded
        t_res = requests.post(token_url, data=token_payload, timeout=15)
        if t_res.status_code not in (200, 201):
            # JSON形式でも試行
            t_res = requests.post(token_url, json=token_payload, timeout=15)
        
        if t_res.status_code not in (200, 201):
            print(f"\nエラー: トークン取得に失敗しました (Status: {t_res.status_code})")
            print(f"レスポンス: {t_res.text}")
            print("\n認証コード（code）が間違っているか、有効期限が切れた可能性があります。最初からやり直してください。")
            return
        
        token_data = t_res.json()
        access_token = token_data.get("access_token")
    except Exception as e:
        print(f"エラー: トークン交換中に例外が発生しました: {e}")
        return

    if not access_token:
        print("エラー: access_token が取得できませんでした。")
        return

    print("\n" + "=" * 60)
    print("🎉 アクセストークン（TOKEN）の取得に成功しました！")
    print("=" * 60)
    print(f"\nTOKEN={access_token}\n")
    print("------------------------------------------------------------")
    print("【設定方法】")
    print("各Botの .env ファイルに以下のように記述してください：\n")
    print(f"SERVER={server_url}")
    print(f"TOKEN={access_token}")
    print("=" * 60)

    # 既存の .env ファイルを更新するか質問
    bot_folders = ["Cubie_A5E_San_Bot", "OrangePi_4_Pro_Bot", "opizero3_llm", "Yon_Rock_Pi_S_Bot"]
    auto_save = input("\n全Botの .env にこのトークンとサーバーURLを自動保存しますか？ (y/N): ").strip().lower()
    if auto_save == "y":
        root_dir = os.path.dirname(os.path.abspath(__file__))
        for b_folder in bot_folders:
            b_path = os.path.join(root_dir, b_folder)
            if os.path.exists(b_path):
                env_file = os.path.join(b_path, ".env")
                example_file = os.path.join(b_path, "env.example")
                
                # 既存の.envまたはenv.exampleをベースにする
                lines = []
                if os.path.exists(env_file):
                    with open(env_file, "r", encoding="utf-8") as f:
                        lines = f.readlines()
                elif os.path.exists(example_file):
                    with open(example_file, "r", encoding="utf-8") as f:
                        lines = f.readlines()
                else:
                    lines = ["SERVER=\n", "TOKEN=\n", "APIKEY=\n"]
                
                new_lines = []
                server_set = False
                token_set = False
                for line in lines:
                    if line.startswith("SERVER="):
                        new_lines.append(f"SERVER={server_url}\n")
                        server_set = True
                    elif line.startswith("TOKEN="):
                        new_lines.append(f"TOKEN={access_token}\n")
                        token_set = True
                    else:
                        new_lines.append(line)
                if not server_set:
                    new_lines.insert(0, f"SERVER={server_url}\n")
                if not token_set:
                    new_lines.insert(1, f"TOKEN={access_token}\n")
                
                with open(env_file, "w", encoding="utf-8") as f:
                    f.writelines(new_lines)
                print(f"-> {env_file} を更新しました。")
        print("\n全Botの .env 更新が完了しました！")

if __name__ == "__main__":
    main()
