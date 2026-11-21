"""
JARVIS — Infos perso du briefing du matin
- Agenda du jour (liens .ics : iCloud, Google Agenda, emploi du temps IUT...)
- Tâches à faire dans les projets Obsidian (cases « - [ ] »)
- Mails non lus (IMAP, sans les marquer comme lus)
- État du serveur maison (optionnel)
"""
import os, re, datetime, requests

# --- AGENDA (.ics)
def _unfold(text):
    return re.sub(r"\r?\n[ \t]", "", text).splitlines()

def _tz(name):
    try:
        from zoneinfo import ZoneInfo
        return ZoneInfo(name)
    except Exception:
        return None

def _parse_dt(value, params):
    """Retourne (datetime local naïf, journée_entière)."""
    v = value.strip()
    if params.get("VALUE") == "DATE" or re.fullmatch(r"\d{8}", v):
        return datetime.datetime.strptime(v[:8], "%Y%m%d"), True
    fmt = "%Y%m%dT%H%M%S"
    if v.endswith("Z"):
        d = datetime.datetime.strptime(v[:-1], fmt).replace(tzinfo=datetime.timezone.utc)
        return d.astimezone().replace(tzinfo=None), False
    d = datetime.datetime.strptime(v[:15], fmt)
    tz = _tz(params.get("TZID", "")) if params.get("TZID") else None
    if tz:
        d = d.replace(tzinfo=tz).astimezone().replace(tzinfo=None)
    return d, False

def _split(line):
    """'DTSTART;TZID=Europe/Paris:20261121T090000' → ('DTSTART', {'TZID':...}, '2026...')"""
    head, _, value = line.partition(":")
    parts = head.split(";")
    params = {}
    for p in parts[1:]:
        k, _, v = p.partition("=")
        params[k.upper()] = v.strip('"')
    return parts[0].upper(), params, value

def _ics_text(v):
    return v.replace("\\n", " ").replace("\\,", ",").replace(chr(92)+";", ";").strip()

def parse_ics(text, day):
    """Événements d'un jour donné (date). Gère les événements répétés (RRULE)."""
    events, cur = [], None
    for line in _unfold(text):
        if line == "BEGIN:VEVENT":
            cur = {"exdates": set()}
        elif line == "END:VEVENT" and cur is not None:
            events.append(cur); cur = None
        elif cur is not None and ":" in line:
            name, params, value = _split(line)
            if name == "SUMMARY": cur["titre"] = _ics_text(value)
            elif name == "LOCATION": cur["lieu"] = _ics_text(value)
            elif name == "DTSTART":
                try: cur["debut"], cur["journee"] = _parse_dt(value, params)
                except Exception: pass
            elif name == "DTEND":
                try: cur["fin"], _ = _parse_dt(value, params)
                except Exception: pass
            elif name == "RRULE": cur["rrule"] = value
            elif name == "EXDATE":
                for x in value.split(","):
                    try: cur["exdates"].add(_parse_dt(x, params)[0])
                    except Exception: pass
            elif name == "RECURRENCE-ID": cur["override"] = True
            elif name == "STATUS" and value.strip().upper() == "CANCELLED": cur["annule"] = True

    start = datetime.datetime.combine(day, datetime.time.min)
    end = start + datetime.timedelta(days=1)
    out = []
    for e in events:
        if "debut" not in e or e.get("annule"): continue
        duree = (e["fin"] - e["debut"]) if e.get("fin") else datetime.timedelta(hours=1)
        occurrences = []
        if e.get("rrule"):
            try:
                from dateutil.rrule import rrulestr
                rule = rrulestr(e["rrule"], dtstart=e["debut"], ignoretz=True)
                occurrences = [d for d in rule.between(start - duree, end, inc=True)
                               if d not in e["exdates"]]
            except Exception:
                occurrences = [e["debut"]]
        else:
            occurrences = [e["debut"]]
        for d in occurrences:
            if d < end and d + duree > start:
                out.append({"titre": e.get("titre", "(sans titre)"), "lieu": e.get("lieu", ""),
                            "debut": d, "journee": e.get("journee", False)})
    # dédoublonnage (exceptions de séries répétées)
    seen, res = set(), []
    for ev in sorted(out, key=lambda x: (not x["journee"], x["debut"])):
        k = (ev["titre"], ev["debut"])
        if k not in seen: seen.add(k); res.append(ev)
    return res

