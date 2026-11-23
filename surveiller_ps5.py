#!/usr/bin/env python3
"""
Surveillance du stock PlayStation Direct (playstation.com/fr-fr).

Lit l'état du bouton d'achat de chaque page produit ("Ajouter au panier"
ou "Non disponible à l'achat") et prévient quand un article passe de
"indisponible" à "disponible".

Notifications possibles (toutes optionnelles, cumulables) :
  - terminal (toujours)
  - notification bureau (Windows / macOS / Linux)
  - push sur téléphone via ntfy.sh (gratuit, sans compte) : --ntfy MON-SUJET
  - e-mail via SMTP : variables d'environnement SMTP_* (voir README)

Aucune dépendance externe : Python 3.8+ suffit.

Exemples :
  python surveiller_ps5.py --once            # une vérification puis quitte
  python surveiller_ps5.py                   # boucle, toutes les 5 min
  python surveiller_ps5.py --intervalle 120 --ntfy ps5-alerte-x7k2q
  python surveiller_ps5.py --test-notif --ntfy ps5-alerte-x7k2q
"""

from __future__ import annotations

import argparse
import gzip
import html
import json
import os
import platform
import random
import re
import smtplib
import ssl
import subprocess
import sys
import time
import urllib.error
import urllib.request
import urllib.parse
from datetime import datetime
from email.message import EmailMessage
from pathlib import Path

ICI = Path(__file__).resolve().parent
FICHIER_URLS = ICI / "urls.txt"
FICHIER_ETAT = ICI / "etat_stock.json"

USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/130.0.0.0 Safari/537.36"
)

# L'état fiable est celui du BOUTON D'ACHAT ("activeCtaId" dans les données de la
# page), PAS le champ schema.org "availability" ni "stockLevelStatus" : ceux-ci
# peuvent indiquer "en stock" alors que la page affiche "Non disponible à l'achat".
CTA_DISPONIBLE = {"ADD_TO_CART", "PREORDER", "PRE_ORDER", "BUY_NOW", "PURCHASE"}
CTA_INDISPONIBLE = {"UNAVAILABLE", "OUT_OF_STOCK", "NOT_AVAILABLE", "SOLD_OUT", "COMING_SOON", "NOTIFY_ME"}

LIBELLES = {
    "ADD_TO_CART": "EN STOCK (Ajouter au panier)",
    "BUY_NOW": "EN STOCK (Acheter)",
    "PURCHASE": "EN STOCK (Acheter)",
    "PREORDER": "PRÉCOMMANDE OUVERTE",
    "PRE_ORDER": "PRÉCOMMANDE OUVERTE",
    "UNAVAILABLE": "non disponible à l'achat",
    "OUT_OF_STOCK": "rupture de stock",
    "NOT_AVAILABLE": "non disponible",
    "SOLD_OUT": "épuisé",
    "COMING_SOON": "bientôt disponible",
    "NOTIFY_ME": "non disponible",
    "AUCHAN_EN_STOCK": "EN STOCK chez Auchan (Ajouter au panier)",
    "AUCHAN_INDISPONIBLE": "indisponible chez Auchan (« Bientôt dispo »)",
}


# --------------------------------------------------------------------------- #
# Récupération et analyse d'une page
# --------------------------------------------------------------------------- #

def telecharger(url: str, timeout: int = 30) -> str:
    req = urllib.request.Request(
        url,
        headers={
            "User-Agent": USER_AGENT,
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "fr-FR,fr;q=0.9,en;q=0.5",
            "Accept-Encoding": "gzip",
            "Cache-Control": "no-cache",
            "Pragma": "no-cache",
        },
    )
    with urllib.request.urlopen(req, timeout=timeout) as rep:
        brut = rep.read()
        if rep.headers.get("Content-Encoding", "").lower() == "gzip":
            brut = gzip.decompress(brut)
        return brut.decode("utf-8", errors="replace")


def _produits_jsonld(page: str):
    """Renvoie les objets schema.org de type Product trouvés dans la page."""
    for bloc in re.findall(
        r'<script[^>]*type="application/ld\+json"[^>]*>(.*?)</script>', page, re.S | re.I
    ):
        try:
            data = json.loads(html.unescape(bloc.strip()))
        except ValueError:
            continue
        pile = data if isinstance(data, list) else [data]
        while pile:
            obj = pile.pop()
            if isinstance(obj, list):
                pile.extend(obj)
            elif isinstance(obj, dict):
                if obj.get("@type") == "Product":
                    yield obj
                if "@graph" in obj:
                    pile.append(obj["@graph"])


