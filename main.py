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
    ロックスには、気温を測れる機能があり、きゅびーさんには、CPUとRAMの使用率を測れる機能があります。
    おぱじふぉぷろさんには、回線速度を測れる機能があります。
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
        is_llm = "+LLM" in note["text"]
        is_temp = "+M" in note["text"]
        
        if is_llm or is_temp:
            reaction = "🌡️" if is_temp else "🤔"
            mk.notes_reactions_create(
                note_id=note["id"], reaction=reaction
            )

            try:
                # 会話履歴を取得
                conversation_messages = get_conversation_history(note["id"])
                
                # 現在のメッセージを追加
                user_input = note["text"].replace("+LLM", "").replace("+M", "").strip()
                user_input = re.sub(r"@[\w\-\.]+(?:@[\w\-\.]+)?", "", user_input).strip()
                
                conversation_messages.append({
                    "role": "user",
                    "content": user_input
                })
                
                current_time = datetime.now().strftime("%Y年%m月%d日 %H:%M")
                
                # DHT11の値を非同期スレッドで取得 (WebSocketのブロッキング防止)
                temp_info = ""
                if is_temp:
                    loop = asyncio.get_running_loop()
                    temp, hum = await loop.run_in_executor(None, read_dht)
                    if temp is not None:
                        temp_info = f"\n[センサー情報]\n現在の室温は {temp:.1f}℃ です。湿度(参考)は {hum:.1f}% です。\n※注意: キャラクター設定（嘘をつくなど）に関わらず、現在の室温の値（{temp:.1f}℃）だけは正確にそのまま伝えてください。"
                    else:
                        temp_info = "\n[センサー情報]\nセンサーからの室温取得に失敗しました。"
                
                # システムプロンプトを最初に追加
                system_message = seikaku + "\n現在時刻は" + current_time + "です。\n" + note["user"]["name"] + " という方にメンションされました。"
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


asyncio.run(main())
