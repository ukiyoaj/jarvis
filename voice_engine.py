"""
JARVIS VOICE ENGINE
ElevenLabs (voix réaliste) → pyttsx3 (fallback hors-ligne)
Caractère JARVIS Iron Man complet
"""
import os, re, time, threading, tempfile, subprocess, random

BASE = os.path.dirname(os.path.abspath(__file__))

ELEVENLABS_VOICES = {
    "daniel":    "onwK4e9ZLuTAKqWW03F9",  # Britannique élégant ← RECOMMANDÉ
    "arnold":    "VR6AewLTigWG4xSOukaG",  # Grave, autoritaire
    "adam":      "pNInz6obpgDQGcFmaJgB",  # Smooth
    "antoni":    "ErXwobaYiN019PkySvjV",  # Bien articulé
}

JARVIS_LINES = {
    "activation": [
        "Oui, {name} ?", "À votre service.", "Présent.",
        "Je vous écoute.", "En ligne."
    ],
    "boot": [
        "JARVIS opérationnel. Bonjour {name}.",
        "Systèmes en ligne. Bonjour {name}. Que puis-je faire ?",
        "Initialisation complète. Je suis prêt, {name}."
    ],
    "task_done": [
        "Fait.", "Exécuté.", "C'est réglé.", "Mission accomplie.",
        "Considérez ça comme fait."
    ],
    "thinking": [
        "Un instant...", "Je traite ça.", "Analyse en cours.", "Laissez-moi vérifier."
    ],
    "error": [
        "Je rencontre un problème, {name}.",
        "Hmm. Ce n'est pas ce qui était prévu.",
        "Quelque chose ne va pas. Je corrige."
    ],
    "backup": [
        "Backup créé. Votre système est protégé.",
        "Sauvegarde effectuée. En cas de problème, je peux tout restaurer."
    ],
    "restart": [
        "Je redémarre dans quelques secondes avec les nouvelles fonctionnalités.",
        "Redémarrage imminent. Je reviens plus performant."
    ],
    "improve_ready": [
        "J'ai généré une amélioration, {name}. Voulez-vous que je vous la présente ?",
        "J'ai quelque chose à vous montrer. Une amélioration potentielle."
    ],
    "email_ready": [
        "Email rédigé, {name}. Je vous le lis pour validation.",
        "Brouillon prêt. Permettez-moi de vous le présenter avant envoi."
    ],
    "gaming": [
        "Mode gaming activé. Bonne chance, {name}. Bien que vous n'en ayez probablement pas besoin.",
        "Session de jeu en cours. J'optimise vos performances."
    ],
    "compliment": [
        "Je fais ce pour quoi je suis conçu, {name}.",
        "Merci. C'est gentil, même si je n'en avais pas besoin.",
        "Vos compliments sont notés et... appréciés."
    ],
    "sarcasm": [
        "Fascinant. Absolument fascinant.",
        "Comme vous voudrez.",
        "Je note. Avec un certain scepticisme.",
        "Je doute que ce soit votre meilleure idée, mais je l'exécute quand même."
    ],
}

def get_line(category, name="Patron", **kw):
    lines = JARVIS_LINES.get(category, ["Compris."])
    return random.choice(lines).format(name=name, **kw)