def analyser(page: str, url: str) -> dict:
    """Extrait nom, prix et disponibilité selon le site. Lève ValueError si rien de fiable."""
    hote = urllib.parse.urlsplit(url).hostname or ""
    if hote.endswith("auchan.fr"):
        return analyser_auchan(page, url)
    return analyser_playstation(page, url)


def analyser_auchan(page: str, url: str) -> dict:
    """Auchan.fr : données « productUpdateDetail » intégrées à la page.
    availability.status = true quand l'offre en ligne peut être ajoutée au panier."""
    m = re.search(r"window\.G\.productUpdateDetail\s*=\s*", page)
    if not m:
        raise ValueError("données produit Auchan introuvables (page bloquée ou structure modifiée ?)")
    try:
        donnees, _ = json.JSONDecoder().raw_decode(page, m.end())
    except ValueError:
        raise ValueError("données produit Auchan illisibles")
    produit = donnees.get("product") or {}
    statut = (produit.get("availability") or {}).get("status")
    if statut is None:
        raise ValueError("disponibilité Auchan absente de la page")

    nom = html.unescape(str(produit.get("name") or "?")).strip()
    vendeur = str((produit.get("seller") or {}).get("name") or "")
    if produit.get("marketplace") and vendeur and "auchan" not in vendeur.lower():
        nom += f" (Auchan, vendu par {vendeur})"   # vendeur tiers : vérifier le prix !
    else:
        nom += " (Auchan)"
    return {
        "nom": nom,
        "prix": (produit.get("price") or {}).get("displayed_tax"),
        "devise": "EUR",
        "dispo": "AUCHAN_EN_STOCK" if statut else "AUCHAN_INDISPONIBLE",
        "disponible": bool(statut),
    }


def analyser_playstation(page: str, url: str) -> dict:
    """PlayStation Direct : état du bouton d'achat (activeCtaId)."""
    produits = list(_produits_jsonld(page))
    if not produits:
        raise ValueError("aucune donnée produit (page bloquée ou structure modifiée ?)")

    # Si plusieurs produits, préférer celui dont l'URL correspond.
    def score(p):
        return 1 if str(p.get("url", "")).rstrip("/") == url.split("#")[0].rstrip("/") else 0

    produit = max(produits, key=score)
    offres = produit.get("offers") or {}
    if isinstance(offres, list):
        offres = offres[0] if offres else {}

    # État du bouton d'achat pour CE produit (cache Apollo intégré à la page).
    donnees = page.replace('\\"', '"')
    pid = produit.get("productID")
    if not pid:
        m = re.search(r'productRetrieve\(\{"productId":"([^"]+)"', donnees)
        pid = m.group(1) if m else None
    if not pid:
        raise ValueError("identifiant produit introuvable")
    m = re.search(r'"Product:%s":\{.{0,8000}?"activeCtaId":"([^"]*)"' % re.escape(pid), donnees, re.S)
    if not m or not m.group(1):
        raise ValueError("état du bouton d'achat introuvable (structure du site modifiée ?)")
    cta = m.group(1).split(":", 1)[0]

    if cta in CTA_DISPONIBLE:
        disponible = True
    elif cta in CTA_INDISPONIBLE:
        disponible = False
    else:
        # Type jamais vu : on préfère alerter (à vérifier) plutôt que rater un réassort.
        disponible = True
        LIBELLES.setdefault(cta, f"ÉTAT INCONNU « {cta} » — à vérifier")

    return {
        "nom": html.unescape(str(produit.get("name", "?"))).strip(),
        "prix": offres.get("price"),
        "devise": offres.get("priceCurrency", "EUR"),
        "dispo": cta,
        "disponible": disponible,
    }


def verifier(url: str, essais: int = 3) -> dict:
    derniere_erreur = None
    for tentative in range(1, essais + 1):
        try:
            return analyser(telecharger(url), url)
        except (urllib.error.URLError, TimeoutError, OSError, ValueError) as e:
            derniere_erreur = e
            if tentative < essais:
                time.sleep(3 * tentative + random.random() * 2)
    raise RuntimeError(str(derniere_erreur))


# --------------------------------------------------------------------------- #
# Notifications
# --------------------------------------------------------------------------- #

