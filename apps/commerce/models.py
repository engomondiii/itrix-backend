from django.db import models
from django.core.exceptions import ValidationError
from apps.core.models import BaseModel


class LegalRelease(BaseModel):
    """An immutable, reviewed document, stored privately rather than in public Git."""
    kind = models.CharField(max_length=16, choices=[('lo', 'License Order'), ('branch', 'Branch Agreement'), ('trial', 'Trial terms')])
    policy = models.CharField(max_length=24, default='legacy')
    version = models.CharField(max_length=40)
    body = models.TextField()
    sha256 = models.CharField(max_length=64)
    approved_at = models.DateTimeField()
    approved_by = models.ForeignKey('authentication.User', on_delete=models.PROTECT)
    active = models.BooleanField(default=False)

    def save(self, *args, **kwargs):
        if not self._state.adding:
            original = type(self).objects.get(pk=self.pk)
            fields = ('kind', 'policy', 'version', 'body', 'sha256', 'approved_at', 'approved_by_id')
            if any(getattr(self, key) != getattr(original, key) for key in fields):
                raise ValidationError('Published legal evidence is immutable; publish a new version.')
        return super().save(*args, **kwargs)

    class Meta:
        constraints = [models.UniqueConstraint(fields=['kind', 'version'], name='commerce_legal_version')]


class VerifiedIdentity(BaseModel):
    client = models.OneToOneField('clients.Client', on_delete=models.PROTECT)
    kind = models.CharField(max_length=16, choices=[('individual', 'Individual'), ('organization', 'Organization')])
    # Minimal verified legal fields only; never identity-document images or agent context.
    details = models.JSONField(default=dict)
    verified_email = models.EmailField()
    verified_by = models.ForeignKey('authentication.User', on_delete=models.PROTECT)
    verified_at = models.DateTimeField()


class Order(BaseModel):
    purpose = models.CharField(max_length=16, default='legacy')
    refund_days = models.PositiveSmallIntegerField(default=30)
    trial = models.ForeignKey('TrialEnrollment', null=True, on_delete=models.PROTECT, related_name='orders')
    recurring_authorized_at = models.DateTimeField(null=True)
    client = models.ForeignKey('clients.Client', on_delete=models.PROTECT)
    kind = models.CharField(max_length=16)
    seats = models.PositiveIntegerField()
    currency = models.CharField(max_length=3, default='USD')
    amount = models.DecimalField(max_digits=12, decimal_places=2)
    discount = models.PositiveIntegerField(default=0)
    identity_snapshot = models.JSONField()
    legal = models.ForeignKey(LegalRelease, on_delete=models.PROTECT)
    legal_body = models.TextField()
    legal_hash = models.CharField(max_length=64)
    accepted_at = models.DateTimeField(null=True)
    acceptance_session_hash = models.CharField(max_length=64, blank=True)
    status = models.CharField(max_length=24, default='quoted')
    payment_reference = models.CharField(max_length=200, null=True, unique=True)
    paid_at = models.DateTimeField(null=True)
    # Frozen at checkout: never recompute lineage using later Branch relationships.
    referral = models.ForeignKey('Branch', on_delete=models.PROTECT, null=True, related_name='orders')
    lineage = models.JSONField(default=list)


class License(BaseModel):
    entitlement_kind = models.CharField(max_length=16, default='legacy')
    starts_at = models.DateTimeField(null=True)
    ends_at = models.DateTimeField(null=True)
    auto_renew = models.BooleanField(default=False)
    cancelled_at = models.DateTimeField(null=True)
    order = models.OneToOneField(Order, on_delete=models.PROTECT)
    status = models.CharField(max_length=16, default='active')
    token_version = models.PositiveIntegerField(default=0)
    revoked_at = models.DateTimeField(null=True)


class Seat(BaseModel):
    license = models.ForeignKey(License, on_delete=models.PROTECT, related_name='assignments')
    email = models.EmailField()
    active = models.BooleanField(default=True)

    class Meta:
        constraints = [models.UniqueConstraint(fields=['license', 'email'], condition=models.Q(active=True), name='commerce_active_seat')]


class Activation(BaseModel):
    seat = models.ForeignKey(Seat, on_delete=models.PROTECT)
    environment_hash = models.CharField(max_length=64)
    token_version = models.PositiveIntegerField()
    valid_until = models.DateTimeField()
    last_validated_at = models.DateTimeField(null=True)
    renewal_due_at = models.DateTimeField(null=True)
    revoked_at = models.DateTimeField(null=True)


class Delivery(BaseModel):
    license = models.ForeignKey(License, on_delete=models.PROTECT)
    build_id = models.CharField(max_length=100)
    platform = models.CharField(max_length=32)
    artifact_sha256 = models.CharField(max_length=64)
    signing_identity = models.CharField(max_length=200)


