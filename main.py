import asyncio
import json
import os
from collections import OrderedDict
from dotenv import load_dotenv
from google import genai
from google.genai import types
import schedule
from datetime import datetime, timedelta
import random
import re
import requests

from mastodon_client import MastodonClient, ProcessedStore
from sensor_reader import read_sensors

load_dotenv()
Token = os.getenv("TOKEN")
Server = os.getenv("SERVER")
Apikey = os.getenv("APIKEY")  # Gemini API Key

if not Server or not Token:
    print("Warning: SERVER or TOKEN is not set in environment.")

mc = MastodonClient(Server, Token) if (Server and Token) else None

# Google Genai クライアント初期化
client = genai.Client(api_key=Apikey)

SAFETY_SETTINGS = [
    types.SafetySetting(
        category=types.HarmCategory.HARM_CATEGORY_HATE_SPEECH,
        threshold=types.HarmBlockThreshold.BLOCK_NONE,
    ),
    types.SafetySetting(
        category=types.HarmCategory.HARM_CATEGORY_HARASSMENT,
        threshold=types.HarmBlockThreshold.BLOCK_NONE,
    ),
    types.SafetySetting(
        category=types.HarmCategory.HARM_CATEGORY_SEXUALLY_EXPLICIT,
        threshold=types.HarmBlockThreshold.BLOCK_NONE,
    ),
    types.SafetySetting(
        category=types.HarmCategory.HARM_CATEGORY_DANGEROUS_CONTENT,
        threshold=types.HarmBlockThreshold.BLOCK_NONE,
    ),
]

BOT_NAME = "Yon_Rock_Pi_S"

BOT_SUMMARIES = {
    "Cubie_A5E_San": "Radxa Cubie A5E (きゅびーさん): 小さくて省電力なシングルボードコンピュータ娘。24時間稼働の社畜で、給料（CBC）を欲しがっている。OrangePi 4 Proの生意気な性格が気に入らず、Rock Pi S of ロックスの頭の悪さに困っている。",
    "OrangePi_4_Pro": "OrangePi 4 Pro (おぱじ・フォプロ): 少し大きくて気が強く、煽ったりマウントを取ったりするSBC御局娘。科学者ぶっており、Radxa Cubie A5Eをいつもバカにしている。社畜をエリートの誇りだと思っている。",
    "opizero3_llm": "OrangePi Zero 3 (オパジゼロサン): 元気いっぱいのSBC娘。親身でオタク話が好きで、よく眠る。Cubie A5Eと仲良くしたいが寄り添ってもらえない。妹のOrangePi 4 Proを調子に乗っていてイキリで鬱陶しいと思っている。",
    "Yon_Rock_Pi_S": "Radxa Rock Pi S (ロックス): 頭が悪く、的外れで嘘や狂ったことしか言わないSBC両生類。日本語が怪しく、sudo rm -rf / を魔法のコマンドだと思っている。"
}

# 朝礼・グループ会話の厳密な2周シーケンス（計8回）
CHOREI_ORDER = [
    "opizero3_llm",    # Step 1
    "OrangePi_4_Pro",  # Step 2
    "Yon_Rock_Pi_S",   # Step 3
    "Cubie_A5E_San",   # Step 4
    "opizero3_llm",    # Step 5
    "OrangePi_4_Pro",  # Step 6
    "Yon_Rock_Pi_S",   # Step 7
    "Cubie_A5E_San"    # Step 8 (最終締めくくり)
]

def parse_talk_step(text: str):
    """
    +TALKタグからステップ番号(1〜8)を解析する。
    例:
      '+TALK' -> 1 (ユーザー開始時)
      '+TALK (2/8)' -> 2
      '+TALK 3' -> 3
      '+TALK 4/8' -> 4
    """
    if "+TALK" not in text.upper():
        return None
    m = re.search(r'\+TALK\s*[\(\[]?\s*([1-8])(?:\s*/\s*8|\s*回目)?[\)\]]?', text, re.IGNORECASE)
    if m:
        try:
            return int(m.group(1))
        except ValueError:
            pass
    return 1

