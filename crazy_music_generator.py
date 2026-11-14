import os
import math
import struct
import random
import tempfile
import shutil
import subprocess

# Scale presets (MIDI note numbers around C3-C6)
SCALE_PALETTES = {
    "diminished": [48, 51, 54, 57, 60, 63, 66, 69, 72, 75, 78, 81, 84],
    "whole_tone": [48, 50, 52, 54, 56, 58, 60, 62, 64, 66, 68, 70, 72],
    "chromatic_chaos": [48, 49, 53, 54, 55, 59, 60, 61, 65, 66, 67, 71, 72, 73],
    "hyper_penta": [48, 51, 53, 55, 60, 63, 65, 67, 72, 75, 77, 79, 84],
    "minor_crazy": [48, 50, 51, 55, 56, 60, 62, 63, 67, 68, 72, 74, 75, 79],
}

# Japanese kana -> (consonant_type, vowel)
# consonant_type: None, 'k', 's', 't', 'n', 'h', 'm', 'y', 'r', 'w', 'g', 'z', 'd', 'b', 'p', 'nn'
KANA_MAP = {
    'あ': (None, 'a'), 'い': (None, 'i'), 'う': (None, 'u'), 'え': (None, 'e'), 'お': (None, 'o'),
    'ぁ': (None, 'a'), 'ぃ': (None, 'i'), 'ぅ': (None, 'u'), 'ぇ': (None, 'e'), 'ぉ': (None, 'o'),
    'か': ('k', 'a'), 'き': ('k', 'i'), 'く': ('k', 'u'), 'け': ('k', 'e'), 'こ': ('k', 'o'),
    'が': ('g', 'a'), 'ぎ': ('g', 'i'), 'ぐ': ('g', 'u'), 'げ': ('g', 'e'), 'ご': ('g', 'o'),
    'さ': ('s', 'a'), 'し': ('s', 'i'), 'す': ('s', 'u'), 'せ': ('s', 'e'), 'そ': ('s', 'o'),
    'ざ': ('z', 'a'), 'じ': ('z', 'i'), 'ず': ('z', 'u'), 'ぜ': ('z', 'e'), 'ぞ': ('z', 'o'),
    'た': ('t', 'a'), 'ち': ('t', 'i'), 'つ': ('t', 'u'), 'て': ('t', 'e'), 'と': ('t', 'o'),
    'だ': ('d', 'a'), 'ぢ': ('z', 'i'), 'づ': ('z', 'u'), 'で': ('d', 'e'), 'ど': ('d', 'o'),
    'な': ('n', 'a'), 'に': ('n', 'i'), 'ぬ': ('n', 'u'), 'ね': ('n', 'e'), 'の': ('n', 'o'),
    'は': ('h', 'a'), 'ひ': ('h', 'i'), 'ふ': ('h', 'u'), 'へ': ('h', 'e'), 'ほ': ('h', 'o'),
    'ば': ('b', 'a'), 'び': ('b', 'i'), 'ぶ': ('b', 'u'), 'べ': ('b', 'e'), 'ぼ': ('b', 'o'),
    'ぱ': ('p', 'a'), 'ぴ': ('p', 'i'), 'ぷ': ('p', 'u'), 'ぺ': ('p', 'e'), 'ぽ': ('p', 'o'),
    'ま': ('m', 'a'), 'み': ('m', 'i'), 'む': ('m', 'u'), 'め': ('m', 'e'), 'も': ('m', 'o'),
    'や': ('y', 'a'), 'ゆ': ('y', 'u'), 'よ': ('y', 'o'),
    'ゃ': ('y', 'a'), 'ゅ': ('y', 'u'), 'ょ': ('y', 'o'),
    'ら': ('r', 'a'), 'り': ('r', 'i'), 'る': ('r', 'u'), 'れ': ('r', 'e'), 'ろ': ('r', 'o'),
    'わ': ('w', 'a'), 'を': (None, 'o'), 'ん': ('nn', 'n'), 'っ': (None, None), 'ー': (None, None),
}

