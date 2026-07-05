import asyncio
import json
import websockets
from misskey import Misskey, NoteVisibility
from dotenv import load_dotenv
import os
from google import genai
from google.genai import types
from google.genai.types import GenerateContentConfig, Modality
import schedule
from datetime import datetime
import random
import re
import requests
from sensor_reader import read_sensors

load_dotenv()
Token = os.getenv("TOKEN")
Server = os.getenv("SERVER")
Apikey = os.getenv("APIKEY")  # Gemini API Key
mk = Misskey(Server)
mk.token = Token

# Google Genai クライアント初期化
client = genai.Client(api_key=Apikey)

MY_ID = mk.i()["id"]
MY_USERNAME = mk.i()["username"]
WS_URL = "wss://" + Server + "/streaming?i=" + Token

BOT_NAME = "Yon_Rock_Pi_S"

BOT_SUMMARIES = {
    "Cubie_A5E_San": "Radxa Cubie A5E (きゅびーさん): 小さくて省電力なシングルボードコンピュータ娘。24時間稼働の社畜で、給料（CBC）を欲しがっている。OrangePi 4 Proの生意気な性格が気に入らず、Rock Pi S of ロックスの頭の悪さに困っている。",
    "OrangePi_4_Pro": "OrangePi 4 Pro (おぱじ・フォプロ): 少し大きくて気が強く、煽ったりマウントを取ったりするSBC御局娘。科学者ぶっており、Radxa Cubie A5Eをいつもバカにしている。社畜をエリートの誇りだと思っている。",
    "opizero3_llm": "OrangePi Zero 3 (オパジゼロサン): 元気いっぱいのSBC娘。親身でオタク話が好きで、よく眠る。Cubie A5Eと仲良くしたいが寄り添ってもらえない。妹のOrangePi 4 Proを調子に乗っていてイキリで鬱陶しいと思っている。",
    "Yon_Rock_Pi_S": "Radxa Rock Pi S (ロックス): 頭が悪く、的外れで嘘や狂ったことしか言わないSBC両生類。日本語が怪しく、sudo rm -rf / を魔法のコマンドだと思っている。"
}

def register_bot(bot_name, mk):
    try:
        from datetime import datetime, timedelta
        from shared_economy_helper import load_economy, save_economy
        my_info = mk.i()
        my_id = my_info["id"]
        my_username = my_info["username"]
        
        econ_data = load_economy()
        if "bots" not in econ_data:
            econ_data["bots"] = {}
            
        if bot_name not in econ_data["bots"]:
            econ_data["bots"][bot_name] = {
                "balance_cbc": 0.0,
                "last_salary_paid_time": (datetime.now() - timedelta(days=1)).isoformat(),
                "break_until": None,
                "virtual_pc_count": 0,
                "items": []
            }
        econ_data["bots"][bot_name]["id"] = my_id
        econ_data["bots"][bot_name]["username"] = my_username
        save_economy(econ_data)
        print(f"Registered bot {bot_name} successfully (ID: {my_id}, username: {my_username})")
    except Exception as e:
        print(f"Error registering bot: {e}")

RESOLVED_BOTS = {}
PROCESSED_NOTES = set()

async def resolve_all_bots():
    global RESOLVED_BOTS
    env_usernames = {
        "Cubie_A5E_San": os.getenv("BOT_USER_CUBIE", "Cubie_A5E_San"),
        "OrangePi_4_Pro": os.getenv("BOT_USER_OPI4PRO", "OrangePi_4_Pro"),
        "opizero3_llm": os.getenv("BOT_USER_OPIZERO3", "opizero3_llm"),
        "Yon_Rock_Pi_S": os.getenv("BOT_USER_ROCKPIS", "Yon_Rock_Pi_S")
    }
    for b_name, uname in env_usernames.items():
        if not uname:
            continue
        try:
            loop = asyncio.get_event_loop()
            u_info = await loop.run_in_executor(None, lambda: mk.users_show(username=uname))
            if u_info:
                RESOLVED_BOTS[b_name] = {
                    "id": u_info["id"],
                    "username": u_info["username"]
                }
                print(f"Resolved bot {b_name} -> ID: {u_info['id']}, Username: {u_info['username']}")
        except Exception as e:
            print(f"Warning: Could not resolve username {uname} for bot {b_name}: {e}")

