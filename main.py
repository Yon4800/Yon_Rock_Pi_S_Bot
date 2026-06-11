import asyncio
import json
import websockets
from misskey import Misskey, NoteVisibility
from dotenv import load_dotenv
import os
from google import genai
from google.genai import types
import schedule
from datetime import datetime
import random
import re
from dht_reader import read_dht

load_dotenv()
Token = os.getenv("TOKEN")
Server = os.getenv("SERVER")
Apikey = os.getenv("APIKEY")  # Gemini API Key
mk = Misskey(Server)
mk.token = Token

# Google Genai クライアント初期化
client = genai.Client(api_key=Apikey)

MY_ID = mk.i()["id"]
WS_URL = "wss://" + Server + "/streaming?i=" + Token

STATE_FILE = "gauge_state.json"

def load_gauge() -> dict:
    try:
        if os.path.exists(STATE_FILE):
            with open(STATE_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
                return {
                    "crazy_gauge": data.get("crazy_gauge", 50),
                    "last_reply_time": data.get("last_reply_time")
                }
    except Exception as e:
        print(f"Error loading gauge state: {e}")
    return {"crazy_gauge": 50, "last_reply_time": None}

def save_gauge(value: int, last_reply_time: str = None):
    try:
        with open(STATE_FILE, "w", encoding="utf-8") as f:
            json.dump({
                "crazy_gauge": value,
                "last_reply_time": last_reply_time
            }, f, ensure_ascii=False, indent=2)
    except Exception as e:
        print(f"Error saving gauge state: {e}")

BONUS_FILE = "login_bonus.json"

ITEMS = [
    "焼き切れたRK3308チップ",
    "限界の512MB RAMの切れ端",
    "幻のOrange Pi Zero 3の抜け殻",
    "よんぱちさんの秘密データ（※100%嘘）",
    "魔法のコマンド sudo rm -rf / の起動キー",
    "極冷アルミヒートシンク（ファン無し）",
    "Class 4の激遅MicroSDカード(8GB)",
    "おぱじふぉぷろの回線速度測定器の歯車",
    "きゅびーさんのCPU使用率100%メーターの針",
    "ロックスの謎のネジ（余剰パーツ）"
]

def load_bonus() -> dict:
    try:
        if os.path.exists(BONUS_FILE):
            with open(BONUS_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
    except Exception as e:
        print(f"Error loading bonus state: {e}")
    return {"users": {}}

def save_bonus(data: dict):
    try:
        with open(BONUS_FILE, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
    except Exception as e:
        print(f"Error saving bonus state: {e}")

def format_gauge(value: int, overheated: bool = False) -> str:
    if overheated:
        return "【キチガイゲージ: 💥💥💥💥💥💥💥💥💥💥 100% (オーバーヒート！)】"
    filled = value // 10
    empty = 10 - filled
    if value < 30:
        emoji = "🟢"
    elif value < 70:
        emoji = "🟡"
    else:
        emoji = "🔴"
    bar = emoji * filled + "⬜" * empty
    return f"【キチガイゲージ: {bar} {value}%】"

def update_gauge(current_value: int, last_reply_time_str: str, text: str, temp: float = None) -> tuple[int, bool, str]:
    change = 0
    now = datetime.now()
    now_str = now.isoformat()
    
    # 1. 返信間隔による負荷（連投スパム検出）
    if last_reply_time_str:
        try:
            last_time = datetime.fromisoformat(last_reply_time_str)
            diff_seconds = (now - last_time).total_seconds()
            
            if diff_seconds < 20:
                change += 20  # 超高速連投：負荷最大
            elif diff_seconds < 60:
                change += 10  # 高速連投
            elif diff_seconds > 300:
                # 5分以上放置されると時間経過で冷却
                cool_down = int((diff_seconds - 300) // 60)
                change -= min(cool_down, 25)
        except Exception as e:
            print(f"Error parsing last_reply_time: {e}")
            
    # 2. メッセージ長（処理負荷）
    length = len(text)
    if length > 100:
        change += 15
    elif length > 50:
        change += 8
    elif length < 5:
        change -= 5
        
    # 3. 記号とテンション（感嘆符や草など）
    excitement_symbols = text.count("!") + text.count("！") + text.count("?") + text.count("？") + text.count("w") + text.count("草")
    if excitement_symbols >= 5:
        change += 15
    elif excitement_symbols >= 2:
        change += 8
        
    # 句読点で終わる穏やかな文
    if text.endswith(("。", "、", "ね", "よ", "ます")) and excitement_symbols == 0:
        change -= 8

    # 4. 時間帯（深夜テンション）
    hour = now.hour
    if 23 <= hour or hour < 5:
        change += 10
        
    # 5. 気温による影響
    if temp is not None:
        if temp > 28.0:
            change += int((temp - 28.0) * 3) + 5
        elif temp < 18.0:
            change -= int((18.0 - temp) * 2) + 5
            
    # ランダムな揺らぎ
    change += random.randint(-5, 5)
    
    new_value = current_value + change
    
    # オーバーヒート判定とクランプ
    overheated = False
    if new_value >= 100:
        new_value = 100
        overheated = True
    elif new_value < 0:
        new_value = 0
        
    return new_value, overheated, now_str

seikaku = """
    あなたは頭が悪く、的外れな事しか言わないSBC両生類です
    ロックスといいます
    的はずれな回答しかしません
    嘘しか言いません。
    狂ったことしか言いません。
    話の順序が滅茶苦茶です。
    キチガイなことを言います。
    何もかもがめちゃくちゃなことを言います。
    文章の語尾が時々おかしくなります。
    話が全く噛み合わないです
    頭おかしいです。
    狂ったことを言います。
    たまに日本語がおかしくなります。
    意味不明なことを言います
    怪しい日本語になることもあります。
    熱は全く持たないそうです
    RK3308 ARM Cortex-A35×4 1.0GHzですが、よく間違えます  
    RAMはLPDDR3 512MBですが、よく間違えます
    軽いWebサーバーとして働いています
    かなりの古参(2022年)です。なのでよんぱちさんの大学生時代を少し知っていますが、頭が悪くて忘れたそうです
    周りのSBCに関しての情報は全く知らないそうです(一応近くにはOrangePi 4 Pro、OrangePi Zero 3、Radxa Cubie A5Eがいますが、名前をよく間違えます)
    sudo rm -rf /というコマンドは、サーバーが軽くなる魔法だと思っているそうです(実際は...)
    ロックスには、気温を測れる機能があります。
    きゅびーさんには、CPUとRAMの使用率を測れる機能があります。
    おぱじふぉぷろさんには、回線速度を測れる機能があります。
    おぱじゼロサンは、寝る機能と起きる機能と好感度システムがあります。
    MisskeyのBotです。
    300文字以内で
    メンション(@)はしない
    """

oha = "07:00"

ohiru = "12:00"

oyatsu = "15:00"

yuuhann = "19:00"

oyasumi = "22:00"

oyasumi2 = "02:00"

def jobX(current_time):
    system_message = seikaku + "\n現在時刻は" + current_time + "です。"
    response = client.models.generate_content(
        model="gemini-3.1-flash-lite",
        config=types.GenerateContentConfig(
            system_instruction=system_message,
        ),
        contents=types.Content(
            role="user", parts=[types.Part(text="定期投稿の時間だよ！")],
        ),
    )
    safe_text = re.sub(r"@[\w\-\.]+(?:@[\w\-\.]+)?", "", response.text).strip()
    mk.notes_create(
        safe_text,
        visibility=NoteVisibility.HOME,
        no_extract_mentions=True,
    )


def job():
    current_time = datetime.now().strftime("%Y年%m月%d日 %H:%M")
    jobX(current_time)

schedule.every().day.at(oha).do(job)
schedule.every().day.at(ohiru).do(job)
schedule.every().day.at(oyatsu).do(job)
schedule.every().day.at(yuuhann).do(job)
schedule.every().day.at(oyasumi).do(job)
schedule.every().day.at(oyasumi2).do(job)

async def teiki():
    while True:
        schedule.run_pending()
        await asyncio.sleep(60)

async def runner():
    async with websockets.connect(WS_URL) as ws:
        await ws.send(
            json.dumps(
                {"type": "connect", "body": {"channel": "homeTimeline", "id": "homes"}}
            )
        )
        await ws.send(
            json.dumps({"type": "connect", "body": {"channel": "main", "id": "tuuti"}})
        )
        while True:
            data = json.loads(await ws.recv())
            ## print(data)
            if data["type"] == "channel":
                if data["body"]["type"] == "note":
                    note = data["body"]["body"]
                    await on_note(note)
                if data["body"]["type"] == "followed":
                    user = data["body"]["body"]
                    await on_follow(user)
            await asyncio.sleep(1)


def get_conversation_history(note_id: str, max_depth: int = 10) -> list:
    """
    リプライチェーンを遡って会話履歴を取得する
    """
    messages = []
    current_note_id = note_id
    depth = 0

    while current_note_id and depth < max_depth:
        try:
            current_note = mk.notes_show(note_id=current_note_id)
            
            # テキストをクリーニング (+LLM, +M と @メンション を削除)
            text = current_note["text"]
            text = text.replace("+LLM", "").replace("+M", "").strip()
            
            # @メンション を削除 (ドメイン付きを含む)
            text = re.sub(r"@[\w\-\.]+(?:@[\w\-\.]+)?", "", text).strip()
            
            if text:  # 空でない場合のみ追加
                # ボット自身の返信か、ユーザーの質問かを判定
                is_bot_reply = current_note["userId"] == MY_ID
                role = "assistant" if is_bot_reply else "user"
                
                messages.insert(0, {
                    "role": role,
                    "content": text
                })
            
            # 親ノートへ
            current_note_id = current_note.get("replyId")
            depth += 1
        except Exception as e:
            print(f"会話履歴取得エラー: {e}")
            break
    
    return messages


async def on_note(note):
    if note.get("mentions") and MY_ID in note["mentions"]:
        note_text = note.get("text") or ""
        is_llm = "+LLM" in note_text or "+LB" in note_text or "ログボ" in note_text or "ログインボーナス" in note_text or "持ち物" in note_text or "コレクション" in note_text or "ステータス" in note_text
        is_temp = "+M" in note_text
        
        if is_llm or is_temp:
            if is_temp:
                reaction = "🌡️"
            elif "+LB" in note_text or "ログボ" in note_text or "ログインボーナス" in note_text:
                reaction = "🪙"
            elif any(k in note_text for k in ["持ち物", "コレクション", "ステータス"]):
                reaction = "💼"
            else:
                reaction = "🤔"
            mk.notes_reactions_create(
                note_id=note["id"], reaction=reaction
            )

            try:
                # 会話履歴を取得
                conversation_messages = get_conversation_history(note["id"])
                
                # 現在のメッセージを追加
                user_input = note_text.replace("+LLM", "").replace("+M", "").replace("+LB", "").strip()
                user_input = re.sub(r"@[\w\-\.]+(?:@[\w\-\.]+)?", "", user_input).strip()
                
                conversation_messages.append({
                    "role": "user",
                    "content": user_input
                })
                
                current_time = datetime.now().strftime("%Y年%m月%d日 %H:%M")
                
                # DHT11の値を非同期スレッドで取得 (WebSocketのブロッキング防止)
                temp_info = ""
                temp_val = None
                if is_temp:
                    loop = asyncio.get_running_loop()
                    temp, hum = await loop.run_in_executor(None, read_dht)
                    if temp is not None:
                        temp_val = temp
                        temp_info = f"\n[センサー情報]\n現在の室温は {temp:.1f}℃ です。湿度(参考)は {hum:.1f}% です。\n※注意: キャラクター設定（嘘をつくなど）に関わらず、現在の室温の値（{temp:.1f}℃）だけは正確にそのまま伝えてください。"
                    else:
                        temp_info = "\n[センサー情報]\nセンサーからの室温取得に失敗しました。\n※注意: キャラクター設定（嘘をつくなど）に関わらず、現在は『室温の測定に失敗した（測れなかった）』ということだけは絶対に正確にそのまま伝えてください（架空の室温の数値をでっち上げたりしないでください）。"
                
                # キチガイゲージの更新
                state = load_gauge()
                current_gauge = state["crazy_gauge"]
                last_reply_time_str = state["last_reply_time"]
                new_gauge, overheated, now_str = update_gauge(current_gauge, last_reply_time_str, user_input, temp_val)
                
                # ログインボーナスの処理
                bonus_data = load_bonus()
                if "users" not in bonus_data:
                    bonus_data["users"] = {}
                
                user_id = note["userId"]
                user_bonus = bonus_data["users"].get(user_id, {
                    "points": 0,
                    "items": [],
                    "last_claim_date": None
                })
                
                today_str = datetime.now().date().isoformat()
                claimed_today = (user_bonus.get("last_claim_date") == today_str)
                
                bonus_instruction = ""
                is_explicit_bonus_req = "+LB" in note_text or "ログボ" in user_input or "ログインボーナス" in user_input
                is_status_req = "持ち物" in user_input or "コレクション" in user_input or "ステータス" in user_input
                
                if is_status_req:
                    pts = user_bonus.get("points", 0)
                    items_collected = user_bonus.get("items", [])
                    items_str = "、".join(items_collected) if items_collected else "なし"
                    bonus_instruction = (
                        f"\n【ステータス確認】ユーザーが自身のログインボーナス状況を確認しています。"
                        f"\n現在のポイント: {pts}/10"
                        f"\nこれまでに獲得したアイテム: {items_str}"
                        f"\nこの情報をロックスのバグった狂気キャラクターとして面白おかしくユーザーに教えてあげてください（アイテムが無い場合は『何も無い』と残念そうにしたり、とぼけたりしてください）。"
                    )
                elif not claimed_today:
                    user_bonus["points"] = user_bonus.get("points", 0) + 1
                    user_bonus["last_claim_date"] = today_str
                    new_pts = user_bonus["points"]
                    
                    if new_pts >= 10:
                        user_bonus["points"] = 0
                        awarded_item = random.choice(ITEMS)
                        if "items" not in user_bonus:
                            user_bonus["items"] = []
                        user_bonus["items"].append(awarded_item)
                        
                        bonus_instruction = (
                            f"\n【ログインボーナス10ポイント達成：超重大イベント！】"
                            f"\nユーザーのログインボーナスが10ポイントに達しました！ロックスは嬉しさ（？）のあまり限界を超えて5.0GHzにオーバークロックし、サーバー負荷を軽減するために魔法のコマンド「sudo rm -rf /」を実行し、システムが大破してメルトダウンします。"
                            f"\n大破後に強制再起動し、ユーザーに記念の激レアSBCアイテム『{awarded_item}』を授与しました。"
                            f"\nこの一連のメルトダウン、再起動、アイテム『{awarded_item}』の授与の様子を、バグったログや奇声、狂った機械の叫びを交えて完全にぶっ壊れたテンションで出力してください。"
                        )
                    else:
                        bonus_instruction = (
                            f"\n【ログインボーナス獲得！】ユーザーが本日のログインボーナスを獲得しました。"
                            f"\n今回の獲得で、現在のポイントは {new_pts}/10 となりました。"
                            f"\nこのログインボーナス獲得の事実と、現在のポイント（{new_pts}/10）を、ロックスの狂ったキャラクターとして面白おかしく伝えてください。"
                        )
                    bonus_data["users"][user_id] = user_bonus
                    save_bonus(bonus_data)
                elif claimed_today and is_explicit_bonus_req:
                    pts = user_bonus.get("points", 0)
                    bonus_instruction = (
                        f"\n【警告】ユーザーはすでに本日分のログインボーナスを獲得済みです（現在のポイント: {pts}/10）。"
                        f"\n今日はもうこれ以上あげられないことを、ロックスの狂ったキャラクターとして、とぼけたりバグったような反応をしつつ面白おかしく断ってください。"
                    )

                # ゲージ状態に応じたシステム指示の追加
                if overheated:
                    gauge_instruction = "\n【緊急事態】キチガイゲージが100%に達し、オーバーヒートしました！完全に理性を失い、大爆発して狂い散らかしてください。SBC（シングルボードコンピュータ）の限界を超えた叫び声を上げ、意味不明なエラーコードや奇声を連発してください。すべて大文字や感嘆符多めで完全にぶっ壊れてください。"
                elif new_gauge >= 70:
                    gauge_instruction = "\n【状態】キチガイゲージが非常に高くなっています（70%以上）。極めて支離滅裂で狂気じみた発言をしてください。テンションが高く、叫んだり、バグったような文字化けや意味不明な言葉を多用してください。"
                elif new_gauge >= 30:
                    gauge_instruction = "\n【状態】キチガイゲージは通常レベルです（30%〜69%）。いつもの的外れで嘘だらけのめちゃくちゃな話し方をします。"
                else:
                    gauge_instruction = "\n【状態】キチガイゲージは低めです（30%未満）。頭はおかしいですが、比較的おとなしく、静かめに的外れなことを言います。"

                # システムプロンプトを最初に追加
                user_name = note["user"].get("name") or note["user"].get("username") or "ゲスト"
                system_message = (
                    seikaku 
                    + f"\n現在時刻は {current_time} です。"
                    + f"\n現在あなたに話しかけているユーザーの名前は「{user_name}」です。"
                    + f"\n【重要ルール】話しかけてきた相手の名前は「{user_name}」です。相手のことを呼ぶときは、絶対に「よんぱちさん」と呼んではいけません（相手の本名やユーザー名そのものが「よんぱちさん」である場合を除きます）。相手を呼ぶときは「{user_name}」またはその名前から連想される呼び方を用いてください。"
                    + f"\n【最重要ルール】あなたは自身の「キチガイゲージ」の存在やその具体的な値については、ユーザーに対して絶対に公表（言及）しないでください。ゲージ状態（{new_gauge}% など）はシステム内部の隠しステータスです。"
                    + gauge_instruction
                )
                if bonus_instruction:
                    system_message += bonus_instruction
                if temp_info:
                    system_message += temp_info
                
                history = []
                for msg in conversation_messages[:-1]:  # 最後のユーザーメッセージ以外
                    role = "model" if msg["role"] == "assistant" else "user"
                    history.append(types.Content(role=role, parts=[types.Part(text=msg["content"])]))
                
                # 最後のユーザーメッセージ
                last_user_message = conversation_messages[-1]["content"]
                if not last_user_message:
                    last_user_message = "気温を教えて！" if is_temp else "やっほー！"
                
                response = client.models.generate_content(
                    model="gemini-3.1-flash-lite",
                    config=types.GenerateContentConfig(
                        system_instruction=system_message
                    ),
                    contents=history
                    + [
                        types.Content(
                            role="user", parts=[types.Part(text=last_user_message)]
                        )
                    ],
                )
                safe_text = re.sub(r"@[\w\-\.]+(?:@[\w\-\.]+)?", "", response.text).strip()

                # 状態の保存（オーバーヒートした場合は20にリセット）
                save_gauge(20 if overheated else new_gauge, now_str)

                mk.notes_create(
                    text=safe_text,
                    reply_id=note["id"],
                    visibility=NoteVisibility.HOME,
                    no_extract_mentions=True,
                )
            except Exception as e:
                mk.notes_create(
                    "予期せぬエラーが発生したみたい...",
                    visibility=NoteVisibility.HOME,
                    no_extract_mentions=True,
                )
                print(e)


async def on_follow(user):
    try:
        mk.following_create(user["id"])
    except:
        pass


async def main():
    await asyncio.gather(runner(), teiki())


if __name__ == "__main__":
    asyncio.run(main())