class Refund(BaseModel):
    order = models.OneToOneField(Order, on_delete=models.PROTECT)
    reason = models.TextField()
    status = models.CharField(max_length=24, default='requested')
    approved_at = models.DateTimeField(null=True)
    approved_by = models.ForeignKey('authentication.User', on_delete=models.PROTECT, null=True)
    provider_reference = models.CharField(max_length=200, blank=True)


class Branch(BaseModel):
    client = models.OneToOneField('clients.Client', on_delete=models.PROTECT)
    qualifying_order = models.ForeignKey(Order, on_delete=models.PROTECT, related_name='branch_applications')
    status = models.CharField(max_length=16, default='applied')
    approved_by = models.ForeignKey('authentication.User', on_delete=models.PROTECT, null=True)
    approved_at = models.DateTimeField(null=True)
    agreement = models.ForeignKey(LegalRelease, on_delete=models.PROTECT, null=True)
    agreement_body = models.TextField(blank=True)
    agreement_hash = models.CharField(max_length=64, blank=True)
    acceptance_session_hash = models.CharField(max_length=64, blank=True)
    accepted_at = models.DateTimeField(null=True)
    code = models.CharField(max_length=32, unique=True, null=True)
    parent = models.ForeignKey('self', on_delete=models.PROTECT, null=True)


class Reward(BaseModel):
    order = models.ForeignKey(Order, on_delete=models.PROTECT)
    branch = models.ForeignKey(Branch, on_delete=models.PROTECT)
    level = models.PositiveSmallIntegerField()
    net_base = models.DecimalField(max_digits=12, decimal_places=2)
    # Accrue exactly; round only the final payout, not each level of each sale.
    amount = models.DecimalField(max_digits=16, decimal_places=4)
    eligible_at = models.DateTimeField()
    status = models.CharField(max_length=24, default='pending')
    payout_reference = models.CharField(max_length=200, blank=True)

    class Meta:
        constraints = [models.UniqueConstraint(fields=['order', 'level'], name='commerce_reward_level')]


class PaymentEvent(BaseModel):
    provider_id = models.CharField(max_length=200, unique=True)
    payload_hash = models.CharField(max_length=64)
    order = models.ForeignKey(Order, on_delete=models.PROTECT)
    kind = models.CharField(max_length=24)


class CommerceAudit(BaseModel):
    action = models.CharField(max_length=40)
    subject_id = models.UUIDField()
    actor_id = models.UUIDField(null=True)
    # Identifiers/status only. No private identities, legal text or payment secrets.
    detail = models.JSONField(default=dict)


class JourneyDecision(BaseModel):
    """Append-only customer feedback, never verified proof or shared knowledge."""
    OUTCOMES = [('continue', 'Continue'), ('tune', 'Tune'), ('another_workload', 'Try another workload'),
                ('expand', 'Expand'), ('stop', 'Stop'), ('refund', 'Refund')]
    license = models.ForeignKey(License, on_delete=models.PROTECT)
    client = models.ForeignKey('clients.Client', on_delete=models.PROTECT)
    outcome = models.CharField(max_length=24, choices=OUTCOMES)
    workload = models.CharField(max_length=200)
    comparable = models.BooleanField(default=False)
    fidelity = models.CharField(max_length=16, choices=[('preserved', 'Preserved'), ('failed', 'Failed'), ('unknown', 'Unknown')])
    net_value = models.CharField(max_length=16, choices=[('positive', 'Positive'), ('nonpositive', 'Nonpositive'), ('unknown', 'Unknown')])
    measured_results = models.TextField(blank=True)
    qualitative_feedback = models.TextField()


class TrialEnrollment(BaseModel):
    """One trial per verified account; identity-level duplicate checks in the service."""
    client = models.OneToOneField('clients.Client', on_delete=models.PROTECT)
    identity_key = models.CharField(max_length=64, unique=True)
    license = models.OneToOneField(License, on_delete=models.PROTECT)
    starts_at = models.DateTimeField()
    ends_at = models.DateTimeField()
    joined_order = models.OneToOneField(Order, on_delete=models.PROTECT, null=True, related_name='converted_trial')


class RenewalRecord(BaseModel):
    """Verified recurring captures; original order evidence is never rewritten."""
    license = models.ForeignKey(License, on_delete=models.PROTECT, related_name='renewals')
    provider_id = models.CharField(max_length=200, unique=True)
    payment_reference = models.CharField(max_length=200, unique=True)
    payload_hash = models.CharField(max_length=64)
    period_start = models.DateTimeField()
    period_end = models.DateTimeField()
    amount = models.DecimalField(max_digits=12, decimal_places=2)
    refund_status = models.CharField(max_length=24, blank=True)
    refund_reason = models.TextField(blank=True)
    paid_at = models.DateTimeField()
