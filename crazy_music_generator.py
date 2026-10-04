import os
import math
import struct
import random
import tempfile
import shutil
import subprocess

def _vlq(val: int) -> bytes:
    """Variable-Length Quantity for MIDI"""
    res = bytearray()
    res.append(val & 0x7F)
    val >>= 7
    while val > 0:
        res.append(0x80 | (val & 0x7F))
        val >>= 7
    res.reverse()
    return bytes(res)

def _build_midi_file(events: list, bpm: int = 180, ticks_per_beat: int = 480) -> bytes:
    """
    events: list of (tick, event_type, channel, param1, param2)
      event_type: 'on' (p1=pitch, p2=vel), 'off' (p1=pitch), 'prog' (p1=program)
    """
    events.sort(key=lambda x: x[0])
    track = bytearray()
    
    # Set Tempo (microseconds per quarter note)
    uspbeat = int(60_000_000 / bpm)
    track += b'\x00\xFF\x51\x03' + struct.pack('>I', uspbeat)[1:]
    
    last_tick = 0
    for ev in events:
        tick = ev[0]
        ev_type = ev[1]
        ch = ev[2] & 0x0F
        delta = max(0, tick - last_tick)
        track += _vlq(delta)
        
        if ev_type == 'on':
            pitch = ev[3] & 0x7F
            vel = ev[4] & 0x7F
            track += bytes([0x90 | ch, pitch, vel])
        elif ev_type == 'off':
            pitch = ev[3] & 0x7F
            track += bytes([0x80 | ch, pitch, 0])
        elif ev_type == 'prog':
            prog = ev[3] & 0x7F
            track += bytes([0xC0 | ch, prog])
            
        last_tick = tick
        
    # End of Track
    track += b'\x00\xFF\x2F\x00'
    
    header = b'MThd' + struct.pack('>IHHH', 6, 0, 1, ticks_per_beat)
    trk_chunk = b'MTrk' + struct.pack('>I', len(track)) + bytes(track)
    return header + trk_chunk