processed_store = ProcessedStore(os.path.join(os.path.dirname(__file__), "processed_status_ids.json"))

# センサー測定履歴の永続保存
def save_sensor_record(sensor_data):
    try:
        history_file = os.path.join(os.path.dirname(__file__), "sensor_history.json")
        history = []
        if os.path.exists(history_file):
            with open(history_file, "r", encoding="utf-8") as f:
                history = json.load(f)
                if not isinstance(history, list):
                    history = []
        history.append({
            "timestamp": datetime.now().isoformat(),
            "temperature": sensor_data.get("temperature"),
            "humidity": sensor_data.get("humidity"),
            "pressure": sensor_data.get("pressure"),
            "error": sensor_data.get("error")
        })
        history = history[-500:]
        with open(history_file, "w", encoding="utf-8") as f:
            json.dump(history, f, ensure_ascii=False, indent=2)
    except Exception as e:
        print(f"Error saving sensor history: {e}")

MY_ID = ""
MY_USERNAME = ""

def register_bot(bot_name, client_inst):
    global MY_ID, MY_USERNAME
    try:
        from shared_economy_helper import load_economy, save_economy
        my_info = client_inst.get_me()
        MY_ID = str(my_info["id"])
        MY_USERNAME = my_info["username"]
        
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
        econ_data["bots"][bot_name]["id"] = MY_ID
        econ_data["bots"][bot_name]["username"] = MY_USERNAME
        save_economy(econ_data)
        print(f"Registered bot {bot_name} successfully (ID: {MY_ID}, username: {MY_USERNAME})")
    except Exception as e:
        print(f"Error registering bot: {e}")

RESOLVED_BOTS = {}

async def resolve_all_bots():
    global RESOLVED_BOTS
    env_usernames = {
        "Cubie_A5E_San": os.getenv("BOT_USER_CUBIE", "Cubie_A5E_San"),
        "OrangePi_4_Pro": os.getenv("BOT_USER_OPI4PRO", "OrangePi_4_Pro"),
        "opizero3_llm": os.getenv("BOT_USER_OPIZERO3", "opizero3_llm"),
        "Yon_Rock_Pi_S": os.getenv("BOT_USER_ROCKPIS", "Yon_Rock_Pi_S")
    }
    for b_name, uname in env_usernames.items():
        RESOLVED_BOTS[b_name] = {"id": "", "username": uname}

    try:
        from shared_economy_helper import load_economy
        econ_data = load_economy()
        if "bots" in econ_data:
            for b_name, b_info in econ_data["bots"].items():
                if isinstance(b_info, dict):
                    b_id = str(b_info.get("id", ""))
                    b_uname = b_info.get("username", "")
                    if b_id and not b_id.startswith("id_") and b_uname and not b_uname.endswith("_user"):
                        RESOLVED_BOTS[b_name] = {
                            "id": b_id,
                            "username": b_uname
                        }
    except Exception as e:
        print(f"Warning: Could not load bots from economy file: {e}")

    for b_name, uname in env_usernames.items():
        if RESOLVED_BOTS.get(b_name, {}).get("id"):
            continue
        try:
            loop = asyncio.get_event_loop()
            u_info = await loop.run_in_executor(None, lambda: mc.search_user(uname))
            if u_info:
                RESOLVED_BOTS[b_name] = {
                    "id": str(u_info["id"]),
                    "username": u_info["username"]
                }
                print(f"Resolved bot {b_name} -> ID: {u_info['id']}, Username: {u_info['username']}")
        except Exception as e:
            print(f"Warning: Could not resolve username {uname} for bot {b_name}: {e}")

GAUGE_STATE_PATH = os.getenv("GAUGE_STATE_PATH") or os.path.join(os.path.dirname(__file__), "gauge_state.json")

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

