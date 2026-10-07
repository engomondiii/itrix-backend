"""Trial-first annual membership. No payment or protected access without launch gates.

Production adapters must implement the documented v1.6 lifecycle contract. No fake
signer, payment provider or reviewed legal text is supplied by this module.
"""
from datetime import timedelta
from decimal import Decimal
from django.conf import settings
from django.db import transaction
from django.utils import timezone
from . import services as s
from .models import LegalRelease, License, Order, Seat, TrialEnrollment, RenewalRecord

POLICY = 'annual_v1_6'
CAPABILITIES = {'trial_delivery', 'asymmetric_entitlements', 'annual_checkout',
                'annual_renewal', 'renewal_notice', 'cancel_renewal', 'renewal_refund'}


def next_year(value):
    try:
        return value.replace(year=value.year + 1)
    except ValueError:  # Leap-day anniversaries use the last valid day of February.
        return value.replace(year=value.year + 1, day=28)


def ready():
    if not getattr(settings, 'ASTOP_MEMBERSHIP_LAUNCH_APPROVED', False):
        return False
    if not all(LegalRelease.objects.filter(kind=k, policy=POLICY, active=True).exists() for k in ('lo', 'trial')):
        return False
    try:
        provider = s.adapter()
        return CAPABILITIES <= set(getattr(provider, 'capabilities', ())) and all(
            callable(getattr(provider, method, None)) for method in
            ('checkout_membership', 'cancel_renewal', 'sign_activation', 'delivery', 'verify_webhook', 'refund'))
    except Exception:
        return False


def require_ready():
    s.require(ready(), 'Trial and membership access are not available yet. Approved terms and production services are required.')


def require_entitlement(license):
    s.require(license.status == 'active', 'Active entitlement required.')
    if license.entitlement_kind != 'legacy':
        require_ready()
        s.require(license.ends_at and timezone.now() < license.ends_at, 'Entitlement expired; new access requires a valid trial or paid membership.')


def require_join(trial, client):
    require_ready()
    s.require(trial.client_id == client.pk and not trial.joined_order_id and
              timezone.now() >= trial.ends_at and trial.license.status == 'active',
              'Join is available only after the full seven-day trial and before any previous conversion.')


def trial_terms():
    require_ready()
    legal = s.active_legal('trial')
    s.require(legal.policy == POLICY, 'Current trial terms required.')
    return {'body': legal.body, 'sha256': legal.sha256, 'version': legal.version}


@transaction.atomic
def enroll(*, client, kind, seats, legal_hash, session):
    require_ready()
    identity = s.current_identity(client, kind)
    s.require(type(seats) is int and ((kind == 'individual' and seats == 1) or
              (kind == 'organization' and 2 <= seats <= 10000)), 'Invalid named-seat scope.')
    legal = s.active_legal('trial')
    s.require(legal.policy == POLICY and legal_hash == legal.sha256 and session, 'Accept the exact approved trial terms.')
    keys = ('legal_name', 'country', 'registration_number' if kind == 'organization' else 'address')
    identity_key = s.digest('|'.join(str(identity.details[k]).strip().casefold() for k in keys))
    s.require(not TrialEnrollment.objects.filter(identity_key=identity_key).exists(), 'This verified counterparty has already enrolled. Contact support for an exception review.')
    now = timezone.now()
    order = Order.objects.create(client=client, kind=kind, seats=seats, purpose='trial', refund_days=0,
        amount=0, identity_snapshot=dict(identity.details, email=client.email, verified_at=identity.verified_at.isoformat()),
        legal=legal, legal_body=legal.body, legal_hash=legal.sha256, accepted_at=now,
        acceptance_session_hash=s.digest(session), status='trial')
    license = License.objects.create(order=order, entitlement_kind='trial', starts_at=now, ends_at=now + timedelta(days=7))
    if kind == 'individual':
        Seat.objects.create(license=license, email=client.email.strip().lower())
    trial = TrialEnrollment.objects.create(client=client, identity_key=identity_key, license=license,
        starts_at=now, ends_at=license.ends_at)
    s.audit('trial_enrolled', trial, client)
    return trial


def checkout(order):
    require_ready()
    s.require(order.purpose == 'annual' and order.status == 'accepted' and order.recurring_authorized_at,
              'Accepted annual membership and recurring authorization required.')
    require_join(order.trial, order.client)
    url = s.adapter().checkout_membership(order_id=str(order.pk), amount=str(order.amount), currency='USD',
        interval='year', automatic_renewal=True, legal_hash=order.legal_hash,
        # Provider must not create/charge a subscription more than once for an order.
        idempotency_key=str(order.pk))
    s.require(isinstance(url, str) and url.startswith('https://'), 'Payment provider unavailable.')
    return url


