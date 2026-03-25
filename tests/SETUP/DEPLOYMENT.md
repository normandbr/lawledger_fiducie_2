# Déploiement de LawLedger avec NSSM + IIS

Ce guide explique comment exécuter LawLedger en tant que service Windows avec
**NSSM** (Non-Sucking Service Manager) et le rendre accessible via IIS à
l'adresse `http://<votre-serveur>/lawledger`.

---

## Prérequis

| Composant | Détails |
|-----------|---------|
| **Windows Server** (ou Windows 10/11 Pro) | IIS activé |
| **Python 3.10+** | Installé et dans le PATH |
| **NSSM** | Téléchargé depuis <https://nssm.cc/download> |
| **IIS – URL Rewrite** | Installé (module Microsoft) |
| **IIS – ARR (Application Request Routing)** | Installé et le proxy activé |
| **SQL Server** | Instance accessible depuis le serveur |

---

## 1. Préparation de l'application

```powershell
# Cloner ou copier le dépôt dans un répertoire permanent
# Exemple : C:\Apps\LawLedger
cd C:\Apps\LawLedger

# Créer un environnement virtuel
python -m venv venv
venv\Scripts\activate

# Installer les dépendances
pip install -r requirements.txt
```

### Configurer le fichier `.env`

Créez un fichier `.env` à la racine du projet (`C:\Apps\LawLedger\.env`) :

```ini
# ── Base de données ──
DB_SERVER=localhost
DB_NAME=LawLedger
DB_USER=sa
DB_PASSWORD=VotreMotDePasse
DB_DRIVER=ODBC Driver 17 for SQL Server

# ── Application ──
SECRET_KEY=une-cle-secrete-aleatoire
HOST=192.168.0.26
PORT=5000
USE_WAITRESS=true

# ── Préfixe URL (IMPORTANT pour /lawledger) ──
URL_PREFIX=/lawledger

# ── Licence ──
LICENSE_FILE=C:\Apps\LawLedger\config\license.json
```

> **Note :** `URL_PREFIX=/lawledger` indique à Flask de générer toutes les URLs
> avec le préfixe `/lawledger`. Sans cette variable, l'application fonctionne
> à la racine (`/`).

---

## 2. Test rapide (sans NSSM)

```powershell
cd C:\Apps\LawLedger
venv\Scripts\activate
python app.py
```

Ouvrez `http://127.0.0.1:5000/` dans un navigateur pour vérifier que
l'application démarre correctement.

---

## 3. Installer le service avec NSSM

```powershell
# Ouvrir une invite de commandes en tant qu'Administrateur
nssm install LawLedger
```

Dans la fenêtre NSSM qui s'ouvre :

| Champ | Valeur |
|-------|--------|
| **Path** | `C:\Apps\LawLedger\venv\Scripts\python.exe` |
| **Startup directory** | `C:\Apps\LawLedger` |
| **Arguments** | `app.py` |

### Onglet « Environment »

Ajoutez les variables d'environnement (une par ligne) :

```
USE_WAITRESS=true
URL_PREFIX=/lawledger
```

> Les autres variables sont lues depuis le fichier `.env`.

### Onglet « I/O » (optionnel, pour le débogage)

| Champ | Valeur |
|-------|--------|
| **Output (stdout)** | `C:\Apps\LawLedger\logs\stdout.log` |
| **Error (stderr)** | `C:\Apps\LawLedger\logs\stderr.log` |

Créez le dossier `logs` au préalable :

```powershell
mkdir C:\Apps\LawLedger\logs
```

### Démarrer le service

```powershell
nssm start LawLedger
```

Vérification :

```powershell
nssm status LawLedger
# Devrait afficher : SERVICE_RUNNING
```

---

## 4. Configurer IIS comme reverse proxy

### 4.1. Activer le proxy ARR

1. Ouvrir **IIS Manager**
2. Sélectionner le serveur (niveau racine)
3. Double-cliquer sur **Application Request Routing Cache**
4. Cliquer sur **Server Proxy Settings…** dans le panneau Actions
5. Cocher **Enable proxy** → **Appliquer**

### 4.2. Configurer la règle de réécriture

Le fichier `web.config` est déjà inclus dans le projet. Il doit être placé à
la racine du site IIS par défaut (`C:\inetpub\wwwroot\web.config`) :

```xml
<?xml version="1.0" encoding="UTF-8"?>
<configuration>
  <system.webServer>
    <rewrite>
      <rules>
        <rule name="LawLedgerProxy" stopProcessing="true">
          <match url="^lawledger/?(.*)" />
          <action type="Rewrite" url="http://127.0.0.1:5000/{R:1}"
                  appendQueryString="true" />
        </rule>
      </rules>
    </rewrite>
  </system.webServer>
</configuration>
```

**Ce que fait cette règle :**
- Intercepte toute URL commençant par `/lawledger/`
- Transmet la requête à Flask sur `http://127.0.0.1:5000/` en **retirant** le
  préfixe `/lawledger`
- Flask reconstitue le préfixe grâce à la variable `URL_PREFIX`

### 4.3. Vérifier

Accédez à `http://192.168.0.26/lawledger` dans un navigateur. Vous devriez
voir la page de connexion de LawLedger.

---

## 5. Commandes NSSM utiles

```powershell
# Vérifier le statut
nssm status LawLedger

# Arrêter le service
nssm stop LawLedger

# Redémarrer le service
nssm restart LawLedger

# Modifier la configuration
nssm edit LawLedger

# Supprimer le service
nssm remove LawLedger confirm
```

---

## 6. Résolution de problèmes

### L'application ne démarre pas

1. Vérifiez les logs dans `C:\Apps\LawLedger\logs\`
2. Testez manuellement :
   ```powershell
   cd C:\Apps\LawLedger
   venv\Scripts\python.exe app.py
   ```
3. Vérifiez que le port 5000 n'est pas déjà utilisé :
   ```powershell
   netstat -an | findstr :5000
   ```

### Erreur 502 Bad Gateway sur IIS

- Le service LawLedger n'est probablement pas en cours d'exécution
- Vérifiez : `nssm status LawLedger`
- Vérifiez que ARR proxy est bien activé

### Les liens/redirections ne fonctionnent pas (404)

- Vérifiez que `URL_PREFIX=/lawledger` est défini dans le `.env` ou dans les
  variables d'environnement NSSM
- Redémarrez le service après toute modification : `nssm restart LawLedger`

### La page de connexion boucle ou les assets ne chargent pas

- Vérifiez que la règle IIS Rewrite est en place et fonctionne
- Vérifiez la console du navigateur (F12) pour des erreurs 404 sur les fichiers
  CSS/JS

---

## 7. Architecture

```
  Navigateur
      │
      ▼
  http://192.168.0.26/lawledger/login
      │
      ▼
  IIS (port 80)
  ┌─────────────────────────────┐
  │  URL Rewrite + ARR Proxy    │
  │  /lawledger/login            │
  │       ↓ strip prefix         │
  │  → http://127.0.0.1:5000/login │
  └─────────────────────────────┘
      │
      ▼
  Flask/Waitress (port 5000)
  ┌─────────────────────────────┐
  │  SCRIPT_NAME = /lawledger   │
  │  Route: /login              │
  │  url_for('login')           │
  │    → /lawledger/login       │
  └─────────────────────────────┘
```
