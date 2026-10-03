from django.urls import path
from .views import (AvailabilityView, BranchView, LicensesView, LicenseActionView,
                    OperatorView, OrderActionView, OrdersView, PaymentWebhookView)
urlpatterns = [
    path('availability/', AvailabilityView.as_view()),
    path('orders/', OrdersView.as_view()),
    path('orders/<uuid:order_id>/<str:action>/', OrderActionView.as_view()),
    path('licenses/', LicensesView.as_view()),
    path('licenses/<uuid:license_id>/<str:action>/', LicenseActionView.as_view()),
    path('branch/', BranchView.as_view()),
    path('provider-events/', PaymentWebhookView.as_view()),
    path('operations/', OperatorView.as_view()),
]
