#!/usr/bin/env python3
import sys, os, time, json, wave, threading
from pathlib import Path
from openai import OpenAI

sys.path.insert(0, '/debug/tkvoice/src/audio_service')
sys.path.insert(0, '/debug/tkvoice')

os.environ['COSYVOICE_MODEL_DIR'] = '/debug/tkvoice/CosyVoice2-0.5B'
os.environ['COSYVOICE_DIR'] = '/debug/tkvoice'
os.environ['TTS_GAIN'] = '2.5'
os.environ['COSYVOICE_FP16'] = '1'
os.environ['TTS_SPEED'] = '1.05'

from audio_service.cosyvoice_provider import CosyVoiceProvider

BASE = Path('/debug/tkvoice')
REQ = BASE / 'request.json'
ASR_REQ = BASE / 'asr_request.json'
RESP = BASE / 'response.json'
ASR_RESP = BASE / 'asr_response.json'
OUT_WAV = BASE / 'output.wav'
POLL = 0.2

# LLM client
llm = OpenAI(api_key='vllm', base_url='http://localhost:8001/v1/')
llm_model = 'Qwen3'
sys_msg = '你是智能助手，回答简洁，30字以内，用中文。'

print('[PIPE] Loading TTS...', flush=True)
t0 = time.time()
tts = CosyVoiceProvider()
print('[PIPE] TTS ready in %.1fs' % (time.time() - t0), flush=True)
print('[PIPE] Watching %s and %s' % (REQ, ASR_REQ), flush=True)

last_req = 0
last_asr = 0

def ask_llm(text):
    try:
        r = llm.chat.completions.create(
            model=llm_model,
            messages=[{'role': 'system', 'content': sys_msg}, {'role': 'user', 'content': text}],
            max_tokens=128, stream=False
        )
        return r.choices[0].message.content.strip()
    except Exception as e:
        print('[PIPE] LLM error: %s' % e, flush=True)
        return text

def handle_tts(text, req_id=0, resp_file=RESP):
    if not text:
        return
    print('[PIPE] TTS: %s' % text[:60], flush=True)
    pcm = tts.tts(text)
    if pcm:
        with wave.open(str(OUT_WAV), 'wb') as wf:
            wf.setnchannels(1); wf.setsampwidth(2); wf.setframerate(24000)
            wf.writeframes(pcm)
        with open(str(resp_file), 'w') as f:
            json.dump({'type': 'done', 'req_id': req_id, 'bytes': len(pcm)}, f)
        print('[PIPE] Done: %d bytes' % len(pcm), flush=True)

while True:
    if REQ.exists():
        mt = REQ.stat().st_mtime
        if mt > last_req:
            last_req = mt
            try:
                with open(REQ) as f:
                    d = json.load(f)
                handle_tts(d.get('text', ''), d.get('req_id', 0), RESP)
            except Exception as e:
                print('[PIPE] Error: %s' % e, flush=True)

    if ASR_REQ.exists():
        mt = ASR_REQ.stat().st_mtime
        if mt > last_asr:
            last_asr = mt
            try:
                with open(ASR_REQ) as f:
                    d = json.load(f)
                text = d.get('text', '')
                if text:
                    print('[PIPE] ASR: %s' % text[:60], flush=True)
                    reply = ask_llm(text)
                    print('[PIPE] LLM: %s' % reply[:60], flush=True)
                    handle_tts(reply, 0, ASR_RESP)
            except Exception as e:
                print('[PIPE] ASR Error: %s' % e, flush=True)

    time.sleep(POLL)