@transaction.atomic
def cancel(*, license_id, client):
    license = License.objects.select_for_update().select_related('order').get(pk=license_id, order__client=client)
    s.require(license.entitlement_kind == 'annual', 'Annual membership required.')
    if license.cancelled_at:
        return license
    # Persist the stop first. Provider cancellation is retriable via the same idempotency key.
    license.auto_renew = False
    license.cancelled_at = timezone.now()
    license.save()
    s.audit('renewal_cancel_requested', license, client)
    return license


def sync_cancellation(license):
    s.require(s.adapter().cancel_renewal(license_id=str(license.pk), order_id=str(license.order_id),
        idempotency_key=f'cancel:{license.pk}') is True, 'Cancellation recorded; provider confirmation pending. Contact support if it persists.')
    s.audit('renewal_cancel_confirmed', license)


@transaction.atomic
def record_renewal(event, payload_hash):
    """Only a verified provider webhook enters here; dates/price are calculated server-side."""
    require_ready()
    license = License.objects.select_for_update().select_related('order').get(pk=event['license_id'])
    prior = RenewalRecord.objects.filter(provider_id=event['id']).first()
    if prior:
        s.require(prior.license_id == license.pk and prior.payload_hash == payload_hash, 'Conflicting renewal event.')
        return prior
    s.require(license.entitlement_kind == 'annual' and license.status == 'active' and
        license.auto_renew and not license.cancelled_at and license.order.recurring_authorized_at,
        'Recurring authorization is not active; reconcile any captured funds with the provider.')
    s.require(license.ends_at and timezone.now() >= license.ends_at, 'Renewal is not due.')
    s.require(event.get('period_start') == license.ends_at.isoformat() and
        Decimal(str(event['license_fee'])) == license.order.amount and event['currency'] == 'USD' and
        event.get('payment_reference'), 'Renewal period, amount or currency mismatch.')
    start = license.ends_at
    end = next_year(start)
    s.require(end > timezone.now(), 'Overdue membership needs explicit rejoin review.')
    row = RenewalRecord.objects.create(license=license, provider_id=event['id'], payload_hash=payload_hash,
        payment_reference=event['payment_reference'], period_start=start, period_end=end,
        paid_at=timezone.now(), amount=license.order.amount)
    license.ends_at = end
    license.save()
    s.audit('membership_renewed', license)
    return row


@transaction.atomic
def request_renewal_refund(*, renewal_id, client, reason):
    row = RenewalRecord.objects.select_for_update().get(pk=renewal_id, license__order__client=client)
    s.require(timezone.now() <= row.paid_at + timedelta(days=14) and isinstance(reason, str) and reason.strip(), 'A reason and payment within the 14-day request window are required; statutory rights remain applicable.')
    if not row.refund_status:
        row.refund_status, row.refund_reason = 'requested', str(reason).strip()[:4000]
        row.save()
        s.audit('renewal_refund_requested', row, client)
    return row


@transaction.atomic
def approve_renewal_refund(*, renewal_id, actor):
    row = RenewalRecord.objects.select_for_update().select_related('license__order').get(pk=renewal_id)
    s.require(row.refund_status == 'requested', 'Refund is not awaiting review.')
    s.revoke_order(order=row.license.order, reason='renewal_refund_approved')
    row.refund_status = 'repayment_pending'
    row.save()
    s.audit('renewal_refund_approved', row, actor)
    return row


def repay_renewal_refund(renewal_id):
    row = RenewalRecord.objects.get(pk=renewal_id, refund_status='repayment_pending')
    reference = s.adapter().refund(payment_reference=row.payment_reference, amount=str(row.amount),
        currency='USD', idempotency_key=f'renewal-refund:{row.pk}')
    s.require(reference, 'Provider has not confirmed repayment.')
    with transaction.atomic():
        row = RenewalRecord.objects.select_for_update().get(pk=row.pk)
        if row.refund_status == 'repayment_pending':
            row.refund_status = 'repaid'
            row.save()
            s.audit('renewal_refund_repaid', row)
    return row


def conversation_state(ctx):
    """Minimal account-owned facts; never infer membership from chat or visitor IDs."""
    if ctx.plane != 'client' or not ctx.client_id:
        return ''
    trial = TrialEnrollment.objects.filter(client_id=ctx.client_id).first()
    licenses = License.objects.filter(order__client_id=ctx.client_id, entitlement_kind='annual').order_by('-created_at')[:3]
    facts = []
    if trial:
        state = 'joined' if trial.joined_order_id else ('trial in progress' if timezone.now() < trial.ends_at else 'trial complete; may review Join')
        facts.append(f'Trial: {state}; expiry {trial.ends_at.isoformat()}.')
    for license in licenses:
        state = license.status if license.ends_at and timezone.now() < license.ends_at else 'expired'
        facts.append(f'Annual membership: {state}; paid-through {license.ends_at}; automatic renewal {license.auto_renew}.')
    if not facts:
        return 'No ASTOP trial or annual membership is recorded for this authenticated account.'
    return ' '.join(facts) + ' These account facts do not establish workload proof or permit actions without user authorization.'
