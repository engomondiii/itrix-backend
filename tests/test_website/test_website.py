from datetime import timedelta
from unittest.mock import patch
import pytest
from django.test import override_settings
from django.utils import timezone
from rest_framework.test import APIClient
from apps.website.models import AdminIdentity, AdminSession, Submission, Outbox, Notice
from apps.website.services import digest

pytestmark = pytest.mark.django_db


def api():
    return APIClient()


def admin():
    identity = AdminIdentity.objects.create(email='admin@itrix.co.kr')
    AdminSession.objects.create(identity=identity, token_hash=digest('session'))
    client = api()
    client.credentials(HTTP_X_WEBSITE_SESSION='session')
    return client


def test_store_urls_require_explicit_confirmation():
    with override_settings(ASTOP_APPLE_STORE_URL='https://apps.apple.com/us/app/astop/id123', ASTOP_APPLE_STORE_CONFIRMED=False):
        data = api().get('/api/v1/website/config/').json()['store']
        assert data['state'] == 'pre_launch' and data['stores'][0]['url'] is None
    with override_settings(ASTOP_APPLE_STORE_URL='https://evil.example/app', ASTOP_APPLE_STORE_CONFIRMED=True):
        assert api().get('/api/v1/website/config/').json()['store']['stores'][0]['url'] is None
    with override_settings(ASTOP_APPLE_STORE_URL='https://apps.apple.com/us/app/astop/id123', ASTOP_APPLE_STORE_CONFIRMED=True):
        assert api().get('/api/v1/website/config/').json()['store']['stores'][0]['available'] is True
    assert api().get('/api/v1/commerce/availability/').json()['checkout_available'] is False


@override_settings(ENABLE_EMAIL_DELIVERY=True)
def test_otp_single_use_hash_lock_and_expiry():
    c = api()
    with patch('apps.website.services.send_mail') as mail, patch('apps.website.services.secrets.randbelow', return_value=321987):
        assert c.post('/api/v1/website/auth/request/', {'email':' ADMIN@itrix.co.kr ', 'language':'en'}).status_code == 200
        identity = AdminIdentity.objects.get()
        assert '321987' not in identity.code_hash and mail.call_count == 1
        assert c.post('/api/v1/website/auth/request/', {'email':'admin@itrix.co.kr'}).status_code == 429
        response = c.post('/api/v1/website/auth/verify/', {'email':'admin@itrix.co.kr','code':'321987'})
        assert response.status_code == 200
        failed = c.post('/api/v1/website/auth/verify/', {'email':'admin@itrix.co.kr','code':'321987'})
        assert failed.status_code == 403
        assert int(failed.data['error']['fields']['remaining_attempts']) == 4
        for _ in range(4):
            failed = c.post('/api/v1/website/auth/verify/', {'email':'admin@itrix.co.kr','code':'000000'})
        assert failed.data['error']['fields']['reason'] == 'locked'
        assert int(failed.data['error']['fields']['remaining_attempts']) == 0
        identity.refresh_from_db()
        assert identity.locked_until > timezone.now()
        assert c.post('/api/v1/website/auth/verify/', {'email':'admin@itrix.co.kr','code':'321987'}).status_code == 429


def test_idle_and_allowlist_enforced_server_side():
    c = admin()
    assert c.get('/api/v1/website/admin/records/').status_code == 200
    AdminSession.objects.update(last_activity=timezone.now()-timedelta(minutes=31))
    assert c.get('/api/v1/website/admin/records/').status_code == 403
    assert api().get('/api/v1/website/admin/logs/').status_code == 403


@override_settings(WEBSITE_INTAKE_ENABLED=True)
@patch('apps.website.services.captcha')
def test_intake_reference_consent_outbox_and_deletion(captcha):
    c = api()
    payload = {'kind':'poc','language':'en','company':'Example','name':'Test','email':'test@example.com',
      'fields':{'use':'Inference'},'privacy':True,'newsletter':True,'privacy_version':'draft-20261016',
      'captcha':'token','request_id':'00000000-0000-4000-8000-000000000001'}
    response = c.post('/api/v1/website/intake/',payload,format='json')
    assert response.status_code == 201, response.data
    assert response.data['reference'].startswith('P-')
    obj = Submission.objects.get()
    assert obj.privacy_at and obj.newsletter_at and Outbox.objects.count()==3
    assert c.post('/api/v1/website/intake/',payload,format='json').status_code == 200
    assert Submission.objects.count()==1
    staff=admin()
    assert staff.post(f'/api/v1/website/admin/records/{obj.pk}/',{'action':'delete','confirm':True},format='json').status_code == 200
    obj.refresh_from_db()
    assert obj.email == '' and obj.fields == {} and not Outbox.objects.exists()


def test_notice_rejects_external_store_link_and_requires_session():
    data={'enabled':True,'starts_at':None,'ends_at':None,'content':{l:{'label':'News','title':'Title','intro':'Hello','rows':[],'button':'Go','link':'https://apps.apple.com/app'} for l in ('ko','en')}}
    c=admin()
    assert c.post('/api/v1/website/admin/notice/',data,format='json').status_code==400
    for v in data['content'].values():v['link']='/poc'
    assert c.post('/api/v1/website/admin/notice/',data,format='json').status_code==200
    assert api().get('/api/v1/website/config/').json()['notice']['en']['title']=='Title'


def test_website_models_are_not_exposed_to_legacy_staff_admin():
    from django.apps import apps
    from django.contrib import admin as django_admin
    assert all(model not in django_admin.site._registry for model in apps.get_app_config('website').get_models())


