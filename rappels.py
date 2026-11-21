"""
JARVIS — Rappels dans Obsidian
Les rappels sont écrits dans la note « Rappels.md » à la racine du coffre :
    - [ ] 📅 2026-11-23 Aller faire ça
Cocher la case ou supprimer la ligne = rappel terminé.
"""
import os, re, datetime

_JOURS = ["lundi", "mardi", "mercredi", "jeudi", "vendredi", "samedi", "dimanche"]
_MOIS = ["janvier", "février", "mars", "avril", "mai", "juin", "juillet", "août",
         "septembre", "octobre", "novembre", "décembre"]
_LINE = re.compile(r"^- \[( |x|X)\] 📅 (\d{4}-\d{2}-\d{2}) (.+)$")

HEADER = """---
tags: [rappels, jarvis]
---
# Rappels

JARVIS ajoute ici les rappels que tu lui demandes. Coche la case ou supprime la ligne quand c'est fait.

"""

def path(cfg):
    v = cfg.get("obsidian_vault", "")
    return os.path.join(v, "Rappels.md") if v and os.path.isdir(v) else None

def _read(cfg):
    p = path(cfg)
    if not p or not os.path.exists(p): return []
    out = []
    for line in open(p, encoding="utf-8").read().splitlines():
        m = _LINE.match(line.strip())
        if m:
            out.append({"fait": m.group(1).lower() == "x",
                        "date": datetime.date.fromisoformat(m.group(2)),
                        "texte": m.group(3).strip(), "ligne": line})
    return out

# --- Dates en français
def parse_date(t, today=None):
    """Cherche une date dans la phrase → (date, morceau_trouvé) ; (None, '') si rien."""
    today = today or datetime.date.today()
    tl = t.lower()
    m = re.search(r"\bdans (\d+) jours?\b", tl)
    if m: return today + datetime.timedelta(int(m.group(1))), m.group(0)
    m = re.search(r"\bdans (une|1) semaine\b", tl)
    if m: return today + datetime.timedelta(7), m.group(0)
    for w, d in (("après-demain", 2), ("apres-demain", 2), ("après demain", 2), ("demain", 1),
                 ("aujourd'hui", 0), ("ce soir", 0), ("ce matin", 0), ("cet après-midi", 0)):
        if w in tl: return today + datetime.timedelta(d), w
    m = re.search(r"\b(?:(?:ce |le )?(?:" + "|".join(_JOURS) + r") )?(?:le )?(\d{1,2})(?:er)? (" + "|".join(_MOIS) + r")s?(?: (\d{4}))?\b", tl)
    if m:
        y = int(m.group(3)) if m.group(3) else today.year
        d = datetime.date(y, _MOIS.index(m.group(2)) + 1, int(m.group(1)))
        if d < today and not m.group(3): d = d.replace(year=y + 1)
        return d, m.group(0)
    m = re.search(r"\b(?:le )?(\d{1,2})/(\d{1,2})(?:/(\d{2,4}))?\b", tl)
    if m:
        y = int(m.group(3)) if m.group(3) else today.year
        if y < 100: y += 2000
        d = datetime.date(y, int(m.group(2)), int(m.group(1)))
        if d < today and not m.group(3): d = d.replace(year=y + 1)
        return d, m.group(0)
    m = re.search(r"\b(?:ce |le )?(" + "|".join(_JOURS) + r")( prochain)?\b", tl)
    if m:
        i = _JOURS.index(m.group(1))
        delta = (i - today.weekday()) % 7
        if delta == 0: delta = 7  # « lundi » dit un lundi = lundi prochain
        return today + datetime.timedelta(delta), m.group(0)
    return None, ""

def date_fr(d, today=None):
    today = today or datetime.date.today()
    if d == today: return "aujourd'hui"
    if d == today + datetime.timedelta(1): return "demain"
    return f"{_JOURS[d.weekday()]} {d.day} {_MOIS[d.month - 1]}"

