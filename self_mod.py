"""
JARVIS SELF-MOD ENGINE
Génère • Valide • Montre • Backup • Installe • Redémarre
"""
import os, sys, json, time, shutil, subprocess, datetime
import hashlib, sqlite3, threading, re

BASE   = os.path.dirname(os.path.abspath(__file__))
MAIN   = os.path.join(BASE, "jarvis.py")
BACKUP = os.path.join(BASE, "backups")
DB     = os.path.join(BASE, "brain", "memory.db")
os.makedirs(BACKUP, exist_ok=True)

_pending = {}

DANGEROUS = [
    r'os\.system\s*\(', r'shutil\.rmtree\s*\(\s*["\']/',
    r'subprocess\.call.*rm\s+-rf', r'eval\s*\(', r'exec\s*\(',
    r'open\s*\(["\'].*config\.json.*["\'],\s*["\']w',
]

# --- BACKUP
def create_backup(reason="auto"):
    ts = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    bdir = os.path.join(BACKUP, f"backup_{ts}_{reason}")
    os.makedirs(bdir, exist_ok=True)
    backed = []
    for f in ["jarvis.py","config.json","self_mod.py","voice_engine.py"]:
        src = os.path.join(BASE, f)
        if os.path.exists(src):
            shutil.copy2(src, os.path.join(bdir, f)); backed.append(f)
    brain_src = os.path.join(BASE, "brain")
    if os.path.exists(brain_src):
        shutil.copytree(brain_src, os.path.join(bdir,"brain"), dirs_exist_ok=True)
    manifest = {"timestamp":ts,"reason":reason,"files":backed,
                "hash":_hash(MAIN),"python":sys.version}
    with open(os.path.join(bdir,"manifest.json"),"w") as f:
        json.dump(manifest, f, indent=2)
    _cleanup(10)
    return bdir, ts

def _hash(path):
    if not os.path.exists(path): return ""
    with open(path,"rb") as f: return hashlib.md5(f.read()).hexdigest()

def _cleanup(keep=10):
    bks = sorted([d for d in os.listdir(BACKUP)
                  if os.path.isdir(os.path.join(BACKUP,d))])
    while len(bks) > keep:
        shutil.rmtree(os.path.join(BACKUP, bks.pop(0)), ignore_errors=True)

def list_backups():
    result = []
    for d in sorted(os.listdir(BACKUP), reverse=True):
        mp = os.path.join(BACKUP, d, "manifest.json")
        if os.path.exists(mp):
            with open(mp) as f: m = json.load(f)
            result.append({"dir":d,"timestamp":m.get("timestamp",""),
                           "reason":m.get("reason",""),"files":m.get("files",[])})
    return result

def restore_backup(bdir_name):
    bp = os.path.join(BACKUP, bdir_name)
    if not os.path.exists(bp): return False, "Backup introuvable."
    create_backup("pre_restore")
    for f in os.listdir(bp):
        src = os.path.join(bp, f)
        if os.path.isfile(src) and (f.endswith(".py") or f == "config.json"):
            shutil.copy2(src, os.path.join(BASE, f))
    return True, f"Backup {bdir_name} restauré."

# --- CODE VALIDATION
def validate(code):
    issues = []
    for p in DANGEROUS:
        if re.search(p, code, re.IGNORECASE):
            issues.append(f"Pattern dangereux: {p[:30]}")
    return len(issues)==0, issues

# --- GENERATE
def generate(request):
    try:
        from jarvis import ask_ai_cascade
    except: return None, "JARVIS non chargé."
    prompt = f"""Tu es expert Python. Génère UNE fonction Python pour JARVIS (assistant Windows).
DEMANDE: {request}
Règles: autonome, safe, docstring, try/except, compatible Windows.
Réponds UNIQUEMENT avec le code Python (def ...). Rien d'autre."""
    code = ask_ai_cascade(prompt, force_quality=True)
    code = re.sub(r'```python\n?|```\n?','',code).strip()
    return code, None

# --- INJECT
def inject(code, fname):
    try:
        with open(MAIN,"r",encoding="utf-8") as f: content = f.read()
        marker = "\n# ─── AUTO-GENERATED ───────────────────────────────────────────────────────\n"
        if marker not in content: content += marker
        if f"def {fname}" in content:
            content = re.sub(rf"def {fname}\(.*?(?=\ndef |\nclass |\nif __name__)",
                             code+"\n\n", content, flags=re.DOTALL)
        else:
            content += f"\n# {fname}\n{code}\n"
        with open(MAIN,"w",encoding="utf-8") as f: f.write(content)
        return True
    except Exception as e:
        print(f"[INJECT] {e}"); return False

