# LawLedger – Système de gestion juridique

LawLedger est une application web Flask de gestion de cabinet juridique.  
Elle gère les clients, dossiers, factures, feuilles de temps, fiducie, et plus encore.

---

## Démarrage rapide

### Prérequis

- Python 3.10 ou plus récent
- pip (gestionnaire de paquets Python)

### Installation

```bash
# 1. Cloner le dépôt (si ce n'est pas déjà fait)
git clone <url-du-dépôt>
cd lawledger_fiducie

# 2. Installer les dépendances
pip install -r requirements.txt

# 3. Copier et configurer le fichier d'environnement
copy .env.example .env    # Windows
cp  .env.example .env     # Mac / Linux
# Puis ouvrir .env et remplir les paramètres (base de données, clé secrète, etc.)

# 4. Lancer l'application
python app.py
```

L'application sera accessible à l'adresse : **http://127.0.0.1:5000**

---

## 🔍 Vérificateur automatique

Le fichier `verifier_mon_app.py` permet de vérifier que toutes les
fonctionnalités principales de l'application fonctionnent correctement.

### Comment lancer le vérificateur

1. Ouvrir un terminal (Invite de commandes ou PowerShell sous Windows).
2. Se placer dans le dossier du projet :

```bash
cd C:\chemin\vers\lawledger_fiducie
```

3. Lancer le vérificateur :

```bash
python verifier_mon_app.py
```

### Ce que vous verrez

| Résultat | Message affiché |
|----------|-----------------|
| ✅ Tout fonctionne | `BRAVO : Tout est OK !` (en **vert**) |
| ❌ Un problème | `ERREUR : Un problème a été détecté` (en **rouge**) avec le détail de l'erreur |

### Installer pytest (si nécessaire)

Le vérificateur utilise `pytest`. S'il n'est pas encore installé :

```bash
pip install pytest
```

---

## Modules principaux

| Module | URL | Accès |
|--------|-----|-------|
| Clients & Dossiers | `/clients` | Tous |
| Factures | `/invoices` | Tous |
| Comptes à recevoir | `/unbilled` | Tous |
| Feuille de temps | `/time-logs` | Tous |
| Grand livre général | `/gl` | **Gestionnaires uniquement** |
| Fiducie | `/fiducie/<id>` | Tous |
| Module RH | `/hr-records` | **Gestionnaires uniquement** |
| Employés | `/employees` | **Gestionnaires uniquement** |

---

## Configuration (fichier `.env`)

| Variable | Description | Exemple |
|----------|-------------|---------|
| `SECRET_KEY` | Clé secrète Flask | `ma-cle-secrete-longue` |
| `DATABASE_URL` | URL de connexion à la base de données | `mssql+pyodbc://...` |
| `HOST` | Nom de domaine externe (pour les emails) | `lawledger.monsite.com` |
| `BIND_HOST` | Adresse d'écoute du serveur | `127.0.0.1` |
| `PORT` | Port interne du serveur Waitress | `5000` |

---

## Lancer les tests manuellement

```bash
# Tous les tests (résultat détaillé)
pytest tests/test_app.py -v

# Arrêt au premier échec
pytest tests/test_app.py -v -x
```

---

## Structure du projet

```
lawledger_fiducie/
├── app.py              # Application Flask principale
├── translations.py     # Traductions FR / EN
├── licensing.py        # Gestion des licences
├── requirements.txt    # Dépendances Python
├── verifier_mon_app.py # Vérificateur automatique (couleurs)
├── tests/
│   └── test_app.py     # Tests automatiques (pytest)
├── templates/          # Gabarits HTML Jinja2
├── static/             # CSS, JS, images
└── config/             # Fichier de licence (non versionné)
```
