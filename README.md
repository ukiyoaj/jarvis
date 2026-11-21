# JARVIS — assistant IA personnel

Assistant vocal en Python qui tourne sur mon PC Windows (ASUS TUF Gaming A15), avec une interface web façon Iron Man, et que je peux aussi utiliser depuis mon iPhone.

> Projet perso d'Amine Jebali — étudiant en BUT Informatique (IUT de Bordeaux).

## Fonctionnalités

| Domaine | Ce que fait JARVIS |
|---|---|
| 🎙️ Voix | Mot-clé « Jarvis » ou `Ctrl+Shift+J`, reconnaissance vocale Google, réponse avec une voix ElevenLabs |
| 🧠 IA | Cascade d'IA : Groq (`openai/gpt-oss-120b`) → Mistral → Gemini → Ollama en local |
| ☀️ Briefing du matin | Cours du jour, rappels, prochains DS, mails non lus, tâches des projets Obsidian, news science/tech et foot |
| 📅 Agenda | Lit l'emploi du temps HyperPlanning (.ics) ; ajoute, déplace et supprime des événements dans le Calendrier iPhone (iCloud / CalDAV) |
| 📚 DS | « c'est quoi mon prochain DS » → matière en clair (pas le code R1.07), date, heure, salle |
| 📝 Rappels | « rajoute un rappel lundi de… » → écrit dans `Rappels.md` du coffre Obsidian |
| 📧 Mails | Lecture des mails IMAP (Zimbra de la fac, Gmail…) sans les marquer comme lus |
| 📓 Obsidian | Lit les projets du coffre pour connaître mes centres d'intérêt ; écrit une note de veille chaque matin |
| 📱 iPhone | Serveur privé via Tailscale + code secret : Raccourcis iOS « Jarvis » (parler) et « Briefing du matin » |
| ✋ Gestes | Contrôle par la webcam (MediaPipe GestureRecognizer) : ✊ 🖐️ 👍 👎 ✌️ |
| 🗺️ Carte | Carte « holographique » Leaflet (fond Esri, sans clé API) |
| 🚀 Démarrage | Lancement automatique avec Windows |

## Architecture

```
jarvis.py              cœur : config, voix, commandes, serveur web (7474) et serveur iPhone (7475)
voice_engine.py        synthèse vocale (ElevenLabs, sinon pyttsx3)
news_matin.py          briefing du matin + lecture du coffre Obsidian + Google News RSS
briefing_extras.py     agenda .ics, DS, mails IMAP, tâches Obsidian, état du serveur
rappels.py             rappels dans Rappels.md (Obsidian)
calendrier_icloud.py   ajout / modification / suppression d'événements iCloud (CalDAV)
self_mod.py            auto-amélioration (génère du code, avec sauvegarde)
ui/index.html          interface web
ui/map.html            carte holographique
LANCER_JARVIS.bat      lancement (attend le réseau)
ACTIVER_DEMARRAGE_AUTO.bat / DESACTIVER_DEMARRAGE_AUTO.bat
```

## Installation

1. Installer **Python 3.11** (cocher « Add to PATH »).
2. Cloner le dépôt puis copier la config :
   ```bat
   copy config.example.json config.json
   ```
3. Remplir `config.json` (clés API, liens d'agenda, boîtes mail…). **Ce fichier n'est jamais envoyé sur GitHub** (voir `.gitignore`).
4. Lancer `LANCER_JARVIS.bat`. Les bibliothèques Python manquantes s'installent toutes seules au premier lancement.
5. (Optionnel) `ACTIVER_DEMARRAGE_AUTO.bat` pour un lancement automatique avec Windows.

### Accès depuis l'iPhone
- Installer **Tailscale** sur le PC et l'iPhone (même compte).
- Le code secret `remote_token` est créé tout seul dans `config.json` au premier lancement.
- Raccourci iOS : `http://<IP-Tailscale-du-PC>:7475/ask?token=<code>&q=<question>` et `/briefing.txt?token=<code>`.

## Exemples de commandes

- « news du jour » · « mes passions »
- « j'ai quoi comme cours lundi » · « j'ai quoi pour le 30 novembre » · « mes cours la semaine prochaine »
- « c'est quoi mon prochain DS » · « mes prochains DS »
- « rajoute un rappel mardi de rendre le TP » · « mes rappels » · « c'est fait rendre le TP »
- « ajoute à mon agenda révision maths mercredi à 14h pendant 2 heures » · « déplace la révision à jeudi 10h » · « supprime le dentiste de mon agenda »
- « mon dernier mail » · « mes mails IUT »
- « active les gestes » / « désactive les gestes »

## Sécurité

- Tous les secrets (clés API, mots de passe d'application, code iPhone) sont dans `config.json`, ignoré par Git.
- Le serveur iPhone (port 7475) n'accepte que le réseau Tailscale et le code secret.
- iCloud et Gmail utilisent des **mots de passe d'application**, jamais le vrai mot de passe.

## Prochaines étapes

- Réponses Instagram via l'API officielle Meta
- Faire tourner JARVIS 24 h/24 sur mon serveur maison (Acer Nitro 5)
- Démarrage plus rapide (chargement des modules lourds à la demande)