# --- WORKFLOW
def self_improve_workflow(request, push_fn=None, speak_fn=None):
    def notify(m):
        if push_fn: push_fn("improvement_step", m)
        if speak_fn: speak_fn(m)
        print(f"[SELF-MOD] {m}")

    notify("Génération du code en cours...")
    fname = "fn_" + re.sub(r'[^a-z0-9]','_', request.lower()[:25]).strip('_')
    code, err = generate(request)
    if err or not code:
        msg = f"Impossible de générer: {err}"
        notify(msg); return {"status":"error","message":msg}

    safe, issues = validate(code)
    preview = {
        "status":"pending_approval","request":request,
        "function_name":fname,"code":code,
        "code_lines":len(code.split('\n')),"safe":safe,
        "safety_issues":issues,"description":request[:100],
    }
    if push_fn: push_fn("improvement_preview", preview)
    notify(f"Code généré — {len(code.split(chr(10)))} lignes. "
           f"{'✓ Sécurisé.' if safe else '⚠️ Vérifiez.'} "
           f"Dites 'installe' pour confirmer.")
    _pending[fname] = {"code":code,"func_name":fname,"description":request}
    return preview

def confirm_improvement(fname=None, push_fn=None, speak_fn=None):
    def notify(m):
        if push_fn: push_fn("improvement_step",m)
        if speak_fn: speak_fn(m)

    imp = _pending.get(fname)
    if not imp and _pending:
        fname = list(_pending.keys())[-1]; imp = _pending[fname]
    if not imp:
        notify("Aucune amélioration en attente."); return False

    notify("Création du backup...")
    bdir, ts = create_backup(f"pre_{imp['func_name'][:20]}")

    safe, issues = validate(imp["code"])
    if not safe:
        notify(f"Code refusé: {issues[0] if issues else '?'}"); return False

    try: compile(imp["code"],"<string>","exec")
    except SyntaxError as e:
        notify(f"Erreur syntaxe: {e}"); return False

    if not inject(imp["code"], imp["func_name"]):
        notify("Échec injection."); return False

    try:
        c = sqlite3.connect(DB)
        c.execute("CREATE TABLE IF NOT EXISTS improvements(id INTEGER PRIMARY KEY,title TEXT,code TEXT,status TEXT,ts TEXT,backup TEXT)")
        c.execute("INSERT INTO improvements(title,code,status,ts,backup) VALUES(?,?,?,?,?)",
            (imp["description"],imp["code"],"installed",
             datetime.datetime.now().isoformat(),bdir))
        c.commit(); c.close()
    except: pass

    del _pending[fname]
    notify(f"✓ Backup créé: backup_{ts}")
    notify(f"✓ Fonction '{imp['func_name']}' installée.")
    notify("Redémarrage dans 3 secondes...")
    if push_fn: push_fn("improvement_installed",{"function":fname,"backup":bdir})
    time.sleep(1); restart_jarvis(3)
    return True

def cancel_improvement(push_fn=None, speak_fn=None):
    _pending.clear()
    msg = "Amélioration annulée. Aucune modification."
    if push_fn: push_fn("improvement_cancelled", msg)
    if speak_fn: speak_fn(msg)
    return msg

def analyze_and_suggest(habits):
    try:
        from jarvis import ask_ai_cascade
        habit_str = "\n".join([f"- '{c}' x{n}" for c,n in habits[:10]])
        prompt = f"""Analyse ces habitudes JARVIS:\n{habit_str}
Propose 2 améliorations. JSON uniquement:
[{{"title":"...","description":"...","function_name":"fn_xxx","trigger_phrase":"...","safe":true}}]"""
        resp = ask_ai_cascade(prompt, force_quality=True)
        resp = re.sub(r'```json\n?|```\n?','',resp).strip()
        m = re.search(r'\[.*\]', resp, re.DOTALL)
        if m: return json.loads(m.group())
    except: pass
    return []

def restart_jarvis(delay=3):
    def _r():
        time.sleep(delay)
        subprocess.Popen([sys.executable, MAIN],
                        creationflags=subprocess.CREATE_NEW_CONSOLE if sys.platform=="win32" else 0)
        os._exit(0)
    threading.Thread(target=_r, daemon=True).start()
    return f"Redémarrage dans {delay}s."