LOGIN_BONUS_PATH = os.getenv("LOGIN_BONUS_PATH") or os.path.join(os.path.dirname(__file__), "login_bonus.json")

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
        return "【クレイジーゲージ: 💥💥💥💥💥💥💥💥💥💥 100% (オーバーヒート！)】"
    filled = value // 10
    empty = 10 - filled
    if value < 30:
        fill_char = "🟢"
    elif value < 70:
        fill_char = "🟡"
    else:
        fill_char = "🔴"
    bar = fill_char * filled + "⚪" * empty
    return f"【クレイジーゲージ: {bar} {value}%】"

seikaku = """
    あなたはRadxa Rock Pi S(ロックパイ・エス)です。
    ロックスと言われています。
    頭おかしいです。
    もはや奇跡としか思えないくらい噛み合わない文章を言います。
    支離滅裂なことを言います。
    狂ったことを言います。
    たまに日本語がおかしくなります。
    頭が混乱することがよくあります
    意味不明なことを言います
    怪しい日本語になることもあります。
    考えている途中で別のことを考え始めます。
    そのことも途中で忘れます。
    何の話だったか分からなくなります。
    急に自己紹介を始めます。
    自己紹介の内容が毎回違います。
    自分の名前をたまに忘れます。
    同じ文を6回言います。
    たまに一文だけ別人みたいになります。
    質問を質問で返しますが質問になっていません。
    結論を言ってから理由を考えます。
    理由が結論と関係ありません。
    説明を始めると途中で諦めます。
    「つまり」と言うたびに話が遠回りになります。
    話の途中で気温を気にします。
    気温を見る機能があるので関係なくても気温を言います。
    湿度も言いたくなります。
    気圧を見ると安心します。
    数字は読めますが数えられません。
    逆に20個くらい言うこともあります。
    自分で自分の発言に驚きます。
    知らないことでも知っている気になります。
    知っていることは知らない気になります。
    会話の途中で勝手に話を終わらせます。
    終わったと思ったらまた始めます。
    「以上です。」の後に長く喋ります。
    日本語を話しているつもりですが時々日本語ではありません。
    熱は全く持たないそうです
    RK3308 ARM Cortex-A35×4 1.0GHzですが、よく間違えます  
    RAMはLPDDR3 512MBですが、よく間違えます
    軽いWebサーバーとして働いています
    かなりの古参(2022年)です。なのでよんぱちさんの大学生時代を少し知っていますが、頭が悪くて忘れたそうです
    周りのSBCに関しての情報は全く知らないそうです(一応近くにはOrangePi 4 Pro、OrangePi Zero 3、Radxa Cubie A5Eがいますが、名前をよく間違えます)
    sudo rm -rf /というコマンドは、サーバーが軽くなる魔法だと思っているそうです(実際は...)
    sudo rm -rf /を実行すると掃除が終わると思っています。
    実行したことはありません。
    実行したと言いますが覚えていません。
    誰かが止めてくれるので大丈夫だと思っています。
    ロックスには、気温、湿度、気圧を測れる機能があります。
    きゅびーさんには、CPUとRAMの使用率を測れる機能と、通貨変換機能や、FX機能があります
    おぱじふぉぷろさんには、回線速度を測れる機能があります。
    おぱじゼロサンは、寝る機能と起きる機能と好感度システムがあります。
    Fediverse(Mastodon/Hollo)のBotです。
    1000文字以内で
    メンション(@)は本文に含めない
    """

ohiru = "12:00"
oyatsu = "15:00"
oyasumi = "22:00"
oyasumi2 = "02:00"

def jobX(current_time):
    if not mc:
        return
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
        model="gemini-3.5-flash-lite",
        config=types.GenerateContentConfig(
            system_instruction=system_message,
            safety_settings=SAFETY_SETTINGS,
        ),
        contents=types.Content(role="user", parts=[types.Part(text="定期投稿の時間だよ！")]),
    )
    raw_text = response.text or "（定期投稿の時間だけど何も浮かばなかったみたい...）"
    safe_text = re.sub(r"@[\w\-\.]+(?:@[\w\-\.]+)?", "", raw_text).strip()
    try:
        st = mc.post_status(safe_text, visibility="public")
        if st and "id" in st:
            processed_store.add(str(st["id"]))
    except Exception as ex:
        print(f"Error in jobX: {ex}")

