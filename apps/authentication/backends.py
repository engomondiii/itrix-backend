"""
Authentication backend.

Authenticate by email (case-insensitive). DRF SimpleJWT calls ``authenticate`` with
``username=<email>`` because USERNAME_FIELD is ``email``; this backend also accepts an
explicit ``email`` kwarg so direct calls work too.
"""

from __future__ import annotations

from django.contrib.auth import get_user_model
from django.contrib.auth.backends import ModelBackend

UserModel = get_user_model()


class EmailBackend(ModelBackend):
    def authenticate(self, request, username=None, password=None, **kwargs):
        email = kwargs.get("email") or username
        if email is None or password is None:
            return None
        try:
            user = UserModel.objects.get(email__iexact=email.strip())
        except UserModel.DoesNotExist:
            # Run the default hasher once to mitigate timing attacks.
            UserModel().set_password(password)
            return None
        except UserModel.MultipleObjectsReturned:  # pragma: no cover - email is unique
            user = UserModel.objects.filter(email__iexact=email.strip()).order_by("id").first()
            if user is None:
                return None

        if user.check_password(password) and self.user_can_authenticate(user):
            return user
        return None