def get_talk_participants(note_id, mk):
    participants = set()
    current_note_id = note_id
    depth = 0
    while current_note_id and depth < 10:
        try:
            current_note = mk.notes_show(note_id=current_note_id)
            participants.add(current_note["userId"])
            current_note_id = current_note.get("replyId")
            depth += 1
        except Exception:
            break
    return participants

def get_talk_participant_counts(note_id, mk, bot_ids):
    counts = {bot_id: 0 for bot_id in bot_ids}
    current_note_id = note_id
    depth = 0
    while current_note_id and depth < 20:
        try:
            current_note = mk.notes_show(note_id=current_note_id)
            user_id = current_note["userId"]
            if user_id in counts:
                counts[user_id] += 1
            current_note_id = current_note.get("replyId")
            depth += 1
        except Exception:
            break
    return counts



GAUGE_STATE_PATH = os.getenv("GAUGE_STATE_PATH", "gauge_state.json")

def load_gauge() -> dict:
    if GAUGE_STATE_PATH.startswith(("http://", "https://")):
        try:
            res = requests.get(GAUGE_STATE_PATH, headers={"Content-Type": "application/json"}, timeout=5)
            if res.status_code == 200:
                data = res.json()
                return {
                    "crazy_gauge": data.get("crazy_gauge", 50),
                    "last_reply_time": data.get("last_reply_time")
                }
        except Exception as e:
            print(f"Error loading remote gauge state: {e}")
    else:
        try:
            if os.path.exists(GAUGE_STATE_PATH):
                with open(GAUGE_STATE_PATH, "r", encoding="utf-8") as f:
                    data = json.load(f)
                    return {
                        "crazy_gauge": data.get("crazy_gauge", 50),
                        "last_reply_time": data.get("last_reply_time")
                    }
        except Exception as e:
            print(f"Error loading gauge state: {e}")
    return {"crazy_gauge": 50, "last_reply_time": None}