def agenda_today(cfg, log=print, day=None):
    day = day or datetime.date.today()
    urls = cfg.get("calendars", [])
    if not urls: return None
    events = []
    for c in urls:
        url = c["url"] if isinstance(c, dict) else c
        nom = c.get("nom", "") if isinstance(c, dict) else ""
        url = url.replace("webcal://", "https://")
        try:
            r = requests.get(url, timeout=15)
            r.raise_for_status()
            for ev in parse_ics(r.text, day):
                ev["agenda"] = nom; events.append(ev)
        except Exception as e:
            log(f"[AGENDA] {nom or url[:40]} : {str(e)[:60]}", "yellow")
    events.sort(key=lambda x: (not x["journee"], x["debut"]))
    return events

def agenda_range(cfg, start, ndays, log=print):
    """{date: [événements]} pour ndays jours à partir de start (télécharge chaque agenda une seule fois)."""
    urls = cfg.get("calendars", [])
    if not urls: return None
    texts = []
    for c in urls:
        url = (c["url"] if isinstance(c, dict) else c).replace("webcal://", "https://")
        try:
            r = requests.get(url, timeout=15); r.raise_for_status(); texts.append(r.text)
        except Exception as e:
            log(f"[AGENDA] {str(e)[:60]}", "yellow")
    out = {}
    for i in range(ndays):
        d = start + datetime.timedelta(days=i)
        evs = []
        for t in texts: evs += parse_ics(t, d)
        evs.sort(key=lambda x: (not x["journee"], x["debut"]))
        out[d] = evs
    return out

_JOURS = ["lundi","mardi","mercredi","jeudi","vendredi","samedi","dimanche"]
_MOIS = ["janvier","février","mars","avril","mai","juin","juillet","août","septembre","octobre","novembre","décembre"]

def _clean_title(t):
    # "R1.01 Initiation au dev. - Cours_1h" -> "R1.01 Initiation au dev. (Cours)"
    t = re.sub(r"\s*-\s*(Cours|TD|TP|CM|DS|Examen|Projet)[_ ]?\d*h?\d*\s*$", lambda m: f" ({m.group(1)})", t)
    return t.strip()

def agenda_range_text(days, cfg=None):
    if days is None: return "Aucun agenda n'est configuré."
    parts = []
    for d, evs in days.items():
        nom = f"{_JOURS[d.weekday()].capitalize()} {d.day} {_MOIS[d.month-1]}"
        if not evs:
            continue
        items = []
        for e in evs:
            h = "toute la journée" if e["journee"] else e["debut"].strftime("%Hh%M")
            lieu = (f", {e['lieu']}" if e["lieu"].lower().startswith(("salle","amphi")) else f", salle {e['lieu']}") if e["lieu"] else ""
            items.append(f"{h} {spoken(e, cfg)}{lieu}")
        parts.append(f"{nom} : " + " ; ".join(items) + ".")
    return "\n".join(parts) if parts else "Rien de prévu sur cette période."

# Noms des matières (BUT Informatique S1). Modifiables dans config.json → "matieres".
MATIERES = {
    "R1.01": "Initiation au développement", "R1.02": "Développement d'interfaces web",
    "R1.03": "Introduction à l'architecture des ordinateurs", "R1.04": "Introduction aux systèmes d'exploitation",
    "R1.05": "Introduction aux bases de données", "R1.06": "Mathématiques discrètes",
    "R1.07": "Outils mathématiques fondamentaux", "R1.08": "Gestion de projet et des organisations",
    "R1.09": "Économie durable et numérique", "R1.10": "Anglais", "R1.11": "Bases de la communication",
    "R1.12": "Projet professionnel et personnel",
    "S1.01": "SAÉ Odomo", "S1.02": "SAÉ Towa", "S1.03": "SAÉ Installation d'un poste",
    "S1.04": "SAÉ Création d'une base de données", "S1.05": "SAÉ Site web", "S1.06": "SAÉ Environnement économique",
}
_CODE = re.compile(r"\b([RSU]\d\.\d{2}|AOP\d\.\d)\b")
_TYPE = re.compile(r"^(Cours|TD|TP|DS|CM|Examen|Projet|SAE|SAÉ)[_ ]?(\d+h\d*)?$", re.I)

