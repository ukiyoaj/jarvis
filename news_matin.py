"""
JARVIS — NEWS DU MATIN + LECTURE DU COFFRE OBSIDIAN
- Lit le coffre Obsidian pour deviner les centres d'intérêt (projets, tags, notes de veille).
- Cherche les news récentes (Google News RSS, gratuit, sans clé).
- Fait résumer par Groq en un briefing court, lu à voix haute.
- Écrit une note "Veille/AAAA-MM-JJ - News du matin.md" dans le coffre.
"""
import os, re, json, datetime, urllib.parse, xml.etree.ElementTree as ET
from email.utils import parsedate_to_datetime
import requests
import briefing_extras as bx
import rappels as rp

BASE = os.path.dirname(os.path.abspath(__file__))
BRAIN = os.path.join(BASE, "brain")
LAST_FILE = os.path.join(BRAIN, "news_last.json")
INTERESTS_FILE = os.path.join(BRAIN, "interets.json")

# Mots trop génériques pour être des centres d'intérêt
_GENERIC = {"projet", "projets", "idée", "idee", "idées", "veille", "journal", "cours",
            "modèle", "modèles", "accueil", "iut", "test", "en cours", "poésie", "poesie",
            "manga", "jarvis", "combo", "jeryo"}

# --- LECTURE DU COFFRE OBSIDIAN
def _frontmatter_tags(text):
    m = re.match(r"^---\s*\n(.*?)\n---", text, re.S)
    if not m: return []
    t = re.search(r"tags:\s*\[(.*?)\]", m.group(1))
    if not t: return []
    return [x.strip().strip("'\"").lower() for x in t.group(1).split(",") if x.strip()]

def _objectif(text):
    """Récupère la ligne sous '## Objectif' (résumé du projet)."""
    m = re.search(r"##\s*Objectif\s*\n+\s*-\s*(.+)", text)
    return m.group(1).strip() if m else ""

def read_vault(vault):
    """Retourne un petit résumé du coffre : projets, objectifs, tags."""
    if not vault or not os.path.isdir(vault):
        return None
    projets, tags = [], set()
    pdir = os.path.join(vault, "Projets")
    if os.path.isdir(pdir):
        for name in sorted(os.listdir(pdir)):
            folder = os.path.join(pdir, name)
            if not os.path.isdir(folder): continue
            main = os.path.join(folder, name + ".md")
            obj = ""
            for root, _, files in os.walk(folder):
                for f in files:
                    if not f.endswith(".md"): continue
                    try:
                        txt = open(os.path.join(root, f), encoding="utf-8").read()
                    except Exception:
                        continue
                    tags.update(_frontmatter_tags(txt))
                    if os.path.join(root, f) == main:
                        obj = _objectif(txt)
            projets.append({"nom": name, "objectif": obj})
    return {"projets": projets, "tags": sorted(t for t in tags if t not in _GENERIC)}

def _groq_chat(cfg, prompt, max_tokens=900):
    k = cfg.get("groq_key", "")
    if not k or k == "YOUR_GROQ_KEY": return None
    try:
        r = requests.post("https://api.groq.com/openai/v1/chat/completions",
            headers={"Authorization": f"Bearer {k}", "Content-Type": "application/json"},
            json={"model": cfg.get("groq_model", "openai/gpt-oss-120b"),
                  "max_tokens": max_tokens, "reasoning_effort": "low",
                  "messages": [{"role": "user", "content": prompt}]}, timeout=40)
        if r.status_code == 200:
            return r.json()["choices"][0]["message"]["content"].strip()
    except Exception:
        pass
    return None

def get_interests(cfg, log=print, force=False):
    """Liste de recherches news (en français), recalculée une fois par jour."""
    today = datetime.date.today().isoformat()
    if not force and os.path.exists(INTERESTS_FILE):
        try:
            d = json.load(open(INTERESTS_FILE, encoding="utf-8"))
            if d.get("date") == today and d.get("v") == 2 and d.get("queries"): return d["queries"]
        except Exception:
            pass

    extra = cfg.get("news_interests_extra", ["intelligence artificielle", "découverte scientifique"])
    vault = read_vault(cfg.get("obsidian_vault", ""))
    queries = []
    if vault:
        resume = "\n".join(f"- {p['nom']} : {p['objectif']}" for p in vault["projets"])
        prompt = (
            "Voici les projets et centres d'intérêt d'un étudiant en informatique, tirés de ses notes :\n"
            f"{resume}\nTags : {', '.join(vault['tags'])}\nIntérêts ajoutés : {', '.join(extra)}\n\n"
            "Propose 6 recherches d'actualités COURTES (1 à 3 mots, en français) qui couvrent ses passions "
            "science/tech. Elles doivent être ASSEZ LARGES pour avoir des articles chaque semaine "
            "(ex: 'hologramme', 'intelligence artificielle', 'robotique', 'cybersécurité'), "
            "pas des termes trop pointus. Ignore les projets "
            "purement créatifs ou personnels (poésie, manga, marque de vêtements). "
            "Réponds UNIQUEMENT par une liste JSON de chaînes, rien d'autre.")
        rep = _groq_chat(cfg, prompt, 300)
        if rep:
            m = re.search(r"\[.*\]", rep, re.S)
            try:
                queries = [q for q in json.loads(m.group(0)) if isinstance(q, str)][:6] if m else []
            except Exception:
                queries = []
        if not queries:  # secours sans IA : on prend les tags
            queries = vault["tags"][:5]
        log(f"[NEWS] Coffre Obsidian lu : {len(vault['projets'])} projets", "green")
    else:
        log("[NEWS] Coffre Obsidian introuvable (config 'obsidian_vault')", "yellow")
    for e in extra:
        if e not in queries: queries.append(e)
    queries = queries[:16]
    try:
        os.makedirs(BRAIN, exist_ok=True)
        json.dump({"date": today, "v": 2, "queries": queries}, open(INTERESTS_FILE, "w", encoding="utf-8"),
                  ensure_ascii=False, indent=1)
    except Exception:
        pass
    log(f"[NEWS] Centres d'intérêt : {queries}", "cyan")
    return queries