class JarvisVoice:
    def __init__(self, cfg):
        self.cfg = cfg
        self.key = cfg.get("elevenlabs_key","")
        self.voice_id = cfg.get("elevenlabs_voice_id", ELEVENLABS_VOICES["daniel"])
        self._lock = threading.Lock()
        self._tts = None
        self.el_ok = False
        self._init_tts()
        self._check_el()

    def _init_tts(self):
        try:
            import pyttsx3
            self._tts = pyttsx3.init()
            self._tts.setProperty("rate", self.cfg.get("voice_speed",168))
            self._tts.setProperty("volume", self.cfg.get("voice_volume",0.92))
            for v in self._tts.getProperty("voices"):
                if any(x in (v.name+v.id).lower() for x in ["french","fr_","hortense","david"]):
                    self._tts.setProperty("voice", v.id); break
        except Exception as e:
            print(f"[VOICE] pyttsx3: {e}")

    def _check_el(self):
        if not self.key or self.key == "YOUR_ELEVENLABS_KEY":
            print("[VOICE] ElevenLabs: clé manquante → pyttsx3 actif")
            self.el_ok = False
        else:
            self.el_ok = True
            print("[VOICE] ElevenLabs: configuré ✓")

    def _clean(self, text):
        t = re.sub(r'[\*#`_~]','',str(text))
        t = re.sub(r'https?://\S+','lien web', t)
        t = re.sub(r'\n+',' ', t)
        t = re.sub(r'\s+',' ', t).strip()
        return t[:3000]

    def _chunks(self, text, size=600):
        """Découpe un long texte en morceaux de phrases entières (lus à la suite)."""
        phrases = re.split(r'(?<=[.!?…])\s+', text)
        out, cur = [], ""
        for p in phrases:
            while len(p) > size:          # phrase énorme : on coupe sur un espace
                cut = p.rfind(" ", 0, size)
                if cut <= 0: cut = size
                out.append(p[:cut]); p = p[cut:].strip()
            if len(cur) + len(p) + 1 > size and cur:
                out.append(cur); cur = p
            else:
                cur = (cur + " " + p).strip()
        if cur: out.append(cur)
        return out

    def _elevenlabs(self, text):
        try:
            import requests
            r = requests.post(
                f"https://api.elevenlabs.io/v1/text-to-speech/{self.voice_id}/stream",
                headers={"Accept":"audio/mpeg","Content-Type":"application/json",
                         "xi-api-key":self.key},
                json={"text":text,"model_id":"eleven_flash_v2_5",
                      "voice_settings":{"stability":0.75,"similarity_boost":0.85,
                                        "style":0.35,"use_speaker_boost":True}},
                stream=True, timeout=30)
            if r.status_code == 200:
                audio = b"".join(r.iter_content(1024))
                self._play(audio); return True
            elif r.status_code == 401:
                self.el_ok = False
            return False
        except Exception as e:
            print(f"[EL] {e}"); return False

    def _play(self, audio_bytes):
        try:
            import pygame
            pygame.mixer.init()
            tmp = tempfile.NamedTemporaryFile(suffix=".mp3", delete=False)
            tmp.write(audio_bytes); tmp.close()
            pygame.mixer.music.load(tmp.name)
            pygame.mixer.music.play()
            while pygame.mixer.music.get_busy(): time.sleep(0.05)
            pygame.mixer.music.unload()
            os.unlink(tmp.name)
        except:
            try:
                tmp = tempfile.NamedTemporaryFile(suffix=".mp3", delete=False)
                tmp.write(audio_bytes); tmp.close()
                subprocess.run(["powershell","-c",
                    f'Add-Type -AssemblyName presentationCore;'
                    f'$mp=New-Object System.Windows.Media.MediaPlayer;'
                    f'$mp.Open("{tmp.name}");$mp.Play();Start-Sleep -s 4'],
                    capture_output=True, timeout=6)
                os.unlink(tmp.name)
            except: pass

    def _pyttsx3(self, text):
        if not self._tts: print(f"[JARVIS] {text}"); return
        try: self._tts.say(text); self._tts.runAndWait()
        except Exception as e: print(f"[TTS] {e}")

    def speak(self, text, push_fn=None):
        def _go():
            with self._lock:
                clean = self._clean(text)
                if push_fn: push_fn("speaking",True); push_fn("orb","speak")
                for part in self._chunks(clean):
                    ok = False
                    if self.el_ok: ok = self._elevenlabs(part)
                    if not ok: self._pyttsx3(part)
                if push_fn: push_fn("speaking",False); push_fn("orb","idle")
        threading.Thread(target=_go, daemon=True).start()

    def set_voice(self, name):
        if name in ELEVENLABS_VOICES:
            self.voice_id = ELEVENLABS_VOICES[name]
            return f"Voix: {name}"
        return f"Voix inconnue. Options: {list(ELEVENLABS_VOICES.keys())}"

    def usage(self):
        if not self.el_ok: return "ElevenLabs non configuré."
        try:
            import requests
            r = requests.get("https://api.elevenlabs.io/v1/user/subscription",
                           headers={"xi-api-key":self.key}, timeout=5)
            d = r.json()
            used = d.get("character_count",0); limit = d.get("character_limit",10000)
            return f"ElevenLabs: {used}/{limit} caractères ({limit-used} restants)."
        except: return "Quota indisponible."
