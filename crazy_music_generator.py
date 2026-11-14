import os
import math
import struct
import random
import tempfile
import shutil
import subprocess

# Scale presets (MIDI note numbers)
SCALE_PALETTES = {
    "diminished": [48, 51, 54, 57, 60, 63, 66, 69, 72, 75, 78, 81, 84],
    "whole_tone": [48, 50, 52, 54, 56, 58, 60, 62, 64, 66, 68, 70, 72],
    "chromatic_chaos": [48, 49, 53, 54, 55, 59, 60, 61, 65, 66, 67, 71, 72, 73],
    "hyper_penta": [48, 51, 53, 55, 60, 63, 65, 67, 72, 75, 77, 79, 84],
    "minor_crazy": [48, 50, 51, 55, 56, 60, 62, 63, 67, 68, 72, 74, 75, 79],
}

# Japanese kana -> (consonant_type, vowel)
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

VOWEL_FORMANTS = {
    'a': [(750.0, 90.0, 1.0), (1280.0, 110.0, 0.75), (2600.0, 150.0, 0.35)],
    'i': [(320.0, 70.0, 1.0), (2250.0, 130.0, 0.70), (3050.0, 180.0, 0.35)],
    'u': [(360.0, 80.0, 1.0), (1100.0, 100.0, 0.55), (2350.0, 150.0, 0.30)],
    'e': [(500.0, 85.0, 1.0), (1900.0, 120.0, 0.70), (2650.0, 160.0, 0.35)],
    'o': [(520.0, 85.0, 1.0), (920.0, 100.0, 0.65), (2450.0, 150.0, 0.30)],
    'n': [(260.0, 70.0, 0.9), (1050.0, 120.0, 0.35), (2200.0, 160.0, 0.20)],
}

SFX_TYPES = [
    "laser", "explosion", "siren", "cat_meow", "boing",
    "bubble", "thunder", "coin", "glitch", "alarm", "heartbeat"
]


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
    w0 = 2.0 * math.pi * min(freq, sr * 0.45) / sr
    q = max(1.0, freq / max(30.0, bw * 1.5))
    alpha = math.sin(w0) / (2.0 * q)
    cos_w0 = math.cos(w0)
    a0 = 1.0 + alpha
    b0 = alpha / a0
    b2 = -alpha / a0
    a1 = (-2.0 * cos_w0) / a0
    a2 = (1.0 - alpha) / a0
    return b0, b2, a1, a2


def _synthesize_vocal_syllable(
    vocal_buffer: list,
    sr: int,
    start_sec: float,
    dur_sec: float,
    pitch: int,
    kana: str,
    gain: float = 1.0,
):
    """Synthesize an expressive crazy Japanese singing syllable (formants + octave double)."""
    total_samples = len(vocal_buffer)
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
    vib_rate = random.uniform(5.5, 8.5)
    vib_depth = random.uniform(0.018, 0.042)
    scoop_offset = random.choice([-0.12, -0.06, 0.0, 0.08, 0.14])

    cons_dur = 0.030 if cons in ('s', 'h', 't', 'k', 'p', 'z') else (0.016 if cons else 0.0)
    cons_samples = int(cons_dur * sr)

    f_state = [[0.0, 0.0, 0.0, 0.0] for _ in range(3)]
    phase = 0.0
    sub_phase = 0.0
    n_samples = e_idx - s_idx

    for idx in range(n_samples):
        local_t = idx / sr
        attack = min(1.0, local_t / 0.012)
        release = min(1.0, (dur_sec - local_t) / 0.020)
        env = max(0.0, min(attack, release))

        scoop = scoop_offset * math.exp(-local_t * 24.0)
        vib = vib_depth * math.sin(2.0 * math.pi * vib_rate * local_t) if local_t > 0.04 else 0.0
        cur_freq = base_freq * (1.0 + scoop + vib)
        phase = (phase + cur_freq / sr) % 1.0
        sub_phase = (sub_phase + (cur_freq * 0.5) / sr) % 1.0

        exc = (2.0 * phase - 1.0) * 0.70 + (0.65 if phase < 0.22 else -0.18)
        if idx < cons_samples:
            noise = random.uniform(-1.0, 1.0)
            exc = (exc * 0.4 + noise * 0.7) if cons in ('s', 'z', 'h') else (exc * 0.6 + noise * 0.5)

        formant_out = 0.0
        for fi, (b0, b2, a1, a2, amp) in enumerate(f_coeffs):
            x1, x2, y1, y2 = f_state[fi]
            y0 = b0 * exc + b2 * x2 - a1 * y1 - a2 * y2
            f_state[fi][0] = exc
            f_state[fi][1] = x1
            f_state[fi][2] = y0
            f_state[fi][3] = y1
            formant_out += y0 * amp

        # Direct pitch + subtle octave-down robotic harmony
        direct_tone = (
            0.24 * math.sin(2.0 * math.pi * phase)
            + 0.12 * math.sin(4.0 * math.pi * phase)
            + 0.08 * math.sin(2.0 * math.pi * sub_phase)
        )
        vocal_buffer[s_idx + idx] += (formant_out * 1.9 + direct_tone) * env * gain


