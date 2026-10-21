from django.urls import path
from . import views as v
urlpatterns = [
    path('config/', v.Configuration.as_view()), path('intake/', v.Intake.as_view()),
    path('unsubscribe/', v.Unsubscribe.as_view()), path('auth/<str:action>/', v.SignIn.as_view()),
    path('admin/session/', v.Session.as_view()), path('admin/records/', v.Records.as_view()),
    path('admin/records/<int:pk>/', v.Record.as_view()), path('admin/export/', v.Export.as_view()),
    path('admin/logs/', v.Logs.as_view()), path('admin/accounts/', v.Accounts.as_view()),
    path('admin/notice/', v.NoticeEditor.as_view()),
]
