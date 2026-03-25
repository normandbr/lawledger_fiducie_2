#!/usr/bin/env python3
"""
verifier_mon_app.py – Vérificateur automatique de LawLedger
============================================================

Ce script lance tous les tests automatiques et affiche le résultat en couleur :

  • VERT  → "BRAVO : Tout est OK !"          (tous les tests ont réussi)
  • ROUGE → "ERREUR : Un problème a été détecté"  (au moins un test a échoué)

Utilisation :
    python verifier_mon_app.py
"""

import subprocess
import sys
import os


sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

# ── Codes couleur ANSI ──────────────────────────────────────────────────────
GREEN  = "\033[92m"
RED    = "\033[91m"
YELLOW = "\033[93m"
BOLD   = "\033[1m"
RESET  = "\033[0m"

BANNER = f"""
{BOLD}{'='*60}
   LawLedger – Vérificateur automatique
{'='*60}{RESET}
"""


def main():
    print(BANNER)

    # Répertoire de ce fichier = racine du projet
    project_root = os.path.dirname(os.path.abspath(__file__))
    tests_dir = os.path.join(project_root, "tests")

    if not os.path.isdir(tests_dir):
        print(f"{RED}{BOLD}ERREUR : Le dossier 'tests/' est introuvable.{RESET}")
        print(f"Assurez-vous que le fichier tests/test_app.py est présent.")
        sys.exit(2)

    print(f"{YELLOW}Lancement des tests en cours…{RESET}\n")

    # Lance pytest avec sortie verbeuse
    result = subprocess.run(
        [sys.executable, "-m", "pytest", tests_dir, "-v", "--tb=short"],
        cwd=project_root,
    )

    print()

    if result.returncode == 0:
        print(f"{GREEN}{BOLD}{'='*60}")
        print(f"  BRAVO : Tout est OK !")
        print(f"  Tous les tests ont réussi.")
        print(f"{'='*60}{RESET}")
    else:
        print(f"{RED}{BOLD}{'='*60}")
        print(f"  ERREUR : Un problème a été détecté.")
        print(f"  Consultez les messages ci-dessus pour le détail.")
        print(f"{'='*60}{RESET}")

    sys.exit(result.returncode)


if __name__ == "__main__":
    main()