# ==============================================================================
# New Bold Instrument Palette (No electric-piano sine plucks!)
# ==============================================================================

def _add_supersaw_chord(audio_buffer: list, sr: int, start_sec: float, dur_sec: float, pitches: list, gain: float = 0.22):
    """Massive detuned supersaw synth pad / stab."""
    total_samples = len(audio_buffer)
    s_idx = int(start_sec * sr)
    e_idx = min(total_samples, int((start_sec + dur_sec) * sr))
    freqs = [_midi_to_freq(p) for p in pitches]
    detunes = (0.991, 1.0, 1.009)
    for i in range(s_idx, e_idx):
        lt = (i - s_idx) / sr
        attack = min(1.0, lt / 0.025)
        release = min(1.0, (dur_sec - lt) / 0.06)
        env = max(0.0, min(attack, release))
        val = 0.0
        for f in freqs:
            for dt in detunes:
                ph = (lt * f * dt) % 1.0
                val += 2.0 * ph - 1.0
        audio_buffer[i] += (val / (len(freqs) * len(detunes))) * env * gain


def _add_distorted_guitar(audio_buffer: list, sr: int, start_sec: float, dur_sec: float, freq: float, gain: float = 0.24):
    """Overdriven waveshaped power-chord synth."""
    total_samples = len(audio_buffer)
    s_idx = int(start_sec * sr)
    e_idx = min(total_samples, int((start_sec + dur_sec) * sr))
    f5 = freq * 1.498  # Power chord 5th
    for i in range(s_idx, e_idx):
        lt = (i - s_idx) / sr
        env = math.exp(-lt * 4.5)
        raw = ((lt * freq) % 1.0) * 2.0 - 1.0 + (((lt * f5) % 1.0) * 2.0 - 1.0) * 0.7
        distorted = math.tanh(raw * 3.8)
        audio_buffer[i] += distorted * env * gain


def _add_acid_bass(audio_buffer: list, sr: int, start_sec: float, dur_sec: float, freq: float, gain: float = 0.30):
    """303-style resonant squelchy acid synth bass."""
    total_samples = len(audio_buffer)
    s_idx = int(start_sec * sr)
    e_idx = min(total_samples, int((start_sec + dur_sec) * sr))
    for i in range(s_idx, e_idx):
        lt = (i - s_idx) / sr
        env = math.exp(-lt * 5.0)
        saw = 2.0 * ((lt * freq) % 1.0) - 1.0
        res_freq = freq * (2.0 + 6.0 * math.exp(-lt * 14.0))
        squelch = math.sin(2.0 * math.pi * res_freq * lt) * math.exp(-lt * 10.0)
        audio_buffer[i] += math.tanh((saw * 0.65 + squelch * 0.65) * 1.6) * env * gain


def _add_wobble_bass(audio_buffer: list, sr: int, start_sec: float, dur_sec: float, freq: float, gain: float = 0.28):
    """Dubstep-style LFO wobble FM growl."""
    total_samples = len(audio_buffer)
    s_idx = int(start_sec * sr)
    e_idx = min(total_samples, int((start_sec + dur_sec) * sr))
    lfo_hz = random.choice([4.0, 6.0, 8.0, 12.0])
    for i in range(s_idx, e_idx):
        lt = (i - s_idx) / sr
        env = min(1.0, lt / 0.015) * math.exp(-lt * 1.8)
        lfo = 0.5 + 0.5 * math.sin(2.0 * math.pi * lfo_hz * lt)
        mod = (1.5 + 4.5 * lfo) * math.sin(2.0 * math.pi * freq * 2.0 * lt)
        val = math.tanh(math.sin(2.0 * math.pi * freq * lt + mod) * 2.0)
        audio_buffer[i] += val * env * gain


