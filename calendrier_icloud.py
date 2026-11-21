"""
JARVIS — Ajouter des événements dans le Calendrier iPhone (iCloud, protocole CalDAV)
config.json :
    "icloud_user": "adresse@icloud.com"            (identifiant Apple)
    "icloud_app_password": "abcd-efgh-ijkl-mnop"  (mot de passe pour app, jamais le vrai mot de passe)
    "icloud_calendar": ""   (nom du calendrier ; vide = le premier trouvé)
"""
import os, re, json, uuid, datetime, xml.etree.ElementTree as ET
import requests

BASE = os.path.dirname(os.path.abspath(__file__))
CACHE = os.path.join(BASE, "brain", "icloud.json")
ROOT = "https://caldav.icloud.com/"
NS = {"d": "DAV:", "c": "urn:ietf:params:xml:ns:caldav", "a": "http://apple.com/ns/ical/"}

# --- CalDAV (iCloud)
def _auth(cfg):
    u, p = cfg.get("icloud_user", ""), cfg.get("icloud_app_password", "")
    if not u or not p: return None
    return (u, p.replace(" ", ""))

def _propfind(url, auth, body, depth="0"):
    r = requests.request("PROPFIND", url, auth=auth, data=body.encode("utf-8"), timeout=20,
                         headers={"Depth": depth, "Content-Type": "application/xml; charset=utf-8"})
    if r.status_code == 401:
        raise PermissionError("iCloud refuse la connexion : vérifie icloud_user et icloud_app_password.")
    if r.status_code >= 400:
        raise RuntimeError(f"iCloud a répondu {r.status_code}")
    return ET.fromstring(r.content), r.url

def _href(tree, path):
    el = tree.find(path, NS)
    return el.text.strip() if el is not None and el.text else None

def _join(base, href):
    if href.startswith("http"): return href
    m = re.match(r"(https?://[^/]+)", base)
    return m.group(1) + href

def discover(cfg, log=print):
    """Trouve l'adresse du calendrier iCloud (mise en cache dans brain/icloud.json)."""
    auth = _auth(cfg)
    if not auth: return None
    want = cfg.get("icloud_calendar", "").strip().lower()
    try:
        with open(CACHE, encoding="utf-8") as f: c = json.load(f)
        if c.get("user") == auth[0] and c.get("want") == want and c.get("url"): return c
    except Exception:
        pass
    t, url = _propfind(ROOT, auth, '<d:propfind xmlns:d="DAV:"><d:prop><d:current-user-principal/></d:prop></d:propfind>')
    principal = _href(t, ".//d:current-user-principal/d:href")
    if not principal: raise RuntimeError("principal iCloud introuvable")
    principal = _join(url, principal)
    t, url = _propfind(principal, auth,
        '<d:propfind xmlns:d="DAV:" xmlns:c="urn:ietf:params:xml:ns:caldav">'
        '<d:prop><c:calendar-home-set/></d:prop></d:propfind>')
    home = _href(t, ".//c:calendar-home-set/d:href")
    if not home: raise RuntimeError("calendriers iCloud introuvables")
    home = _join(url, home)
    t, url = _propfind(home, auth,
        '<d:propfind xmlns:d="DAV:" xmlns:c="urn:ietf:params:xml:ns:caldav">'
        '<d:prop><d:displayname/><d:resourcetype/><c:supported-calendar-component-set/></d:prop></d:propfind>', "1")
    cals = []
    for resp in t.findall("d:response", NS):
        href = _href(resp, "d:href")
        if resp.find(".//d:resourcetype/c:calendar", NS) is None: continue
        comps = [c.get("name") for c in resp.findall(".//c:supported-calendar-component-set/c:comp", NS)]
        if comps and "VEVENT" not in comps: continue
        name = _href(resp, ".//d:displayname") or href.rstrip("/").split("/")[-1]
        cals.append({"nom": name, "url": _join(url, href)})
    if not cals: raise RuntimeError("aucun calendrier iCloud qui accepte des événements")
    chosen = next((c for c in cals if c["nom"].lower() == want), None) if want else None
    if not chosen:
        prefs = ("calendrier", "calendar", "domicile", "home", "perso", "personnel")
        chosen = next((c for c in cals if c["nom"].lower() in prefs), cals[0])
    res = {"user": auth[0], "want": want, "url": chosen["url"], "nom": chosen["nom"],
           "tous": [c["nom"] for c in cals]}
    try:
        os.makedirs(os.path.dirname(CACHE), exist_ok=True)
        with open(CACHE, "w", encoding="utf-8") as f: json.dump(res, f, ensure_ascii=False, indent=1)
    except Exception:
        pass
    log(f"[ICLOUD] Calendrier « {res['nom']} » (dispo : {', '.join(res['tous'])})", "green")
    return res

