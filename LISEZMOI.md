# Surveillance du stock PS5 (PlayStation Direct France)

Ce script vérifie régulièrement les pages produit de `playstation.com/fr-fr` listées dans `urls.txt`.
Il vous prévient dès qu'un article passe de **« rupture de stock »** à **« disponible »**.

Pour savoir si un article est en stock, il lit l'état du **bouton d'achat** tel que le site l'affiche : « Ajouter au panier » ou « Non disponible à l'achat ».
Il ne se fie pas au champ `availability` de la page, qui peut dire « en stock » alors que l'achat est impossible.

## Ce qu'il faut

- Python 3.8 ou plus récent, sans aucune bibliothèque à installer :
  - Windows : https://www.python.org/downloads/ (cochez « Add Python to PATH ») ;
  - macOS et Linux : souvent déjà installé.
- Un ordinateur allumé avec le script lancé. Il ne vérifie rien quand le PC dort.

## Démarrage rapide

```bash
python surveiller_ps5.py --once
```

Cette commande fait une vérification unique et affiche l'état de chaque article.

```bash
python surveiller_ps5.py
```

Cette commande surveille en continu, environ toutes les 5 minutes. Arrêtez-la avec Ctrl+C.

## Recevoir l'alerte sur votre téléphone (recommandé)

1. Installez l'application gratuite **ntfy** (iOS ou Android).
2. Dans l'application, abonnez-vous à un sujet au **nom difficile à deviner**, par exemple `ps5-alerte-x7k2q9`. Les sujets ntfy sont publics : n'importe qui connaissant le nom peut lire vos messages.
3. Testez :

```bash
python surveiller_ps5.py --test-notif --ntfy ps5-alerte-x7k2q9
```

4. Lancez la surveillance :

```bash
python surveiller_ps5.py --ntfy ps5-alerte-x7k2q9
```

Quand vous touchez la notification, la page du produit s'ouvre directement.

## Alerte par e-mail (optionnel)

Définissez ces variables d'environnement avant de lancer le script. L'exemple ci-dessous est pour Gmail, avec un « mot de passe d'application ».

```bash
export SMTP_HOST=smtp.gmail.com
export SMTP_PORT=587
export SMTP_USER=vous@gmail.com
export SMTP_PASSWORD="mot-de-passe-application"
export SMTP_TO=vous@exemple.fr
```

Sous Windows (PowerShell), écrivez `$env:SMTP_HOST="smtp.gmail.com"` à la place de `export ...`, et de même pour les autres variables.

## Nouvelles consoles

À chaque tour, le script regarde aussi la page « Toutes les consoles PS5 » :
https://www.playstation.com/fr-fr/consoles/ps5/shop-all/

Vous recevez une notification « NOUVELLE CONSOLE » dans deux cas :
- **nouveau nom :** une console jamais vue apparaît en haut de la liste, où le site affiche les nouveautés. La notification donne son nom et son prix ;
- **nombre en hausse :** le nombre total de consoles en vente augmente, par exemple de 28 à 29.

Le premier lancement mémorise la liste actuelle sans rien envoyer.
Pour surveiller une nouvelle console jusqu'à son retour en stock, ajoutez le lien de sa page dans `urls.txt`.
Pour désactiver cette détection, ajoutez l'option `--sans-catalogue`.

## Options

| Option | Effet |
|---|---|
| `--once` | Une seule vérification, puis le script s'arrête |
| `--intervalle 120` | Secondes entre deux tours (minimum 60, 300 par défaut) |
| `--ntfy SUJET` | Notification push sur le téléphone via ntfy.sh |
| `--alerte-initiale` | Alerte aussi pour les articles **déjà** en stock au premier tour |
| `--sans-bureau` | Pas de notification sur le bureau de l'ordinateur |
| `--alerte-erreurs 5` | Alerte si une page reste illisible N fois de suite |
| `--sans-catalogue` | Ne pas surveiller l'arrivée de nouvelles consoles |
| `--notif-demarrage` | Envoie « ✅ Surveillance démarrée » après la première vérification |
| `--battement 8,20` | Envoie « 🟢 Surveillance PS5 OK » chaque jour à ces heures (Paris). `--battement ""` pour désactiver |
| `--test-notif` | Envoie une notification de test, puis s'arrête |

## Fonctionnement

- **Une seule alerte par retour en stock.** Le script ne vous relance pas tant que l'article reste disponible. S'il repasse en rupture puis revient, vous êtes de nouveau prévenu.
- L'état est mémorisé dans `etat_stock.json`. Vous pouvez arrêter et relancer le script sans recevoir de fausses alertes.
- Pour ajouter ou retirer un article, modifiez `urls.txt` (une URL par ligne).
- Sites pris en charge : **playstation.com/fr-fr** (PlayStation Direct) et **auchan.fr**.
- Chez Auchan, l'article compte comme disponible quand l'offre en ligne peut être ajoutée au panier. Si elle vient d'un **vendeur tiers** de la marketplace, l'alerte l'indique (« vendu par … ») : vérifiez le prix avant d'acheter.
- Une pause de quelques secondes sépare les pages pour ne pas surcharger le site. **Ne descendez pas sous 2 minutes d'intervalle** : le site pourrait bloquer votre adresse IP.

## Lancer au démarrage de l'ordinateur

- **Windows** : dans le Planificateur de tâches, créez une tâche « À l'ouverture de session ». L'action est `pythonw.exe`, avec comme argument `C:\chemin\surveiller_ps5.py --ntfy VOTRE-SUJET`.
- **macOS / Linux** : ajoutez cette ligne à `crontab -e` :

```bash
@reboot cd /chemin/ps5-stock-monitor && python3 surveiller_ps5.py --ntfy VOTRE-SUJET >> surveillance.log 2>&1
```