# Formants (F1, F2, F3) in Hz for Japanese vowels (slightly bright/robotic character)
VOWEL_FORMANTS = {
    'a': [(750.0, 90.0, 1.0), (1280.0, 110.0, 0.75), (2600.0, 150.0, 0.35)],
    'i': [(320.0, 70.0, 1.0), (2250.0, 130.0, 0.70), (3050.0, 180.0, 0.35)],
    'u': [(360.0, 80.0, 1.0), (1100.0, 100.0, 0.55), (2350.0, 150.0, 0.30)],
    'e': [(500.0, 85.0, 1.0), (1900.0, 120.0, 0.70), (2650.0, 160.0, 0.35)],
    'o': [(520.0, 85.0, 1.0), (920.0, 100.0, 0.65), (2450.0, 150.0, 0.30)],
    'n': [(260.0, 70.0, 0.9), (1050.0, 120.0, 0.35), (2200.0, 160.0, 0.20)],
}


def _katakana_to_hiragana(text: str) -> str:
    res = []
    for ch in text:
        code = ord(ch)
        if 0x30A1 <= code <= 0x30F6:
            res.append(chr(code - 0x60))
        else:
            res.append(ch)
    return "".join(res)


def _midi_to_freq(pitch: int) -> float:
    return 440.0 * (2.0 ** ((pitch - 69) / 12.0))


def _vlq(val: int) -> bytes:
    """Variable-Length Quantity for MIDI."""
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

    uspbeat = int(60_000_000 / max(40, bpm))
    track += b'\x00\xFF\x51\x03' + struct.pack('>I', uspbeat)[1:]

    last_tick = 0
    for ev in events:
        tick = ev[0]
        ev_type = ev[1]
        ch = ev[2] & 0x0F
        delta = max(0, tick - last_tick)
        track += _vlq(delta)

        if ev_type == 'on':
            track += bytes([0x90 | ch, ev[3] & 0x7F, ev[4] & 0x7F])
        elif ev_type == 'off':
            track += bytes([0x80 | ch, ev[3] & 0x7F, 0])
        elif ev_type == 'prog':
            track += bytes([0xC0 | ch, ev[3] & 0x7F])

        last_tick = tick

    track += b'\x00\xFF\x2F\x00'
    header = b'MThd' + struct.pack('>IHHH', 6, 0, 1, ticks_per_beat)
    trk_chunk = b'MTrk' + struct.pack('>I', len(track)) + bytes(track)
    return header + trk_chunk


def _biquad_bp_coeffs(freq: float, bw: float, sr: int):
    """Compute biquad bandpass filter coefficients (normalized)."""
    w0 = 2.0 * math.pi * min(freq, sr * 0.45) / sr
    q = max(1.0, freq / max(20.0, bw))
    alpha = math.sin(w0) / (2.0 * q)
    cos_w0 = math.cos(w0)
    a0 = 1.0 + alpha
    b0 = alpha / a0
    b2 = -alpha / a0
    a1 = (-2.0 * cos_w0) / a0
    a2 = (1.0 - alpha) / a0
    return b0, b2, a1, a2