def describe(summary, cfg=None):
    """'Devoir Surveillé S1 - DS_1h - M. X - R1.07' → {'nom': 'Outils mathématiques fondamentaux',
       'type': 'DS', 'duree': '1h', 'ds': True}"""
    mat = dict(MATIERES); mat.update((cfg or {}).get("matieres", {}))
    parts = [p.strip() for p in summary.split(" - ")]
    typ, duree = "", ""
    for p in parts[1:]:
        m = _TYPE.match(p)
        if m: typ, duree = m.group(1).upper() if m.group(1).lower() != "cours" else "Cours", (m.group(2) or ""); break
    ds = typ == "DS" or "devoir surveill" in summary.lower()
    codes = _CODE.findall(summary)
    code = codes[0] if codes else ""
    if ds:
        # pour un DS, la matière est à la fin : "... - R1.07" (ou "rattrapage DS R1.06 ...")
        code = codes[-1] if codes else ""
        nom = mat.get(code) or (code or "matière inconnue")
        if "rattrapage" in summary.lower(): nom = "rattrapage de " + nom
        return {"nom": nom, "type": "DS", "duree": duree, "ds": True, "code": code}
    titre = parts[0]
    if code and code in mat: nom = mat[code]
    else: nom = re.sub(r"^" + re.escape(code) + r"\s*", "", titre).strip() if code else titre
    nom = nom.strip("_ ").strip() or titre
    return {"nom": nom, "type": typ, "duree": duree, "ds": False, "code": code}

def de(nom):
    """« de » ou « d' » devant un nom (DS d'Anglais, DS de Mathématiques)."""
    return ("d'" if nom[:1].lower() in "aeiouyéèêàâîôûh" else "de ") + nom

def humanize(text, cfg=None):
    """Remplace les codes (R1.07…) par le nom de la matière dans un texte libre."""
    mat = dict(MATIERES); mat.update((cfg or {}).get("matieres", {}))
    return _CODE.sub(lambda m: mat.get(m.group(1), m.group(1)), text)

def spoken(ev, cfg=None):
    d = describe(ev["titre"], cfg)
    if d["ds"]:
        nom = d["nom"]
        if nom.startswith("rattrapage de "):
            return "rattrapage du DS " + de(nom[len("rattrapage de "):]) + (f" ({d['duree']})" if d["duree"] else "")
        return "DS " + de(nom) + (f" ({d['duree']})" if d["duree"] else "")
    return d["nom"] + (f" ({d['type']})" if d["type"] else "")

def next_ds(cfg, n=1, days=150, log=print, filtre=None, today=None):
    """Prochains DS (à partir de maintenant)."""
    today = today or datetime.date.today()
    jours = agenda_range(cfg, today, days, log)
    if jours is None: return None
    now = datetime.datetime.now()
    res = []
    for d, evs in jours.items():
        for e in evs:
            info = describe(e["titre"], cfg)
            if not info["ds"] or e["debut"] < now: continue
            if filtre and filtre not in (info["nom"] + " " + info["code"]).lower(): continue
            res.append({**e, **info})
            if len(res) >= n: return res
    return res

