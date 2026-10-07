from datetime import timedelta
import pytest
from django.core.exceptions import ValidationError
from django.utils import timezone
from apps.commerce import services as s, membership as m
from apps.commerce.models import TrialEnrollment, PaymentEvent, Reward, Order, RenewalRecord
from tests.test_commerce.test_commerce import Adapter, buyer
from tests.factories.user_factory import AdminUserFactory

pytestmark = pytest.mark.django_db

class MembershipAdapter(Adapter):
    capabilities = m.CAPABILITIES
    def checkout_membership(self, **kwargs):
        assert kwargs['interval'] == 'year' and kwargs['automatic_renewal']
        return 'https://example.test/checkout'
    def cancel_renewal(self, **kwargs):
        return True
    def verify_webhook(self, *args):
        return {'verified': False}

@pytest.fixture
def launch(settings, monkeypatch):
    settings.ASTOP_MEMBERSHIP_LAUNCH_APPROVED = True
    monkeypatch.setattr(s, 'adapter', lambda: MembershipAdapter())
    actor = AdminUserFactory()
    for kind in ('lo', 'trial'):
        s.publish_legal(kind=kind, policy=m.POLICY, version='approved-test', body='Approved exact annual/trial terms.', actor=actor)
    return actor


def trial(actor, **kwargs):
    c = buyer(actor, kwargs.get('kind', 'individual'))
    t = m.enroll(client=c, kind=kwargs.get('kind', 'individual'), seats=kwargs.get('seats', 1),
        legal_hash=s.active_legal('trial').sha256, session='trial-consent')
    return c,t


def mature(t):
    t.starts_at -= timedelta(days=8)
    t.ends_at -= timedelta(days=8)
    t.save()


def joined(actor):
    c,t=trial(actor);mature(t)
    o=s.quote(client=c,kind='individual',seats=1,trial=t)
    s.accept_order(order_id=o.pk,client=c,legal_hash=o.legal_hash,session='annual-consent',authorize_renewal=True)
    s.record_payment(order_id=o.pk,provider_id=str(o.pk),payment_reference=str(o.pk),amount='20',currency='USD',payload_hash='payment')
    o.refresh_from_db()
    return c,t,o


def test_legacy_adapter_or_unapproved_terms_cannot_launch(launch, monkeypatch, settings):
    assert m.ready()
    monkeypatch.setattr(s,'adapter',lambda:Adapter())
    assert not m.ready()
    settings.ASTOP_MEMBERSHIP_LAUNCH_APPROVED=False
    with pytest.raises(ValidationError):m.trial_terms()


def test_trial_has_no_payment_or_rewards_and_cannot_be_charged_early(launch):
    c,t=trial(launch)
    assert t.ends_at-t.starts_at==timedelta(days=7)
    assert t.license.order.amount==0 and t.license.order.status=='trial'
    assert not PaymentEvent.objects.exists() and not Reward.objects.exists()
    with pytest.raises(ValidationError):s.quote(client=c,kind='individual',seats=1,trial=t)
    with pytest.raises(ValidationError):s.record_payment(order_id=t.license.order_id,provider_id='fake',payment_reference='fake',amount=0,currency='USD',payload_hash='fake')


def test_trial_activation_never_outlives_trial_and_expiry_blocks_delivery(launch):
    c,t=trial(launch)
    a,_=s.activate(license_id=t.license_id,client=c,environment_hash='a'*64)
    assert a.valid_until==t.ends_at
    t.license.ends_at=timezone.now()-timedelta(seconds=1);t.license.save()
    for fn,extra in ((s.activate,{'environment_hash':'a'*64}),(s.deliver,{'platform':'macos-arm64'})):
        with pytest.raises(ValidationError):fn(license_id=t.license_id,client=c,**extra)


def test_join_requires_explicit_renewal_consent_and_preserves_trial_evidence(launch):
    c,t=trial(launch);mature(t)
    o=s.quote(client=c,kind='individual',seats=1,trial=t)
    with pytest.raises(ValidationError):s.accept_order(order_id=o.pk,client=c,legal_hash=o.legal_hash,session='yes')
    assert o.refund_days==14 and o.purpose=='annual'
    assert t.license.order.purpose=='trial'


def test_duplicate_counterparty_trial_is_rejected(launch):
    c,t=trial(launch)
    with pytest.raises(ValidationError):m.enroll(client=c,kind='individual',seats=1,legal_hash=s.active_legal('trial').sha256,session='again')
    assert TrialEnrollment.objects.count()==1


