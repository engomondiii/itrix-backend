"""Retry provider cancellation for annual memberships whose future authority stopped."""
from django.core.management.base import BaseCommand, CommandError
from apps.commerce.models import License
from apps.commerce.membership import sync_cancellation

class Command(BaseCommand):
    help = 'Reconcile cancelled/revoked memberships with the configured payment provider (idempotent).'

    def handle(self, *args, **options):
        from django.db.models import Q
        failures = 0
        for license in License.objects.filter(entitlement_kind='annual', auto_renew=False).filter(
            Q(cancelled_at__isnull=False) | Q(status__in=['revoked', 'suspended'])):
            try:
                sync_cancellation(license)
            except Exception:
                failures += 1
                self.stderr.write(f'Provider cancellation pending for license {license.pk}')
        if failures:
            raise CommandError(f'{failures} provider cancellation(s) pending; retry and review provider state.')
        self.stdout.write('Membership cancellation reconciliation completed.')
