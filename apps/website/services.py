import csv
import hashlib
import io
import secrets
from datetime import timedelta
from html import escape
from urllib.parse import urlsplit
import requests
from django.conf import settings
from django.contrib.auth.hashers import make_password, check_password
from django.core import signing
from django.core.mail import EmailMultiAlternatives
from django.db import transaction
from django.utils import timezone
from rest_framework.exceptions import ValidationError, PermissionDenied, Throttled
from .models import AdminIdentity, AdminSession, Audit, Outbox, Subscription


def digest(value):
    return hashlib.sha256(value.encode()).hexdigest()


def allowed():
    return {s.strip().lower() for s in settings.WEBSITE_ADMIN_EMAILS.split(',') if s.strip()}


def ip(request):
    # The Next BFF authenticates its forwarded client address; direct requests use peer IP.
    supplied = request.headers.get('X-Website-Proxy-Key', '')
    expected = getattr(settings, 'WEBSITE_PROXY_KEY', '')
    if expected and secrets.compare_digest(supplied, expected):
        value = request.headers.get('X-Website-Client-IP', '')
    else:
        value = request.META.get('REMOTE_ADDR', '')
    import ipaddress
    try:
        return str(ipaddress.ip_address(value))
    except ValueError:
        return None


def audit(request, actor, action, target='', **detail):
    Audit.objects.create(actor=actor, action=action, target=str(target), ip=ip(request), detail=detail)


def send_mail(to, subject, paragraphs, button=None):
    if not getattr(settings, 'ENABLE_EMAIL_DELIVERY', False):
        raise RuntimeError('Email delivery unavailable')
    body = '\n\n'.join(paragraphs)
    rows = ''.join('<tr><td style="padding:12px 28px;color:#CBD5E1;font:15px Arial,sans-serif;white-space:pre-line">'+escape(p)+'</td></tr>' for p in paragraphs)
    if button:
        label, url = button
        rows += f'<tr><td style="padding:24px 28px"><a style="background:#F8FAFC;color:#1F2937;padding:12px 20px;text-decoration:none" href="{escape(url, quote=True)}">{escape(label)}</a></td></tr>'
        body += '\n\n'+url
    html = '<!doctype html><html><body style="margin:0;background:#020406"><table role="presentation" width="100%" cellspacing="0" cellpadding="0"><tr><td align="center"><table role="presentation" width="600" style="max-width:100%;background:#080D10" cellspacing="0" cellpadding="0"><tr><td style="padding:28px;color:#F8FAFC;font:bold 28px Arial">itriX</td></tr>'+rows+'</table></td></tr></table></body></html>'
    message = EmailMultiAlternatives(subject, body, settings.WEBSITE_FROM_EMAIL, [to])
    message.attach_alternative(html, 'text/html')
    if message.send() != 1:
        raise RuntimeError('Delivery failed')


@transaction.atomic
def request_code(request, email, language):
    email = email.strip().lower()
    if email not in allowed():
        raise PermissionDenied('This email isn’t authorized for admin access.')
    AdminIdentity.objects.get_or_create(email=email)
    identity = AdminIdentity.objects.select_for_update().get(email=email)
    now = timezone.now()
    if identity.locked_until and identity.locked_until > now:
        raise Throttled(detail='Please try again in 15 minutes.')
    if identity.last_sent and now - identity.last_sent < timedelta(minutes=1):
        raise Throttled(detail='Wait one minute before requesting another code.')
    if not identity.window_start or now - identity.window_start >= timedelta(hours=1):
        identity.window_start, identity.sent_count = now, 0
    if identity.sent_count >= 5:
        raise Throttled(detail='Hourly code limit reached.')
    code = f'{secrets.randbelow(1000000):06d}'
    identity.code_hash = make_password(code)
    identity.code_expires = now + timedelta(minutes=5)
    identity.last_sent, identity.sent_count = now, identity.sent_count + 1
    identity.language = language
    identity.save()
    # No EmailLog: OTP plaintext must not be retained. Delivery failure rolls back issuance.
    ko = language == 'ko'
    send_mail(email, 'itriX 관리자 인증 코드' if ko else 'itriX admin sign-in code',
        [f'{code}', '5분간 유효하며 한 번만 사용할 수 있습니다.' if ko else 'Valid for 5 minutes. Use once.',
         f'{now.isoformat()} · IP: {ip(request) or "unknown"}',
         '요청하지 않았다면 이 메일을 무시하세요.' if ko else 'Ignore this email if you did not request it.'])


