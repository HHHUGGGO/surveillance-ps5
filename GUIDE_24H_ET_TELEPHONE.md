# Surveillance 24 h/24 avec notifications sur le téléphone

Ce guide fait tourner la surveillance **gratuitement sur les serveurs de GitHub**. Votre ordinateur peut rester éteint.
Les alertes arrivent sur votre téléphone grâce à l'application gratuite **ntfy**.
Comptez environ 15 minutes, une seule fois.

---

## Étape 1 : préparer les notifications sur le téléphone (2 min)

1. Installez **ntfy** depuis l'App Store (iPhone) ou le Play Store (Android).
2. Ouvrez l'application, touchez **+** (« Subscribe to topic ») et inventez un nom de sujet **long et difficile à deviner**, par exemple `ps5-alerte-8kq3zx71`.
   Ce nom fait office de mot de passe : n'importe qui le connaissant pourrait lire vos alertes.
3. Sur iPhone, acceptez les notifications quand l'application le demande.
4. Testez depuis un navigateur sur votre ordinateur : ouvrez `https://ntfy.sh/ps5-alerte-8kq3zx71` (avec **votre** sujet), écrivez « test » dans le champ en bas de la page et envoyez. La notification doit arriver sur le téléphone.

## Étape 2 : créer un compte et un dépôt GitHub (5 min)

1. Créez un compte gratuit sur https://github.com.
2. En haut à droite, cliquez sur **+** puis **New repository** :
   - Nom : `surveillance-ps5` ;
   - Visibilité : **Public**. Les minutes de calcul sont illimitées et gratuites pour un dépôt public. Un dépôt privé serait limité à 2 000 minutes par mois, ce qui ne suffit pas pour une surveillance 24 h/24. Seuls le script et la liste des URL sont visibles. Votre sujet ntfy reste secret (étape 4).
   - Cliquez sur **Create repository**.

## Étape 3 : envoyer les fichiers (3 min)

1. Dans le dépôt, cliquez sur le lien **uploading an existing file**.
2. Faites glisser `surveiller_ps5.py`, `urls.txt` et `LISEZMOI.md`, puis cliquez sur **Commit changes**.
3. Ajoutez le fichier d'automatisation, en le créant à la main pour être sûr qu'il soit au bon endroit :
   - cliquez sur **Add file > Create new file** ;
   - comme nom, tapez exactement : `.github/workflows/surveillance.yml` (les `/` créent les dossiers) ;
   - copiez-collez tout le contenu du fichier `surveillance.yml` fourni ;
   - cliquez sur **Commit changes**.

## Étape 4 : donner votre sujet ntfy à GitHub, en secret (1 min)

1. Dans le dépôt, ouvrez **Settings** puis **Secrets and variables > Actions**.
2. Cliquez sur **New repository secret** :
   - Name : `NTFY_SUJET`
   - Secret : votre sujet, par exemple `ps5-alerte-8kq3zx71`
3. Cliquez sur **Add secret**.

## Étape 5 : lancer et vérifier (3 min)

1. Ouvrez l'onglet **Actions**. Si GitHub le demande, cliquez sur **I understand my workflows, go ahead and enable them**.
2. Cliquez sur **Surveillance stock PS5** à gauche, puis **Run workflow > Run workflow**.
3. Cliquez sur l'exécution qui démarre, puis sur l'étape **Surveiller** : vous devez voir la liste des articles avec ❌ ou ✅.
   - Si toutes les lignes affichent une **erreur**, le site PlayStation bloque peut-être les serveurs de GitHub. Dans ce cas, utilisez l'option B ci-dessous.

C'est terminé. Chaque session vérifie les articles **toutes les 5 minutes** pendant environ 5 h 45, puis **lance elle-même la suivante** (relais), jour et nuit. Les tâches programmées de GitHub sont souvent retardées ou sautées : elles ne servent ici que de filet de sécurité, toutes les 2 heures, si la chaîne se casse.

Dans l'onglet Actions, la session en cours a un rond jaune 🟡 pendant environ 5 h 45. La suivante apparaît « en attente », puis prend le relais. C'est normal.

---

## À savoir

- **La surveillance tourne-t-elle toujours ?** Chaque jour vers **8 h** et vers **20 h** (heure de Paris), vous recevez « 🟢 Surveillance PS5 OK » avec le résultat de la dernière vérification. Elle part juste après une vraie vérification, en général dans les 5 minutes qui suivent l'heure. **Si elle n'arrive pas, c'est que la surveillance ne tourne plus** : regardez l'onglet Actions.
- **Lancement manuel :** quand vous cliquez sur « Run workflow », vous recevez « ✅ Surveillance démarrée ». Cela confirme que GitHub, le secret `NTFY_SUJET` et votre téléphone fonctionnent ensemble.

- **Nouvelles consoles :** vous êtes aussi prévenu quand une console est ajoutée à la page « Toutes les consoles PS5 » (notification « NOUVELLE CONSOLE »).

- **Une seule notification par retour en stock.** Pour éviter les faux signaux, l'outil confirme d'abord la disponibilité deux fois, en une vingtaine de secondes.
- **Petits trous possibles :** GitHub lance parfois les sessions programmées avec 5 à 15 minutes de retard aux heures chargées. La couverture est donc quasi continue, pas parfaite.
- **60 jours d'inactivité :** GitHub met en pause les tâches programmées d'un dépôt public si personne n'y touche pendant 60 jours. Il envoie un e-mail avant, et il suffit de cliquer sur « Enable workflow » dans l'onglet Actions.
- **Modifier la liste :** éditez `urls.txt` directement sur GitHub (icône crayon), avec une URL par ligne.
- **Arrêter :** dans **Actions > Surveillance stock PS5**, cliquez sur **⋯ > Disable workflow**. Annuler la session en cours avec **Cancel workflow** arrête aussi le relais, mais le filet de sécurité la relancera dans les 2 heures, sauf si le workflow est désactivé.
- **Redémarrer après un arrêt :** **Run workflow**. Vous recevez alors « ✅ Surveillance démarrée ».

---

## Option B : sur une machine allumée en permanence

Utilisez cette option si vous avez un Raspberry Pi, un vieux PC ou un serveur, ou si GitHub est bloqué par le site.
Elle permet des vérifications plus fréquentes et sans trous.

**Linux ou Raspberry Pi.** Créez le fichier `/etc/systemd/system/surveillance-ps5.service` (remplacez le chemin, l'utilisateur et le sujet) :

```ini
[Unit]
Description=Surveillance stock PS5
After=network-online.target
Wants=network-online.target

[Service]
User=pi
WorkingDirectory=/home/pi/surveillance-ps5
Environment=NTFY_SUJET=ps5-alerte-8kq3zx71
ExecStart=/usr/bin/python3 surveiller_ps5.py --intervalle 300 --sans-bureau
Restart=always
RestartSec=60

[Install]
WantedBy=multi-user.target
```

Puis activez le service :

```bash
sudo systemctl enable --now surveillance-ps5
```

Pour suivre ce qu'il fait :

```bash
journalctl -u surveillance-ps5 -f
```

**Windows**, sur un PC qui ne se met pas en veille : dans le Planificateur de tâches, créez une tâche « À l'ouverture de session ». L'action est `pythonw.exe`, avec comme argument `C:\chemin\surveiller_ps5.py --intervalle 300 --ntfy VOTRE-SUJET`.