def notif_bureau(titre: str, message: str) -> None:
    systeme = platform.system()
    try:
        if systeme == "Darwin":
            script = 'display notification {} with title {} sound name "Glass"'.format(
                json.dumps(message), json.dumps(titre)
            )
            subprocess.run(["osascript", "-e", script], check=False, timeout=10)
        elif systeme == "Windows":
            ps = (
                "Add-Type -AssemblyName System.Windows.Forms;"
                "$n=New-Object System.Windows.Forms.NotifyIcon;"
                "$n.Icon=[System.Drawing.SystemIcons]::Information;$n.Visible=$true;"
                f"$n.ShowBalloonTip(15000,{json.dumps(titre)},{json.dumps(message)},'Info');"
                "Start-Sleep -s 16;$n.Dispose()"
            )
            subprocess.Popen(
                ["powershell", "-NoProfile", "-WindowStyle", "Hidden", "-Command", ps],
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            )
        else:
            subprocess.run(["notify-send", "-u", "critical", titre, message], check=False, timeout=10)
    except (OSError, subprocess.SubprocessError):
        pass  # pas d'environnement graphique : tant pis, le terminal suffit


def notif_ntfy(sujet: str, titre: str, message: str, lien: str | None, serveur: str,
               priorite: int = 5, tags: tuple = ("video_game", "rotating_light")) -> bool:
    """Publication au format JSON (titre et message en UTF-8 sans souci d'encodage).
    priorite : 1 (min) … 3 (normale) … 5 (urgente)."""
    corps = {"topic": sujet, "title": titre, "message": message,
             "priority": priorite, "tags": list(tags)}
    if lien:
        corps["click"] = lien
    req = urllib.request.Request(
        serveur.rstrip("/") + "/",
        data=json.dumps(corps, ensure_ascii=False).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        urllib.request.urlopen(req, timeout=20).read()
        return True
    except (urllib.error.URLError, OSError) as e:
        journal(f"  ! échec ntfy : {e}")
        return False


def notif_info(args, titre: str, message: str, tags: tuple = ("white_check_mark",)) -> None:
    """Notification d'information (démarrage, « tout va bien ») : ntfy seulement,
    priorité normale, pas de bip ni d'e-mail."""
    journal(f"ℹ️  {titre} — {message.splitlines()[0] if message else ''}")
    if args.ntfy:
        if notif_ntfy(args.ntfy, titre, message, URL_BOUTIQUE, args.ntfy_serveur, priorite=3, tags=tags):
            journal("     (notification envoyée sur le téléphone)")
    else:
        journal("     (pas de sujet ntfy configuré : rien envoyé au téléphone)")


def notif_email(titre: str, message: str) -> None:
    hote = os.environ.get("SMTP_HOST")
    dest = os.environ.get("SMTP_TO")
    if not (hote and dest):
        return
    utilisateur = os.environ.get("SMTP_USER", "")
    mail = EmailMessage()
    mail["Subject"] = titre
    mail["From"] = os.environ.get("SMTP_FROM", utilisateur or dest)
    mail["To"] = dest
    mail.set_content(message)
    port = int(os.environ.get("SMTP_PORT", "587"))
    try:
        ctx = ssl.create_default_context()
        if port == 465:
            serveur = smtplib.SMTP_SSL(hote, port, context=ctx, timeout=30)
        else:
            serveur = smtplib.SMTP(hote, port, timeout=30)
            serveur.starttls(context=ctx)
        with serveur:
            if utilisateur:
                serveur.login(utilisateur, os.environ.get("SMTP_PASSWORD", ""))
            serveur.send_message(mail)
    except (OSError, smtplib.SMTPException) as e:
        journal(f"  ! échec e-mail : {e}")


def alerter(args, titre: str, message: str, lien: str | None = None) -> None:
    print("\a", end="")  # bip terminal
    journal(f"🚨 {titre}\n{message}")
    if not args.sans_bureau:
        notif_bureau(titre, message)
    if args.ntfy:
        notif_ntfy(args.ntfy, titre, message, lien, args.ntfy_serveur)
    notif_email(titre, message)


# --------------------------------------------------------------------------- #
# Boucle principale
# --------------------------------------------------------------------------- #

def journal(texte: str) -> None:
    print(f"[{datetime.now():%Y-%m-%d %H:%M:%S}] {texte}", flush=True)


def charger_urls() -> list[str]:
    if not FICHIER_URLS.exists():
        sys.exit(f"Fichier introuvable : {FICHIER_URLS}")
    urls = []
    for ligne in FICHIER_URLS.read_text(encoding="utf-8").splitlines():
        ligne = ligne.strip()
        if ligne and not ligne.startswith("#"):
            urls.append(ligne.split("#")[0])
    return list(dict.fromkeys(urls))  # sans doublons, ordre conservé


def charger_etat() -> dict:
    try:
        return json.loads(FICHIER_ETAT.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def sauver_etat(etat: dict) -> None:
    tmp = FICHIER_ETAT.with_suffix(".tmp")
    tmp.write_text(json.dumps(etat, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(FICHIER_ETAT)


def format_prix(info: dict) -> str:
    if info.get("prix") in (None, ""):
        return ""
    symbole = "€" if info.get("devise") == "EUR" else info.get("devise", "")
    return f"{float(info['prix']):.2f} {symbole}".replace(".", ",")


# --------------------------------------------------------------------------- #
# Détection des nouvelles consoles (page « Toutes les consoles PS5 »)
# --------------------------------------------------------------------------- #

URL_BOUTIQUE = "https://www.playstation.com/fr-fr/consoles/ps5/shop-all/"


def _nettoyer_nom(nom: str) -> str:
    nom = re.sub(r"\\+[tnr]", " ", nom)  # tabulations / retours échappés
    nom = re.sub(r"\\+u([0-9a-fA-F]{4})", lambda m: chr(int(m.group(1), 16)), nom)
    nom = re.sub(r"\\+(.)", r"\1", nom)
    return re.sub(r"\s+", " ", html.unescape(nom)).strip()


def lire_catalogue() -> tuple[int | None, dict]:
    """Renvoie (nombre total de consoles annoncé, {id: {nom, prix}} des consoles affichées).

    La page publique contient les 20 premières consoles (les nouveautés sont en haut)
    et le nombre total ("totalCount")."""
    donnees = telecharger(URL_BOUTIQUE).replace('\\"', '"')
    produits = {}
    for m in re.finditer(r'\{"__typename":"Product","id":"([^"]+)","name":"((?:[^"\\]|\\.)*)"', donnees):
        pid = m.group(1)
        if pid in produits:
            continue
        prix = re.search(r'"basePrice":"([^"]*)"', donnees[m.end():m.end() + 600])
        produits[pid] = {"nom": _nettoyer_nom(m.group(2)), "prix": prix.group(1) if prix else ""}
    total = re.search(r'"pageInfo":\{[^}]*"totalCount":(\d+)', donnees)
    if not produits:
        raise ValueError("liste des consoles introuvable (structure du site modifiée ?)")
    return (int(total.group(1)) if total else None), produits


def verifier_catalogue(args, etat: dict) -> None:
    precedent = etat.get("__catalogue__")
    try:
        total, produits = lire_catalogue()
    except (urllib.error.URLError, TimeoutError, OSError, ValueError) as e:
        journal(f"  ? Liste des consoles illisible : {e}")
        return

    if precedent is None:  # premier passage : on mémorise sans alerter
        etat["__catalogue__"] = {"total": total, "vus": produits}
        sauver_etat(etat)
        journal(f"  📋 Catalogue mémorisé : {total} console(s) en vente sur le site.")
        return

    vus = precedent.get("vus", {})
    nouveaux = {pid: p for pid, p in produits.items() if pid not in vus}
    ancien_total = precedent.get("total")

    if nouveaux:
        lignes = "\n".join(f"• {p['nom']} — {p['prix']}" for p in nouveaux.values())
        alerter(args, f"NOUVELLE CONSOLE sur PlayStation Direct ({len(nouveaux)})",
                f"{lignes}\n{URL_BOUTIQUE}", URL_BOUTIQUE)
    elif total and ancien_total and total > ancien_total:
        alerter(args, "NOUVELLE CONSOLE sur PlayStation Direct",
                f"Le nombre de consoles est passé de {ancien_total} à {total}.\n"
                f"Elle n'est pas dans le haut de la liste : ouvrez la page et cliquez sur « Afficher plus ».\n"
                f"{URL_BOUTIQUE}", URL_BOUTIQUE)
    elif total and ancien_total and total < ancien_total:
        journal(f"  📋 Une ou plusieurs consoles retirées du site ({ancien_total} → {total}).")
    else:
        journal(f"  📋 Pas de nouvelle console ({total} en vente).")

    etat["__catalogue__"] = {"total": total, "vus": {**vus, **produits}}
    sauver_etat(etat)


def tour(args, urls: list[str], etat: dict) -> None:
    if not args.sans_catalogue:
        verifier_catalogue(args, etat)
    nb_dispo = 0
    nb_erreurs = 0
    for i, url in enumerate(urls):
        if i:
            time.sleep(args.pause + random.random() * args.pause)  # rester discret
        precedent = etat.get(url, {})
        try:
            info = verifier(url)
        except RuntimeError as e:
            nb_erreurs += 1
            erreurs = precedent.get("erreurs", 0) + 1
            etat[url] = {**precedent, "erreurs": erreurs}
            journal(f"  ? {url}\n      erreur ({erreurs}x d'affilée) : {e}")
            if erreurs == args.alerte_erreurs:
                alerter(args, "Surveillance PS5 : page illisible",
                        f"{url}\nInaccessible {erreurs} fois de suite : {e}", url)
            continue

        etait_dispo = precedent.get("disponible")

        # Avant d'alerter, re-vérifier quelques secondes plus tard : le site affiche
        # parfois "Ajouter au panier" pendant quelques secondes seulement.
        # Il faut 2 confirmations consécutives (après ~6 s puis ~12 s).
        if info["disponible"] and not etait_dispo:
            for delai in (6, 12):
                time.sleep(delai)
                try:
                    confirmation = verifier(url)
                except RuntimeError:
                    confirmation = info  # en cas de doute, on garde le signal positif
                if not confirmation["disponible"]:
                    journal(f"  ~ {info['nom']} : « disponible » non confirmé (signal fugace ignoré)")
                    info = confirmation
                    break
                info = confirmation

        libelle = LIBELLES.get(info["dispo"], info["dispo"])
        marque = "✅" if info["disponible"] else "❌"
        journal(f"  {marque} {info['nom']} — {format_prix(info)} — {libelle}")
        if info["disponible"]:
            nb_dispo += 1
            # Alerte au passage indisponible -> disponible (ou dès le 1er tour si --alerte-initiale)
            if etait_dispo is False or (etait_dispo is None and args.alerte_initiale):
                alerter(
                    args,
                    f"PS5 DISPONIBLE : {info['nom']}"[:200],
                    f"{info['nom']}\n{libelle} — {format_prix(info)}\n{url}",
                    url,
                )
        elif etait_dispo:
            journal(f"     (de nouveau en rupture : {info['nom']})")

        etat[url] = {
            **info,
            "erreurs": 0,
            "derniere_verif": datetime.now().isoformat(timespec="seconds"),
            **({"dernier_passage_en_stock": datetime.now().isoformat(timespec="seconds")}
               if info["disponible"] and not etait_dispo else
               {k: v for k, v in precedent.items() if k == "dernier_passage_en_stock"}),
        }
        sauver_etat(etat)
    journal(f"Tour terminé : {nb_dispo}/{len(urls)} article(s) disponible(s).")
    return {"total": len(urls), "dispo": nb_dispo, "erreurs": nb_erreurs,
            "consoles": (etat.get("__catalogue__") or {}).get("total")}


# --------------------------------------------------------------------------- #
# Notifications « la surveillance tourne » (démarrage + 8 h / 20 h)
# --------------------------------------------------------------------------- #

def maintenant_local(fuseau: str) -> datetime:
    try:
        from zoneinfo import ZoneInfo
        return datetime.now(ZoneInfo(fuseau))
    except Exception:  # Python < 3.9 ou base de fuseaux absente (Windows sans tzdata)
        return datetime.now()


def resume_tour(stats: dict, heure: datetime) -> str:
    lignes = [f"{stats['total']} article(s) vérifié(s) à {heure:%H:%M} : "
              f"{stats['dispo']} disponible(s)."]
    if stats.get("consoles"):
        lignes.append(f"{stats['consoles']} console(s) en vente sur le site.")
    if stats["erreurs"]:
        lignes.append(f"⚠️ {stats['erreurs']} page(s) illisible(s) à ce tour.")
    else:
        lignes.append("Aucune erreur.")
    return "\n".join(lignes)


def battement_si_heure(args, etat: dict, stats: dict) -> None:
    """Envoie « tout va bien » une fois par créneau (ex. 8 h et 20 h), au premier tour
    terminé après l'heure prévue (au plus tard 3 h après)."""
    if not args.battement:
        return
    maintenant = maintenant_local(args.fuseau)
    deja = etat.setdefault("__battements__", [])
    for h in args.battement:
        cle = f"{maintenant:%Y-%m-%d} {h:02d}h"
        if h <= maintenant.hour < h + 3 and cle not in deja:
            notif_info(args, f"🟢 Surveillance PS5 OK ({h} h)", resume_tour(stats, maintenant),
                       tags=("green_circle",))
            deja.append(cle)
            del deja[:-10]  # ne garder que les derniers
            sauver_etat(etat)


def heures(texte: str) -> list[int]:
    if not texte.strip():
        return []
    valeurs = sorted({int(x) for x in texte.replace(" ", "").split(",") if x})
    if any(not 0 <= v <= 23 for v in valeurs):
        raise argparse.ArgumentTypeError("heures entre 0 et 23, ex. 8,20")
    return valeurs


def main() -> None:
    p = argparse.ArgumentParser(description="Surveille le stock PS5 sur playstation.com/fr-fr")
    p.add_argument("--once", action="store_true", help="une seule vérification puis quitter")
    p.add_argument("--intervalle", type=int, default=300,
                   help="secondes entre deux tours (défaut 300 = 5 min, minimum 60)")
    p.add_argument("--pause", type=float, default=2.0,
                   help="pause (s) entre deux pages d'un même tour (défaut 2)")
    p.add_argument("--ntfy", metavar="SUJET", default=os.environ.get("NTFY_SUJET") or None,
                   help="sujet ntfy.sh pour recevoir une notification push sur le téléphone "
                        "(ou variable d'environnement NTFY_SUJET)")
    p.add_argument("--sans-catalogue", action="store_true",
                   help="ne pas surveiller l'apparition de nouvelles consoles sur le site")
    p.add_argument("--duree", type=float, default=0,
                   help="s'arrêter après N minutes (utile pour GitHub Actions ; 0 = sans fin)")
    p.add_argument("--ntfy-serveur", default="https://ntfy.sh")
    p.add_argument("--sans-bureau", action="store_true", help="pas de notification bureau")
    p.add_argument("--alerte-initiale", action="store_true",
                   help="alerter aussi pour les articles déjà disponibles au 1er tour")
    p.add_argument("--alerte-erreurs", type=int, default=5,
                   help="alerter quand une page échoue N fois d'affilée (défaut 5)")
    p.add_argument("--test-notif", action="store_true", help="envoyer une notification de test et quitter")
    p.add_argument("--notif-demarrage", action="store_true",
                   help="envoyer « Surveillance démarrée » après le 1er tour (preuve que tout marche)")
    p.add_argument("--battement", type=heures, default=heures("8,20"),
                   help="heures (fuseau --fuseau) d'envoi d'un « tout va bien », ex. 8,20 ; "
                        "chaîne vide pour désactiver (défaut 8,20)")
    p.add_argument("--fuseau", default="Europe/Paris", help="fuseau horaire des heures de --battement")
    args = p.parse_args()

    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")

    if args.test_notif:
        alerter(args, "Test surveillance PS5", "Les notifications fonctionnent 👍",
                "https://www.playstation.com/fr-fr/")
        return

    urls = charger_urls()
    etat = charger_etat()
    intervalle = max(60, args.intervalle)
    journal(f"Surveillance de {len(urls)} article(s)"
            + ("" if args.once else f", toutes les {intervalle // 60} min environ") + ".")

    fin = time.monotonic() + args.duree * 60 if args.duree > 0 else None
    premier_tour = True
    while True:
        debut_tour = time.monotonic()
        try:
            stats = tour(args, urls, etat)
            if premier_tour and args.notif_demarrage:
                notif_info(args, "✅ Surveillance PS5 démarrée",
                           resume_tour(stats, maintenant_local(args.fuseau)))
            battement_si_heure(args, etat, stats)
        except KeyboardInterrupt:
            raise
        except Exception as e:  # ne jamais arrêter la surveillance sur une erreur imprévue
            journal(f"Erreur inattendue : {e!r}")
        premier_tour = False
        if args.once:
            break
        # L'intervalle se compte d'un début de tour au suivant (léger aléa de ±5 %).
        duree_tour = time.monotonic() - debut_tour
        attente = max(5.0, intervalle * random.uniform(0.95, 1.05) - duree_tour)
        if fin is not None:
            if time.monotonic() + attente + duree_tour > fin:
                journal("Durée maximale atteinte, arrêt.")
                break
        time.sleep(attente)


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\nArrêt de la surveillance.")