# --- NEWS DU MATIN
def fetch_news(query, max_items=3, max_age_h=72):
    url = ("https://news.google.com/rss/search?q=" + urllib.parse.quote(query)
           + "&hl=fr&gl=FR&ceid=FR:fr")
    out = []
    try:
        r = requests.get(url, timeout=10, headers={"User-Agent": "Mozilla/5.0 JARVIS"})
        root = ET.fromstring(r.content)
        now = datetime.datetime.now(datetime.timezone.utc)
        for it in root.iter("item"):
            title = (it.findtext("title") or "").strip()
            link = (it.findtext("link") or "").strip()
            src = (it.findtext("source") or "").strip()
            try:
                d = parsedate_to_datetime(it.findtext("pubDate"))
                if (now - d).total_seconds() > max_age_h * 3600: continue
            except Exception:
                pass
            if src and title.endswith(" - " + src): title = title[: -len(src) - 3]
            out.append({"titre": title, "source": src, "lien": link, "sujet": query})
            if len(out) >= max_items: break
    except Exception:
        pass
    return out

def build_briefing(cfg, log=print):
    """Retourne (texte_à_lire, liste_articles, infos_perso)."""
    # 1) Infos perso : agenda, mails, tâches, serveur
    perso = {}
    try: perso["agenda"] = bx.agenda_today(cfg, log)
    except Exception as e: log(f"[AGENDA] {e}", "yellow"); perso["agenda"] = None
    try: perso["mails"] = bx.unread_mails(cfg, log=log)
    except Exception as e: log(f"[MAILS] {e}", "yellow"); perso["mails"] = None
    try: perso["taches"] = bx.project_tasks(cfg.get("obsidian_vault", ""))
    except Exception: perso["taches"] = []
    try: perso["serveur"] = bx.server_status(cfg)
    except Exception: perso["serveur"] = None
    try: perso["rappels"] = rp.due(cfg)
    except Exception: perso["rappels"] = []
    try:
        ds = bx.next_ds(cfg, 3, 7, log)
        perso["ds"] = ds or []
    except Exception: perso["ds"] = []
    ds_txt = ("DS dans les 7 prochains jours : " + bx.next_ds_text(perso["ds"])) if perso["ds"] else ""
    blocs = [x for x in (bx.agenda_text(perso["agenda"], cfg),
                         bx.humanize(rp.briefing_text(cfg), cfg), ds_txt,
                         bx.mails_text(perso["mails"]), bx.server_text(perso["serveur"]),
                         bx.humanize(bx.tasks_text(perso["taches"]), cfg)) if x]

    # 2) News
    queries = get_interests(cfg, log)
    articles, seen = [], set()
    for q in queries:
        for a in fetch_news(q):
            key = a["titre"].lower()[:60]
            if key in seen: continue
            seen.add(key); articles.append(a)
    liste = "\n".join(f"- [{a['sujet']}] {a['titre']} ({a['source']})" for a in articles[:40])

    owner = cfg.get("owner_name", "Patron")
    jours = ["lundi","mardi","mercredi","jeudi","vendredi","samedi","dimanche"]
    mois = ["janvier","février","mars","avril","mai","juin","juillet","août","septembre",
            "octobre","novembre","décembre"]
    n = datetime.date.today()
    date_txt = f"{jours[n.weekday()]} {n.day} {mois[n.month-1]}"
    prompt = (
        f"Tu es JARVIS, l'assistant de {owner}. Nous sommes {date_txt}. Fais-lui son briefing du matin "
        "EN FRANÇAIS, lu à voix haute, dans cet ordre :\n"
        "1. 'Bonjour' + la date.\n"
        "2. Sa journée : les cours et rendez-vous de l'agenda avec les heures (s'il n'y a rien, dis-le en une phrase). "
        "Dis toujours le NOM de la matière, jamais son code (pas de R1.07).\n"
        "2 bis. Ses RAPPELS du jour : cite-les TOUS clairement, ce sont les choses qu'il s'est demandé de faire "
        "(signale ceux en retard). Puis préviens s'il a un DS dans les 7 jours (matière, jour, heure).\n"
        "3. Les mails non lus : combien, et les plus importants en une phrase (ignore pubs et newsletters).\n"
        "4. L'état du serveur maison, seulement si l'info est fournie.\n"
        "5. Ce qu'il pourrait avancer aujourd'hui : choisis 2 tâches parmi ses projets, "
        "en tenant compte du temps libre dans son agenda.\n"
        "6. 3 à 5 news science/tech, une phrase chacune.\n"
        "7. Un court point foot (PSG, Real Madrid, FC Barcelone, France, Tunisie) s'il y a des news.\n"
        "Ton naturel, un peu à la Iron Man. Pas de markdown, pas de liste, pas de liens. Maximum 280 mots.\n\n"
        "=== INFOS PERSO ===\n" + ("\n\n".join(blocs) or "(aucune)") +
        "\n\n=== NEWS ===\n" + (liste or "(aucune news trouvée)"))
    texte = _groq_chat(cfg, prompt, 1500)
    if not texte:
        courts = [x for x in (bx.agenda_text(perso["agenda"]), bx.mails_text(perso["mails"]),
                              bx.server_text(perso["serveur"])) if x]
        texte = "Bonjour. " + " ".join(re.sub(r"\n- ", ". ", b) for b in courts)
        if articles: texte += " Titres du jour : " + ". ".join(a["titre"] for a in articles[:4]) + "."
    return texte, articles, perso