def next_ds_text(res, today=None):
    if res is None: return "Aucun agenda n'est configuré."
    if not res: return "Aucun DS de prévu dans les prochains mois. Profite."
    today = today or datetime.date.today()
    out = []
    for i, e in enumerate(res):
        d = e["debut"].date()
        quand = ("aujourd'hui" if d == today else "demain" if d == today + datetime.timedelta(1)
                 else f"{_JOURS[d.weekday()]} {d.day} {_MOIS[d.month-1]}")
        dans = (d - today).days
        rel = f", dans {dans} jours" if dans > 1 else ""
        lieu = f", {e['lieu']}" if e["lieu"] else ""
        dur = f", {e['duree'].replace('h', ' heure' if e['duree'].startswith('1h') else ' heures')}" if e["duree"] else ""
        debut = "Ton prochain DS" if i == 0 else "Ensuite"
        out.append(f"{debut} : {e['nom']}, {quand} à {e['debut'].strftime('%Hh%M')}{rel}{dur}{lieu}.")
    return " ".join(out)

def agenda_text(events, cfg=None):
    if events is None: return ""
    if not events: return "Agenda : rien de prévu aujourd'hui."
    lignes = []
    for e in events:
        h = "toute la journée" if e["journee"] else e["debut"].strftime("%Hh%M")
        lieu = f" ({e['lieu']})" if e["lieu"] else ""
        lignes.append(f"- {h} : {spoken(e, cfg)}{lieu}")
    return "Agenda du jour :\n" + "\n".join(lignes)

# --- TÂCHES DES PROJETS (Obsidian)
_SKIP_PROJECTS = {"Poésie"}
def project_tasks(vault, max_per_project=2):
    """Premières cases non cochées de chaque projet (section 'Prochaines étapes' en priorité)."""
    pdir = os.path.join(vault or "", "Projets")
    if not os.path.isdir(pdir): return []
    res = []
    for name in sorted(os.listdir(pdir)):
        if name in _SKIP_PROJECTS: continue
        main = os.path.join(pdir, name, name + ".md")
        if not os.path.isfile(main): continue
        try: txt = open(main, encoding="utf-8").read()
        except Exception: continue
        m = re.search(r"##\s*Prochaines étapes\s*\n(.*?)(?=\n##|\Z)", txt, re.S)
        zone = m.group(1) if m else txt
        todo = re.findall(r"^\s*-\s\[ \]\s+(.+)$", zone, re.M)[:max_per_project]
        for t in todo:
            res.append({"projet": name, "tache": t.strip()})
    return res

def tasks_text(tasks):
    if not tasks: return ""
    return "Tâches en attente dans ses projets :\n" + "\n".join(
        f"- [{t['projet']}] {t['tache']}" for t in tasks)

# --- MAILS (Gmail, lecture sans marquer comme lu)
def _dec(h):
    from email.header import decode_header, make_header
    try: return str(make_header(decode_header(h or "")))
    except Exception: return h or ""

def _accounts(cfg):
    """Liste des boîtes mail : cfg['mail_accounts'] + l'ancien réglage Gmail."""
    accs = list(cfg.get("mail_accounts", []))
    gm, pw = cfg.get("gmail_address", ""), cfg.get("gmail_app_password", "")
    if gm and pw and not any(a.get("user") == gm for a in accs):
        accs.insert(0, {"nom": "Gmail", "imap": "imap.gmail.com", "user": gm, "password": pw})
    return [a for a in accs if a.get("imap") and a.get("user") and a.get("password")]

def _unread_one(acc, n, log):
    import imaplib, email
    try:
        m = imaplib.IMAP4_SSL(acc["imap"], int(acc.get("port", 993)), timeout=15)
        pw = acc["password"].replace(" ", "") if "gmail" in acc["imap"] else acc["password"]
        m.login(acc["user"], pw)
        m.select("INBOX", readonly=True)
        _, data = m.search(None, "UNSEEN")
        ids = data[0].split()
        mails = []
        for i in reversed(ids[-n:]):
            _, d = m.fetch(i, "(BODY.PEEK[HEADER.FIELDS (FROM SUBJECT)])")
            msg = email.message_from_bytes(d[0][1])
            frm = _dec(msg.get("From"))
            frm = re.sub(r"\s*<.*?>", "", frm).strip('" ') or frm
            mails.append({"de": frm[:40], "sujet": _dec(msg.get("Subject"))[:80]})
        m.logout()
        return {"nom": acc.get("nom", acc["user"]), "total": len(ids), "mails": mails}
    except Exception as e:
        log(f"[MAILS] {acc.get('nom', acc['imap'])} : {str(e)[:80]}", "yellow")
        return {"nom": acc.get("nom", acc["user"]), "erreur": str(e)[:80]}