def verify_code(request, email, code):
    email = email.strip().lower()
    token = None
    with transaction.atomic():
        identity = AdminIdentity.objects.select_for_update().filter(email=email).first()
        now = timezone.now()
        if email not in allowed() or not identity:
            raise PermissionDenied('Invalid or expired code.')
        if identity.locked_until and identity.locked_until > now:
            raise Throttled(detail='Please try again in 15 minutes.')
        valid = bool(identity.code_hash and identity.code_expires and identity.code_expires > now and
                     len(code) == 6 and code.isdigit() and check_password(code, identity.code_hash))
        if not valid:
            identity.failures += 1
            if identity.failures >= 5:
                identity.locked_until = now + timedelta(minutes=15)
                identity.code_hash = ''
                identity.failures = 0
            identity.save()
        else:
            identity.code_hash, identity.failures, identity.last_login = '', 0, now
            identity.locked_until = None
            identity.save()
            token = secrets.token_urlsafe(48)
            AdminSession.objects.create(token_hash=digest(token), identity=identity)
            audit(request, email, 'sign_in')
    # Raise outside atomic: incorrect attempts and lockouts must persist.
    if not token:
        raise PermissionDenied('Invalid or expired code.')
    return token


def session(request, touch=False):
    token = request.headers.get('X-Website-Session', '')
    obj = AdminSession.objects.select_related('identity').filter(token_hash=digest(token)).first() if token else None
    if not obj or obj.identity_id not in allowed() or obj.last_activity <= timezone.now() - timedelta(minutes=30):
        if obj:
            obj.delete()
        raise PermissionDenied('Session expired. Sign in again.')
    if touch:
        obj.last_activity = timezone.now()
        obj.save(update_fields=['last_activity'])
    return obj


def captcha(token, remote_ip):
    secret = getattr(settings, 'WEBSITE_TURNSTILE_SECRET', '')
    if not secret or not token:
        raise ValidationError({'captcha': 'Spam protection is unavailable or incomplete. Please contact itriX.'})
    try:
        result = requests.post('https://challenges.cloudflare.com/turnstile/v0/siteverify',
            data={'secret': secret, 'response': token, 'remoteip': remote_ip or ''}, timeout=8).json()
    except (requests.RequestException, ValueError):
        raise ValidationError({'captcha': 'Spam check failed. Please try again.'})
    hosts = {h.strip() for h in settings.WEBSITE_CAPTCHA_HOSTS.split(',') if h.strip()}
    if not result.get('success') or result.get('hostname') not in hosts or result.get('action') != 'website_intake':
        raise ValidationError({'captcha': 'Spam check failed. Please try again.'})


def subscription_token(sub):
    return signing.dumps({'id': str(sub.pk)}, salt='website-newsletter')


def get_subscription(token):
    try:
        data = signing.loads(token, salt='website-newsletter', max_age=60 * 60 * 24 * 365)
        return Subscription.objects.get(pk=data['id'])
    except (signing.BadSignature, Subscription.DoesNotExist, KeyError, ValueError):
        raise ValidationError('Invalid or expired subscription link.')


def deliver_outbox(limit=100):
    ids = Outbox.objects.filter(sent_at__isnull=True, submission__deleted_at__isnull=True).order_by('pk').values_list('pk', flat=True)[:limit]
    for pk in list(ids):
        with transaction.atomic():
            item = Outbox.objects.select_for_update().select_related('submission').get(pk=pk)
            if item.sent_at:
                continue
            s = item.submission
            item.attempts += 1
            ko = s.language == 'ko'
            base = settings.WEBSITE_PUBLIC_URL.rstrip('/')
            if item.role == 'admin':
                paragraphs = [f'{s.reference} · {s.kind}', s.company, s.created_at.isoformat(), 'A new submission is ready for review.']
                button = ('Dashboard', base + '/itx-console-7k2m')
                subject = f'itriX · {s.reference}'
            else:
                subject = ('itriX 접수 확인 · ' if ko else 'itriX request received · ') + s.reference
                paragraphs = [subject, s.company, s.fields.get('use') or s.fields.get('message') or 'ASTOP Store availability',
                    ('접수 검토 → 담당자 확인 → 다음 단계 안내' if ko else 'We will review your request, confirm the right contact, and agree the next step.') if s.kind == 'poc' else
                    ('영업일 기준 2일 이내에 회신드리겠습니다.' if ko else 'We aim to reply within two business days.')]
                button = ('Ask X', base + ('/' if ko else '/en') + '#ask-chat')
            try:
                send_mail(item.recipient, subject, paragraphs, button)
                item.sent_at = timezone.now()
            except Exception:
                # No provider response/PII in logs; failed records remain retryable.
                pass
            item.save(update_fields=['attempts', 'sent_at'])