def _synthesize_vocal_syllable(
    audio_buffer: list,
    sr: int,
    start_sec: float,
    dur_sec: float,
    pitch: int,
    kana: str,
    gain: float = 0.48,
):
    """Synthesize a single Japanese singing syllable using formant biquad resonators."""
    total_samples = len(audio_buffer)
    s_idx = int(start_sec * sr)
    e_idx = min(total_samples, int((start_sec + dur_sec) * sr))
    if e_idx <= s_idx:
        return

    norm_kana = _katakana_to_hiragana(kana.strip())
    cons, vowel = (None, 'a')
    for ch in norm_kana:
        if ch in KANA_MAP:
            cons, vowel = KANA_MAP[ch]
            if vowel is not None:
                break
    if vowel is None:
        vowel = 'a'

    formants = VOWEL_FORMANTS.get(vowel, VOWEL_FORMANTS['a'])
    f_coeffs = [_biquad_bp_coeffs(f, bw, sr) + (amp,) for (f, bw, amp) in formants]

    base_freq = _midi_to_freq(pitch)
    # Slight pitch scoop at start + crazy vibrato
    vib_rate = random.uniform(5.0, 7.5)
    vib_depth = random.uniform(0.012, 0.028)
    scoop_offset = random.choice([-0.08, -0.04, 0.0, 0.05])

    # Consonant burst duration
    cons_dur = 0.032 if cons in ('s', 'h', 't', 'k', 'p', 'z') else (0.018 if cons else 0.0)
    cons_samples = int(cons_dur * sr)

    # Filter state for 3 parallel formants: (x1, x2, y1, y2)
    f_state = [[0.0, 0.0, 0.0, 0.0] for _ in range(3)]
    phase = 0.0
    n_samples = e_idx - s_idx

    for idx in range(n_samples):
        local_t = idx / sr
        progress = idx / max(1, n_samples)

        # Envelope
        attack = min(1.0, local_t / 0.015)
        release = min(1.0, (dur_sec - local_t) / 0.025)
        env = max(0.0, min(attack, release))

        # Pitch with scoop & vibrato
        scoop = scoop_offset * math.exp(-local_t * 28.0)
        vib = vib_depth * math.sin(2.0 * math.pi * vib_rate * local_t) if local_t > 0.06 else 0.0
        cur_freq = base_freq * (1.0 + scoop + vib)
        phase = (phase + cur_freq / sr) % 1.0

        # Glottal-like pulse + sawtooth excitation
        exc = (2.0 * phase - 1.0) * 0.65 + (0.5 if phase < 0.18 else -0.15)

        # Consonant noise/burst
        if idx < cons_samples:
            noise = random.uniform(-1.0, 1.0)
            if cons in ('s', 'z', 'h'):
                exc = exc * 0.35 + noise * 0.75
            else:
                exc = exc * 0.55 + noise * 0.55

        out = 0.0
        for fi, (b0, b2, a1, a2, amp) in enumerate(f_coeffs):
            x1, x2, y1, y2 = f_state[fi]
            y0 = b0 * exc + b2 * x2 - a1 * y1 - a2 * y2
            f_state[fi][0] = exc
            f_state[fi][1] = x1
            f_state[fi][2] = y0
            f_state[fi][3] = y1
            out += y0 * amp

        audio_buffer[s_idx + idx] += out * env * gain


def _add_fm_bell(audio_buffer: list, sr: int, start_sec: float, dur_sec: float, freq: float, gain: float = 0.18):
    total_samples = len(audio_buffer)
    s_idx = int(start_sec * sr)
    e_idx = min(total_samples, int((start_sec + dur_sec) * sr))
    mod_ratio = random.choice([1.414, 2.0, 2.756, 3.5])
    mod_index = random.uniform(2.0, 5.5)
    for i in range(s_idx, e_idx):
        lt = (i - s_idx) / sr
        env = math.exp(-lt * 6.5)
        mod = mod_index * math.exp(-lt * 8.0) * math.sin(2.0 * math.pi * freq * mod_ratio * lt)
        val = math.sin(2.0 * math.pi * freq * lt + mod)
        audio_buffer[i] += val * env * gain


def _add_chord_pad(audio_buffer: list, sr: int, start_sec: float, dur_sec: float, pitches: list, gain: float = 0.09):
    total_samples = len(audio_buffer)
    s_idx = int(start_sec * sr)
    e_idx = min(total_samples, int((start_sec + dur_sec) * sr))
    freqs = [_midi_to_freq(p) for p in pitches]
    for i in range(s_idx, e_idx):
        lt = (i - s_idx) / sr
        attack = min(1.0, lt / 0.05)
        release = min(1.0, (dur_sec - lt) / 0.08)
        env = max(0.0, min(attack, release))
        val = 0.0
        for f in freqs:
            p1 = (lt * f) % 1.0
            p2 = (lt * f * 1.006) % 1.0
            val += ((2.0 * p1 - 1.0) + (2.0 * p2 - 1.0)) * 0.5
        audio_buffer[i] += (val / max(1, len(freqs))) * env * gain


