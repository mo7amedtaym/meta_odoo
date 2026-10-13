import hashlib
import hmac
import time

try:
    from .core import normalize_key
except ImportError:
    import importlib.util
    from pathlib import Path
    spec = importlib.util.spec_from_file_location('_social_core', Path(__file__).with_name('core.py'))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    normalize_key = mod.normalize_key

def compute_signature(timestamp, raw_body, secret):
    raw_body = raw_body if isinstance(raw_body, bytes) else str(raw_body).encode('utf-8')
    msg = str(timestamp).encode('utf-8') + b'.' + raw_body
    return hmac.new(str(secret).encode('utf-8'), msg, hashlib.sha256).hexdigest()

def verify_signature(timestamp, raw_body, secret, signature):
    if not timestamp or not secret or not signature:
        return False
    return hmac.compare_digest(compute_signature(timestamp, raw_body, secret), str(signature).strip())

def timestamp_is_fresh(timestamp, now=None, tolerance=300):
    try:
        ts = int(timestamp)
    except (TypeError, ValueError):
        return False
    now = int(time.time() if now is None else now)
    return abs(now - ts) <= int(tolerance)

def normalize_payload(payload):
    first = str(payload.get('first_name') or '').strip()
    last = str(payload.get('last_name') or '').strip()
    fields = {}
    if first or last:
        fields['full_name'] = ' '.join(v for v in (first, last) if v)
    reserved = {
        'form_id','form_name','ad_account_id','campaign_id','campaign_name','ad_id','ad_name',
        'ad_squad_id','ad_squad_name','lead_id','create_time'
    }
    for key, value in payload.items():
        if key in reserved or key in ('first_name','last_name'):
            continue
        normalized = normalize_key(key)
        if normalized:
            fields[normalized] = value
    return {
        'provider': 'snapchat',
        'external_lead_id': str(payload.get('lead_id') or ''),
        'external_form_id': str(payload.get('form_id') or ''),
        'external_ad_account_id': str(payload.get('ad_account_id') or ''),
        'external_campaign_id': str(payload.get('campaign_id') or ''),
        'campaign_name': payload.get('campaign_name'),
        'external_adgroup_id': str(payload.get('ad_squad_id') or ''),
        'adgroup_name': payload.get('ad_squad_name'),
        'external_ad_id': str(payload.get('ad_id') or ''),
        'ad_name': payload.get('ad_name'),
        'received_at': payload.get('create_time'),
        'fields': fields,
        'raw': payload,
    }