def _esc(s):
    return s.replace("\\", "\\\\").replace(";", "\\;").replace(",", "\\,").replace("\n", "\\n")

def build_ics(titre, debut, fin=None, journee=False, lieu=""):
    uid = str(uuid.uuid4()).upper()
    now = datetime.datetime.now(datetime.timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    lines = ["BEGIN:VCALENDAR", "VERSION:2.0", "PRODID:-//JARVIS//FR", "CALSCALE:GREGORIAN",
             "BEGIN:VEVENT", f"UID:{uid}", f"DTSTAMP:{now}", f"SUMMARY:{_esc(titre)}"]
    if journee:
        d = debut if isinstance(debut, datetime.date) and not isinstance(debut, datetime.datetime) else debut.date()
        lines += [f"DTSTART;VALUE=DATE:{d:%Y%m%d}", f"DTEND;VALUE=DATE:{d + datetime.timedelta(1):%Y%m%d}"]
    else:
        to_utc = lambda x: x.astimezone().astimezone(datetime.timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        lines += [f"DTSTART:{to_utc(debut)}", f"DTEND:{to_utc(fin or debut + datetime.timedelta(hours=1))}"]
    if lieu: lines.append(f"LOCATION:{_esc(lieu)}")
    lines += ["BEGIN:VALARM", "ACTION:DISPLAY", "DESCRIPTION:Rappel", "TRIGGER:-PT30M", "END:VALARM"] if not journee else []
    lines += ["END:VEVENT", "END:VCALENDAR"]
    return uid, "\r\n".join(lines) + "\r\n"

def add_event(cfg, titre, debut, fin=None, journee=False, lieu="", log=print):
    auth = _auth(cfg)
    if not auth:
        return False, ("Il me manque l'accès à iCloud : remplis icloud_user et icloud_app_password "
                       "dans config.json.")
    try:
        cal = discover(cfg, log)
        uid, ics = build_ics(titre, debut, fin, journee, lieu)
        url = cal["url"].rstrip("/") + f"/{uid}.ics"
        r = requests.put(url, auth=auth, data=ics.encode("utf-8"), timeout=20,
                         headers={"Content-Type": "text/calendar; charset=utf-8", "If-None-Match": "*"})
        if r.status_code in (200, 201, 204):
            log(f"[ICLOUD] Ajouté : {titre} ({debut})", "green")
            return True, cal["nom"]
        if r.status_code in (404, 410):  # calendrier supprimé → on oublie le cache
            try: os.remove(CACHE)
            except Exception: pass
        return False, f"iCloud a refusé l'ajout (erreur {r.status_code})."
    except Exception as e:
        log(f"[ICLOUD] {e}", "red")
        return False, str(e)[:120]

# --- Comprendre la phrase : « ajoute à mon agenda révision maths mercredi à 14h pendant 2 heures »
TRIGGER = re.compile(
    r"(ajoute|rajoute|mets|met|note|inscris|programme|crée|cree|planifie)(-moi|-le| moi)?\b.{0,20}?"
    r"\b(à|a|dans|sur|au) (mon |ma |le |l')?(agenda|calendrier|planning)\b"
    r"|(crée|cree|ajoute|rajoute|programme|planifie)(-moi| moi)? (un |une )?(événement|evenement|rendez-vous|rdv|réunion|reunion)\b",
    re.I)

_NOMBRES = {"une": 1, "un": 1, "deux": 2, "trois": 3, "quatre": 4, "cinq": 5, "six": 6,
            "demi": 0.5, "une demi": 0.5}

def parse_event(text, parse_date, today=None):
    """→ dict(titre, debut, fin, journee) ; parse_date = rappels.parse_date"""
    today = today or datetime.date.today()
    t = TRIGGER.sub(" ", text)
    d, found = parse_date(t, today)
    if found: t = re.sub(re.escape(found), " ", t, flags=re.I)
    d = d or today
    # heure : "à 14h", "14h30", "à 9 heures", "à midi", "8h du matin", "à 3h de l'après-midi"
    heure = None
    m = re.search(r"\b(?:à |a |vers )?(\d{1,2})\s?(?:heures?|h)\s?(\d{2})?(?:\s?(du matin|de l'après-midi|de l'apres-midi|du soir))?\b", t, re.I)
    if m:
        h, mi = int(m.group(1)), int(m.group(2) or 0)
        if m.group(3) and m.group(3).lower() != "du matin" and h < 12: h += 12
        heure = (h, mi); t = t.replace(m.group(0), " ")
    elif re.search(r"\bà midi\b", t, re.I):
        heure = (12, 0); t = re.sub(r"\bà midi\b", " ", t, flags=re.I)
    # durée : "pendant 2 heures", "pendant 30 minutes", "pendant 1h30", "pendant une heure et demie"
    duree = datetime.timedelta(hours=1)
    m = re.search(r"\b(?:pendant|durant|pour)\s+(\d+|une|un|deux|trois|quatre|cinq|six)\s?(heures?|minutes?|min|h)\s?(\d{2})?(\s?et demie?)?", t, re.I)
    if m:
        n = int(m.group(1)) if m.group(1).isdigit() else _NOMBRES.get(m.group(1).lower(), 1)
        if m.group(2).lower().startswith("h"):
            duree = datetime.timedelta(hours=n, minutes=int(m.group(3) or 0) + (30 if m.group(4) else 0))
        else:
            duree = datetime.timedelta(minutes=n)
        t = t.replace(m.group(0), " ")
    # titre
    t = re.sub(r"\s+", " ", t).strip(" ,.:;?!")
    for _ in range(3):
        t = re.sub(r"^(un |une |le |la |l'|de |d'|pour |que |qu'|:)+", "", t, flags=re.I).strip()
        t = re.sub(r"\s+(le|à|a|de|pour|ce|cet|cette)$", "", t, flags=re.I).strip()
    titre = (t[0].upper() + t[1:]) if t else "Événement"
    if heure:
        debut = datetime.datetime.combine(d, datetime.time(*heure))
        return {"titre": titre, "debut": debut, "fin": debut + duree, "journee": False}
    return {"titre": titre, "debut": d, "fin": None, "journee": True}

# --- Lire / modifier / supprimer des événements iCloud
def _unfold(text):
    return re.sub(r"\r?\n[ \t]", "", text).splitlines()

def _dt(value, params):
    v = value.strip()
    if params.get("VALUE") == "DATE" or re.fullmatch(r"\d{8}", v):
        return datetime.datetime.strptime(v[:8], "%Y%m%d").date(), True
    if v.endswith("Z"):
        d = datetime.datetime.strptime(v[:-1], "%Y%m%dT%H%M%S").replace(tzinfo=datetime.timezone.utc)
        return d.astimezone().replace(tzinfo=None), False
    d = datetime.datetime.strptime(v[:15], "%Y%m%dT%H%M%S")
    try:
        from zoneinfo import ZoneInfo
        if params.get("TZID"): d = d.replace(tzinfo=ZoneInfo(params["TZID"])).astimezone().replace(tzinfo=None)
    except Exception:
        pass
    return d, False

def _parse_event_ics(text):
    ev, inside = {}, False
    for line in _unfold(text):
        if line == "BEGIN:VEVENT": inside = True; continue
        if line == "END:VEVENT": break
        if not inside or ":" not in line: continue
        head, _, value = line.partition(":")
        parts = head.split(";"); name = parts[0].upper()
        params = dict(p.split("=", 1) for p in parts[1:] if "=" in p)
        if name == "UID": ev["uid"] = value.strip()
        elif name == "SUMMARY": ev["titre"] = value.replace("\\,", ",").replace(chr(92)+";", ";").replace("\\n", " ").strip()
        elif name == "LOCATION": ev["lieu"] = value.replace("\\,", ",").strip()
        elif name == "DTSTART":
            try: ev["debut"], ev["journee"] = _dt(value, params)
            except Exception: pass
        elif name == "DTEND":
            try: ev["fin"], _ = _dt(value, params)
            except Exception: pass
        elif name == "RRULE": ev["repete"] = True
    return ev if "debut" in ev else None

def find_events(cfg, start, end, log=print):
    """Événements du calendrier iCloud entre deux dates."""
    auth = _auth(cfg)
    if not auth: return None
    cal = discover(cfg, log)
    s = datetime.datetime.combine(start, datetime.time.min).astimezone(datetime.timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    e = datetime.datetime.combine(end, datetime.time.min).astimezone(datetime.timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    body = ('<c:calendar-query xmlns:d="DAV:" xmlns:c="urn:ietf:params:xml:ns:caldav">'
            '<d:prop><d:getetag/><c:calendar-data/></d:prop>'
            '<c:filter><c:comp-filter name="VCALENDAR"><c:comp-filter name="VEVENT">'
            f'<c:time-range start="{s}" end="{e}"/></c:comp-filter></c:comp-filter></c:filter></c:calendar-query>')
    r = requests.request("REPORT", cal["url"], auth=auth, data=body.encode("utf-8"), timeout=20,
                         headers={"Depth": "1", "Content-Type": "application/xml; charset=utf-8"})
    if r.status_code >= 400: raise RuntimeError(f"iCloud a répondu {r.status_code}")
    tree = ET.fromstring(r.content)
    out = []
    for resp in tree.findall("d:response", NS):
        href = _href(resp, "d:href"); data = _href(resp, ".//c:calendar-data")
        if not href or not data: continue
        ev = _parse_event_ics(data)
        if not ev: continue
        ev["href"] = _join(cal["url"], href); ev["etag"] = _href(resp, ".//d:getetag")
        out.append(ev)
    def key(x):
        d = x["debut"]
        return d if isinstance(d, datetime.datetime) else datetime.datetime.combine(d, datetime.time.min)
    return sorted(out, key=key)

def update_event(cfg, ev, debut, fin=None, journee=False, titre=None, log=print):
    auth = _auth(cfg)
    _, ics = build_ics(titre or ev.get("titre", "Événement"), debut, fin, journee, ev.get("lieu", ""))
    ics = re.sub(r"UID:[^\r\n]+", "UID:" + ev["uid"], ics, count=1)   # on garde le même UID
    r = requests.put(ev["href"], auth=auth, data=ics.encode("utf-8"), timeout=20,
                     headers={"Content-Type": "text/calendar; charset=utf-8"})
    if r.status_code in (200, 201, 204):
        log(f"[ICLOUD] Modifié : {titre or ev.get('titre')} → {debut}", "green"); return True
    log(f"[ICLOUD] Modification refusée ({r.status_code})", "red"); return False

def delete_event(cfg, ev, log=print):
    r = requests.delete(ev["href"], auth=_auth(cfg), timeout=20)
    if r.status_code in (200, 204, 404):
        log(f"[ICLOUD] Supprimé : {ev.get('titre')}", "green"); return True
    log(f"[ICLOUD] Suppression refusée ({r.status_code})", "red"); return False

EDIT = re.compile(r"\b(chang|modifi|déplac|deplac|décal|decal|repouss|avanc|boug|report|remet|remplac)\w*"
                  r"|\b(mets|mettes|mettre)[- ](le|la|les)\b|\bplutôt\b", re.I)
DELETE = re.compile(r"\b(supprim|annul|enlèv|enlev|retir|effac)\w*", re.I)
CAL_WORDS = re.compile(r"\b(agenda|calendrier|événement|evenement|rendez-vous|rdv|réunion|reunion|date|heure|horaire|"
                       r"créneau|creneau|séance|seance)\b", re.I)
