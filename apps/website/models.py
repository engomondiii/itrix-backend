"""Website intake is separate from sales-engine conversations and legacy entitlements."""
import uuid
from django.db import models
from django.utils import timezone


class Submission(models.Model):
    kind = models.CharField(max_length=12)  # poc / contact / interest
    language = models.CharField(max_length=2, default='ko')
    company = models.CharField(max_length=200, blank=True)
    name = models.CharField(max_length=200)
    email = models.EmailField()
    fields = models.JSONField(default=dict)
    privacy_at = models.DateTimeField()
    newsletter_at = models.DateTimeField(null=True)
    privacy_version = models.CharField(max_length=80)
    ip = models.GenericIPAddressField(null=True)
    status = models.CharField(max_length=16, default='new')
    read_at = models.DateTimeField(null=True)
    created_at = models.DateTimeField(default=timezone.now, db_index=True)
    deleted_at = models.DateTimeField(null=True)
    request_id = models.UUIDField(default=uuid.uuid4, unique=True)

    @property
    def reference(self):
        return f"{ {'poc': 'P', 'contact': 'C', 'interest': 'I'}[self.kind]}-{self.pk:04d}"


class Note(models.Model):
    submission = models.ForeignKey(Submission, on_delete=models.CASCADE)
    author = models.EmailField()
    text = models.TextField()
    created_at = models.DateTimeField(default=timezone.now)


class Audit(models.Model):
    actor = models.CharField(max_length=254)
    action = models.CharField(max_length=40)
    target = models.CharField(max_length=100, blank=True)
    ip = models.GenericIPAddressField(null=True)
    detail = models.JSONField(default=dict)
    created_at = models.DateTimeField(default=timezone.now, db_index=True)


class AdminIdentity(models.Model):
    email = models.EmailField(primary_key=True)
    code_hash = models.CharField(max_length=256, blank=True)
    code_expires = models.DateTimeField(null=True)
    last_sent = models.DateTimeField(null=True)
    window_start = models.DateTimeField(null=True)
    sent_count = models.PositiveIntegerField(default=0)
    failures = models.PositiveIntegerField(default=0)
    locked_until = models.DateTimeField(null=True)
    last_login = models.DateTimeField(null=True)
    language = models.CharField(max_length=2, default='ko')


class AdminSession(models.Model):
    token_hash = models.CharField(max_length=64, primary_key=True)
    identity = models.ForeignKey(AdminIdentity, on_delete=models.CASCADE)
    last_activity = models.DateTimeField(default=timezone.now, db_index=True)


class Notice(models.Model):
    id = models.PositiveSmallIntegerField(primary_key=True, default=1)
    enabled = models.BooleanField(default=False)
    starts_at = models.DateTimeField(null=True)
    ends_at = models.DateTimeField(null=True)
    content = models.JSONField(default=dict)  # {ko/en: label/title/intro/rows/button/link}
    updated_at = models.DateTimeField(auto_now=True)


class Subscription(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    email = models.EmailField(unique=True)
    language = models.CharField(max_length=2, default='ko')
    subscribed = models.BooleanField(default=True)
    consent_at = models.DateTimeField(default=timezone.now)
    updated_at = models.DateTimeField(auto_now=True)


class Outbox(models.Model):
    """Transactional mail survives transient delivery failure without storing OTP plaintext."""
    submission = models.ForeignKey(Submission, on_delete=models.CASCADE)
    role = models.CharField(max_length=20)  # applicant / admin
    recipient = models.EmailField()
    sent_at = models.DateTimeField(null=True)
    attempts = models.PositiveIntegerField(default=0)
    created_at = models.DateTimeField(default=timezone.now)