def _add_chiptune_lead(audio_buffer: list, sr: int, start_sec: float, dur_sec: float, freq: float, gain: float = 0.22):
    """8-bit GameBoy/NES duty-cycle lead with fast vibrato & pitch slide."""
    total_samples = len(audio_buffer)
    s_idx = int(start_sec * sr)
    e_idx = min(total_samples, int((start_sec + dur_sec) * sr))
    duty = random.choice([0.125, 0.25, 0.5])
    bend = random.choice([0.0, -0.06, 0.08, 0.15]) if random.random() < 0.4 else 0.0
    for i in range(s_idx, e_idx):
        lt = (i - s_idx) / sr
        env = math.exp(-lt * 6.0)
        cur_f = freq * (1.0 + bend * (lt / max(0.01, dur_sec)))
        ph = (lt * cur_f) % 1.0
        val = 0.75 if ph < duty else -0.75
        audio_buffer[i] += val * env * gain


# ==============================================================================
# Keyword-driven Procedural Sound Effects (SFX)
# ==============================================================================

def _add_sfx(audio_buffer: list, sr: int, start_sec: float, sfx_type: str, gain: float = 0.34):
    """Forcibly mash a procedural sound effect into the track based on user keywords."""
    total_samples = len(audio_buffer)
    s_idx = int(start_sec * sr)

    if sfx_type == "laser":
        dur = 0.28
        e_idx = min(total_samples, int((start_sec + dur) * sr))
        for i in range(s_idx, e_idx):
            lt = (i - s_idx) / sr
            f = 1800.0 * math.exp(-lt * 11.0) + 180.0
            audio_buffer[i] += math.sin(2.0 * math.pi * f * lt) * (1.0 - lt / dur) * gain

    elif sfx_type == "explosion":
        dur = 0.55
        e_idx = min(total_samples, int((start_sec + dur) * sr))
        lp = 0.0
        for i in range(s_idx, e_idx):
            lt = (i - s_idx) / sr
            env = math.exp(-lt * 5.0)
            lp = lp * 0.82 + random.uniform(-1.0, 1.0) * 0.18
            boom = math.sin(2.0 * math.pi * (95.0 * math.exp(-lt * 6.0) + 32.0) * lt)
            audio_buffer[i] += math.tanh((lp * 3.5 + boom * 0.8) * 1.5) * env * gain

    elif sfx_type == "siren":
        dur = 0.65
        e_idx = min(total_samples, int((start_sec + dur) * sr))
        for i in range(s_idx, e_idx):
            lt = (i - s_idx) / sr
            f = 680.0 + 320.0 * math.sin(2.0 * math.pi * 4.5 * lt)
            ph = (lt * f) % 1.0
            audio_buffer[i] += (0.6 if ph < 0.5 else -0.6) * min(1.0, (dur - lt) / 0.05) * gain * 0.75

    elif sfx_type == "cat_meow":
        dur = 0.42
        e_idx = min(total_samples, int((start_sec + dur) * sr))
        for i in range(s_idx, e_idx):
            lt = (i - s_idx) / sr
            p = lt / dur
            f = 420.0 + 380.0 * math.sin(math.pi * p)
            env = math.sin(math.pi * p)
            val = math.sin(2.0 * math.pi * f * lt) * 0.6 + math.sin(4.0 * math.pi * f * lt) * 0.4
            audio_buffer[i] += val * env * gain

    elif sfx_type == "boing":
        dur = 0.35
        e_idx = min(total_samples, int((start_sec + dur) * sr))
        for i in range(s_idx, e_idx):
            lt = (i - s_idx) / sr
            f = 180.0 + 420.0 * (lt / dur) + 60.0 * math.sin(2.0 * math.pi * 22.0 * lt)
            audio_buffer[i] += math.sin(2.0 * math.pi * f * lt) * math.exp(-lt * 4.5) * gain

    elif sfx_type == "bubble":
        dur = 0.16
        e_idx = min(total_samples, int((start_sec + dur) * sr))
        f0 = random.uniform(300.0, 600.0)
        for i in range(s_idx, e_idx):
            lt = (i - s_idx) / sr
            f = f0 * (1.0 + 2.2 * (lt / dur))
            audio_buffer[i] += math.sin(2.0 * math.pi * f * lt) * math.sin(math.pi * lt / dur) * gain

    elif sfx_type == "thunder":
        dur = 0.75
        e_idx = min(total_samples, int((start_sec + dur) * sr))
        lp = 0.0
        for i in range(s_idx, e_idx):
            lt = (i - s_idx) / sr
            env = math.exp(-lt * 2.8) * (0.6 + 0.4 * math.sin(2.0 * math.pi * 9.0 * lt))
            lp = lp * 0.88 + random.uniform(-1.0, 1.0) * 0.12
            audio_buffer[i] += math.tanh(lp * 5.0) * env * gain

    elif sfx_type == "coin":
        dur = 0.25
        e_idx = min(total_samples, int((start_sec + dur) * sr))
        for i in range(s_idx, e_idx):
            lt = (i - s_idx) / sr
            f = 987.77 if lt < 0.07 else 1318.51
            ph = (lt * f) % 1.0
            audio_buffer[i] += (0.5 if ph < 0.5 else -0.5) * math.exp(-lt * 7.0) * gain

    elif sfx_type == "alarm":
        dur = 0.45
        e_idx = min(total_samples, int((start_sec + dur) * sr))
        for i in range(s_idx, e_idx):
            lt = (i - s_idx) / sr
            gate = 1.0 if (int(lt * 16) % 2 == 0) else 0.0
            ph = (lt * 1046.5) % 1.0
            audio_buffer[i] += (0.6 if ph < 0.5 else -0.6) * gate * gain * 0.8

    elif sfx_type == "heartbeat":
        for offset in (0.0, 0.16):
            os_idx = int((start_sec + offset) * sr)
            oe_idx = min(total_samples, int((start_sec + offset + 0.14) * sr))
            for i in range(os_idx, oe_idx):
                lt = (i - os_idx) / sr
                f = 75.0 * math.exp(-lt * 18.0) + 38.0
                audio_buffer[i] += math.sin(2.0 * math.pi * f * lt) * math.exp(-lt * 14.0) * gain * 1.2

    else:  # glitch
        dur = 0.20
        e_idx = min(total_samples, int((start_sec + dur) * sr))
        hold = 0.0
        for i in range(s_idx, e_idx):
            if i % random.randint(4, 18) == 0:
                hold = random.uniform(-0.8, 0.8)
            audio_buffer[i] += hold * gain


