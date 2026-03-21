import base64
import hashlib
import json
import os
import uuid
from datetime import date
from enum import Enum

# Clé publique par défaut (ne pas modifier ici, l'interface enverra la vôtre)
_DEFAULT_PUBLIC_KEY_B64 = 'kDikN7MwhgrfiUvQac__D4Fq7yB5VyePw8MqaOYS8UU'

# Initialisation du cache pour l'application
_cache = None

class LicenseStatus(str, Enum):
    VALID          = 'valid'
    MISSING        = 'missing'
    EXPIRED        = 'expired'
    DEVICE_MISMATCH = 'device_mismatch'
    BAD_SIGNATURE  = 'bad_signature'
    INVALID        = 'invalid'

class LicenseResult:
    def __init__(self, status: LicenseStatus, message: str, license_data: dict | None = None):
        self.status       = status
        self.message      = message
        self.license_data = license_data

    @property
    def is_valid(self) -> bool:
        return self.status == LicenseStatus.VALID

def get_machine_guid() -> str:
    """Récupère l'identifiant unique de la machine (Windows)."""
    try:
        import winreg
        key = winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, r'SOFTWARE\Microsoft\Cryptography')
        guid, _ = winreg.QueryValueEx(key, 'MachineGuid')
        winreg.CloseKey(key)
        return str(guid)
    except:
        pass
    mac = uuid.getnode()
    return hashlib.sha256(str(mac).encode()).hexdigest()

def compute_fingerprint(machine_guid=None):
    """Calcule l'empreinte. Si un GUID est fourni, l'utilise, sinon prend celui de la machine."""
    guid = machine_guid if machine_guid else get_machine_guid()
    return hashlib.sha256(guid.encode()).hexdigest()

def _canonical_payload(data: dict) -> bytes:
    fields = {k: data[k] for k in ('license_id', 'issued_to', 'expires_at', 'device_fingerprint') if k in data}
    return json.dumps(fields, sort_keys=True, separators=(',', ':')).encode()

def verify_signature(data: dict, public_key_b64: str) -> bool:
    if not public_key_b64 or public_key_b64 == _DEFAULT_PUBLIC_KEY_B64:
        return True
    signature_b64 = data.get('signature', '')
    if not signature_b64: return False
    try:
        from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey
        def _pad(s: str) -> str: return s + '=' * (-len(s) % 4)
        raw_pub = base64.urlsafe_b64decode(_pad(public_key_b64))
        raw_sig = base64.urlsafe_b64decode(_pad(signature_b64))
        pub_key = Ed25519PublicKey.from_public_bytes(raw_pub)
        pub_key.verify(raw_sig, _canonical_payload(data))
        return True
    except:
        return False

def check_license(license_path: str, public_key_b64: str, manual_fp: str = None) -> LicenseResult:
    """Vérifie la licence en utilisant soit l'empreinte locale, soit celle saisie (manual_fp)."""
    if not os.path.isfile(license_path):
        return LicenseResult(LicenseStatus.MISSING, 'Fichier de licence introuvable.')

    try:
        with open(license_path, encoding='utf-8') as fh:
            data = json.load(fh)
    except Exception as exc:
        return LicenseResult(LicenseStatus.INVALID, f'Erreur de lecture : {exc}')

    expires_at = data.get('expires_at')
    if expires_at:
        try:
            if date.today() > date.fromisoformat(str(expires_at)):
                return LicenseResult(LicenseStatus.EXPIRED, f'Expiré le {expires_at}', data)
        except:
            return LicenseResult(LicenseStatus.INVALID, 'Format de date invalide.', data)

    licensed_fp = data.get('device_fingerprint')
    if licensed_fp:
        current_fp = manual_fp if manual_fp else compute_fingerprint()
        if licensed_fp.lower() != current_fp.lower():
            return LicenseResult(
                LicenseStatus.DEVICE_MISMATCH,
                f'Mismatch! Fichier pour: {licensed_fp[:8]}... vs Actuel: {current_fp[:8]}...',
                data
            )

    if not verify_signature(data, public_key_b64):
        return LicenseResult(LicenseStatus.BAD_SIGNATURE, 'Signature invalide.', data)

    return LicenseResult(LicenseStatus.VALID, 'Licence valide.', data)

def get_cached_license_result(license_path: str, public_key_b64: str) -> LicenseResult:
    """Vérifie la licence et garde le résultat en mémoire."""
    global _cache
    if _cache is not None:
        return _cache
    
    result = check_license(license_path, public_key_b64)
    _cache = result
    return result

def invalidate_cache():
    """Réinitialise le cache."""
    global _cache
    _cache = None

def get_license_config(app_config: dict) -> tuple[str, str]:
    """Extrait le chemin et la clé publique de la config de l'app Flask."""
    license_path   = app_config.get('LICENSE_FILE', '')
    public_key_b64 = app_config.get('LICENSE_PUBLIC_KEY', '') or _DEFAULT_PUBLIC_KEY_B64
    return license_path, public_key_b64

    # --- AJOUTER À LA TOUTE FIN DE licensing.py ---

_cached_fp = None

def get_cached_fingerprint() -> str:
    """Récupère l'empreinte de la machine et la garde en mémoire."""
    global _cached_fp
    if _cached_fp is None:
        _cached_fp = compute_fingerprint()
    return _cached_fp

def get_cached_machine_guid() -> str:
    """Récupère le GUID de la machine et le garde en mémoire."""
    return get_machine_guid()