def generate_crazy_music(output_dir: str = None) -> tuple[str, str]:
    """
    ロックス特製のめちゃくちゃででたらめな狂気の曲を生成する
    戻り値: (midi_file_path, mp3_file_path)
    """
    if not output_dir:
        output_dir = tempfile.gettempdir()
        
    sr = 22050
    duration = random.uniform(7.0, 11.0)
    bpm = random.randint(160, 260)
    ticks_per_beat = 480
    seconds_per_tick = (60.0 / bpm) / ticks_per_beat
    
    total_samples = int(sr * duration)
    audio_buffer = [0.0] * total_samples
    
    midi_events = []
    # Program Change: Channel 0 = Synth Lead (80), Channel 1 = Synth Bass (38)
    midi_events.append((0, 'prog', 0, random.choice([80, 81, 87, 29, 30]), 0))
    midi_events.append((0, 'prog', 1, random.choice([38, 39, 34, 35]), 0))
    
    # 狂気の音階（半音階や不協和音、全音音階をごちゃ混ぜ）
    scale_palette = [
        [48, 51, 54, 57, 60, 63, 66, 69, 72, 75, 78, 81, 84, 87],  # ディミニッシュ（狂気）
        [48, 50, 52, 54, 56, 58, 60, 62, 64, 66, 68, 70, 72],      # 全音音階（浮遊・異常）
        [48, 49, 53, 54, 55, 59, 60, 61, 65, 66, 67, 71, 72, 73],  # 半音だらけの不協和音
        [36, 48, 51, 53, 55, 63, 65, 67, 75, 77, 79, 87, 89]       # 跳躍ペンタ
    ]
    crazy_scale = random.choice(scale_palette)
    
    # 1. メロディ（超高速アルペジオ、でたらめなフレーズ、突然のグリッチ）
    t = 0.0
    while t < duration:
        note_dur = random.choice([0.05, 0.08, 0.10, 0.14, 0.20, 0.28])
        if random.random() < 0.92:
            pitch = random.choice(crazy_scale)
            freq = 440.0 * (2.0 ** ((pitch - 69) / 12.0))
            vel = random.randint(85, 127)
            
            start_tick = int(t / seconds_per_tick)
            end_tick = int((t + note_dur * 0.9) / seconds_per_tick)
            midi_events.append((start_tick, 'on', 0, pitch, vel))
            midi_events.append((end_tick, 'off', 0, pitch, 0))
            
            # PCM音源合成（矩形波＋周波数モジュレーション・ピッチベンド）
            s_idx = int(t * sr)
            e_idx = min(total_samples, int((t + note_dur) * sr))
            bend_factor = random.choice([0.0, -0.05, 0.08, 0.15]) if random.random() < 0.4 else 0.0
            wave_type = random.choice(['square', 'saw', 'pulse'])
            
            for i in range(s_idx, e_idx):
                local_t = (i - s_idx) / sr
                env = math.exp(-local_t * 8.0)
                cur_freq = freq * (1.0 + bend_factor * (local_t / note_dur))
                phase = (local_t * cur_freq) % 1.0
                
                if wave_type == 'square':
                    val = 0.6 if phase < 0.5 else -0.6
                elif wave_type == 'saw':
                    val = 2.0 * phase - 1.0
                else:  # pulse
                    val = 0.8 if phase < 0.25 else -0.2
                    
                audio_buffer[i] += val * env * 0.28
                
        t += note_dur
        
    # 2. ベース（重低音、突発的なトリル）
    t = 0.0
    while t < duration:
        bass_dur = random.choice([0.16, 0.24, 0.32, 0.48])
        if random.random() < 0.8:
            bass_pitch = random.choice([36, 38, 41, 42, 44, 46, 48])
            freq = 440.0 * (2.0 ** ((bass_pitch - 69) / 12.0))
            vel = random.randint(90, 127)
            
            start_tick = int(t / seconds_per_tick)
            end_tick = int((t + bass_dur * 0.85) / seconds_per_tick)
            midi_events.append((start_tick, 'on', 1, bass_pitch, vel))
            midi_events.append((end_tick, 'off', 1, bass_pitch, 0))
            
            s_idx = int(t * sr)
            e_idx = min(total_samples, int((t + bass_dur) * sr))
            for i in range(s_idx, e_idx):
                local_t = (i - s_idx) / sr
                env = math.exp(-local_t * 4.0)
                # 三角波
                phase = (local_t * freq) % 1.0
                val = 4.0 * abs(phase - 0.5) - 1.0
                audio_buffer[i] += val * env * 0.35
                
        t += bass_dur
        
    # 3. ノイズパーカッション（ランダムなビート、破壊的なスネア＆キック音）
    t = 0.0
    beat_step = 60.0 / bpm
    while t < duration:
        # キック（ピッチ急降下サイン波）
        s_idx = int(t * sr)
        e_idx = min(total_samples, int((t + 0.12) * sr))
        for i in range(s_idx, e_idx):
            local_t = (i - s_idx) / sr
            k_freq = 150.0 * math.exp(-local_t * 30.0) + 40.0
            val = math.sin(2.0 * math.pi * k_freq * local_t)
            env = max(0.0, 1.0 - local_t / 0.12)
            audio_buffer[i] += val * env * 0.45
            
        # スネア/ノイズバースト
        if random.random() < 0.6:
            snare_t = t + beat_step * 0.5
            if snare_t < duration:
                ss_idx = int(snare_t * sr)
                se_idx = min(total_samples, int((snare_t + 0.08) * sr))
                for i in range(ss_idx, se_idx):
                    local_t = (i - ss_idx) / sr
                    env = math.exp(-local_t * 25.0)
                    noise = random.uniform(-1.0, 1.0)
                    audio_buffer[i] += noise * env * 0.25
                    
        t += beat_step
        
    # 4. MIDIファイル書き出し
    midi_bytes = _build_midi_file(midi_events, bpm=bpm, ticks_per_beat=ticks_per_beat)
    rand_id = random.randint(1000, 9999)
    midi_path = os.path.join(output_dir, f"rocks_crazy_{rand_id}.mid")
    with open(midi_path, "wb") as f:
        f.write(midi_bytes)
        
    # 5. MP3ファイルエンコード
    # 16-bit PCM Mono生成
    pcm_bytes = bytearray()
    for s in audio_buffer:
        s = max(-1.0, min(1.0, s))
        pcm_bytes.extend(struct.pack('<h', int(s * 32767)))
        
    mp3_path = os.path.join(output_dir, f"rocks_crazy_{rand_id}.mp3")
    encoded = False
    
    # 優先度1: lameenc (高速・ピュアライブラリ)
    try:
        import lameenc
        encoder = lameenc.Encoder()
        encoder.set_bit_rate(128)
        encoder.set_in_sample_rate(sr)
        encoder.set_channels(1)
        encoder.set_quality(3)
        mp3_data = encoder.encode(bytes(pcm_bytes)) + encoder.flush()
        with open(mp3_path, "wb") as f:
            f.write(mp3_data)
        encoded = True
    except Exception as e:
        print(f"[crazy_music_generator] lameenc encoding failed: {e}")
        
    # 優先度2: ffmpeg CLI (もしシステムにあれば)
    if not encoded and shutil.which("ffmpeg"):
        try:
            raw_path = os.path.join(output_dir, f"temp_{rand_id}.raw")
            with open(raw_path, "wb") as f:
                f.write(pcm_bytes)
            subprocess.run([
                "ffmpeg", "-y", "-f", "s16le", "-ar", str(sr), "-ac", "1",
                "-i", raw_path, "-b:a", "128k", mp3_path
            ], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=True)
            if os.path.exists(raw_path):
                os.remove(raw_path)
            encoded = True
        except Exception as e:
            print(f"[crazy_music_generator] ffmpeg encoding failed: {e}")
            
    # 優先度3: lame CLI (もしシステムにあれば)
    if not encoded and shutil.which("lame"):
        try:
            import wave
            wav_path = os.path.join(output_dir, f"temp_{rand_id}.wav")
            with wave.open(wav_path, "wb") as wf:
                wf.setnchannels(1)
                wf.setsampwidth(2)
                wf.setframerate(sr)
                wf.writeframes(pcm_bytes)
            subprocess.run(["lame", "-b", "128", wav_path, mp3_path],
                           stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=True)
            if os.path.exists(wav_path):
                os.remove(wav_path)
            encoded = True
        except Exception as e:
            print(f"[crazy_music_generator] lame CLI encoding failed: {e}")

    # 万一エンコーダーが皆無の場合のWAVフォールバック
    if not encoded:
        import wave
        wav_path = os.path.join(output_dir, f"rocks_crazy_{rand_id}.wav")
        with wave.open(wav_path, "wb") as wf:
            wf.setnchannels(1)
            wf.setsampwidth(2)
            wf.setframerate(sr)
            wf.writeframes(pcm_bytes)
        mp3_path = wav_path
        
    return midi_path, mp3_path
