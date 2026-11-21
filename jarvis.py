"""
JARVIS v4 - assistant vocal personnel pour Windows.
Voix, cascade d'IA, briefing du matin, agenda, rappels, mails,
accès iPhone (Tailscale), gestes, carte, auto-amélioration.
"""
import os, sys, json, time, threading, subprocess, webbrowser
import datetime, re, queue, ctypes, shutil, winreg, socket
import urllib.request, urllib.parse, random, sqlite3
import http.server, socketserver, base64, smtplib, ssl
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart

# --- AUTO-INSTALL
PKGS = [
    ("speechrecognition","speech_recognition"),("pyttsx3",None),
    ("requests",None),("keyboard",None),("psutil",None),("pyaudio",None),
    ("pillow","PIL"),("pywin32","win32api"),("pygetwindow","pygetwindow"),
    ("pyautogui",None),("colorama",None),("numpy",None),
    ("opencv-python","cv2"),("schedule",None),
    ("deep-translator","deep_translator"),("mediapipe",None),
    ("google-generativeai","google.generativeai"),
    ("pygame",None),("instagrapi",None),
    ("python-dateutil","dateutil"),("tzdata",None),
]
def install(p, i=None):
    try: __import__(i or p); return True
    except ImportError:
        try:
            subprocess.check_call([sys.executable,"-m","pip","install",p,"-q"],
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            return True
        except: return False

print("JARVIS - démarrage...")
for p,i in PKGS: install(p,i)

import speech_recognition as sr
import requests, keyboard, psutil, pyautogui, pygetwindow as gw
import numpy as np, schedule
from PIL import Image, ImageDraw, ImageGrab
import win32api, win32con, win32gui, win32process
from colorama import Fore, Style, init as colorama_init
colorama_init(); pyautogui.FAILSAFE=False; pyautogui.PAUSE=0.02

# --- PATHS
BASE   = os.path.dirname(os.path.abspath(__file__))
UI_DIR = os.path.join(BASE,"ui")
BRAIN  = os.path.join(BASE,"brain")
DB     = os.path.join(BRAIN,"memory.db")
CFG_F  = os.path.join(BASE,"config.json")
LOG_F  = os.path.join(BASE,"jarvis.log")
for d in [UI_DIR,BRAIN,os.path.join(BASE,"backups")]:
    os.makedirs(d, exist_ok=True)

# --- CONFIG
CFG = {
    "elevenlabs_key":"YOUR_ELEVENLABS_KEY",
    "elevenlabs_voice_id":"onwK4e9ZLuTAKqWW03F9",
    "voice_speed":168,"voice_volume":0.92,
    "anthropic_key":"YOUR_ANTHROPIC_KEY",
    "groq_key":"YOUR_GROQ_KEY",
    "mistral_key":"YOUR_MISTRAL_KEY",
    "gemini_key":"YOUR_GEMINI_KEY",
    "gemini_pro_key":"YOUR_GEMINI_PRO_KEY",
    "ollama_model":"llama3",
    "gmail_address":"","gmail_app_password":"",
    "instagram_username":"","instagram_password":"",
    "wake_word":"jarvis","alt_wake_words":["hey jarvis","ok jarvis","yo jarvis"],
    "hotkey":"ctrl+shift+j","language":"fr-FR","owner_name":"Patron","ui_port":7474,
    "opera_path":os.path.join(os.environ.get("LOCALAPPDATA",""),r"Programs\Opera\opera.exe"),
    "chrome_path":r"C:\Program Files\Google\Chrome\Application\chrome.exe",
    "wallpaper_folder":os.path.join(os.environ["USERPROFILE"],"Pictures"),
    "auto_learn":True,"confirm_improve":True,"gesture_enabled":False,
    "favorite_genres":["fps","action","rpg"],"crypto_watchlist":["BTC","ETH","SOL"],
    "stock_watchlist":["AAPL","NVDA","MSFT"],
    "obsidian_vault":os.path.join(os.environ["USERPROFILE"],r"iCloudDrive\iCloud~md~obsidian\Amine"),
    "news_auto":True,"news_interests_extra":["science","nouvelles technologies"],
    "remote_enabled":True,"remote_port":7475,"remote_token":"",
    "calendars":[],"server_checks":[],
    "icloud_user":"","icloud_app_password":"","icloud_calendar":"",
}
if os.path.exists(CFG_F):
    with open(CFG_F) as f: CFG.update(json.load(f))
if not CFG.get("remote_token"):
    import secrets
    CFG["remote_token"]=secrets.token_urlsafe(16)
    with open(CFG_F,"w") as _f: json.dump(CFG,_f,indent=2,ensure_ascii=True)
def save_cfg():
    with open(CFG_F,"w") as f: json.dump(CFG,f,indent=2,ensure_ascii=True)

# --- DB
def init_db():
    c=sqlite3.connect(DB); x=c.cursor()
    x.executescript("""
    CREATE TABLE IF NOT EXISTS memory(key TEXT UNIQUE,value TEXT,ts TEXT);
    CREATE TABLE IF NOT EXISTS convos(id INTEGER PRIMARY KEY,role TEXT,
        content TEXT,ts TEXT,ai_used TEXT,app_ctx TEXT);
    CREATE TABLE IF NOT EXISTS habits(cmd TEXT UNIQUE,cnt INTEGER DEFAULT 1,last TEXT,ctx TEXT);
    CREATE TABLE IF NOT EXISTS emails_sent(id INTEGER PRIMARY KEY,
        to_addr TEXT,subject TEXT,body TEXT,ts TEXT,status TEXT);
    CREATE TABLE IF NOT EXISTS scheduled_posts(id INTEGER PRIMARY KEY,
        platform TEXT,content TEXT,scheduled_at TEXT,status TEXT DEFAULT 'pending');
    CREATE TABLE IF NOT EXISTS improvements(id INTEGER PRIMARY KEY,
        title TEXT,code TEXT,status TEXT DEFAULT 'pending',ts TEXT,backup TEXT);
    """); c.commit(); c.close()
init_db()

def db_habit(cmd,ctx=""):
    c=sqlite3.connect(DB)
    r=c.execute("SELECT cnt FROM habits WHERE cmd=?",(cmd,)).fetchone()
    if r: c.execute("UPDATE habits SET cnt=cnt+1,last=?,ctx=? WHERE cmd=?",
        (datetime.datetime.now().isoformat(),ctx,cmd))
    else: c.execute("INSERT INTO habits VALUES(?,1,?,?)",
        (cmd,datetime.datetime.now().isoformat(),ctx))
    c.commit(); c.close()

def db_top_habits(n=10):
    c=sqlite3.connect(DB)
    r=c.execute("SELECT cmd,cnt FROM habits ORDER BY cnt DESC LIMIT ?",(n,)).fetchall()
    c.close(); return r

# --- STATE
S={
    "active":False,"listening":False,"thinking":False,"speaking":False,
    "status":"En veille","convos":[],"metrics":{},"reminders":[],
    "current_app":"","online":True,"concentration_mode":False,"focus_activity":"",
    "last_cmd":"","pending_email":None,"pending_post":None,
    "pending_improvement":None,"local_ai_ok":False,"gesture_active":False,
}
UIQ = queue.Queue()
def push(ev,data): UIQ.put(json.dumps({"event":ev,"data":data}))
def log(msg,col="white"):
    cols={"cyan":Fore.CYAN,"yellow":Fore.YELLOW,"red":Fore.RED,
          "green":Fore.GREEN,"magenta":Fore.MAGENTA,"white":Fore.WHITE}
    print(cols.get(col,Fore.WHITE)+msg+Style.RESET_ALL)
    push("log",{"msg":msg,"color":col})
    with open(LOG_F,"a",encoding="utf-8") as f:
        f.write(f"[{datetime.datetime.now():%H:%M:%S}] {msg}\n")

# --- VOICE
from voice_engine import JarvisVoice, get_line
voice = JarvisVoice(CFG)
def speak(text): voice.speak(text, push_fn=push)

# --- NEWS DU MATIN + COFFRE OBSIDIAN
import news_matin
import briefing_extras as bx
import rappels as rp
import calendrier_icloud as ci
def do_morning_news():
    try: return news_matin.morning_news(CFG, log)
    except Exception as e:
        log(f"[NEWS] {e}","red"); return "Je n'ai pas pu préparer les news."

# --- MIC (ASUS TUF)
rec = sr.Recognizer()
rec.energy_threshold=2200; rec.dynamic_energy_threshold=True; rec.pause_threshold=0.75
# Commandes vocales : 1,5 s de silence = fin de phrase
rec_cmd = sr.Recognizer()
rec_cmd.energy_threshold=2200; rec_cmd.dynamic_energy_threshold=True
rec_cmd.pause_threshold=1.5; rec_cmd.non_speaking_duration=0.8

def listen_wake():
    kws = [CFG["wake_word"]]+CFG.get("alt_wake_words",[])
    with sr.Microphone() as src:
        rec.adjust_for_ambient_noise(src,0.8)
        log(f"[✓] Écoute: {kws}","cyan")
        while True:
            try:
                audio=rec.listen(src,timeout=1,phrase_time_limit=4)
                txt=rec.recognize_google(audio,language=CFG["language"]).lower()
                if any(w in txt for w in kws): activate()
            except: pass

def listen_cmd():
    S["listening"]=True; push("status","EN ÉCOUTE..."); push("orb","listen")
    speak(get_line("activation",CFG["owner_name"]))
    try:
        with sr.Microphone() as src:
            rec_cmd.adjust_for_ambient_noise(src,0.3)
            audio=rec_cmd.listen(src,timeout=9,phrase_time_limit=30)
        txt=rec_cmd.recognize_google(audio,language=CFG["language"])
        push("user_text",txt)
        db_habit(txt[:80],S["current_app"]); return txt
    except sr.WaitTimeoutError: speak("Je n'ai rien entendu.")
    except sr.UnknownValueError: speak("Je n'ai pas compris, répétez.")
    except Exception as e: log(f"[MIC] {e}","red")
    finally: S["listening"]=False
    return None

# --- CASCADE IA: Local→Groq→Mistral→Gemini→GeminiPro→Local
SYS = f"""Tu es JARVIS v4.0, l'IA de {CFG['owner_name']} sur ASUS TUF Gaming Windows.
Caractère: élégant, précis, légèrement sarcastique. Comme le vrai JARVIS d'Iron Man.
Langue: français par défaut. Change si demandé.
Appelle "{CFG['owner_name']}" naturellement, pas à chaque phrase.
Réponses COURTES (2-3 phrases). Pas de markdown. Lues à voix haute par ElevenLabs.
IMPORTANT : tu n'as PAS les actualités, l'agenda ni les mails dans cette conversation. N'invente JAMAIS d'actualités,
de cours, de rendez-vous ou de mails. Si on te les demande, propose les commandes « news du matin », « mon agenda demain »,
« mes cours de la semaine prochaine », « mon prochain DS », « mes rappels » ou « mes derniers mails »."""

def check_ollama():
    try:
        r=requests.get("http://localhost:11434/api/tags",timeout=2)
        S["local_ai_ok"]=len(r.json().get("models",[]))>0
    except: S["local_ai_ok"]=False

def _complexity(t):
    if any(w in t.lower() for w in ["heure","date","ouvre","lance","ferme","ok","merci","bonjour","volume","stats","screenshot","wifi","batterie"]): return "simple"
    if any(w in t.lower() for w in ["explique","analyse","rédige","code","programme","stratégie","rapport","synthèse","investissement"]): return "complex"
    return "medium"

def _local(t):
    try:
        r=requests.post("http://localhost:11434/api/chat",
            json={"model":CFG["ollama_model"],"stream":False,
                  "messages":[{"role":"system","content":SYS},{"role":"user","content":t}]},timeout=30)
        return r.json()["message"]["content"],True
    except: return None,False

def _groq(t):
    k=CFG.get("groq_key","")
    if not k or k=="YOUR_GROQ_KEY": return None,False
    try:
        r=requests.post("https://api.groq.com/openai/v1/chat/completions",
            headers={"Authorization":f"Bearer {k}","Content-Type":"application/json"},
            json={"model":CFG.get("groq_model","openai/gpt-oss-120b"),"max_tokens":1000,"reasoning_effort":"low",
                  "messages":[{"role":"system","content":SYS},{"role":"user","content":t}]},timeout=15)
        if r.status_code==200: return r.json()["choices"][0]["message"]["content"],True
        log(f"[GROQ] Erreur {r.status_code}: {r.text[:200]}","red")
        return None,False
    except Exception as e:
        log(f"[GROQ] {e}","red"); return None,False

def _mistral(t):
    k=CFG.get("mistral_key","")
    if not k or k=="YOUR_MISTRAL_KEY": return None,False
    try:
        r=requests.post("https://api.mistral.ai/v1/chat/completions",
            headers={"Authorization":f"Bearer {k}","Content-Type":"application/json"},
            json={"model":"mistral-small","max_tokens":500,
                  "messages":[{"role":"system","content":SYS},{"role":"user","content":t}]},timeout=15)
        if r.status_code==200: return r.json()["choices"][0]["message"]["content"],True
        return None,False
    except: return None,False

def _gemini(t, pro=False):
    k=CFG.get("gemini_pro_key" if pro else "gemini_key","")
    ph="YOUR_GEMINI_PRO_KEY" if pro else "YOUR_GEMINI_KEY"
    if not k or k==ph or len(k)<10: return None,False
    try:
        from google import genai
        client=genai.Client(api_key=k)
        model="gemini-2.0-flash"
        response=client.models.generate_content(
            model=model,
            contents=SYS+"\n\nUtilisateur: "+t
        )
        return response.text,True
    except Exception as e:
        log(f"[GEMINI{'PRO' if pro else ''}] {e}","yellow"); return None,False

def ask_ai_cascade(text, force_quality=False):
    S["thinking"]=True; push("status","IA EN COURS...")
    cplx=_complexity(text) if not force_quality else "complex"
    S["convos"].append({"role":"user","content":text})
    if len(S["convos"])>20: S["convos"]=S["convos"][-20:]
    reply=None; ai=""

    if cplx=="simple" and S["local_ai_ok"]:
        reply,ok=_local(text)
        if ok: ai="LOCAL 🖥️"
    if not reply:
        reply,ok=_groq(text)
        if ok: ai="GROQ ⚡"
    if not reply:
        reply,ok=_mistral(text)
        if ok: ai="MISTRAL 🌟"
    if not reply or cplx=="complex":
        r,ok=_gemini(text,True)
        if ok: reply=r; ai="GEMINI PRO"
    if not reply:
        r,ok=_gemini(text,False)
        if ok: reply=r; ai="GEMINI"
    if not reply and S["local_ai_ok"]:
        reply,ok=_local(text)
        if ok: ai="LOCAL 🖥️"
    if not reply: reply="Toutes les IA sont indisponibles. Vérifiez config.json."

    S["convos"].append({"role":"assistant","content":reply})
    push("ai_used",ai); log(f"[{ai}]","magenta")
    c=sqlite3.connect(DB)
    c.execute("INSERT INTO convos(role,content,ts,ai_used,app_ctx) VALUES(?,?,?,?,?)",
        ("user",text,datetime.datetime.now().isoformat(),ai,S["current_app"]))
    c.execute("INSERT INTO convos(role,content,ts,ai_used,app_ctx) VALUES(?,?,?,?,?)",
        ("assistant",reply,datetime.datetime.now().isoformat(),ai,""))
    c.commit(); c.close()
    S["thinking"]=False
    return reply

# --- SELF-MOD
from self_mod import (self_improve_workflow, confirm_improvement,
                      cancel_improvement, list_backups, restore_backup,
                      analyze_and_suggest, restart_jarvis)

def request_improvement(req):
    res=self_improve_workflow(req, push_fn=push, speak_fn=speak)
    S["pending_improvement"]=res
    return res.get("message","Code en génération...")

# --- GESTES (MediaPipe Tasks — GestureRecognizer)
# Les versions récentes de MediaPipe n'ont plus mp.solutions :
# on utilise le modèle officiel "gesture_recognizer.task" (téléchargé une seule fois dans brain/).
_gesture_cap=None
_GESTURE_MODEL=os.path.join(BRAIN,"gesture_recognizer.task")
_GESTURE_URL="https://storage.googleapis.com/mediapipe-models/gesture_recognizer/gesture_recognizer/float16/1/gesture_recognizer.task"
_GESTURE_MAP={"Closed_Fist":"fist","Open_Palm":"open","Thumb_Up":"thumbs_up",
              "Thumb_Down":"thumbs_down","Victory":"two","Pointing_Up":"point"}

def _load_gesture_model():
    if not os.path.exists(_GESTURE_MODEL) or os.path.getsize(_GESTURE_MODEL)<100000:
        log("[GESTES] Téléchargement du modèle (une seule fois)...","yellow")
        r=requests.get(_GESTURE_URL,timeout=60); r.raise_for_status()
        with open(_GESTURE_MODEL,"wb") as f: f.write(r.content)
    from mediapipe.tasks import python as mpt
    from mediapipe.tasks.python import vision
    opts=vision.GestureRecognizerOptions(
        base_options=mpt.BaseOptions(model_asset_path=_GESTURE_MODEL),
        running_mode=vision.RunningMode.VIDEO, num_hands=1,
        min_hand_detection_confidence=0.6, min_tracking_confidence=0.5)
    return vision.GestureRecognizer.create_from_options(opts)

def init_gestures():
    global _gesture_cap
    if S["gesture_active"]: return "Les gestes sont déjà activés."
    try:
        import cv2
        recognizer=_load_gesture_model()
        _gesture_cap=cv2.VideoCapture(0,cv2.CAP_DSHOW)
        if not _gesture_cap.isOpened():
            _gesture_cap=None
            log("[GESTES] Webcam introuvable ou déjà utilisée","red")
            return "Je n'arrive pas à ouvrir la webcam."
        S["gesture_active"]=True
        threading.Thread(target=_gesture_loop,args=(recognizer,),daemon=True).start()
        log("[GESTES] Activés (webcam OK)","green")
        push("log",{"msg":"[OK] Gestes activés","color":"green"})
        return "Contrôle gestuel activé."
    except Exception as e:
        log(f"[GESTES] {e}","red")
        return f"Gestes indisponibles : {str(e)[:80]}"

def _gesture_loop(recognizer):
    global _gesture_cap
    import cv2, mediapipe as mp
    try:
        last=""; cand=""; streak=0; t0=time.time()
        STABLE=8   # ~1/3 s : le geste doit être tenu pour compter
        while S["gesture_active"]:
            ret,frame=_gesture_cap.read()
            if not ret: time.sleep(0.05); continue
            rgb=cv2.cvtColor(frame,cv2.COLOR_BGR2RGB)
            img=mp.Image(image_format=mp.ImageFormat.SRGB,data=rgb)
            res=recognizer.recognize_for_video(img,int((time.time()-t0)*1000))
            g="none"
            if res.gestures and res.gestures[0]:
                top=res.gestures[0][0]
                if top.score>=0.5: g=_GESTURE_MAP.get(top.category_name,"none")
                lm=res.hand_landmarks[0]
                push("hand_pos",{"x":lm[0].x,"y":lm[0].y,"gesture":g})
            # Anti-clignotement : on ne valide un geste que s'il reste stable
            if g==cand: streak+=1
            else: cand=g; streak=1
            if streak==STABLE:
                if g!="none" and g!=last:
                    log(f"[GESTES] Détecté : {g}","cyan")
                    _do_gesture(g)
                last=g
            time.sleep(0.03)
    except Exception as e: log(f"[GESTES] {e}","red")
    finally:
        try: recognizer.close()
        except: pass
        try:
            if _gesture_cap: _gesture_cap.release()
        except: pass
        _gesture_cap=None
        log("[GESTES] Webcam libérée","yellow")

_gtime={}
def _do_gesture(g):
    now=time.time()
    if now-_gtime.get(g,0)<2: return
    _gtime[g]=now
    if g=="fist": activate(); push("gesture_event","✊ JARVIS ACTIVÉ")
    elif g=="open": push("gesture_event","🖐️ STOP")
    elif g=="thumbs_up":
        push("gesture_event","👍 CONFIRMÉ")
        if S.get("pending_email"): threading.Thread(target=lambda:_process("envoie"),daemon=True).start()
        elif S.get("pending_post"): speak("Post confirmé.")
        elif S.get("pending_improvement"): threading.Thread(target=lambda:_process("installe"),daemon=True).start()
    elif g=="thumbs_down":
        S["pending_email"]=None; S["pending_post"]=None
        push("gesture_event","👎 ANNULÉ"); speak("Action annulée.")
    elif g=="two": push("gesture_event","✌️ SCROLL")

def stop_gestures():
    if not S["gesture_active"]: return "Les gestes sont déjà désactivés."
    S["gesture_active"]=False   # la boucle s'arrête et libère la webcam
    log("[GESTES] Désactivés","yellow")
    return "Gestes désactivés."

# --- EMAIL
def draft_email(to,subject,hint):
    body=ask_ai_cascade(
        f"Rédige un email en français. À: {to}. Sujet: {subject}. Message: {hint}. "
        f"Corps uniquement, sans objet ni signature.",force_quality=True)
    S["pending_email"]={"to":to,"subject":subject,"body":body}
    push("email_draft",S["pending_email"])
    speak(get_line("email_ready",CFG["owner_name"]))
    speak(f"À {to}. Objet: {subject}. Corps: {body[:180]}")
    speak("Dites 'envoie' pour confirmer, ou faites un pouce levé.")
    return f"Email prêt pour {to}. En attente de confirmation."

def send_email():
    d=S.get("pending_email")
    if not d: return "Aucun email en attente."
    gm=CFG.get("gmail_address",""); pw=CFG.get("gmail_app_password","")
    if not gm or not pw: return "Configurez Gmail dans config.json."
    try:
        msg=MIMEMultipart()
        msg["From"]=gm; msg["To"]=d["to"]; msg["Subject"]=d["subject"]
        msg.attach(MIMEText(d["body"],"plain","utf-8"))
        with smtplib.SMTP_SSL("smtp.gmail.com",465,context=ssl.create_default_context()) as srv:
            srv.login(gm,pw); srv.sendmail(gm,d["to"],msg.as_string())
        S["pending_email"]=None; push("email_sent",d["to"])
        c=sqlite3.connect(DB)
        c.execute("INSERT INTO emails_sent(to_addr,subject,body,ts,status) VALUES(?,?,?,?,?)",
            (d["to"],d["subject"],d["body"],datetime.datetime.now().isoformat(),"sent"))
        c.commit(); c.close()
        return f"Email envoyé à {d['to']}."
    except Exception as e: return f"Erreur envoi: {str(e)[:60]}"

def read_emails(n=5):
    import imaplib,email as elib
    gm=CFG.get("gmail_address",""); pw=CFG.get("gmail_app_password","")
    if not gm or not pw: return "Gmail non configuré."
    try:
        m=imaplib.IMAP4_SSL("imap.gmail.com"); m.login(gm,pw.replace(" ","")); m.select("inbox",readonly=True)
        _,msgs=m.search(None,"UNSEEN"); ids=msgs[0].split()[-n:]
        res=[]
        for i in ids:
            _,data=m.fetch(i,"(BODY.PEEK[])")
            msg=elib.message_from_bytes(data[0][1])
            body=""; 
            if msg.is_multipart():
                for p in msg.walk():
                    if p.get_content_type()=="text/plain":
                        body=p.get_payload(decode=True).decode(errors='ignore')[:120]; break
            else: body=msg.get_payload(decode=True).decode(errors='ignore')[:120]
            from email.header import decode_header, make_header
            _d=lambda h: str(make_header(decode_header(h or "")))
            res.append(f"De: {_d(msg['From'])[:25]} | {_d(msg['Subject'])[:30]} | {body[:60]}")
        m.logout()
        return "\n".join(res) if res else "Aucun nouvel email."
    except Exception as e: return f"Erreur: {str(e)[:60]}"

# --- INSTAGRAM
def schedule_post(content,when):
    S["pending_post"]={"platform":"instagram","content":content,"time":when}
    push("post_preview",S["pending_post"])
    speak(f"Post Instagram préparé: {content[:60]}. Programmé pour {when}. Dites 'confirme le post' ou pouce levé.")
    return f"Post Instagram prêt pour {when}."

def publish_post():
    p=S.get("pending_post")
    if not p: return "Aucun post en attente."
    try:
        from instagrapi import Client
        cl=Client(); cl.login(CFG["instagram_username"],CFG["instagram_password"])
        S["pending_post"]=None
        return "Post Instagram publié."
    except Exception as e:
        S["pending_post"]=None
        return f"Instagram: {str(e)[:60]}. Vérifiez vos identifiants."

def check_posts():
    while True:
        if S.get("pending_post"):
            p=S["pending_post"]
            now=datetime.datetime.now().strftime("%H:%M")
            sched=p.get("time","")
            if now in sched or sched=="maintenant":
                publish_post()
        time.sleep(30)

# --- GAMING
def game_deals():
    try:
        r=requests.get("https://www.cheapshark.com/api/1.0/deals?storeID=1&upperPrice=15&sortBy=Deal+Rating&pageSize=8",timeout=10)
        deals=r.json()[:5]
        push("game_deals",deals)
        return "Offres Steam: " + " | ".join([f"{d.get('title','')[:20]} {d.get('salePrice','?')}$ (-{float(d.get('savings',0)):.0f}%)" for d in deals])
    except: return "Offres indisponibles."

def epic_free():
    try:
        r=requests.get("https://store-site-backend-static.ak.epicgames.com/freeGamesPromotions?locale=fr",timeout=10)
        games=r.json()["data"]["Catalog"]["searchStore"]["elements"]
        free=[g["title"] for g in games if g.get("promotions") and g["promotions"].get("promotionalOffers")]
        push("game_deals",[{"title":g,"salePrice":"0","normalPrice":"?","savings":"100"} for g in free])
        return f"Jeux gratuits Epic: {', '.join(free)}" if free else "Aucun jeu gratuit Epic."
    except: return "Epic indisponible."

def game_recs(mood=""):
    r=ask_ai_cascade(f"Recommande 4 jeux PC pour quelqu'un qui aime {','.join(CFG['favorite_genres'])}. Humeur: {mood or 'normale'}. Nom, genre, note/10, pourquoi. Jeux 2023-2025.",force_quality=True)
    push("game_recs",r); return r

# --- FINANCE
def get_crypto():
    try:
        ids={"BTC":"bitcoin","ETH":"ethereum","SOL":"solana","BNB":"binancecoin","ADA":"cardano"}
        coin_ids=",".join([ids.get(c,c.lower()) for c in CFG["crypto_watchlist"]])
        r=requests.get(f"https://api.coingecko.com/api/v3/simple/price?ids={coin_ids}&vs_currencies=eur&include_24hr_change=true",timeout=10)
        data=r.json(); push("crypto_prices",data)
        parts=[]
        for cid,val in data.items():
            chg=val.get("eur_24h_change",0) or 0
            parts.append(f"{cid[:3].upper()}: {val.get('eur','?')}€ {'📈' if chg>0 else '📉'}{chg:.1f}%")
        return "Crypto: "+" | ".join(parts)
    except: return "Crypto indisponible."

def get_stocks():
    try:
        res=[]
        for t in CFG["stock_watchlist"][:3]:
            r=requests.get(f"https://query1.finance.yahoo.com/v8/finance/chart/{t}?interval=1d&range=1d",
                timeout=8,headers={"User-Agent":"Mozilla/5.0"})
            d=r.json()["chart"]["result"][0]["meta"]
            p=d["regularMarketPrice"]; prev=d["chartPreviousClose"]
            chg=((p-prev)/prev)*100
            res.append(f"{t}: {p:.2f}$ {'📈' if chg>0 else '📉'}{chg:.1f}%")
        push("stock_prices",res); return "Actions: "+" | ".join(res)
    except: return "Bourse indisponible."

def finance_analysis():
    cr=get_crypto(); st=get_stocks()
    r=ask_ai_cascade(f"Données: {cr} | {st}. Analyse neutre du marché en 3 phrases. Rappelle que ce n'est pas un conseil financier.",force_quality=True)
    push("finance_analysis",r); return r

# --- VISION
def analyze_screen():
    try:
        import cv2
        img=ImageGrab.grab(); arr=np.array(img)
        ts=datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
        path=os.path.join(BRAIN,f"vision_{ts}.jpg")
        cv2.imwrite(path,cv2.cvtColor(arr,cv2.COLOR_RGB2BGR))
        with open(path,"rb") as f: b64=base64.b64encode(f.read()).decode()
        k=CFG.get("anthropic_key","")
        if k and k!="YOUR_ANTHROPIC_KEY":
            r=requests.post("https://api.anthropic.com/v1/messages",
                headers={"x-api-key":k,"anthropic-version":"2023-06-01","content-type":"application/json"},
                json={"model":"claude-sonnet-4-20250514","max_tokens":250,
                      "messages":[{"role":"user","content":[
                          {"type":"image","source":{"type":"base64","media_type":"image/jpeg","data":b64}},
                          {"type":"text","text":"Décris brièvement cet écran en 2-3 phrases."}]}]},timeout=15)
            return r.json()["content"][0]["text"]
        return "Vision: configurez anthropic_key pour l'analyse d'image."
    except Exception as e: return f"Erreur vision: {str(e)[:50]}"

def webcam_vision():
    try:
        import cv2
        cap=cv2.VideoCapture(0); ret,frame=cap.read(); cap.release()
        if not ret: return "Webcam introuvable."
        ts=datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
        path=os.path.join(BRAIN,f"webcam_{ts}.jpg"); cv2.imwrite(path,frame)
        with open(path,"rb") as f: b64=base64.b64encode(f.read()).decode()
        k=CFG.get("anthropic_key","")
        if k and k!="YOUR_ANTHROPIC_KEY":
            r=requests.post("https://api.anthropic.com/v1/messages",
                headers={"x-api-key":k,"anthropic-version":"2023-06-01","content-type":"application/json"},
                json={"model":"claude-sonnet-4-20250514","max_tokens":300,
                      "messages":[{"role":"user","content":[
                          {"type":"image","source":{"type":"base64","media_type":"image/jpeg","data":b64}},
                          {"type":"text","text":"Identifie et décris précisément ce que tu vois. Si c'est un composant, donne les specs."}]}]},timeout=15)
            return r.json()["content"][0]["text"]
        return "Webcam capturée. Configurez anthropic_key pour l'analyse."
    except Exception as e: return f"Erreur webcam: {str(e)[:50]}"

# --- WINDOWS
APPS={
    "chrome":r"C:\Program Files\Google\Chrome\Application\chrome.exe",
    "opera":os.path.join(os.environ.get("LOCALAPPDATA",""),r"Programs\Opera\opera.exe"),
    "opera gx":os.path.join(os.environ.get("LOCALAPPDATA",""),r"Programs\Opera GX\opera.exe"),
    "notepad":"notepad.exe","calculatrice":"calc.exe","explorateur":"explorer.exe",
    "gestionnaire":"taskmgr.exe","cmd":"cmd.exe","powershell":"powershell.exe",
    "spotify":os.path.join(os.environ.get("APPDATA",""),r"Spotify\Spotify.exe"),
    "discord":os.path.join(os.environ.get("LOCALAPPDATA",""),r"Discord\Update.exe"),
    "vscode":os.path.join(os.environ.get("LOCALAPPDATA",""),r"Programs\Microsoft VS Code\Code.exe"),
    "steam":r"C:\Program Files (x86)\Steam\Steam.exe",
    "obs":r"C:\Program Files\obs-studio\bin\64bit\obs64.exe",
    "photoshop":r"C:\Program Files\Adobe\Adobe Photoshop 2024\Photoshop.exe",
    "word":r"C:\Program Files\Microsoft Office\root\Office16\WINWORD.EXE",
    "excel":r"C:\Program Files\Microsoft Office\root\Office16\EXCEL.EXE",
    "vlc":r"C:\Program Files\VideoLAN\VLC\vlc.exe",
    "whatsapp":os.path.join(os.environ.get("LOCALAPPDATA",""),r"WhatsApp\WhatsApp.exe"),
}
SITES={"youtube":"https://youtube.com","google":"https://google.com","gmail":"https://gmail.com",
       "github":"https://github.com","netflix":"https://netflix.com","twitch":"https://twitch.tv",
       "twitter":"https://twitter.com","x":"https://twitter.com","reddit":"https://reddit.com",
       "amazon":"https://amazon.fr","steam store":"https://store.steampowered.com",
       "epic":"https://epicgames.com/store/fr/","tiktok":"https://tiktok.com",
       "instagram":"https://instagram.com","discord":"https://discord.com"}
FOCUS={
    "gaming":{"keep":["steam","discord","obs"],"hide":["word","excel","outlook","teams"],"wp":"gaming","vol":80,"plan":"performance"},
    "travail":{"keep":["word","excel","outlook","chrome"],"hide":["steam","discord","netflix"],"wp":"cyberpunk","vol":30,"plan":"performance"},
    "stream":{"keep":["obs","chrome","discord"],"hide":["word","excel"],"wp":"fire","vol":60,"plan":"performance"},
    "code":{"keep":["vscode","chrome","cmd"],"hide":["steam","discord","netflix"],"wp":"space","vol":40,"plan":"performance"},
    "photoshop":{"keep":["photoshop","illustrator"],"hide":["steam","discord"],"wp":"cyberpunk","vol":50,"plan":"performance"},
    "étude":{"keep":["chrome","word","notion"],"hide":["steam","discord","netflix"],"wp":"nature","vol":20,"plan":"équilibré"},
    "détente":{"keep":["netflix","spotify","discord"],"hide":["word","vscode"],"wp":"space","vol":70,"plan":"économie"},
}

def gen_wallpaper(theme="cyberpunk"):
    w,h=pyautogui.size(); img=Image.new("RGB",(w,h),(0,5,15)); draw=ImageDraw.Draw(img)
    pals={"cyberpunk":[(0,212,255),(0,85,255)],"space":[(80,0,200),(200,100,255)],
          "fire":[(255,50,0),(255,220,0)],"nature":[(0,150,80),(50,220,50)],
          "gaming":[(0,255,100),(150,0,255)],"iron man":[(255,60,0),(255,170,0)]}
    c=pals.get(theme,pals["cyberpunk"])
    for y in range(h):
        r2=y/h; draw.line([(0,y),(w,y)],fill=(int(c[0][0]*(1-r2)+c[1][0]*r2)//8,int(c[0][1]*(1-r2)+c[1][1]*r2)//8,int(c[0][2]*(1-r2)+c[1][2]*r2)//8))
    for _ in range(400):
        x,y=random.randint(0,w),random.randint(0,h); s=random.randint(1,3)
        draw.ellipse([x-s,y-s,x+s,y+s],fill=random.choice(c))
    p=os.path.join(os.environ["TEMP"],f"jarvis_wp_{theme}.png"); img.save(p); return p

def set_wp(path):
    ctypes.windll.user32.SystemParametersInfoW(20,0,os.path.abspath(path),3)
    return f"Fond d'écran: {os.path.basename(path)}"

def set_volume(lv):
    subprocess.run(["powershell","-c",
        f"$o=New-Object -com WScript.Shell;For($i=0;$i-lt 50;$i++){{$o.SendKeys([char]174)}};For($i=0;$i-lt [math]::Round({lv}/2);$i++){{$o.SendKeys([char]175)}}"],
        capture_output=True,timeout=5)
    return f"Volume: {lv}%"

def power_plan(plan):
    plans={"performance":"8c5e7fda-e8bf-4a96-9a85-a6e23a8c635c",
           "équilibré":"381b4222-f694-41f0-9685-ff5bb260df2e",
           "économie":"a1841308-3541-4fab-bc81-f71556f20b4a"}
    if plan in plans: subprocess.run(["powercfg","/setactive",plans[plan]],capture_output=True)
    return f"Plan: {plan}"

def activate_focus(act=""):
    if not act:
        speak("Quel est votre activité ? Gaming, travail, stream, code, Photoshop, étude ou détente ?")
        return "Précisez votre activité."
    p=next((v for k,v in FOCUS.items() if k in act.lower()),None)
    if not p: p=FOCUS["travail"]
    try: set_wp(gen_wallpaper(p["wp"]))
    except: pass
    try: set_volume(p["vol"])
    except: pass
    try: power_plan(p["plan"])
    except: pass
    hidden=[]
    for w in gw.getAllWindows():
        if not w.title: continue
        if any(h in w.title.lower() for h in p["hide"]):
            try: w.minimize(); hidden.append(w.title[:12])
            except: pass
    S["concentration_mode"]=True; S["focus_activity"]=act
    push("focus_mode",{"active":True,"activity":act})
    return f"Mode {act} activé. {len(hidden)} app(s) cachée(s)."

def clean_system():
    freed=0
    for td in [os.environ.get("TEMP",""),r"C:\Windows\Temp"]:
        if not os.path.exists(td): continue
        for f in os.listdir(td):
            fp=os.path.join(td,f)
            try:
                s=os.path.getsize(fp) if os.path.isfile(fp) else 0
                shutil.rmtree(fp,ignore_errors=True) if os.path.isdir(fp) else os.remove(fp)
                freed+=s
            except: pass
    try: subprocess.run(["powershell","-c","Clear-RecycleBin -Force"],capture_output=True,timeout=10)
    except: pass
    return f"Nettoyage: {freed//1024//1024}Mo libérés."

def screenshot():
    ts=datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    path=os.path.join(os.environ["USERPROFILE"],"Desktop",f"JARVIS_{ts}.png")
    pyautogui.screenshot().save(path); push("screenshot_taken",path)
    return f"Capture: {os.path.basename(path)}"

def dark_mode(on=True):
    val=0 if on else 1
    for v in ["AppsUseLightTheme","SystemUsesLightTheme"]:
        subprocess.run(["reg","add",r"HKCU\SOFTWARE\Microsoft\Windows\CurrentVersion\Themes\Personalize",
            "/v",v,"/t","REG_DWORD","/d",str(val),"/f"],capture_output=True)
    return "Mode sombre activé." if on else "Mode clair activé."

def uninstall_app(name):
    try:
        r=subprocess.run(["winget","uninstall","--name",name,"--silent","--accept-source-agreements"],
            capture_output=True,text=True,timeout=60)
        if r.returncode==0: return f"{name} désinstallé."
    except: pass
    return f"'{name}' introuvable dans winget."

def opera_movie(movie):
    for p in [CFG["opera_path"],os.path.join(os.environ.get("LOCALAPPDATA",""),r"Programs\Opera GX\opera.exe")]:
        if os.path.exists(p):
            wins=[w for w in gw.getAllWindows() if 'opera' in w.title.lower()]
            if not wins: subprocess.Popen([p]); time.sleep(2)
            else: wins[0].activate(); time.sleep(0.5)
            break
    q=urllib.parse.quote(movie+" streaming vf gratuit")
    pyautogui.hotkey('ctrl','t'); time.sleep(0.4)
    pyautogui.hotkey('ctrl','l'); time.sleep(0.3)
    pyautogui.write(f"https://google.com/search?q={q}",interval=0.02)
    pyautogui.press('enter')
    return f"Recherche '{movie}' en streaming dans Opera."

def add_reminder(text,mins):
    S["reminders"].append({"text":text,"when":time.time()+mins*60})
    push("reminder_added",{"text":text,"minutes":mins})
    return f"Rappel dans {mins}min: {text}"

def check_reminders():
    while True:
        for r in S["reminders"][:]:
            if time.time()>=r["when"]:
                speak(f"Rappel: {r['text']}"); push("reminder_fire",r["text"])
                S["reminders"].remove(r)
        time.sleep(8)

def get_active_app():
    try:
        hwnd=win32gui.GetForegroundWindow()
        title=win32gui.GetWindowText(hwnd)
        _,pid=win32process.GetWindowThreadProcessId(hwnd)
        pname=psutil.Process(pid).name().lower()
        S["current_app"]=pname; push("active_app",{"title":title,"process":pname})
        return title,pname
    except: return "",""

# --- PARSER COMMANDES
_JOURS_FR=["lundi","mardi","mercredi","jeudi","vendredi","samedi","dimanche"]
def _agenda_period(t):
    """Devine la période demandée → (date_début, nb_jours)."""
    today=datetime.date.today()
    if "après-demain" in t or "apres-demain" in t or "après demain" in t: return today+datetime.timedelta(2),1
    if "demain" in t: return today+datetime.timedelta(1),1
    if "semaine prochaine" in t:
        return today+datetime.timedelta(7-today.weekday()),7
    if "cette semaine" in t or "la semaine" in t:
        return today,7-today.weekday()
    if "week-end" in t or "weekend" in t:
        return today+datetime.timedelta((5-today.weekday())%7),2
    d,found=rp.parse_date(t,today)
    if d and not any(j in found for j in _JOURS_FR):   # "le 30 novembre", "30/11", "dans 3 jours"
        return d,1
    for i,j in enumerate(_JOURS_FR):
        if j in t:
            delta=(i-today.weekday())%7
            if "prochain" in t and delta==0: delta=7
            return today+datetime.timedelta(delta),1
    return today,1

def ask_agenda(t):
    start,n=_agenda_period(t)
    days=bx.agenda_range(CFG,start,n,log) or {}
    today=datetime.date.today()
    rappels=[r for r in rp._read(CFG) if not r["fait"]]
    parts=[]
    for i in range(n):
        d=start+datetime.timedelta(i)
        evs=days.get(d,[])
        todo=[r["texte"] for r in rappels if r["date"]==d]
        if d==today: todo+=[r["texte"]+" (en retard)" for r in rappels if r["date"]<today]
        if not evs and not todo: continue
        nom=rp.date_fr(d,today); nom=nom[0].upper()+nom[1:]
        bloc=[]
        if evs:
            items=[]
            for e in evs:
                h="toute la journée" if e["journee"] else e["debut"].strftime("%Hh%M")
                items.append(f"{h} {bx.spoken(e,CFG)}")
            bloc.append("cours : "+" ; ".join(items))
        if todo: bloc.append(("À faire : " if evs else "à faire : ")+" ; ".join(todo))
        parts.append(f"{nom}, "+". ".join(bloc)+".")
    if not parts:
        quand=rp.date_fr(start,today) if n==1 else "sur cette période"
        return bx.humanize(f"Rien de prévu {quand}, ni cours ni rappel.",CFG)
    return bx.humanize("\n".join(parts),CFG)

def ask_mails(t):
    only="iut" if ("iut" in t or "fac" in t or "université" in t or "universite" in t) else ("gmail" if "gmail" in t else None)
    n=1 if ("dernier mail" in t or "dernier email" in t or "dernier message" in t) else 3
    return bx.last_mails_text(bx.last_mails(CFG,n,only,log))

def ask_next_ds(t):
    n=3 if any(w in t for w in ["prochains","mes ds","mes devoirs","mes examens","les ds"]) else 1
    filtre=None
    m=re.search(r"(?:ds|devoir surveillé|devoir|examen|contrôle|controle|partiel)s?\s+(?:de |d'|d’|en )(.+)",t)
    if m:
        filtre=m.group(1).strip(" ?.!")
        if filtre in ("la semaine","cette semaine"): filtre=None
    return bx.next_ds_text(bx.next_ds(CFG,n,150,log,filtre))

def add_to_calendar(text):
    e=ci.parse_event(text,rp.parse_date)
    ok,info=ci.add_event(CFG,e["titre"],e["debut"],e["fin"],e["journee"],log=log)
    if not ok: return info
    S["last_event"]={"titre":e["titre"],"t":time.time()}
    today=datetime.date.today()
    if e["journee"]:
        quand=rp.date_fr(e["debut"],today)
    else:
        quand=f"{rp.date_fr(e['debut'].date(),today)} de {e['debut']:%Hh%M} à {e['fin']:%Hh%M}"
    return f"C'est dans ton agenda {info} : {e['titre']}, {quand}."

def edit_calendar(text):
    """Modifier / déplacer / supprimer un événement du Calendrier iPhone (l'IA repère lequel)."""
    today=datetime.date.today()
    try:
        evs=ci.find_events(CFG,today-datetime.timedelta(1),today+datetime.timedelta(60),log)
    except Exception as e:
        return f"Je n'arrive pas à lire ton agenda iCloud : {str(e)[:80]}"
    if evs is None: return "Il me manque l'accès à iCloud dans config.json."
    if not evs: return "Je ne trouve aucun événement dans ton agenda iPhone pour les deux prochains mois."
    evs=[e for e in evs if not e.get("repete")][:40]
    last=(S.get("last_event") or {})
    recent=last.get("titre") if time.time()-last.get("t",0)<900 else None
    lignes=[]
    for i,e in enumerate(evs):
        d=e["debut"]
        if e.get("journee"): quand=f"{d:%Y-%m-%d} (journée entière)"
        else: quand=f"{d:%Y-%m-%d} {d:%H:%M}-{(e.get('fin') or d):%H:%M}"
        mark=" ← dernier ajouté" if recent and e.get("titre")==recent else ""
        lignes.append(f"{i}: {e.get('titre','?')} | {quand}{mark}")
    jours=["lundi","mardi","mercredi","jeudi","vendredi","samedi","dimanche"]
    prompt=(f"Aujourd'hui : {jours[today.weekday()]} {today:%Y-%m-%d}, il est {datetime.datetime.now():%H:%M}.\n"
            f"Événements de l'agenda :\n"+"\n".join(lignes)+
            f"\n\nDemande de l'utilisateur : « {text} »\n"
            "Quel événement veut-il modifier ou supprimer, et comment ? Si la demande est une correction "
            "(« non, pas samedi mais aujourd'hui »), c'est en général le dernier ajouté. "
            "Réponds UNIQUEMENT en JSON : {\"action\": \"modifier\" ou \"supprimer\" ou \"aucun\", "
            "\"index\": numéro, \"date\": \"AAAA-MM-JJ\" ou null, \"debut\": \"HH:MM\" ou null, "
            "\"fin\": \"HH:MM\" ou null, \"titre\": nouveau titre ou null}. "
            "Mets null pour ce qui ne change pas.")
    rep=news_matin._groq_chat(CFG,prompt,400)
    m=re.search(r"\{.*\}",rep or "",re.S)
    try: d=json.loads(m.group(0))
    except Exception: return "Je n'ai pas compris quel événement modifier. Redis-moi son nom et la nouvelle date."
    if d.get("action") not in ("modifier","supprimer") or not isinstance(d.get("index"),int) or not 0<=d["index"]<len(evs):
        return "Je n'ai pas trouvé l'événement dont tu parles dans ton agenda."
    ev=evs[d["index"]]
    if d["action"]=="supprimer":
        return f"C'est supprimé : {ev.get('titre')}." if ci.delete_event(CFG,ev,log) else "iCloud a refusé la suppression."
    old_deb=ev["debut"]; old_fin=ev.get("fin")
    journee=ev.get("journee",False)
    new_date=datetime.date.fromisoformat(d["date"]) if d.get("date") else (old_deb if journee else old_deb.date())
    if d.get("debut"):
        h,mi=map(int,d["debut"].split(":")); journee=False
        debut=datetime.datetime.combine(new_date,datetime.time(h,mi))
    elif not journee:
        debut=datetime.datetime.combine(new_date,old_deb.time())
    else:
        debut=new_date
    if journee: fin=None
    elif d.get("fin"):
        h,mi=map(int,d["fin"].split(":")); fin=datetime.datetime.combine(new_date,datetime.time(h,mi))
        if fin<=debut: fin=debut+datetime.timedelta(hours=1)
    else:
        duree=(old_fin-old_deb) if (old_fin and not ev.get("journee")) else datetime.timedelta(hours=1)
        fin=debut+duree
    titre=d.get("titre") or ev.get("titre")
    if not ci.update_event(CFG,ev,debut,fin,journee,titre,log): return "iCloud a refusé la modification."
    S["last_event"]={"titre":titre,"t":time.time()}
    if journee: quand=rp.date_fr(new_date,today)
    else: quand=f"{rp.date_fr(new_date,today)} de {debut:%Hh%M} à {fin:%Hh%M}"
    return f"C'est modifié : {titre}, {quand}."

def parse(text):
    t=text.lower().strip()

    # AJOUT DANS LE CALENDRIER IPHONE (iCloud)
    if ci.TRIGGER.search(t):
        return add_to_calendar(text)

    # MODIFIER / SUPPRIMER UN ÉVÉNEMENT (iCloud)
    last=S.get("last_event") or {}
    correction = time.time()-last.get("t",0)<900 and re.match(r"^(non|plutôt|en fait|finalement|pas pour)\b",t)
    has_when = bool(ci.CAL_WORDS.search(t) or rp.parse_date(t)[0] or re.search(r"\b\d{1,2}\s?h(\d{2})?\b|\bmidi\b",t))
    if "rappel" not in t and (correction or ((ci.EDIT.search(t) or ci.DELETE.search(t)) and has_when)):
        return edit_calendar(text)

    # RAPPELS (Obsidian) — sauf "rappelle-moi dans 10 minutes" (minuteur, plus bas)
    if re.search(rp._TRIGGERS,t) and not re.search(r"dans \d+ minute",t):
        return bx.humanize(rp.add_from_text(CFG,text),CFG)
    if any(w in t for w in ["c'est fait","j'ai fait","supprime le rappel","enlève le rappel","retire le rappel","efface le rappel"]):
        return bx.humanize(rp.done(CFG,text),CFG)
    if any(w in t for w in ["mes rappels","mes tâches","mes taches","à faire","a faire","je dois faire"]):
        if rp.parse_date(t)[0] or any(w in t for w in ["semaine","week-end","weekend"]):
            return ask_agenda(t)          # "qu'est-ce que j'ai à faire le 30 novembre"
        return bx.humanize(rp.list_text(CFG),CFG)

    # PROCHAIN DS
    if re.search(r"prochains? (ds|devoir|examen|contrôle|controle|partiel)",t) or \
       any(w in t for w in ["mes ds","mes devoirs surveillés","quand est mon ds","quand j'ai ds","mes examens"]):
        return ask_next_ds(t)

    # AGENDA (avant HEURE/DATE : "à quelle heure j'ai cours demain" doit aller ici)
    if any(w in t for w in ["cours","agenda","emploi du temps","edt","planning","rendez-vous","rdv",
                             "j'ai quoi","j'ai rien","qu'est-ce que j'ai","quest ce que j'ai","prévu","de prévu",
                             "examen","partiel","ds "]) \
       and not any(w in t for w in ["crée","ajoute un","annule"]):
        return ask_agenda(t)

    # MAILS (lecture) — l'envoi reste plus bas
    if any(w in t for w in ["mail","email","e-mail","courriel","boîte de réception","boite de reception"]) \
       and not any(w in t for w in ["envoie","écris","ecris","rédige","redige","réponds","reponds"]):
        return ask_mails(t)

    # HEURE/DATE
    if re.search(r"\bquelle heure\b|\bl'heure (qu'il est|actuelle)\b",t) and len(t)<45:
        return f"Il est {datetime.datetime.now():%H heures %M}."
    if re.search(r"\b(quel jour|quelle date|on est le combien|date d'aujourd'hui|on est quel jour)\b",t) and len(t)<45:
        n=datetime.datetime.now()
        j=["lundi","mardi","mercredi","jeudi","vendredi","samedi","dimanche"]
        m=["janvier","février","mars","avril","mai","juin","juillet","août","septembre","octobre","novembre","décembre"]
        return f"Nous sommes {j[n.weekday()]} {n.day} {m[n.month-1]} {n.year}."

    # AUTO-MOD
    if any(w in t for w in ["améliore-toi","ajoute une fonction","ajoute la capacité","apprends à","nouvelle fonctionnalité",
                             "rajoute une fonction","rajoute la capacité"]):
        req=re.sub(r'.*(améliore-toi|ajoute une fonction|ajoute la capacité|apprends à|nouvelle fonctionnalité|rajoute une fonction|rajoute la capacité)\s*','',t).strip()
        return request_improvement(req or text)
    if any(w in t for w in ["installe","confirme l'amélioration","oui installe","applique la"]):
        if S.get("pending_improvement"):
            fn=S["pending_improvement"].get("function_name","last")
            return "Installation en cours..." if confirm_improvement(fn,push,speak) else "Échec."
    if any(w in t for w in ["annule l'amélioration","non annule","refuse l'amélioration"]):
        return cancel_improvement(push,speak)
    if any(w in t for w in ["liste les backups","voir les sauvegardes","backups disponibles"]):
        bk=list_backups()
        push("backups_list",bk)
        if not bk: return "Aucun backup disponible."
        return f"{len(bk)} backup(s): " + " | ".join([f"{b['timestamp'][:16]} ({b['reason']})" for b in bk[:3]])
    if any(w in t for w in ["restaure","reviens en arrière","annule les changements"]):
        bk=list_backups()
        if bk:
            ok,msg=restore_backup(bk[0]["dir"])
            if ok: speak("Backup restauré. Je redémarre."); time.sleep(2); restart_jarvis(2)
            return msg
        return "Aucun backup."

    # EMAIL
    if any(w in t for w in ["envoie un email","envoie un mail","écris un email","rédige un mail"]):
        to_m=re.search(r'(?:à|a|pour)\s+([\w\.\@\-]+@[\w\.]+|[\w]+)',t)
        sb_m=re.search(r'(?:objet|sujet)\s*:?\s*(.+?)(?:\s+(?:et|disant|que)|$)',t)
        to=to_m.group(1) if to_m else "destinataire@email.com"
        subj=sb_m.group(1) if sb_m else "Message"
        body=re.sub(r'.*(disant|que|message|corps)\s*:?\s*','',t).strip() or text
        return draft_email(to,subj,body)
    if any(w in t for w in ["envoie","confirme l'email","oui envoie le"]):
        if S.get("pending_email"): return send_email()
    if any(w in t for w in ["lis mes emails","nouveaux emails","vérifie mes mails"]):
        return read_emails()
    if any(w in t for w in ["réponds à","répondre au mail de"]):
        sender_m=re.search(r'(?:à|a)\s+([\w\.\@]+)',t)
        msg_m=re.search(r'(?:disant|que|en disant)\s*:?\s*(.+)',t)
        return draft_email(sender_m.group(1) if sender_m else "?",
                          "Re: votre message", msg_m.group(1) if msg_m else text)

    # INSTAGRAM
    if any(w in t for w in ["programme un post","post instagram","publier sur insta"]):
        c_m=re.search(r'(?:contenu|texte|disant)\s*:?\s*(.+?)(?:\s+(?:pour|à)\s+|$)',t)
        t_m=re.search(r'(?:pour|à)\s+(demain|\d{1,2}h\d*|\d{2}:\d{2})',t)
        return schedule_post(c_m.group(1) if c_m else text, t_m.group(1) if t_m else "demain 10:00")
    if any(w in t for w in ["confirme le post","publie le post","oui publie"]):
        return publish_post()

    # NEWS DU MATIN / COFFRE OBSIDIAN
    if any(w in t for w in ["relis les news","répète les news","repete les news"]):
        return news_matin.last_briefing().get("texte") or do_morning_news()
    if any(w in t for w in ["news du matin","news du jour","mes news","les news","briefing","actus du jour",
                             "actualités du jour","infos du jour","les actus","actualités","quoi de neuf"]) \
       and not any(w in t for w in ["jeu","gaming","steam"]):
        return do_morning_news()
    if any(w in t for w in ["centres d'intérêt","centre d'intérêt","mes passions","qu'est-ce qui m'intéresse"]):
        q=news_matin.get_interests(CFG, log, force=True)
        return "D'après vos notes Obsidian, vous suivez : " + ", ".join(q) + "."

    # GAMING
    if any(w in t for w in ["offres jeux","soldes jeux","promos jeux","deals gaming","deals steam"]): return game_deals()
    if any(w in t for w in ["recommande","conseille","quel jeu","jeu à jouer"]):
        m=re.search(r'(?:humeur|envie de)\s*(.+)',t)
        return game_recs(m.group(1) if m else "")
    if any(w in t for w in ["jeux gratuits","free games","epic gratuit","epic cette semaine"]): return epic_free()
    if any(w in t for w in ["actus gaming","news jeux","actualités jeux"]):
        return ask_ai_cascade("Donne-moi 3 actualités gaming importantes de cette semaine. Sois bref.")

    # FINANCE
    if any(w in t for w in ["crypto","bitcoin","btc","ethereum","eth","solana"]): return get_crypto()
    if any(w in t for w in ["bourse","actions","nasdaq","aapl","nvda","tesla"]): return get_stocks()
    if any(w in t for w in ["analyse marché","investir","opportunité financière","tendance marché"]): return finance_analysis()

    # GESTES
    # "désactive" d'abord : "désactive les gestes" contient "active les gestes" !
    if any(w in t for w in ["désactive les gestes","desactive les gestes","arrête les gestes","stop les gestes","coupe les gestes"]):
        return stop_gestures()
    if any(w in t for w in ["active les gestes","contrôle par les mains","contrôle gestuel"]):
        return init_gestures()

    # VISION
    if any(w in t for w in ["regarde mon écran","analyse l'écran","que vois-tu","vision écran"]): return analyze_screen()
    if any(w in t for w in ["regarde la webcam","analyse la webcam","identifie ce que"]): return webcam_vision()

    # VOIX
    if any(w in t for w in ["change ta voix","voix daniel","voix britannique"]):
        return voice.set_voice("daniel")
    if any(w in t for w in ["quota voix","combien de caractères","elevenlabs quota"]): return voice.usage()

    # MODE CONCENTRATION
    if any(w in t for w in ["mode gaming","mode travail","mode stream","mode code","mode photoshop","mode étude","mode détente","mode concentration"]):
        act=""
        for a in ["gaming","travail","stream","code","photoshop","étude","détente"]:
            if a in t: act=a; break
        return activate_focus(act)
    if any(w in t for w in ["désactive la concentration","fin du mode","sortir du mode"]):
        S["concentration_mode"]=False; push("focus_mode",{"active":False,"activity":""})
        return "Mode concentration désactivé."

    # FILM/OPERA
    if any(w in t for w in ["film","movie","série"]) and any(w in t for w in ["opera","opéra","regarde","mets"]):
        mv=re.sub(r'.*(film|movie|série|regarde|mets)\s*','',t)
        mv=re.sub(r'(sur opera|opera|opéra)','',mv).strip()
        if mv: return opera_movie(mv)

    # FOND D'ÉCRAN
    for theme in ["cyberpunk","space","fire","nature","iron man","gaming"]:
        if theme in t and any(w in t for w in ["fond","wallpaper","génère"]):
            return set_wp(gen_wallpaper(theme))
    if any(w in t for w in ["change le fond","fond aléatoire"]):
        imgs=[os.path.join(CFG["wallpaper_folder"],f) for f in os.listdir(CFG["wallpaper_folder"])
              if f.lower().endswith(('.jpg','.jpeg','.png'))] if os.path.exists(CFG["wallpaper_folder"]) else []
        return set_wp(random.choice(imgs)) if imgs else set_wp(gen_wallpaper("cyberpunk"))

    # DÉSINSTALLER
    if any(w in t for w in ["désinstalle","supprime le logiciel","supprime l'application"]):
        app=re.sub(r'.*(désinstalle|supprime le logiciel|supprime l\'application)\s*','',t).strip()
        if app: return uninstall_app(app)

    # NETTOYAGE
    if any(w in t for w in ["nettoie","nettoyage","libère de l'espace","vide le cache"]): return clean_system()
    if any(w in t for w in ["screenshot","capture","screenshoot","capture d'écran"]): return screenshot()
    if any(w in t for w in ["mode sombre","dark mode"]): return dark_mode(True)
    if any(w in t for w in ["mode clair","light mode"]): return dark_mode(False)

    # VOLUME
    m=re.search(r'volume.*?(\d+)',t)
    if m: return set_volume(int(m.group(1)))
    if any(w in t for w in ["coupe le son","mute","silence"]): return set_volume(0)
    if any(w in t for w in ["volume max","son maximum","volume à fond"]): return set_volume(100)

    # APPS
    for app,path in APPS.items():
        if app in t and any(w in t for w in ["ouvre","lance","démarre"]):
            if os.path.exists(path): subprocess.Popen([path]); return f"{app.capitalize()} lancé."
            try: subprocess.Popen(app.split()[0]+".exe"); return f"{app.capitalize()} lancé."
            except: return f"'{app}' introuvable."

    # SITES
    for site,url in SITES.items():
        if site in t and any(w in t for w in ["ouvre","va sur","aller","accède"]):
            webbrowser.open(url); return f"Ouverture de {site.capitalize()}."

    # RECHERCHE
    if any(w in t for w in ["cherche","recherche","googl"]):
        q=re.sub(r'.*(cherche|recherche|googl\w*)\s*','',t).strip()
        if q: webbrowser.open(f"https://google.com/search?q={urllib.parse.quote(q)}"); return f"Recherche: {q}"

    # RAPPEL
    m=re.search(r'rappelle.{0,20}dans (\d+) minute',t)
    if m:
        mins=int(m.group(1)); msg=re.sub(r'rappelle.*?dans \d+ minute.*?:?\s*','',t).strip() or "Rappel"
        return add_reminder(msg,mins)

    # SYSTÈME
    if any(w in t for w in ["stats système","rapport système","état du pc","info pc"]):
        cpu=psutil.cpu_percent(0.5); ram=psutil.virtual_memory()
        b=psutil.sensors_battery()
        return f"CPU: {cpu}% | RAM: {ram.used//1024//1024}Mo/{ram.total//1024//1024}Mo ({ram.percent}%) | {'Batterie: '+str(round(b.percent))+'%' if b else 'PC fixe'}"
    if any(w in t for w in ["batterie","battery"]):
        b=psutil.sensors_battery()
        return f"Batterie: {b.percent:.0f}%{' ⚡ en charge' if b.power_plugged else ''}" if b else "Pas de batterie."
    if "wifi" in t:
        r=subprocess.run(["netsh","wlan","show","interfaces"],capture_output=True,text=True,encoding="cp850")
        ssid=re.search(r"SSID\s+:\s(.+)",r.stdout)
        return f"WiFi: {ssid.group(1).strip() if ssid else 'non connecté'}"
    if any(w in t for w in ["processus lourds","ram utilisée","ralentit","top processus"]):
        procs=sorted([(p.info['name'],p.info['memory_info'].rss//1024//1024)
                      for p in psutil.process_iter(['name','memory_info'])
                      if p.info.get('memory_info') and p.info['memory_info'].rss>30*1024*1024],
                     key=lambda x:x[1],reverse=True)[:5]
        return "Top RAM: "+" | ".join([f"{n}({m}Mo)" for n,m in procs])
    if any(w in t for w in ["disque","espace disque","stockage"]):
        d=psutil.disk_usage("C:\\"); return f"Disque C: {d.used//1024**3}Go/{d.total//1024**3}Go ({d.percent}%)"

    # ALIMENTATION
    if "plan performance" in t: return power_plan("performance")
    if "plan économie" in t: return power_plan("économie")
    if "plan équilibré" in t: return power_plan("équilibré")

    # VERROUILLER / ÉTEINDRE
    if any(w in t for w in ["verrouille","lock l'écran"]): ctypes.windll.user32.LockWorkStation(); return "Écran verrouillé."
    if any(w in t for w in ["éteins le pc","shutdown","arrête le pc"]): subprocess.run(["shutdown","/s","/t","10"]); return "Arrêt dans 10 secondes."
    if any(w in t for w in ["redémarre","restart","reboot"]): subprocess.run(["shutdown","/r","/t","5"]); return "Redémarrage dans 5s."
    if any(w in t for w in ["mise en veille","sleep","veille"]): subprocess.run(["rundll32.exe","powrprof.dll,SetSuspendState","0","1","0"]); return "Mise en veille."

    # TRADUCTION
    m=re.search(r'traduis?\s+(?:en\s+)?(\w+)\s*:?\s*(.+)',t)
    if m:
        langs={"anglais":"en","espagnol":"es","allemand":"de","italien":"it",
               "japonais":"ja","arabe":"ar","russe":"ru","chinois":"zh","coréen":"ko","portugais":"pt"}
        tgt=langs.get(m.group(1).lower(),"en")
        try:
            from deep_translator import GoogleTranslator
            return GoogleTranslator(source='auto',target=tgt).translate(m.group(2))
        except: return ask_ai_cascade(f"Traduis en {m.group(1)}: {m.group(2)}")

    return None

# --- PIPELINE
def activate():
    if S["active"]: return
    S["active"]=True; push("status","ACTIVÉ")
    threading.Thread(target=_voice_pipe, daemon=True).start()

def _voice_pipe():
    try:
        txt=listen_cmd()
        if txt: _process(txt)
    except Exception as e:
        import traceback
        log(f"[ERREUR] {e}","red")
        with open(LOG_F,"a",encoding="utf-8") as f: f.write(traceback.format_exc()+"\n")
        push("response",f"Petit souci technique : {str(e)[:80]}"); push("status","EN VEILLE")
    finally: S["active"]=False

def _process_text(txt):
    if S["active"]: return
    S["active"]=True; push("user_text",txt)
    def _run():
        try: _process(txt)
        except Exception as e:
            import traceback
            log(f"[ERREUR] {e}","red")
            with open(LOG_F,"a",encoding="utf-8") as f: f.write(traceback.format_exc()+"\n")
            push("response",f"Petit souci technique : {str(e)[:80]}"); push("status","EN VEILLE")
        finally: S["active"]=False
    threading.Thread(target=_run, daemon=True).start()

def _process(txt):
    push("status","ANALYSE...")
    log(f"[USER] {txt}","yellow")
    resp=parse(txt)
    if not resp:
        push("status","IA EN COURS...")
        resp=ask_ai_cascade(txt)
    push("response",resp); push("status","EN VEILLE")
    speak(resp)

# --- METRICS
def metrics_loop():
    while True:
        try:
            cpu=psutil.cpu_percent(1); ram=psutil.virtual_memory()
            disk=psutil.disk_usage("C:\\"); b=psutil.sensors_battery()
            bk_count=len([d for d in os.listdir(os.path.join(BASE,"backups"))
                         if os.path.isdir(os.path.join(BASE,"backups",d))])
            S["metrics"]={
                "cpu":cpu,"ram":ram.percent,"ram_used":ram.used//1024//1024,
                "ram_total":ram.total//1024//1024,"disk":disk.percent,
                "battery":b.percent if b else -1,"charging":b.power_plugged if b else False,
                "procs":len(psutil.pids()),"online":S["online"],
                "focus":S["concentration_mode"],"focus_activity":S["focus_activity"],
                "backups":bk_count,
                "ai_cascade":{
                    "local":"🟢" if S["local_ai_ok"] else "⚫",
                    "groq":"🟢" if CFG.get("groq_key","")!="YOUR_GROQ_KEY" else "⚫",
                    "mistral":"🟢" if CFG.get("mistral_key","")!="YOUR_MISTRAL_KEY" else "⚫",
                    "gemini":"🟢" if CFG.get("gemini_key","")!="YOUR_GEMINI_KEY" else "⚫",
                    "pro":"♾️" if CFG.get("gemini_pro_key","")!="YOUR_GEMINI_PRO_KEY" else "⚫",
                    "el":"🎙️" if CFG.get("elevenlabs_key","")!="YOUR_ELEVENLABS_KEY" else "⚫",
                }
            }
            push("metrics",S["metrics"])
        except: pass
        time.sleep(2)

# --- HTTP SERVER
class Handler(http.server.SimpleHTTPRequestHandler):
    def __init__(self,*a,**k): super().__init__(*a,directory=UI_DIR,**k)
    def end_headers(self):
        # Empêche le navigateur de garder une vieille version de l'interface
        self.send_header("Cache-Control","no-store, no-cache, must-revalidate")
        super().end_headers()
    def do_GET(self):
        p=self.path
        if p.startswith("/briefing"):
            body=json.dumps(news_matin.last_briefing(),ensure_ascii=False).encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type","application/json; charset=utf-8")
            self.send_header("Content-Length",str(len(body))); self.end_headers()
            self.wfile.write(body); return
        if p=="/events":
            self.send_response(200)
            self.send_header("Content-Type","text/event-stream")
            self.send_header("Cache-Control","no-cache")
            self.send_header("Access-Control-Allow-Origin","*"); self.end_headers()
            self.wfile.write(f"data: {json.dumps({'event':'metrics','data':S['metrics']})}\n\n".encode())
            self.wfile.flush()
            while True:
                try:
                    msg=UIQ.get(timeout=1)
                    self.wfile.write(f"data: {msg}\n\n".encode()); self.wfile.flush()
                except queue.Empty: self.wfile.write(b": ping\n\n"); self.wfile.flush()
                except: break
        elif p=="/activate": activate(); self._j({"ok":True})
        elif p.startswith("/send"):
            qv=urllib.parse.parse_qs(urllib.parse.urlparse(p).query).get("q",[""])[0]
            if qv: _process_text(qv)
            self._j({"ok":True})
        elif p=="/backups": self._j(list_backups())
        elif p=="/metrics": self._j(S["metrics"])
        else: super().do_GET()
    def _j(self,d):
        self.send_response(200); self.send_header("Content-Type","application/json")
        self.send_header("Access-Control-Allow-Origin","*"); self.end_headers()
        self.wfile.write(json.dumps(d).encode())
    def log_message(self,*a): pass

# --- ACCÈS DISTANT (iPhone via Tailscale)
# Serveur séparé, port 7475 : il ne fait QUE donner le briefing.
# Accepté seulement depuis Tailscale (100.64.0.0/10) ou ce PC, et avec le code secret.
import ipaddress, hmac
_TS_NET=ipaddress.ip_network("100.64.0.0/10")
class RemoteHandler(http.server.BaseHTTPRequestHandler):
    def _send(self,code,body,ctype="text/plain; charset=utf-8"):
        b=body.encode("utf-8")
        self.send_response(code); self.send_header("Content-Type",ctype)
        self.send_header("Content-Length",str(len(b))); self.end_headers(); self.wfile.write(b)
    def do_GET(self):
        try: ip=ipaddress.ip_address(self.client_address[0])
        except ValueError: return self._send(403,"Interdit")
        if not (ip.is_loopback or ip in _TS_NET):
            return self._send(403,"Interdit")
        u=urllib.parse.urlparse(self.path)
        tok=urllib.parse.parse_qs(u.query).get("token",[""])[0]
        if not hmac.compare_digest(tok,CFG.get("remote_token","")):
            log(f"[DISTANT] Code refusé depuis {ip}","red")
            return self._send(401,"Code secret invalide")
        if u.path in ("/briefing.txt","/briefing.json"):
            if not news_matin.already_done_today():
                do_morning_news()
            d=news_matin.last_briefing()
            log(f"[DISTANT] Briefing envoyé à {ip}","green")
            if u.path=="/briefing.json":
                return self._send(200,json.dumps(d,ensure_ascii=False),"application/json; charset=utf-8")
            return self._send(200,d.get("texte","Pas de briefing disponible."))
        if u.path=="/ask":
            q=urllib.parse.parse_qs(u.query).get("q",[""])[0].strip()
            if not q: return self._send(400,"Question vide")
            log(f"[iPhone] {q}","yellow"); push("user_text","📱 "+q)
            try:
                resp=parse(q) or ask_ai_cascade(q)
            except Exception as e:
                log(f"[ERREUR] {e}","red"); resp=f"Petit souci technique : {str(e)[:80]}"
            resp=bx.humanize(str(resp),CFG)
            push("response",resp)
            return self._send(200,resp)
        if u.path=="/ping": return self._send(200,"JARVIS en ligne")
        return self._send(404,"Introuvable")
    def log_message(self,*a): pass

def _tailscale_ip():
    try:
        r=subprocess.run(["tailscale","ip","-4"],capture_output=True,text=True,timeout=5)
        return r.stdout.strip().splitlines()[0] if r.returncode==0 and r.stdout.strip() else None
    except Exception: return None

def start_remote_server():
    if not CFG.get("remote_enabled",True): return
    try:
        srv=socketserver.ThreadingTCPServer(("0.0.0.0",CFG["remote_port"]),RemoteHandler)
        threading.Thread(target=srv.serve_forever,daemon=True).start()
        ts=_tailscale_ip()
        if ts: log(f"[✓] iPhone:    http://{ts}:{CFG['remote_port']}/briefing.txt?token=...","green")
        else: log("[DISTANT] Serveur iPhone prêt, mais Tailscale n'est pas détecté sur ce PC","yellow")
    except Exception as e:
        log(f"[DISTANT] {e}","red")

# --- MAIN
def main():
    print(Fore.CYAN+"JARVIS v4 - ElevenLabs, cascade IA, briefing, agenda, iPhone, gestes"+Style.RESET_ALL)

    try: urllib.request.urlopen("https://8.8.8.8",timeout=2); S["online"]=True; log("[NET] En ligne ✓","green")
    except: S["online"]=False; log("[NET] Hors-ligne","yellow")

    threading.Thread(target=check_ollama, daemon=True).start()
    def start_server():
        socketserver.TCPServer.allow_reuse_address = True
        server = socketserver.ThreadingTCPServer(("localhost",CFG["ui_port"]),Handler)
        server.serve_forever()
    threading.Thread(target=start_server, daemon=True).start()
    start_remote_server()
    log(f"[✓] Interface: http://localhost:{CFG['ui_port']}","green")
    log(f"[✓] Carte:     http://localhost:{CFG['ui_port']}/map.html","green")

    threading.Thread(target=metrics_loop, daemon=True).start()
    threading.Thread(target=check_reminders, daemon=True).start()
    threading.Thread(target=check_posts, daemon=True).start()

    def _watch_app():
        while True: get_active_app(); time.sleep(3)
    threading.Thread(target=_watch_app, daemon=True).start()

    def _auto_suggest():
        habits=db_top_habits(10)
        sugg=analyze_and_suggest(habits)
        if sugg: push("auto_suggestions",sugg); speak(f"J'ai {len(sugg)} amélioration(s) à vous proposer, {CFG['owner_name']}.")
    schedule.every(6).hours.do(lambda:threading.Thread(target=_auto_suggest,daemon=True).start())
    threading.Thread(target=lambda:[schedule.run_pending() or time.sleep(60) for _ in iter(int,1)],daemon=True).start()

    keyboard.add_hotkey(CFG["hotkey"], activate)
    log(f"[✓] Raccourci: {CFG['hotkey']}","green")
    log(f"[✓] Mots-clés: {[CFG['wake_word']]+CFG['alt_wake_words']}","green")
    log(f"[✓] ElevenLabs: {'configuré ✓' if CFG.get('elevenlabs_key','')!='YOUR_ELEVENLABS_KEY' else 'non configuré (pyttsx3 actif)'}","green")

    time.sleep(1); webbrowser.open(f"http://localhost:{CFG['ui_port']}")
    speak(get_line("boot",CFG["owner_name"]))
    log("[JARVIS] Prêt.\n","cyan")

    # News du matin automatiques : une fois par jour, au premier lancement entre 5 h et 13 h
    def _auto_news():
        time.sleep(4)
        if S["active"]: time.sleep(10)
        txt=do_morning_news()
        push("response",txt); speak(txt)
    if CFG.get("news_auto",True) and 5<=datetime.datetime.now().hour<13 and not news_matin.already_done_today():
        threading.Thread(target=_auto_news,daemon=True).start()

    # Lancer l'ecoute vocale dans un thread separe
    t_wake = threading.Thread(target=listen_wake, daemon=True)
    t_wake.start()

    # Garder le programme actif
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        log("\n[JARVIS] Arret.","cyan")

if __name__=="__main__": main()
