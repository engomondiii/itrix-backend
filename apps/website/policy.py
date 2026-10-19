"""Retail availability is controlled by explicit per-store approval, never by old checkout flags."""
from urllib.parse import urlsplit
import re
from django.conf import settings


def store_policy():
    stores = []
    for key, hosts in [('APPLE', {'apps.apple.com'}), ('MICROSOFT', {'apps.microsoft.com', 'www.microsoft.com'})]:
        url = getattr(settings, f'ASTOP_{key}_STORE_URL', '')
        parsed = urlsplit(url)
        # A generic vendor homepage must not become a purchase destination.
        path_ok = bool(re.fullmatch(r'/(?:[a-z]{2}(?:-[a-z]{2})?/)?app/[^/]+/id[0-9]+/?', parsed.path)) if key == 'APPLE' else bool(
            re.fullmatch(r'/(?:[a-z]{2}-[a-z]{2}/)?(?:detail|store/detail)/[^/]+(?:/[^/]+)?/?', parsed.path, re.I))
        live = bool(path_ok and getattr(settings, f'ASTOP_{key}_STORE_CONFIRMED', False) and
                    parsed.scheme == 'https' and parsed.hostname in hosts and parsed.path not in ('', '/') and
                    not parsed.username and not parsed.password)
        stores.append({'store': key.lower(), 'available': live, 'url': url if live else None})
    return {'state': 'post_launch' if any(s['available'] for s in stores) else 'pre_launch',
            'checkout_available': False, 'trial_available': False, 'website_downloads': False,
            'monthly_usd': '10.00', 'annual_usd': '100.00', 'pricing_status': 'working_standard',
            'stores': stores, 'interest_path': '/contact?topic=interest', 'enterprise_path': '/poc',
            'message': 'ASTOP is being prepared for Store release. Register interest or request Strategic Enterprise Validation.'}