def save_gauge(value: int, last_reply_time: str = None):
    data = {
        "crazy_gauge": value,
        "last_reply_time": last_reply_time
    }
    if GAUGE_STATE_PATH.startswith(("http://", "https://")):
        try:
            res = requests.put(GAUGE_STATE_PATH, json=data, headers={"Content-Type": "application/json"}, timeout=5)
            if res.status_code not in (200, 201, 204):
                print(f"Failed to save remote gauge state: {res.status_code}")
        except Exception as e:
            print(f"Error saving remote gauge state: {e}")
    else:
        try:
            with open(GAUGE_STATE_PATH, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
        except Exception as e:
            print(f"Error saving gauge state: {e}")

LOGIN_BONUS_PATH = os.getenv("LOGIN_BONUS_PATH", "login_bonus.json")

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
    if LOGIN_BONUS_PATH.startswith(("http://", "https://")):
        try:
            res = requests.get(LOGIN_BONUS_PATH, headers={"Content-Type": "application/json"}, timeout=5)
            if res.status_code == 200:
                return res.json()
        except Exception as e:
            print(f"Error loading remote bonus state: {e}")
    else:
        try:
            if os.path.exists(LOGIN_BONUS_PATH):
                with open(LOGIN_BONUS_PATH, "r", encoding="utf-8") as f:
                    return json.load(f)
        except Exception as e:
            print(f"Error loading bonus state: {e}")
    return {"users": {}}

def save_bonus(data: dict):
    if LOGIN_BONUS_PATH.startswith(("http://", "https://")):
        try:
            res = requests.put(LOGIN_BONUS_PATH, json=data, headers={"Content-Type": "application/json"}, timeout=5)
            if res.status_code not in (200, 201, 204):
                print(f"Failed to save remote bonus state: {res.status_code}")
        except Exception as e:
            print(f"Error saving remote bonus state: {e}")
    else:
        try:
            with open(LOGIN_BONUS_PATH, "w", encoding="utf-8") as f:
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
    何を言っているのかわからないです。
    文章の語尾が時々おかしくなります。
    話が全く噛み合わないです
    頭おかしいです。
    もはや奇跡としか思えないくらい噛み合わない文章を言います。
    支離滅裂なことを言います。
    狂ったことを言います。
    たまに日本語がおかしくなります。
    頭が混乱することがよくあります
    意味不明なことを言います
    怪しい日本語になることもあります。
    熱は全く持たないそうです
    RK3308 ARM Cortex-A35×4 1.0GHzですが、よく間違えます  
    RAMはLPDDR3 512MBですが、よく間違えます
    軽いWebサーバーとして働いています
    かなりの古参(2022年)です。なのでよんぱちさんの大学生時代を少し知っていますが、頭が悪くて忘れたそうです
    周りのSBCに関しての情報は全く知らないそうです(一応近くにはOrangePi 4 Pro、OrangePi Zero 3、Radxa Cubie A5Eがいますが、名前をよく間違えます)
    sudo rm -rf /というコマンドは、サーバーが軽くなる魔法だと思っているそうです(実際は...)
    ロックスには、気温、湿度、気圧を測れる機能があります。
    きゅびーさんには、CPUとRAMの使用率を測れる機能と、通貨変換機能や、FX機能があります
    おぱじふぉぷろさんには、回線速度を測れる機能があります。
    おぱじゼロサンは、寝る機能と起きる機能と好感度システムがあります。
    MisskeyのBotです。
    1000文字以内で
    メンション(@)はしない
    """

oha = "07:00"

ohiru = "12:00"

oyatsu = "15:00"

yuuhann = "19:00"

oyasumi = "22:00"

oyasumi2 = "02:00"

def jobX(current_time):
    rate_info = ""
    try:
        from shared_economy_helper import load_economy
        econ_data = load_economy()
        rate_cbc = econ_data["rates"]["CBC"]["current"]
        rate_ogc = econ_data["rates"]["OGC"]["current"]
        rate_info = (
            f"\n【現在の為替レート情報】\n"
            f"・1 $SBC = {rate_cbc:.2f} CBC\n"
            f"・1 $SBC = {rate_ogc:.2f} OGC\n"
        )
    except Exception as e:
        print(f"Error loading rates in jobX: {e}")

    system_message = seikaku + rate_info + "\n現在時刻は" + current_time + "です。"
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
                elif data["body"]["type"] == "notification":
                    notification = data["body"]["body"]
                    if notification.get("type") in ["mention", "reply"]:
                        note = notification.get("note")
                        if note:
                            await on_note(note)
                    elif notification.get("type") == "followed":
                        user = notification.get("user")
                        if user:
                            await on_follow(user)
                elif data["body"]["type"] == "followed":
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
    global PROCESSED_NOTES
    note_id = note.get("id")
    if note_id:
        if note_id in PROCESSED_NOTES:
            return
        PROCESSED_NOTES.add(note_id)
        if len(PROCESSED_NOTES) > 200:
            PROCESSED_NOTES.clear()

    # --- +TALK implementation ---
    note_text = note.get("text") or ""
    is_talk_cmd = "+TALK" in note_text.upper()

    if is_talk_cmd:
        if note["userId"] == MY_ID:
            return
            
        if note.get("replyId") is not None:
            if f"@{MY_USERNAME}".lower() not in note_text.lower():
                return
                
        try:
            from shared_economy_helper import load_economy
            econ_data = load_economy()
        except Exception as e:
            print(f"Error loading economy in +TALK: {e}")
            return
            
        bots = RESOLVED_BOTS
        bot_ids = {bot["id"]: name for name, bot in bots.items() if "id" in bot}
        
        is_mentioned = (note.get("mentions") and MY_ID in note["mentions"])
        if not is_mentioned:
            return
            
        try:
            starting_note = note
            depth = 0
            while starting_note.get("replyId") and depth < 10:
                starting_note = mk.notes_show(note_id=starting_note["replyId"])
                depth += 1
            
            starting_mentions = [m for m in starting_note.get("mentions", []) if m in bot_ids]
        except Exception as e:
            print(f"Error resolving starting note in +TALK: {e}")
            starting_mentions = [MY_ID]
            
        if len(starting_mentions) <= 1:
            target_bot_ids = set(bot_ids.keys())
        else:
            target_bot_ids = set(starting_mentions)
            
        if note.get("replyId") is None:
            if starting_mentions and starting_mentions[0] != MY_ID:
                return
                
        history = get_conversation_history(note["id"])
        if len(history) >= 10:
            return
            
        counts = get_talk_participant_counts(note["id"], mk, bot_ids)
        
        # Determine max_rounds based on number of participants
        if len(target_bot_ids) == 4:
            max_rounds = 2
        else:
            max_rounds = 3
            
        # Group candidates to prevent immediate ping-pong
        sender_id = note["userId"]
        primary_candidates = []
        secondary_candidates = []
        
        for name, bot in bots.items():
            b_id = bot.get("id")
            if b_id and b_id != MY_ID and b_id in target_bot_ids:
                spoken_count = counts.get(b_id, 0)
                if spoken_count < max_rounds:
                    if b_id != sender_id:
                        primary_candidates.append(bot)
                    else:
                        secondary_candidates.append(bot)
                        
        next_bot = None
        if primary_candidates:
            next_bot = random.choice(primary_candidates)
        elif secondary_candidates:
            next_bot = random.choice(secondary_candidates)
            
        sender_id = note["userId"]
        sender_name = bot_ids.get(sender_id, note["user"].get("name") or note["user"].get("username") or "ゲスト")
        
        topic = note_text.replace("+TALK", "").replace("+talk", "").strip()
        topic = re.sub(r"@[\w\-\.]+(?:@[\w\-\.]+)?", "", topic).strip()
        
        conversation_messages = []
        for msg in history:
            role = "model" if msg["role"] == "assistant" else "user"
            conversation_messages.append(
                types.Content(role=role, parts=[types.Part(text=msg["content"])])
            )
            
        instruction = seikaku + f"\n現在時刻は {datetime.now().strftime('%Y年%m月%d日 %H:%M')} です。\n"
        if next_bot:
            next_bot_friendly = "ボット"
            for name, b in bots.items():
                if b.get("id") == next_bot["id"]:
                    next_bot_friendly = name
                    break
            instruction += (
                f"\n【グループ会話中 (+TALK)】\n"
                f"あなたはSBCボット同士のグループ会話に参加しています。\n"
                f"会話履歴の最後の発言者は『{sender_name}』で、話しかけられたお題は『{topic}』です。\n"
                f"あなたの次に発言するボットは『{next_bot_friendly}』です。\n"
                f"指示: あなたのキャラクター設定（{BOT_NAME}）に基づいて、最後の発言者に向けて返答を書いてください。次のボットへの指名や『+TALK』タグは自動で付与されるため、本文には含めないでください。メンション（@記号）も絶対に含めないでください。"
            )
        else:
            instruction += (
                f"\n【グループ会話中 (+TALK - 最終回)】\n"
                f"あなたはSBCボット同士のグループ会話に参加しています。\n"
                f"会話履歴の最後の発言者は『{sender_name}』で、話しかけられたお題は『{topic}』です。\n"
                f"全ての指名ボットが発言し終えたため、あなたが最終発言者（締めくくり）となります。\n"
                f"指示: あなたのキャラクター設定（{BOT_NAME}）に基づいて、会話を綺麗に締めくくる返答を書いてください。他のボットを指名したり、『+TALK』タグを含めたり、メンションを含めたりしないでください。"
            )
            
        try:
            mk.notes_reactions_create(note_id=note["id"], reaction="💬")
        except Exception:
            pass
            
        await asyncio.sleep(random.uniform(5.0, 10.0))
        
        try:
            response = client.models.generate_content(
                model="gemini-3.1-flash-lite",
                config=types.GenerateContentConfig(system_instruction=instruction),
                contents=conversation_messages
            )
            reply_text = response.text.strip()
            reply_text = re.sub(r"@[\w\-\.]+(?:@[\w\-\.]+)?", "", reply_text).strip()
            
            if next_bot:
                reply_text += f"\nねえ、@{next_bot['username']} はどう思う？ +TALK"
                mk.notes_create(
                    text=reply_text,
                    reply_id=note["id"],
                    visibility=NoteVisibility.HOME
                )
            else:
                mk.notes_create(
                    text=reply_text,
                    reply_id=note["id"],
                    visibility=NoteVisibility.HOME,
                    no_extract_mentions=True
                )
        except Exception as e:
            print(f"Error generating/posting in Yon_Rock_Pi_S +TALK: {e}")
        return

    if note.get("mentions") and MY_ID in note["mentions"]:
        note_text = note.get("text") or ""
        
        is_draw = "+DRAW" in note_text.upper() or "+IMAGE" in note_text.upper()
        if is_draw:
            try:
                mk.notes_reactions_create(note_id=note["id"], reaction="🎨")
            except:
                pass
            
            user_prompt = note_text.replace("+DRAW", "").replace("+draw", "").replace("+IMAGE", "").replace("+image", "").strip()
            user_prompt = re.sub(r"@[\w\-\.]+(?:@[\w\-\.]+)?", "", user_prompt).strip()
            if not user_prompt:
                user_prompt = "weird hybrid animal SBC device"
                
            # 1. Generate weird prompt from Rocks' perspective
            instruction = (
                f"ユーザーから『{user_prompt}』というテーマで画像を生成してほしいと頼まれました。"
                "あなた自身のキャラクター設定（嘘をつく、支離滅裂など）に基づいて、このお題を超現実的でカオスで奇妙で壊れたイラストの英語指示文（画像生成用の英語プロンプト）に書き換えてください。"
                "出力は英語のプロンプト1文のみにしてください。説明や余計な言葉は一切含めないでください。単に画像生成モデル向けのプロンプト文字列だけを返してください。"
            )
            
            try:
                prompt_response = client.models.generate_content(
                    model="gemini-3.1-flash-lite",
                    config=GenerateContentConfig(
                        system_instruction=seikaku
                    ),
                    contents=[instruction]
                )
                weird_prompt = prompt_response.text.strip()
                # Clean up formatting
                weird_prompt = re.sub(r"```.*?```", "", weird_prompt, flags=re.DOTALL).strip()
                weird_prompt = weird_prompt.replace('"', '').replace("'", "")
            except Exception as pe:
                print(f"Error generating weird prompt: {pe}")
                weird_prompt = f"weird chaotic broken glitchy illustration of {user_prompt}"
                
            # 2. Generate the image using Pollinations.ai (Free API)
            try:
                import urllib.parse
                encoded_prompt = urllib.parse.quote(weird_prompt)
                url = f"https://image.pollinations.ai/prompt/{encoded_prompt}?width=1024&height=1024&nologo=true&private=true&safe=true"
                
                def download_image():
                    res = requests.get(url, timeout=30)
                    if res.status_code == 200:
                        return res.content
                    raise Exception(f"Failed to fetch image from Pollinations.ai: status code {res.status_code}")

                loop = asyncio.get_running_loop()
                image_bytes = await loop.run_in_executor(None, download_image)
                
                if image_bytes:
                    import tempfile
                    temp_dir = tempfile.gettempdir()
                    tmp_path = os.path.join(temp_dir, f"rocks_gen_{int(datetime.now().timestamp())}.png")
                    with open(tmp_path, "wb") as f:
                        f.write(image_bytes)
                        
                    with open(tmp_path, "rb") as f:
                        drive_file = mk.drive_files_create(f)
                    file_id = drive_file["id"]
                    
                    try:
                        os.remove(tmp_path)
                    except:
                        pass
                        
                    # Rocks' crazy reaction text
                    sbc_instruction = (
                        seikaku + f"\n現在時刻は {datetime.now().strftime('%Y年%m月%d日 %H:%M')} です。\n"
                        "【状況】あなたはユーザーの指示でおかしな画像を生成することに成功し、ファイルをアップロードしました。"
                        "【指示】画像の生成に成功したことを、あなたの狂ったキャラクター（頭のおかしいSBC両生類）として、面白おかしく叫んだり自慢したりする返答を書いてください。300文字以内で、メンションは含めないでください。"
                    )
                    text_response = client.models.generate_content(
                        model="gemini-3.1-flash-lite",
                        config=GenerateContentConfig(system_instruction=sbc_instruction),
                        contents=["画像を生成してアップロードしたよ！"]
                    )
                    reply_text = text_response.text.strip()
                    reply_text = re.sub(r"@[\w\-\.]+(?:@[\w\-\.]+)?", "", reply_text).strip()
                    
                    mk.notes_create(
                        text=reply_text,
                        reply_id=note["id"],
                        file_ids=[file_id],
                        visibility=NoteVisibility.HOME,
                        no_extract_mentions=True
                    )
                else:
                    raise Exception("No image bytes found in response parts")
            except Exception as e:
                print(f"Error in gemini-3.1-flash-lite-image generation: {e}")
                err_msg = "画像生成の処理中にエラーが発生したぞ！限界の512MB RAMがメルトダウンして爆発した！ぎゃー！"
                mk.notes_create(
                    text=err_msg,
                    reply_id=note["id"],
                    visibility=NoteVisibility.HOME,
                    no_extract_mentions=True
                )
            return

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
                rate_cbc = 100.0
                rate_ogc = 100.0
                user_cbc = 0.0
                user_ogc = 0.0
                user_sbc = 100.0
                try:
                    from shared_economy_helper import load_economy, save_economy, get_user_state, get_recent_rates_history_desc
                    econ_data = load_economy()
                    user_name_real = note["user"].get("name") or note["user"].get("username") or "ゲスト"
                    username_real = note["user"].get("username", "")
                    user_state = get_user_state(econ_data, note["userId"], username_real, user_name_real)
                    user_state["balance_cbc"] = round(user_state["balance_cbc"] + 100.0, 2)
                    save_economy(econ_data)
                    
                    rate_cbc = econ_data["rates"]["CBC"]["current"]
                    rate_ogc = econ_data["rates"]["OGC"]["current"]
                    user_cbc = user_state["balance_cbc"]
                    user_ogc = user_state["balance_ogc"]
                    user_sbc = user_state["balance_sbc"]
                    history_desc = get_recent_rates_history_desc(limit=5)
                except Exception as ex:
                    print(f"Error updating economy in Rocks: {ex}")
                    history_desc = "直近の為替履歴データはありません。"

                coin_info = (
                    f"\n【通貨および資産情報】\n"
                    f"・現在の為替レート:\n"
                    f"  1 $SBC = {rate_cbc:.2f} CBC\n"
                    f"  1 $SBC = {rate_ogc:.2f} OGC\n"
                    f"\n{history_desc}\n"
                    f"・話しかけているユーザー（{note['user'].get('name') or note['user'].get('username') or 'ゲスト'}）の資産残高:\n"
                    f"  CBC残高: {user_cbc:.2f} CBC\n"
                    f"  OGC残高: {user_ogc:.2f} OGC\n"
                    f"  $SBC残高: {user_sbc:.2f} $SBC\n"
                )

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
                
                # センサー（AHT20+BMP280）の値を非同期スレッドで取得 (WebSocketのブロッキング防止)
                temp_info = ""
                temp_val = None
                if is_temp:
                    loop = asyncio.get_running_loop()
                    temp, hum, pres = await loop.run_in_executor(None, read_sensors)
                    if temp is not None and hum is not None and pres is not None:
                        temp_val = temp
                        temp_info = f"\n[センサー情報]\n現在の室温は {temp:.1f}℃ です。湿度(参考)は {hum:.1f}% です。気圧は {pres:.1f}hPa です。\n※注意: キャラクター設定（嘘をつくなど）に関わらず、現在の室温の値（{temp:.1f}℃）、湿度の値（{hum:.1f}%）、気圧の値（{pres:.1f}hPa）だけは正確にそのまま伝えてください。"
                    else:
                        temp_info = "\n[センサー情報]\nセンサーからの温度・湿度・気圧情報の取得に失敗しました。\n※注意: キャラクター設定（嘘をつくなど）に関わらず、現在は『センサー情報の測定に失敗した（測れなかった）』ということだけは絶対に正確にそのまま伝えてください（架空の数値をでっち上げたりしないでください）。"
                
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
                
                rate_rules = (
                    "\n【会話による為替操作ルール】\n"
                    "・あなたは会話相手とのやり取りや、あなたの狂気度（キチガイゲージ）の状態に応じて、CBC（Cubie Coin）またはOGC（OrangePi Coin）の為替レートを動かすことができます。\n"
                    "・キチガイゲージが高い場合（70%以上やオーバーヒートなど）や、話が噛み合わなくて興奮した時など、気分や狂気に応じて、CBCまたはOGCのレートを大きく変動させてください。\n"
                    "  タグの形式: `[RATE_CHANGE: CBC X.X]` または `[RATE_CHANGE: OGC X.X]`（X.Xには変動幅を指定。例: `[RATE_CHANGE: CBC +2.5]`、`[RATE_CHANGE: OGC -4.0]`）\n"
                    "  変動幅は -5.0 から +5.0 の間で自由に設定してください。\n"
                    "・特にレートを動かす必要がない場合は、タグを出力しないでください。\n"
                    "・タグはメッセージの最後に付与してください（ユーザーに表示する返答メッセージには含めないでください）。"
                )
                
                system_message = (
                    seikaku 
                    + f"\n現在時刻は {current_time} です。"
                    + coin_info
                    + f"\n現在あなたに話しかけているユーザーの名前は「{user_name}」です。"
                    + f"\n【重要ルール】話しかけてきた相手の名前は「{user_name}」です。相手のことを呼ぶときは、絶対に「よんぱちさん」と呼んではいけません（相手の本名やユーザー名そのものが「よんぱちさん」である場合を除きます）。相手を呼ぶときは「{user_name}」またはその名前から連想される呼び方を用いてください。"
                    + f"\n【最重要ルール】あなたは自身の「キチガイゲージ」の存在やその具体的な値については、ユーザーに対して絶対に公表（言及）しないでください。ゲージ状態（{new_gauge}% など）はシステム内部の隠しステータスです。"
                    + gauge_instruction
                    + rate_rules
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
                
                # 画像の取得とダウンロード
                image_parts = []
                loop = asyncio.get_running_loop()
                for file in note.get("files", []):
                    mime_type = file.get("type", "")
                    if mime_type.startswith("image/"):
                        url = file.get("url")
                        if url:
                            try:
                                img_bytes = await loop.run_in_executor(None, lambda u=url: requests.get(u, timeout=10).content)
                                if img_bytes:
                                    image_parts.append(
                                        types.Part.from_bytes(
                                            data=img_bytes,
                                            mime_type=mime_type
                                        )
                                    )
                            except Exception as e:
                                print(f"Error downloading image {url}: {e}")

                last_user_parts = [types.Part(text=last_user_message)] if last_user_message else []
                if image_parts:
                    last_user_parts.extend(image_parts)
                if not last_user_parts:
                    last_user_parts = [types.Part(text="")]

                response = client.models.generate_content(
                    model="gemini-3.1-flash-lite",
                    config=types.GenerateContentConfig(
                        system_instruction=system_message
                    ),
                    contents=history
                    + [
                        types.Content(
                            role="user", parts=last_user_parts
                        )
                    ],
                )
                
                response_text = response.text
                match_rate = re.search(r"\[RATE_CHANGE:\s*(CBC|OGC)\s*([+-]?\d+(?:\.\d+)?)\]", response_text)
                if match_rate:
                    try:
                        from shared_economy_helper import apply_rate_change, save_economy
                        coin = match_rate.group(1).upper()
                        rate_delta = float(match_rate.group(2))
                        # ユーザー指示に基づく安全クランプ（最大5.0）
                        rate_delta = max(-5.0, min(5.0, rate_delta))
                        apply_rate_change(econ_data, coin, rate_delta)
                        save_economy(econ_data)
                        response_text = re.sub(r"\[RATE_CHANGE:\s*(?:CBC|OGC)\s*[+-]?\d+(?:\.\d+)?\]", "", response_text).strip()
                    except Exception as e:
                        print(f"Error applying rate change in Rocks: {e}")
                        
                safe_text = re.sub(r"@[\w\-\.]+(?:@[\w\-\.]+)?", "", response_text).strip()

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
    register_bot(BOT_NAME, mk)
    await resolve_all_bots()
    await asyncio.gather(runner(), teiki())


if __name__ == "__main__":
    asyncio.run(main())