# --- Actions
_VERBE = r"(rajoute|ajoute|mets|met|note|écris|ecris|garde|enregistre|programme|crée|cree)"
_TRIGGERS = (_VERBE + r"(-moi|-le|-la| moi)?\b.{0,25}?\b(rappels?|notes?|tâches?|taches?|liste|todo)\b"
             r"|rappelle[- ]moi|fais[- ]moi penser|note[- ]moi|n'oublie pas de me rappeler")

def add_from_text(cfg, text, today=None):
    today = today or datetime.date.today()
    p = path(cfg)
    if not p: return "Je ne trouve pas ton coffre Obsidian, vérifie 'obsidian_vault' dans config.json."
    d, found = parse_date(text, today)
    d = d or today
    t = re.sub(_TRIGGERS, " ", text, flags=re.I)
    if found: t = re.sub(re.escape(found), " ", t, flags=re.I)
    t = re.sub(r"\s+", " ", t).strip()
    for _ in range(3):
        t = re.sub(r"^\W*(pour |de |d'|d’|qu'|que |à |a |:|je dois avoir |je dois |il faut que je |faut que je |il faut |faut |avoir )+", "",
                   t, flags=re.I).strip()
        t = re.sub(r"\s+(pour|avant|d'ici|le|au plus tard)\s*$", "", t, flags=re.I).strip()
    t = t.strip(" .,:;?!")
    if not t: return "Qu'est-ce que je dois te rappeler ?"
    t = t[0].upper() + t[1:]
    line = f"- [ ] 📅 {d.isoformat()} {t}"
    exists = os.path.exists(p)
    with open(p, "a", encoding="utf-8") as f:
        if not exists: f.write(HEADER)
        f.write(line + "\n")
    return f"C'est noté pour {date_fr(d, today)} : {t}."

def due(cfg, today=None):
    """Rappels non faits pour aujourd'hui ou en retard."""
    today = today or datetime.date.today()
    return [r for r in _read(cfg) if not r["fait"] and r["date"] <= today]

def upcoming(cfg, days=7, today=None):
    today = today or datetime.date.today()
    lim = today + datetime.timedelta(days)
    return sorted([r for r in _read(cfg) if not r["fait"] and r["date"] <= lim], key=lambda r: r["date"])

def list_text(cfg, today=None):
    today = today or datetime.date.today()
    rs = upcoming(cfg, 60, today)[:10]
    if not rs: return "Aucun rappel en cours."
    parts = []
    for r in rs:
        quand = "en retard depuis " + date_fr(r["date"], today) if r["date"] < today else date_fr(r["date"], today)
        parts.append(f"{quand} : {r['texte']}")
    return "Tes rappels : " + " ; ".join(parts) + "."

def briefing_text(cfg, today=None):
    today = today or datetime.date.today()
    rs = due(cfg, today)
    if not rs: return ""
    lignes = [f"- {r['texte']}" + (f" (prévu {date_fr(r['date'], today)}, en retard)" if r["date"] < today else "")
              for r in rs]
    return "Rappels à faire aujourd'hui :\n" + "\n".join(lignes)

def done(cfg, text, today=None):
    """« c'est fait X » / « supprime le rappel X » → retire la ligne la plus proche."""
    p = path(cfg)
    rs = [r for r in _read(cfg) if not r["fait"]]
    if not p or not rs: return "Je n'ai aucun rappel en cours."
    q = re.sub(r"(c'est fait|j'ai fait|supprime|enlève|enleve|retire|efface|le rappel|la tâche|la tache)", " ",
               text, flags=re.I)
    mots = {w for w in re.findall(r"\w{3,}", q.lower())}
    best = max(rs, key=lambda r: len(mots & set(re.findall(r"\w{3,}", r["texte"].lower()))))
    if not mots or not (mots & set(re.findall(r"\w{3,}", best["texte"].lower()))):
        return "Je ne sais pas quel rappel retirer. Dis-moi un mot du rappel."
    lines = open(p, encoding="utf-8").read().splitlines()
    lines = [l for l in lines if l != best["ligne"]]
    open(p, "w", encoding="utf-8").write("\n".join(lines) + "\n")
    return f"Bien joué. J'ai retiré : {best['texte']}."