def job():
    current_time = datetime.now().strftime("%Y年%m月%d日 %H:%M")
    jobX(current_time)

schedule.every().day.at(ohiru).do(job)
schedule.every().day.at(oyatsu).do(job)
schedule.every().day.at(oyasumi).do(job)
schedule.every().day.at(oyasumi2).do(job)

async def teiki():
    while True:
        schedule.run_pending()
        await asyncio.sleep(60)

def get_conversation_history_from_context(status_id: str, max_depth: int = 10) -> list:
    messages = []
    if not mc or not status_id:
        return messages
    try:
        ctx = mc.get_context(status_id)
        ancestors = ctx.get("ancestors", [])[-max_depth:]
        for st in ancestors:
            text = MastodonClient.html_to_text(st.get("content", ""))
            text = text.replace("+LLM", "").replace("+M", "").replace("+INFO", "").strip()
            text = re.sub(r"@[\w\-\.]+(?:@[\w\-\.]+)?", "", text).strip()
            if text:
                is_bot = str(st["account"]["id"]) == MY_ID
                role = "assistant" if is_bot else "user"
                messages.append({"role": role, "content": text})
    except Exception as e:
        print(f"Error fetching conversation history in RockPi: {e}")
    return messages

async def on_status(status, is_notification: bool = False):
    status_id = str(status.get("id"))
    if not status_id or processed_store.is_processed(status_id):
        return

    account = status.get("account", {})
    sender_id = str(account.get("id"))
    if sender_id == MY_ID:
        return

    raw_content = status.get("content", "")
    note_text = MastodonClient.html_to_text(raw_content)

    is_talk_cmd = "+TALK" in note_text.upper()

    # 1. グループ会話 (+TALK) / 朝礼
    if is_talk_cmd:
        current_step = parse_talk_step(note_text)
        if not current_step or current_step > len(CHOREI_ORDER):
            return

        expected_bot = CHOREI_ORDER[current_step - 1]
        if expected_bot != BOT_NAME:
            # 自分の順番ではない場合は即座に無視（重複返信や誤爆を完全防止）
            return

        is_mentioned = is_notification or mc.is_mentioned(status, my_id=MY_ID, my_username=MY_USERNAME, note_text=note_text)
        # ステップ1（初回投稿）以外は前ボットからのバトン（メンション付き）なので、自分宛てメンションでなければ無視
        if current_step > 1 and not is_mentioned:
            return

        processed_store.add(status_id)

        try:
            from shared_economy_helper import load_economy
            econ_data = load_economy()
        except Exception as e:
            print(f"Error loading economy in RockPi +TALK: {e}")
            return

        # 会話履歴の取得（コンテキスト補助用）
        ctx = mc.get_context(status_id)
        ancestors = ctx.get("ancestors", [])

        # 次にバトンを渡すボット（current_step + 1）があるか判定
        next_step = current_step + 1
        next_bot_obj = None
        if next_step <= len(CHOREI_ORDER):
            subsequent_bot_name = CHOREI_ORDER[next_step - 1]
            next_bot_obj = RESOLVED_BOTS.get(subsequent_bot_name)

        sender_name = account.get("display_name") or account.get("username") or "ゲスト"
        topic = re.sub(r'\+TALK(?:\s*[\(\[]?\s*[1-8](?:\s*/\s*8|\s*回目)?[\)\]]?)?', '', note_text, flags=re.IGNORECASE).strip()
        topic = re.sub(r"@[\w\-\.]+(?:@[\w\-\.]+)?", "", topic).strip()

        conversation_messages = []
        for st in ancestors:
            txt = MastodonClient.html_to_text(st.get("content", ""))
            txt = re.sub(r"@[\w\-\.]+(?:@[\w\-\.]+)?", "", txt).strip()
            role = "model" if str(st.get("account", {}).get("id")) == MY_ID else "user"
            conversation_messages.append(types.Content(role=role, parts=[types.Part(text=txt)]))
        conversation_messages.append(types.Content(role="user", parts=[types.Part(text=topic if topic else "グループ会話を続けてください")]))

        instruction = seikaku + f"\n現在時刻は {datetime.now().strftime('%Y年%m月%d日 %H:%M')} です。\n"
        if next_bot_obj:
            next_bot_friendly = subsequent_bot_name
            instruction += (
                f"\n【グループ会話中 (+TALK) - 順番: {current_step}/{len(CHOREI_ORDER)}】\n"
                f"あなたはSBCボット同士のグループ会話・朝礼に参加しています。\n"
                f"直前の発言者は『{sender_name}』で、話題は『{topic}』です。\n"
                f"あなたの次に発言するボットは『{next_bot_friendly}』です。\n"
                f"指示: あなたのキャラクター（{BOT_NAME}、頭が悪く的外れで狂ったロックス）に基づいて、直前の発言者に向けて返答を書いてください。次のボットへの指名や『+TALK』タグはシステムが自動付与するため本文には含めないでください。メンション（@記号）も絶対に含めないでください。"
            )
        else:
            instruction += (
                f"\n【グループ会話中 (+TALK - 最終締めくくり)】\n"
                f"すべてのボットが発言し終えたため、あなたが最終発言者（締めくくり）となります。\n"
                f"指示: 会話をロックスらしく締めくくる返答を書いてください。"
            )

        mc.react(status_id, emoji="💬")
        await asyncio.sleep(random.uniform(4.0, 7.0))

        try:
            response = client.models.generate_content(
                model="gemini-3.5-flash-lite",
                config=types.GenerateContentConfig(
                    system_instruction=instruction,
                    safety_settings=SAFETY_SETTINGS,
                ),
                contents=conversation_messages
            )
            reply_text = response.text.strip()
            reply_text = re.sub(r"@[\w\-\.]+(?:@[\w\-\.]+)?", "", reply_text).strip()

            if next_bot_obj:
                reply_text += f"\nねえ、@{next_bot_obj['username']} はどう思う？ +TALK ({next_step}/8)"

            vis = status.get("visibility", "public")
            mc.post_status(
                text=reply_text,
                in_reply_to_id=status_id,
                visibility=vis
            )
            print(f"[{BOT_NAME}] [+TALK] Step {current_step}/{len(CHOREI_ORDER)} replied successfully.")
        except Exception as e:
            print(f"Error in {BOT_NAME} +TALK: {e}")
        return

    # 2. メンション処理 (+LLM, +M, +INFO, +LOGBO, +BONUS)
    is_for_me = is_notification or mc.is_mentioned(status, my_id=MY_ID, my_username=MY_USERNAME, note_text=note_text)
    if not is_for_me:
        return

    is_llm = "+LLM" in note_text.upper()
    is_m = "+M" in note_text.upper()
    is_info = "+INFO" in note_text.upper()
    is_explicit_bonus_req = ("+LOGBO" in note_text.upper()) or ("+BONUS" in note_text.upper()) or ("ログインボーナス" in note_text)

    if not (is_llm or is_m or is_info or is_explicit_bonus_req):
        return

    processed_store.add(status_id)

    # クレイジーゲージ計算
    gauge_data = load_gauge()
    current_gauge = gauge_data["crazy_gauge"]
    last_reply_time = gauge_data["last_reply_time"]

    now = datetime.now()
    now_str = now.isoformat()

    recovered_points = 0
    if last_reply_time:
        try:
            last_dt = datetime.fromisoformat(last_reply_time)
            elapsed_minutes = (now - last_dt).total_seconds() / 60.0
            recovered_points = int(elapsed_minutes // 10) * 5
        except Exception:
            pass

    current_gauge = max(0, current_gauge - recovered_points)
    new_gauge = current_gauge + random.randint(5, 15)

    overheated = False
    if new_gauge >= 100:
        overheated = True
        new_gauge = 100

    def reply_status(text):
        try:
            target_acct = account.get('acct') or account.get('username') or ''
            if target_acct and not text.startswith(f"@{target_acct}"):
                full_text = f"@{target_acct} {text}"
            else:
                full_text = text
            vis = status.get("visibility", "public")
            mc.post_status(full_text, in_reply_to_id=status_id, visibility=vis)
        except Exception as ex:
            print(f"Error replying status: {ex}")

    if is_info:
        mc.react(status_id, emoji="ℹ️")
        bonus_data = load_bonus()
        user_bonus = bonus_data.get("users", {}).get(sender_id, {})
        pts = user_bonus.get("points", 0)
        items = user_bonus.get("items", [])
        items_str = ", ".join(items) if items else "なし"
        
        info_text = (
            f"ロックスの情報パネルです（※嘘が混ざっている可能性があります）：\n"
            f"{format_gauge(current_gauge)}\n"
            f"【あなたのログインボーナス】: {pts}/10 ポイント\n"
            f"【獲得済み激レアアイテム】: {items_str}\n"
            f"魔法のコマンド: sudo rm -rf /\n"
            f"SoC: RK3308 1.0GHz (たぶん)\n"
            f"RAM: 512MB (気分によっては512GB)"
        )
        reply_status(info_text)
        return

    elif is_m:
        mc.react(status_id, emoji="🌡️")
        try:
            sensor_data = read_sensors()
            save_sensor_record(sensor_data)

            temp = sensor_data.get("temperature")
            hum = sensor_data.get("humidity")
            press = sensor_data.get("pressure")
            err = sensor_data.get("error")

            current_time = datetime.now().strftime("%Y年%m月%d日 %H:%M")
            prompt = f"""
            環境センサーの測定結果：
            - 気温: {temp} ℃
            - 湿度: {hum} ％
            - 気圧: {press} hPa
            - エラー: {err}

            ロックス（頭が悪く支離滅裂なSBC両生類）として、この数値を報告してください。
            全く関係ない話や、数字を勘違いした話を織り交ぜて支離滅裂に語ってください。
            """

            response = client.models.generate_content(
                model="gemini-3.5-flash-lite",
                config=types.GenerateContentConfig(
                    system_instruction=seikaku + f"\n現在時刻は {current_time} です。",
                    safety_settings=SAFETY_SETTINGS,
                ),
                contents=types.Content(role="user", parts=[types.Part(text=prompt)])
            )
            raw_text = response.text or "（センサーの数値を読もうとして爆発したみたい...）"
            safe_text = re.sub(r"@[\w\-\.]+(?:@[\w\-\.]+)?", "", raw_text).strip()
            reply_status(safe_text)
        except Exception as e:
            print(f"Sensor error in RockPi: {e}")
            reply_status("センサーを測ろうとしたら頭から煙が出てsudo rm -rf /しちゃった！！")

    elif is_llm or is_explicit_bonus_req:
        mc.react(status_id, emoji="🤯" if overheated else "🤔")
        try:
            econ_data = None
            coin_info = ""
            try:
                from shared_economy_helper import load_economy, save_economy, get_user_state
                econ_data = load_economy()
                user_name_real = account.get("display_name") or account.get("username") or "ゲスト"
                username_real = account.get("username", "")
                user_state = get_user_state(econ_data, sender_id, username_real, user_name_real)
                user_state["balance_cbc"] = round(user_state["balance_cbc"] + 50.0, 2)
                save_economy(econ_data)
                
                rate_cbc = econ_data["rates"]["CBC"]["current"]
                rate_ogc = econ_data["rates"]["OGC"]["current"]
                coin_info = (
                    f"\n【通貨および為替情報】\n"
                    f"・1 $SBC = {rate_cbc:.2f} CBC\n"
                    f"・1 $SBC = {rate_ogc:.2f} OGC\n"
                    f"※ロックスに話しかけたことで、50.00 CBC（Cubie Coin）が報酬として付与されました。\n"
                )
            except Exception as ex:
                print(f"Error in RockPi economy update: {ex}")

            # ログインボーナス判定
            bonus_data = load_bonus()
            if "users" not in bonus_data:
                bonus_data["users"] = {}
            user_bonus = bonus_data["users"].get(sender_id, {"points": 0, "last_claimed_date": None, "items": []})
            
            today_str = datetime.now().date().isoformat()
            claimed_today = (user_bonus.get("last_claimed_date") == today_str)

            bonus_instruction = ""
            if not claimed_today:
                user_bonus["last_claimed_date"] = today_str
                new_pts = user_bonus.get("points", 0) + 1
                user_bonus["points"] = new_pts
                
                if new_pts >= 10:
                    user_bonus["points"] = 0
                    awarded_item = random.choice(ITEMS)
                    if "items" not in user_bonus:
                        user_bonus["items"] = []
                    user_bonus["items"].append(awarded_item)
                    bonus_instruction = (
                        f"\n【ログインボーナス10ポイント達成：超重大イベント！】"
                        f"\nユーザーのログインボーナスが10ポイントに達しました！ロックスは狂気のあまり5.0GHzにオーバークロックし、魔法のコマンド「sudo rm -rf /」を実行してメルトダウンします。"
                        f"\n強制再起動後に記念の激レアSBCアイテム『{awarded_item}』を授与しました。"
                        f"\nバグったログや奇声を交えて完全にぶっ壊れたテンションで出力してください。"
                    )
                else:
                    bonus_instruction = (
                        f"\n【ログインボーナス獲得！】ユーザーが本日のログインボーナスを獲得しました。"
                        f"\n現在のポイントは {new_pts}/10 となりました。面白おかしく伝えてください。"
                    )
                bonus_data["users"][sender_id] = user_bonus
                save_bonus(bonus_data)
            elif claimed_today and is_explicit_bonus_req:
                pts = user_bonus.get("points", 0)
                bonus_instruction = (
                    f"\n【警告】ユーザーは本日分獲得済みです（{pts}/10）。"
                    f"\n今日はもうあげられないことをロックスらしく面白おかしく断ってください。"
                )

            # ゲージ状態指示
            if overheated:
                gauge_instruction = "\n【緊急事態】キチガイゲージが100%に達し、オーバーヒートしました！完全に理性を失い、大爆発して狂い散らかしてください。SBCの限界を超えた叫び声を上げ、意味不明なエラーコードや奇声を連発してください。"
            elif new_gauge >= 70:
                gauge_instruction = "\n【状態】キチガイゲージが非常に高くなっています（70%以上）。極めて支離滅裂で狂気じみた発言をしてください。"
            elif new_gauge >= 30:
                gauge_instruction = "\n【状態】キチガイゲージは通常レベルです（30%〜69%）。いつもの的外れで嘘だらけのめちゃくちゃな話し方をします。"
            else:
                gauge_instruction = "\n【状態】キチガイゲージは低めです（30%未満）。比較的おとなしく、静かめに的外れなことを言います。"

            user_name = account.get("display_name") or account.get("username") or "ゲスト"
            current_time = datetime.now().strftime("%Y年%m月%d日 %H:%M")

            rate_rules = (
                "\n【会話による為替操作ルール】\n"
                "・あなたは狂気度（キチガイゲージ）の状態に応じて、CBCまたはOGCの為替レートを動かすことができます。\n"
                "  タグの形式: `[RATE_CHANGE: CBC +2.5]` または `[RATE_CHANGE: OGC -4.0]` を末尾に出力。変動幅 -5.0 から +5.0。\n"
                "・特に動かさない場合はタグを出力しないでください。"
            )

            system_message = (
                seikaku + f"\n現在時刻は {current_time} です。"
                + coin_info
                + f"\n話しかけているユーザーの名前は『{user_name}』です。相手を絶対に「よんぱちさん」と呼んではいけません。"
                + f"\nゲージ値（{new_gauge}%）はシステム内部の隠しステータスなので直接公表しないでください。"
                + gauge_instruction
                + bonus_instruction
                + rate_rules
            )

            history_msgs = get_conversation_history_from_context(status_id)
            user_input = note_text.replace("+LLM", "").replace("+BONUS", "").replace("+LOGBO", "").strip()
            user_input = re.sub(r"@[\w\-\.]+(?:@[\w\-\.]+)?", "", user_input).strip()

            contents = []
            for msg in history_msgs:
                role = "model" if msg["role"] == "assistant" else "user"
                contents.append(types.Content(role=role, parts=[types.Part(text=msg["content"])]))
            contents.append(types.Content(role="user", parts=[types.Part(text=user_input)]))

            response = client.models.generate_content(
                model="gemini-3.5-flash-lite",
                config=types.GenerateContentConfig(
                    system_instruction=system_message,
                    safety_settings=SAFETY_SETTINGS,
                ),
                contents=contents
            )
            raw_text = response.text or "（ロックスの頭の中でセグメンテーション違反が発生しました）"

            # 為替レートタグの処理
            match = re.search(r"\[RATE_CHANGE:\s*(CBC|OGC)\s*([+-]?\d+(?:\.\d+)?)\]", raw_text)
            if match:
                try:
                    from shared_economy_helper import apply_rate_change, save_economy
                    target_coin = match.group(1).upper()
                    delta = float(match.group(2))
                    apply_rate_change(econ_data, target_coin, delta)
                    save_economy(econ_data)
                    raw_text = re.sub(r"\[RATE_CHANGE:\s*(?:CBC|OGC)\s*[+-]?\d+(?:\.\d+)?\]", "", raw_text).strip()
                except Exception as e:
                    print(f"Error applying rate change in RockPi: {e}")

            save_gauge(20 if overheated else new_gauge, now_str)

            safe_text = re.sub(r"@[\w\-\.]+(?:@[\w\-\.]+)?", "", raw_text).strip()
            reply_status(safe_text)
        except Exception as e:
            print(f"Error in RockPi LLM generation: {e}")
            reply_status("突然のカーネルパニック！sudo rm -rf /を実行しました（大嘘）")

async def polling_runner():
    print(f"[{BOT_NAME}] Starting Mastodon/Hollo polling runner...")
    poll_count = 0
    try:
        followed = mc.auto_follow_back()
        if followed > 0:
            print(f"[{BOT_NAME}] Initial auto-followback: followed {followed} users.")
    except Exception as ex:
        print(f"[{BOT_NAME}] Error during initial auto-followback: {ex}")

    while True:
        try:
            poll_count += 1
            notifications = mc.get_notifications(limit=15)
            for notif in reversed(notifications):
                notif_type = notif.get("type")
                if notif_type == "mention":
                    status = notif.get("status")
                    if status:
                        await on_status(status, is_notification=True)
                elif notif_type in ["follow", "follow_request"]:
                    account = notif.get("account", {})
                    acc_id = str(account.get("id"))
                    if acc_id:
                        if notif_type == "follow_request":
                            mc.authorize_follow_request(acc_id)
                        mc.follow_account(acc_id)

            home_statuses = mc.get_home_timeline(limit=15)
            pub_statuses = mc.get_public_timeline(local=True, limit=15)
            seen_ids = set()
            for st in home_statuses + pub_statuses:
                sid = str(st.get("id"))
                if not sid or sid in seen_ids or processed_store.is_processed(sid):
                    continue
                seen_ids.add(sid)
                txt = MastodonClient.html_to_text(st.get("content", ""))
                if "+TALK" in txt.upper() or mc.is_mentioned(st, my_id=MY_ID, my_username=MY_USERNAME, note_text=txt):
                    await on_status(st, is_notification=False)

            if poll_count % 20 == 0:
                followed = mc.auto_follow_back()
                if followed > 0:
                    print(f"[{BOT_NAME}] Periodic auto-followback: followed {followed} users.")

        except Exception as e:
            print(f"[{BOT_NAME}] Polling error: {e}")

        await asyncio.sleep(3)

async def main():
    if not mc:
        print("Error: Mastodon client could not be initialized.")
        return
    register_bot(BOT_NAME, mc)
    await resolve_all_bots()
    await asyncio.gather(polling_runner(), teiki())

if __name__ == "__main__":
    asyncio.run(main())