def _last_one(acc, n, log):
    import imaplib, email
    try:
        m = imaplib.IMAP4_SSL(acc["imap"], int(acc.get("port", 993)), timeout=15)
        pw = acc["password"].replace(" ", "") if "gmail" in acc["imap"] else acc["password"]
        m.login(acc["user"], pw)
        m.select("INBOX", readonly=True)
        _, data = m.search(None, "ALL")
        ids = data[0].split()
        _, u = m.search(None, "UNSEEN")
        unseen = set(u[0].split())
        mails = []
        for i in reversed(ids[-n:]):
            _, d = m.fetch(i, "(BODY.PEEK[HEADER.FIELDS (FROM SUBJECT DATE)])")
            msg = email.message_from_bytes(d[0][1])
            frm = re.sub(r"\s*<.*?>", "", _dec(msg.get("From"))).strip('" ')
            mails.append({"de": frm[:40], "sujet": _dec(msg.get("Subject"))[:90],
                          "non_lu": i in unseen})
        m.logout()
        return {"nom": acc.get("nom", acc["user"]), "non_lus": len(unseen), "mails": mails}
    except Exception as e:
        log(f"[MAILS] {acc.get('nom', acc['imap'])} : {str(e)[:80]}", "yellow")
        return {"nom": acc.get("nom", acc["user"]), "erreur": str(e)[:80]}

def last_mails(cfg, n=3, only=None, log=print):
    accs = _accounts(cfg)
    if only: accs = [a for a in accs if only.lower() in a.get("nom", "").lower()] or accs
    return [_last_one(a, n, log) for a in accs] if accs else None

def last_mails_text(info):
    if not info: return "Aucune boîte mail n'est configurée."
    parts = []
    for b in info:
        if "erreur" in b:
            parts.append(f"Boîte {b['nom']} : je n'arrive pas à me connecter, vérifiez le mot de passe dans config.json.")
            continue
        if not b["mails"]:
            parts.append(f"Boîte {b['nom']} : vide."); continue
        l = " ; ".join(f"{'nouveau, ' if m['non_lu'] else ''}de {m['de']} : {m['sujet']}" for m in b["mails"])
        parts.append(f"Boîte {b['nom']}, {b['non_lus']} non lu(s). Derniers mails : {l}.")
    return "\n".join(parts)

def unread_mails(cfg, n=5, log=print):
    """Mails non lus de toutes les boîtes (sans les marquer comme lus)."""
    accs = _accounts(cfg)
    if not accs: return None
    return [_unread_one(a, n, log) for a in accs]

def mails_text(info):
    if not info: return ""
    parts = []
    for b in info:
        if "erreur" in b:
            parts.append(f"Mails {b['nom']} : connexion impossible.")
        elif not b["total"]:
            parts.append(f"Mails {b['nom']} : aucun non lu.")
        else:
            l = "\n".join(f"- {m['de']} : {m['sujet']}" for m in b["mails"])
            parts.append(f"Mails {b['nom']} : {b['total']} non lu(s). Les plus récents :\n{l}")
    return "\n".join(parts)

# --- SERVEUR MAISON (pour plus tard)
def server_status(cfg):
    """cfg['server_checks'] = [{"nom": "Immich", "url": "http://100.x.x.x:2283"}, ...]"""
    checks = cfg.get("server_checks", [])
    if not checks: return None
    res = []
    for c in checks:
        try:
            r = requests.get(c["url"], timeout=5)
            ok = r.status_code < 500
        except Exception:
            ok = False
        res.append({"nom": c.get("nom", c["url"]), "ok": ok})
    return res

def server_text(res):
    if not res: return ""
    ko = [r["nom"] for r in res if not r["ok"]]
    if not ko: return f"Serveur maison : tout va bien ({len(res)} services en ligne)."
    return "Serveur maison : PROBLÈME, ne répond pas → " + ", ".join(ko)