def _apply_delay_and_soft_clip(audio_buffer: list, sr: int, delay_sec: float = 0.15, feedback: float = 0.20):
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
    ロックス特製のめちゃくちゃででたらめな狂気の曲（新楽器群・キーワードSE強制ミックス・ボーカル対応）を生成する。
    """
    if not output_dir:
        output_dir = tempfile.gettempdir()

    sr = 22050
    comp = composition if isinstance(composition, dict) else {}
    bpm = int(comp.get("bpm", random.randint(145, 220)))
    bpm = max(100, min(260, bpm))

    scale_name = comp.get("scale", random.choice(list(SCALE_PALETTES.keys())))
    crazy_scale = SCALE_PALETTES.get(scale_name, random.choice(list(SCALE_PALETTES.values())))

    valid_insts = ["supersaw", "distorted_guitar", "chiptune_8bit", "acid_bass", "wobble_dubstep"]
    instruments = comp.get("instruments")
    if not isinstance(instruments, list) or not instruments:
        instruments = random.sample(valid_insts, k=random.randint(3, 4))

    sfx_list = comp.get("sfx")
    if not isinstance(sfx_list, list):
        sfx_list = []

    beat_step = 60.0 / bpm
    ticks_per_beat = 480
    seconds_per_tick = beat_step / ticks_per_beat

    if vocal_notes:
        total_vocal_beats = sum(max(0.25, float(n.get("beats", 0.5))) for n in vocal_notes)
        duration = max(8.0, min(16.0, total_vocal_beats * beat_step + 1.0))
    else:
        duration = random.uniform(8.5, 11.5)

    total_samples = int(sr * duration)
    audio_buffer = [0.0] * total_samples

    midi_events = []
    midi_events.append((0, 'prog', 0, 81, 0))  # Lead / Supersaw
    midi_events.append((0, 'prog', 1, 38, 0))  # Synth Bass / Acid
    midi_events.append((0, 'prog', 2, 30, 0))  # Distortion Guitar
    midi_events.append((0, 'prog', 3, 87, 0))  # Bass+Lead / Wobble
    midi_events.append((0, 'prog', 4, 80, 0))  # Square Chiptune
    midi_events.append((0, 'prog', 5, 54, 0))  # Synth Voice

    # 1. Supersaw Chords (Channel 0)
    if "supersaw" in instruments:
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
                midi_events.append((st_tk, 'on', 0, p, 85))
                midi_events.append((en_tk, 'off', 0, p, 0))
            _add_supersaw_chord(audio_buffer, sr, t, min(chord_dur, duration - t), chord_pitches, gain=0.22)
            t += chord_dur

    # 2. Distorted Guitar Power Riffs (Channel 2)
    if "distorted_guitar" in instruments:
        t = 0.0
        while t < duration:
            riff_dur = random.choice([beat_step * 0.5, beat_step])
            if random.random() < 0.80:
                pitch = random.choice([p for p in crazy_scale if 48 <= p <= 67] or crazy_scale)
                st_tk = int(t / seconds_per_tick)
                en_tk = int(min(duration, t + riff_dur * 0.9) / seconds_per_tick)
                midi_events.append((st_tk, 'on', 2, pitch, 105))
                midi_events.append((en_tk, 'off', 2, pitch, 0))
                _add_distorted_guitar(audio_buffer, sr, t, min(riff_dur, duration - t), _midi_to_freq(pitch), gain=0.22)
            t += riff_dur

    # 3. 8-bit Chiptune Lead (Channel 4)
    if "chiptune_8bit" in instruments:
        t = 0.0
        while t < duration:
            note_dur = random.choice([beat_step * 0.25, beat_step * 0.5])
            if random.random() < 0.85:
                pitch = random.choice([p for p in crazy_scale if p >= 60] or crazy_scale)
                st_tk = int(t / seconds_per_tick)
                en_tk = int(min(duration, t + note_dur * 0.85) / seconds_per_tick)
                midi_events.append((st_tk, 'on', 4, pitch, 95))
                midi_events.append((en_tk, 'off', 4, pitch, 0))
                _add_chiptune_lead(audio_buffer, sr, t, min(note_dur, duration - t), _midi_to_freq(pitch), gain=0.20)
            t += note_dur

    # 4. Wobble Dubstep Growl (Channel 3)
    if "wobble_dubstep" in instruments:
        t = 0.0
        while t < duration:
            w_dur = beat_step * random.choice([1.0, 2.0])
            if random.random() < 0.72:
                pitch = random.choice([36, 38, 41, 43, 46, 48])
                st_tk = int(t / seconds_per_tick)
                en_tk = int(min(duration, t + w_dur * 0.9) / seconds_per_tick)
                midi_events.append((st_tk, 'on', 3, pitch, 110))
                midi_events.append((en_tk, 'off', 3, pitch, 0))
                _add_wobble_bass(audio_buffer, sr, t, min(w_dur, duration - t), _midi_to_freq(pitch), gain=0.26)
            t += w_dur

    # 5. Acid 303 Bass (Channel 1, always active)
    t = 0.0
    while t < duration:
        b_dur = beat_step * random.choice([0.5, 0.75, 1.0])
        if random.random() < 0.88:
            pitch = random.choice([36, 38, 41, 42, 43, 46, 48])
            st_tk = int(t / seconds_per_tick)
            en_tk = int(min(duration, t + b_dur * 0.85) / seconds_per_tick)
            midi_events.append((st_tk, 'on', 1, pitch, 110))
            midi_events.append((en_tk, 'off', 1, pitch, 0))
            _add_acid_bass(audio_buffer, sr, t, min(b_dur, duration - t), _midi_to_freq(pitch), gain=0.28)
        t += b_dur

    # 6. Heavy Drums (Channel 9)
    t = 0.0
    step_idx = 0
    sub_step = beat_step * 0.5
    while t < duration:
        st_tk = int(t / seconds_per_tick)
        if step_idx % 2 == 0 or random.random() < 0.25:
            midi_events.append((st_tk, 'on', 9, 36, 120))
            midi_events.append((st_tk + 120, 'off', 9, 36, 0))
            s_idx = int(t * sr)
            e_idx = min(total_samples, int((t + 0.14) * sr))
            for i in range(s_idx, e_idx):
                lt = (i - s_idx) / sr
                k_freq = 165.0 * math.exp(-lt * 28.0) + 42.0
                env = max(0.0, 1.0 - lt / 0.14)
                audio_buffer[i] += math.tanh(math.sin(2.0 * math.pi * k_freq * lt) * 1.6) * env * 0.42

        if step_idx % 2 == 1 or random.random() < 0.2:
            midi_events.append((st_tk, 'on', 9, 38, 110))
            midi_events.append((st_tk + 120, 'off', 9, 38, 0))
            s_idx = int(t * sr)
            e_idx = min(total_samples, int((t + 0.09) * sr))
            for i in range(s_idx, e_idx):
                lt = (i - s_idx) / sr
                env = math.exp(-lt * 24.0)
                snap = math.sin(2.0 * math.pi * 200.0 * math.exp(-lt * 25.0) * lt)
                audio_buffer[i] += (random.uniform(-1.0, 1.0) * 0.75 + snap * 0.5) * env * 0.28

        if random.random() < 0.8:
            midi_events.append((st_tk, 'on', 9, 42, 80))
            midi_events.append((st_tk + 60, 'off', 9, 42, 0))
            s_idx = int(t * sr)
            e_idx = min(total_samples, int((t + 0.035) * sr))
            for i in range(s_idx, e_idx):
                lt = (i - s_idx) / sr
                audio_buffer[i] += random.uniform(-1.0, 1.0) * math.exp(-lt * 60.0) * 0.11

        t += sub_step
        step_idx += 1

    # 7. Forcibly Mash Keyword-Driven SFX into the Mix!
    if sfx_list:
        sfx_t = 0.3
        while sfx_t < duration - 0.5:
            sfx_name = random.choice(sfx_list)
            _add_sfx(audio_buffer, sr, sfx_t, sfx_name, gain=0.40)
            sfx_t += random.uniform(1.1, 2.2)

    # 8. Vocal Synth (Channel 5)
    vocal_buffer = [0.0] * total_samples if vocal_notes else None
    if vocal_notes:
        vt = 0.20
        for note_item in vocal_notes:
            if vt >= duration - 0.12:
                break
            kana = str(note_item.get("kana", "あ")).strip()
            if not kana or kana in (" ", "　", "、", "。", "！", "？"):
                vt += min(0.12, duration - vt)
                continue
            pitch = int(note_item.get("pitch", 64))
            pitch = max(48, min(84, pitch))
            beats = max(0.3, min(2.0, float(note_item.get("beats", 0.5))))
            note_sec = min(max(0.18, beats * beat_step), duration - vt)

            st_tk = int(vt / seconds_per_tick)
            en_tk = int((vt + note_sec * 0.9) / seconds_per_tick)
            midi_events.append((st_tk, 'on', 5, pitch, 120))
            midi_events.append((en_tk, 'off', 5, pitch, 0))

            _synthesize_vocal_syllable(vocal_buffer, sr, vt, note_sec * 0.95, pitch, kana, gain=1.0)
            vt += note_sec

    # Keep BGM loud & energetic even when vocal is present!
    _apply_delay_and_soft_clip(audio_buffer, sr, delay_sec=0.15, feedback=0.20)
    if vocal_buffer:
        v_peak = max((abs(x) for x in vocal_buffer), default=0.0)
        v_scale = (0.85 / v_peak) if v_peak > 1e-6 else 1.0
        for i in range(total_samples):
            mixed = audio_buffer[i] * 0.78 + vocal_buffer[i] * v_scale
            audio_buffer[i] = math.tanh(mixed * 1.15)

    # 9. Write MIDI
    midi_bytes = _build_midi_file(midi_events, bpm=bpm, ticks_per_beat=ticks_per_beat)
    rand_id = random.randint(1000, 9999)
    midi_path = os.path.join(output_dir, f"rocks_crazy_{rand_id}.mid")
    with open(midi_path, "wb") as f:
        f.write(midi_bytes)

    # 10. Encode MP3 (or WAV fallback)
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