def save_to_vault(cfg, texte, articles, log=print, perso=None):
    vault = cfg.get("obsidian_vault", "")
    if not vault or not os.path.isdir(vault): return None
    d = datetime.date.today().isoformat()
    folder = os.path.join(vault, "Veille")
    os.makedirs(folder, exist_ok=True)
    path = os.path.join(folder, f"{d} - News du matin.md")
    lines = ["---", "type: veille", "tags: [veille, news, jarvis]", f"date: {d}", "---",
             f"# News du matin — {d}", "", "## Briefing de JARVIS", texte, ""]
    perso = perso or {}
    if perso.get("agenda") is not None:
        lines += ["## Agenda", bx.agenda_text(perso["agenda"]).replace("Agenda du jour :\n", ""), ""]
    if perso.get("rappels"):
        lines += ["## Rappels du jour", "Coche-les dans [[Rappels]] quand c'est fait."] + \
                 [f"- {r['texte']}" for r in perso["rappels"]] + [""]
    if perso.get("taches"):
        lines += ["## À avancer"] + [f"- [ ] {t['tache']} — [[{t['projet']}]]" for t in perso["taches"]] + [""]
    boites = [b for b in (perso.get("mails") or []) if "total" in b]
    if boites:
        lines += ["## Mails"] + [f"- {b['nom']} : {b['total']} non lu(s)" for b in boites] + [""]
    lines += ["## Articles"]
    for sujet in dict.fromkeys(a["sujet"] for a in articles):
        lines.append(f"### {sujet}")
        for a in articles:
            if a["sujet"] == sujet:
                lines.append(f"- [{a['titre']}]({a['lien']}) — {a['source']}")
        lines.append("")
    lines.append("Retour : [[Veille]] · [[JARVIS]]")
    try:
        open(path, "w", encoding="utf-8").write("\n".join(lines))
        log(f"[NEWS] Note écrite dans le coffre : Veille/{os.path.basename(path)}", "green")
        return path
    except Exception as e:
        log(f"[NEWS] Impossible d'écrire dans le coffre : {e}", "red")
        return None

def morning_news(cfg, log=print):
    """Briefing complet : news + note Obsidian. Retourne le texte à lire."""
    log("[NEWS] Préparation des news du matin...", "cyan")
    texte, articles, perso = build_briefing(cfg, log)
    save_to_vault(cfg, texte, articles, log, perso)
    try:
        os.makedirs(BRAIN, exist_ok=True)
        json.dump({"date": datetime.date.today().isoformat(), "texte": texte,
                   "articles": articles}, open(LAST_FILE, "w", encoding="utf-8"),
                  ensure_ascii=False, indent=1)
    except Exception:
        pass
    log(f"[NEWS] {len(articles)} articles trouvés", "green")
    return texte

def already_done_today():
    try:
        return json.load(open(LAST_FILE, encoding="utf-8")).get("date") == datetime.date.today().isoformat()
    except Exception:
        return False

def last_briefing():
    try:
        return json.load(open(LAST_FILE, encoding="utf-8"))
    except Exception:
        return {}
