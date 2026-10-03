"""Read-only ledger inspection. Workflow services are the only normal write path."""
from django.contrib import admin
from apps.core.admin import ItrixModelAdmin
from . import models

class LedgerAdmin(ItrixModelAdmin):
    list_display = ('id', 'created_at', 'updated_at')
    search_fields = ('id',)
    def get_readonly_fields(self, request, obj=None):
        return tuple(field.name for field in self.model._meta.fields)
    def has_add_permission(self, request):
        return False
    def has_delete_permission(self, request, obj=None):
        return False
    def has_change_permission(self, request, obj=None):
        return False

for model in (models.LegalRelease, models.VerifiedIdentity, models.Order, models.License,
              models.Seat, models.Activation, models.Delivery, models.Refund, models.Branch,
              models.Reward, models.PaymentEvent, models.CommerceAudit):
    admin.site.register(model, LedgerAdmin)