@override_settings(ENABLE_EMAIL_DELIVERY=True)
def test_reissued_and_expired_codes_cannot_create_sessions():
    c = api()
    with patch('apps.website.services.send_mail'), patch('apps.website.services.secrets.randbelow', side_effect=[111111, 222222]):
        assert c.post('/api/v1/website/auth/request/', {'email':'admin@itrix.co.kr'}).status_code == 200
        AdminIdentity.objects.update(last_sent=timezone.now()-timedelta(minutes=2))
        assert c.post('/api/v1/website/auth/request/', {'email':'admin@itrix.co.kr'}).status_code == 200
        assert c.post('/api/v1/website/auth/verify/', {'email':'admin@itrix.co.kr','code':'111111'}).status_code == 403
        AdminIdentity.objects.update(code_expires=timezone.now()-timedelta(seconds=1))
        assert c.post('/api/v1/website/auth/verify/', {'email':'admin@itrix.co.kr','code':'222222'}).status_code == 403
        assert not AdminSession.objects.exists()


def test_session_is_revoked_when_allowlist_changes():
    c = admin()
    with override_settings(WEBSITE_ADMIN_EMAILS='associate@iwl.kr'):
        assert c.get('/api/v1/website/admin/records/').status_code == 403
    assert not AdminSession.objects.exists()


def test_passive_reads_do_not_extend_session_and_language_is_saved():
    c = admin()
    before = timezone.now()-timedelta(minutes=20)
    AdminSession.objects.update(last_activity=before)
    assert c.get('/api/v1/website/admin/session/').status_code == 200
    assert AdminSession.objects.get().last_activity == before
    assert c.post('/api/v1/website/admin/session/', {'language':'en'}).status_code == 200
    assert AdminIdentity.objects.get().language == 'en'
    assert AdminSession.objects.get().last_activity > before


def test_store_hosts_alone_do_not_authorize_non_listing_urls():
    from apps.website.policy import store_policy
    for url in ['https://www.microsoft.com/', 'https://www.microsoft.com/security', 'https://apps.microsoft.com/?redirect=evil', 'https://apps.apple.com/us/']:
        with override_settings(ASTOP_APPLE_STORE_CONFIRMED=True,ASTOP_MICROSOFT_STORE_CONFIRMED=True,ASTOP_APPLE_STORE_URL=url,ASTOP_MICROSOFT_STORE_URL=url):
            assert all(not item['available'] for item in store_policy()['stores'])
    with override_settings(ASTOP_MICROSOFT_STORE_CONFIRMED=True,ASTOP_MICROSOFT_STORE_URL='https://apps.microsoft.com/detail/9TESTASTOP'):
        assert store_policy()['stores'][1]['available']


def test_signed_subscription_lifecycle_and_invalid_token():
    from apps.website.models import Subscription
    from apps.website.services import subscription_token
    obj=Subscription.objects.create(email='test@example.invalid')
    token=subscription_token(obj)
    assert 'test@example' not in token
    c=api()
    assert c.get('/api/v1/website/unsubscribe/',{'token':token}).data['email']=='t***@example.invalid'
    assert c.post('/api/v1/website/unsubscribe/',{'token':token,'subscribe':False},format='json').status_code==200
    obj.refresh_from_db(); assert not obj.subscribed
    assert c.post('/api/v1/website/unsubscribe/',{'token':token,'subscribe':True},format='json').status_code==200
    obj.refresh_from_db(); assert obj.subscribed
    assert c.get('/api/v1/website/unsubscribe/',{'token':token+'changed'}).status_code==400


def test_csv_export_is_scoped_escaped_and_audited():
    from apps.website.models import Audit
    Submission.objects.create(kind='contact',name='Tester',company='=2+2',email='test@example.invalid',privacy_at=timezone.now(),privacy_version='test')
    Submission.objects.create(kind='poc',name='Hidden',company='Other',email='other@example.invalid',privacy_at=timezone.now(),privacy_version='test')
    c=admin()
    response=c.post('/api/v1/website/admin/export/?kind=contact',{'confirm':True},format='json')
    assert response.status_code==200
    text=response.content.decode('utf-8-sig')
    assert "'=2+2" in text and 'other@example.invalid' not in text
    assert response.content.startswith(b'\xef\xbb\xbf')
    assert Audit.objects.filter(action='csv_export',actor='admin@itrix.co.kr').exists()


def test_admin_alert_does_not_include_applicant_contact_or_message():
    from apps.website.services import deliver_outbox
    obj=Submission.objects.create(kind='contact',name='Private Person',email='private@example.invalid',company='Example Company',fields={'message':'Private inquiry text'},privacy_at=timezone.now(),privacy_version='test')
    Outbox.objects.create(submission=obj,recipient='admin@itrix.co.kr',role='admin')
    with patch('apps.website.services.send_mail') as mail:
        deliver_outbox()
    text=' '.join(mail.call_args.args[2])
    assert 'Example Company' in text and obj.reference in text
    assert 'Private Person' not in text and obj.email not in text and 'Private inquiry text' not in text
    assert Outbox.objects.get().sent_at


def test_mail_failure_remains_retryable():
    from apps.website.services import deliver_outbox
    obj=Submission.objects.create(kind='contact',name='Test',email='test@example.invalid',privacy_at=timezone.now(),privacy_version='test')
    Outbox.objects.create(submission=obj,recipient=obj.email,role='applicant')
    with patch('apps.website.services.send_mail',side_effect=RuntimeError('test outage')):deliver_outbox()
    assert Outbox.objects.get().sent_at is None and Outbox.objects.get().attempts==1
    with patch('apps.website.services.send_mail'):deliver_outbox()
    assert Outbox.objects.get().sent_at and Outbox.objects.get().attempts==2