def test_join_is_idempotent_and_cannot_convert_twice(launch):
    c,t,o=joined(launch)
    s.record_payment(order_id=o.pk,provider_id=str(o.pk),payment_reference=str(o.pk),amount=20,currency='USD',payload_hash='payment')
    t.refresh_from_db()
    assert t.joined_order_id==o.pk and o.license.entitlement_kind=='annual'
    assert o.license.ends_at==m.next_year(o.paid_at)
    with pytest.raises(ValidationError):s.quote(client=c,kind='individual',seats=1,trial=t)


def test_annual_refund_window_is_14_days_and_original_order_is_immutable(launch):
    c,t,o=joined(launch)
    o.paid_at=timezone.now()-timedelta(days=15);o.save()
    with pytest.raises(ValidationError):s.request_refund(order_id=o.pk,client=c,reason='No fit')
    assert o.refund_days==14


def test_cancel_preserves_paid_access_and_blocks_future_recurring_capture(launch):
    c,t,o=joined(launch)
    license=m.cancel(license_id=o.license.pk,client=c)
    m.sync_cancellation(license)
    assert license.status=='active' and not license.auto_renew
    assert s.deliver(license_id=license.pk,client=c,platform='macos-arm64')
    with pytest.raises(ValidationError):m.record_renewal({'license_id':license.pk,'id':'renewal'},'x')


def test_renewal_has_own_payment_and_refund_review(launch):
    c,t,o=joined(launch)
    license=o.license;license.ends_at=timezone.now()-timedelta(seconds=1);license.save()
    event=dict(license_id=license.pk,id='renew-1',payment_reference='renew-pay-1',period_start=license.ends_at.isoformat(),license_fee='20',currency='USD')
    row=m.record_renewal(event,'renew-hash')
    assert m.record_renewal(event,'renew-hash').pk==row.pk and RenewalRecord.objects.count()==1
    row=m.request_renewal_refund(renewal_id=row.pk,client=c,reason='No longer useful')
    assert row.refund_status=='requested'
    row=m.approve_renewal_refund(renewal_id=row.pk,actor=launch)
    assert row.refund_status=='repayment_pending'
    assert m.repay_renewal_refund(row.pk).refund_status=='repaid'
    o.refresh_from_db();assert o.payment_reference==str(o.pk)


def test_api_cannot_bypass_trial_or_use_someone_elses_license(launch,api_client):
    c,t=trial(launch)
    other=buyer(launch)
    api_client.force_authenticate(user=other)
    assert api_client.post(f'/api/v1/commerce/licenses/{t.license_id}/cancel-renewal/',{},format='json').status_code==409
    api_client.force_authenticate(user=c)
    assert api_client.post('/api/v1/commerce/orders/',{'kind':'individual','seats':1},format='json').status_code==400


def test_cancellation_failure_is_durable_and_retryable(launch, monkeypatch):
    c,t,o=joined(launch)
    monkeypatch.setattr(MembershipAdapter, 'cancel_renewal', lambda *args, **kwargs: False)
    license=m.cancel(license_id=o.license.pk,client=c)
    with pytest.raises(ValidationError):m.sync_cancellation(license)
    license.refresh_from_db()
    assert not license.auto_renew and license.cancelled_at
    monkeypatch.setattr(MembershipAdapter, 'cancel_renewal', lambda *args, **kwargs: True)
    assert m.cancel(license_id=license.pk,client=c).pk==license.pk
    m.sync_cancellation(license)


def test_stale_terms_no_identity_and_wrong_customer_cannot_enroll_or_join(launch):
    c=buyer(launch)
    with pytest.raises(ValidationError):m.enroll(client=c,kind='individual',seats=1,legal_hash='wrong',session='x')
    assert not TrialEnrollment.objects.exists()
    owner,t=trial(launch);mature(t)
    with pytest.raises(ValidationError):s.quote(client=c,kind='individual',seats=1,trial=t)
    with pytest.raises(ValidationError):s.quote(client=owner,kind='organization',seats=2,trial=t)


def test_chat_state_is_account_scoped_and_never_disclosed_on_public_plane(launch):
    from apps.agents.services.context import AgentContext
    c,t=trial(launch)
    assert m.conversation_state(AgentContext(client_id=str(c.pk),plane='public'))==''
    state=m.conversation_state(AgentContext(client_id=str(c.pk),plane='client'))
    assert 'trial in progress' in state and c.email not in state
    other=buyer(launch)
    assert 'No ASTOP trial' in m.conversation_state(AgentContext(client_id=str(other.pk),plane='client'))