def _add_pluck(audio_buffer: list, sr: int, start_sec: float, dur_sec: float, freq: float, gain: float = 0.16):
    total_samples = len(audio_buffer)
    s_idx = int(start_sec * sr)
    e_idx = min(total_samples, int((start_sec + dur_sec) * sr))
    for i in range(s_idx, e_idx):
        lt = (i - s_idx) / sr
        env = math.exp(-lt * 14.0)
        val = (
            0.55 * math.sin(2.0 * math.pi * freq * lt)
            + 0.30 * math.sin(4.0 * math.pi * freq * lt)
            + 0.15 * math.sin(6.0 * math.pi * freq * lt)
        )
        audio_buffer[i] += val * env * gain


def _apply_delay_and_soft_clip(audio_buffer: list, sr: int, delay_sec: float = 0.18, feedback: float = 0.25):
    delay_samples = int(delay_sec * sr)
    n = len(audio_buffer)
    for i in range(delay_samples, n):
        audio_buffer[i] += audio_buffer[i - delay_samples] * feedback
    for i in range(n):
        audio_buffer[i] = math.tanh(audio_buffer[i] * 1.15)


def generate_crazy_music(
    output_dir: str = None,
    composition: dict = None,
    vocal_notes: list = None,
) -> tuple[str, str]:
    """
    ロックス特製のめちゃくちゃででたらめな狂気の曲（多楽器ミックス・AI作曲・ボーカル対応）を生成する。
    composition: {"bpm": int, "scale": str, "instruments": [...], "melody_intervals": [...]}
    vocal_notes: [{"kana": "あ", "pitch": 64, "beats": 0.5}, ...]
    戻り値: (midi_file_path, mp3_file_path)
    """
    if not output_dir:
        output_dir = tempfile.gettempdir()

    sr = 22050
    comp = composition if isinstance(composition, dict) else {}
    bpm = int(comp.get("bpm", random.randint(150, 240)))
    bpm = max(100, min(280, bpm))

    scale_name = comp.get("scale", random.choice(list(SCALE_PALETTES.keys())))
    crazy_scale = SCALE_PALETTES.get(scale_name, random.choice(list(SCALE_PALETTES.values())))

    instruments = comp.get("instruments")
    if not isinstance(instruments, list) or not instruments:
        instruments = random.sample(["lead", "fm_bell", "pad", "pluck"], k=random.randint(3, 4))

    beat_step = 60.0 / bpm
    ticks_per_beat = 480
    seconds_per_tick = beat_step / ticks_per_beat

    # Determine duration (fit vocal_notes if present, otherwise 8-11 sec)
    if vocal_notes:
        total_vocal_beats = sum(max(0.15, float(n.get("beats", 0.5))) for n in vocal_notes)
        duration = max(7.5, min(16.0, total_vocal_beats * beat_step + 0.8))
    else:
        duration = random.uniform(8.0, 11.5)

    total_samples = int(sr * duration)
    audio_buffer = [0.0] * total_samples

    midi_events = []
    # Multi-channel GM Program Changes
    midi_events.append((0, 'prog', 0, random.choice([80, 81, 87, 30]), 0))  # Lead
    midi_events.append((0, 'prog', 1, random.choice([38, 39, 34, 35]), 0))  # Bass
    midi_events.append((0, 'prog', 2, random.choice([10, 14, 98, 102]), 0)) # FM Bell
    midi_events.append((0, 'prog', 3, random.choice([18, 50, 89, 95]), 0))  # Pad / Organ
    midi_events.append((0, 'prog', 4, random.choice([25, 29, 46, 107]), 0)) # Pluck
    midi_events.append((0, 'prog', 5, 54, 0))                               # Synth Voice

    # 1. Chord Pad / Organ (Channel 3)
    if "pad" in instruments:
        t = 0.0
        chord_dur = beat_step * 2.0
        while t < duration:
            root_idx = random.randint(0, max(0, len(crazy_scale) - 5))
            chord_pitches = [
                crazy_scale[root_idx],
                crazy_scale[min(len(crazy_scale) - 1, root_idx + 2)],
                crazy_scale[min(len(crazy_scale) - 1, root_idx + 4)],
            ]
            st_tk = int(t / seconds_per_tick)
            en_tk = int(min(duration, t + chord_dur * 0.95) / seconds_per_tick)
            for p in chord_pitches:
                midi_events.append((st_tk, 'on', 3, p, 70))
                midi_events.append((en_tk, 'off', 3, p, 0))
            _add_chord_pad(audio_buffer, sr, t, min(chord_dur, duration - t), chord_pitches, gain=0.10)
            t += chord_dur

    # 2. Lead Synth (Channel 0)
    if "lead" in instruments:
        t = 0.0
        while t < duration:
            note_dur = random.choice([0.06, 0.09, 0.12, 0.18, 0.24])
            if random.random() < 0.88:
                pitch = random.choice(crazy_scale)
                freq = _midi_to_freq(pitch)
                vel = random.randint(80, 120)
                st_tk = int(t / seconds_per_tick)
                en_tk = int(min(duration, t + note_dur * 0.9) / seconds_per_tick)
                midi_events.append((st_tk, 'on', 0, pitch, vel))
                midi_events.append((en_tk, 'off', 0, pitch, 0))

                s_idx = int(t * sr)
                e_idx = min(total_samples, int((t + note_dur) * sr))
                bend = random.choice([0.0, -0.05, 0.08, 0.14]) if random.random() < 0.35 else 0.0
                wave_type = random.choice(['square', 'saw', 'pulse'])
                lead_gain = 0.14 if vocal_notes else 0.22

                for i in range(s_idx, e_idx):
                    lt = (i - s_idx) / sr
                    env = math.exp(-lt * 8.0)
                    cur_f = freq * (1.0 + bend * (lt / note_dur))
                    ph = (lt * cur_f) % 1.0
                    if wave_type == 'square':
                        val = 0.6 if ph < 0.5 else -0.6
                    elif wave_type == 'saw':
                        val = 2.0 * ph - 1.0
                    else:
                        val = 0.8 if ph < 0.25 else -0.2
                    audio_buffer[i] += val * env * lead_gain
            t += note_dur

    # 3. FM Bell / Sci-Fi Synth (Channel 2)
    if "fm_bell" in instruments:
        t = 0.0
        while t < duration:
            step_dur = random.choice([beat_step * 0.5, beat_step, beat_step * 1.5])
            if random.random() < 0.72:
                pitch = random.choice([p for p in crazy_scale if p >= 60] or crazy_scale)
                st_tk = int(t / seconds_per_tick)
                en_tk = int(min(duration, t + step_dur * 0.85) / seconds_per_tick)
                midi_events.append((st_tk, 'on', 2, pitch, 90))
                midi_events.append((en_tk, 'off', 2, pitch, 0))
                _add_fm_bell(audio_buffer, sr, t, min(0.35, duration - t), _midi_to_freq(pitch), gain=0.14)
            t += step_dur

    # 4. Pluck / Fast Arp (Channel 4)
    if "pluck" in instruments:
        t = 0.0
        arp_step = beat_step * 0.25
        while t < duration:
            if random.random() < 0.75:
                pitch = random.choice(crazy_scale)
                st_tk = int(t / seconds_per_tick)
                en_tk = int(min(duration, t + arp_step * 0.8) / seconds_per_tick)
                midi_events.append((st_tk, 'on', 4, pitch, 85))
                midi_events.append((en_tk, 'off', 4, pitch, 0))
                _add_pluck(audio_buffer, sr, t, min(0.22, duration - t), _midi_to_freq(pitch), gain=0.13)
            t += arp_step

    # 5. Bass (Channel 1)
    t = 0.0
    while t < duration:
        bass_dur = random.choice([beat_step * 0.5, beat_step, beat_step * 1.5])
        if random.random() < 0.85:
            bass_pitch = random.choice([36, 38, 41, 42, 43, 46, 48])
            freq = _midi_to_freq(bass_pitch)
            st_tk = int(t / seconds_per_tick)
            en_tk = int(min(duration, t + bass_dur * 0.85) / seconds_per_tick)
            midi_events.append((st_tk, 'on', 1, bass_pitch, 105))
            midi_events.append((en_tk, 'off', 1, bass_pitch, 0))

            s_idx = int(t * sr)
            e_idx = min(total_samples, int((t + bass_dur) * sr))
            for i in range(s_idx, e_idx):
                lt = (i - s_idx) / sr
                env = math.exp(-lt * 4.5)
                ph = (lt * freq) % 1.0
                tri = 4.0 * abs(ph - 0.5) - 1.0
                sub = math.sin(2.0 * math.pi * freq * lt)
                audio_buffer[i] += (tri * 0.6 + sub * 0.4) * env * 0.28
        t += bass_dur

    # 6. Drums (Channel 9: Kick=36, Snare=38, Hi-Hat=42)
    t = 0.0
    step_idx = 0
    sub_step = beat_step * 0.5
    while t < duration:
        st_tk = int(t / seconds_per_tick)
        # Kick on downbeats or random
        if step_idx % 2 == 0 or random.random() < 0.25:
            midi_events.append((st_tk, 'on', 9, 36, 110))
            midi_events.append((st_tk + 120, 'off', 9, 36, 0))
            s_idx = int(t * sr)
            e_idx = min(total_samples, int((t + 0.12) * sr))
            for i in range(s_idx, e_idx):
                lt = (i - s_idx) / sr
                k_freq = 150.0 * math.exp(-lt * 30.0) + 40.0
                env = max(0.0, 1.0 - lt / 0.12)
                audio_buffer[i] += math.sin(2.0 * math.pi * k_freq * lt) * env * 0.36

        # Snare on offbeats or random
        if step_idx % 2 == 1 or random.random() < 0.2:
            midi_events.append((st_tk, 'on', 9, 38, 100))
            midi_events.append((st_tk + 120, 'off', 9, 38, 0))
            s_idx = int(t * sr)
            e_idx = min(total_samples, int((t + 0.08) * sr))
            for i in range(s_idx, e_idx):
                lt = (i - s_idx) / sr
                env = math.exp(-lt * 26.0)
                audio_buffer[i] += random.uniform(-1.0, 1.0) * env * 0.20

        # Hi-hat
        if random.random() < 0.75:
            midi_events.append((st_tk, 'on', 9, 42, 75))
            midi_events.append((st_tk + 60, 'off', 9, 42, 0))
            s_idx = int(t * sr)
            e_idx = min(total_samples, int((t + 0.03) * sr))
            for i in range(s_idx, e_idx):
                lt = (i - s_idx) / sr
                env = math.exp(-lt * 65.0)
                audio_buffer[i] += random.uniform(-1.0, 1.0) * env * 0.08

        t += sub_step
        step_idx += 1

    # 7. Vocal Synth (Pattern A: Formant Singing, Channel 5)
    if vocal_notes:
        vt = 0.25
        for note_item in vocal_notes:
            if vt >= duration - 0.15:
                break
            kana = str(note_item.get("kana", "あ"))
            pitch = int(note_item.get("pitch", 64))
            pitch = max(48, min(84, pitch))
            beats = max(0.2, min(2.0, float(note_item.get("beats", 0.5))))
            note_sec = min(beats * beat_step, duration - vt)

            st_tk = int(vt / seconds_per_tick)
            en_tk = int((vt + note_sec * 0.9) / seconds_per_tick)
            midi_events.append((st_tk, 'on', 5, pitch, 115))
            midi_events.append((en_tk, 'off', 5, pitch, 0))

            _synthesize_vocal_syllable(audio_buffer, sr, vt, note_sec * 0.95, pitch, kana, gain=0.52)
            vt += note_sec

    # Apply feedback delay + soft clipping for rich mix
    _apply_delay_and_soft_clip(audio_buffer, sr, delay_sec=0.16, feedback=0.22)

    # 8. Write MIDI
    midi_bytes = _build_midi_file(midi_events, bpm=bpm, ticks_per_beat=ticks_per_beat)
    rand_id = random.randint(1000, 9999)
    midi_path = os.path.join(output_dir, f"rocks_crazy_{rand_id}.mid")
    with open(midi_path, "wb") as f:
        f.write(midi_bytes)

    # 9. Encode MP3 (or WAV fallback)
    pcm_bytes = bytearray()
    for s in audio_buffer:
        s = max(-1.0, min(1.0, s))
        pcm_bytes.extend(struct.pack('<h', int(s * 32767)))

    mp3_path = os.path.join(output_dir, f"rocks_crazy_{rand_id}.mp3")
    encoded = False

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
