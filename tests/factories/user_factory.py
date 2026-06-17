"""User factories for tests."""

from __future__ import annotations

import factory
from django.contrib.auth import get_user_model

User = get_user_model()

DEFAULT_PASSWORD = "test-pass-12345"


class UserFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = User
        skip_postgeneration_save = True

    name = factory.Sequence(lambda n: f"Team Member {n}")
    email = factory.Sequence(lambda n: f"member{n}@itrix.example")
    role = User.Role.ASSESSMENT
    team_role = User.TeamRole.ASSESSMENT_TEAM
    is_active = True
    is_staff = False

    @factory.post_generation
    def password(obj, create, extracted, **kwargs):
        obj.set_password(extracted or DEFAULT_PASSWORD)
        if create:
            obj.save()


class AdminUserFactory(UserFactory):
    name = factory.Sequence(lambda n: f"Admin {n}")
    email = factory.Sequence(lambda n: f"admin{n}@itrix.example")
    role = User.Role.ADMIN
    team_role = User.TeamRole.ADMIN
    is_staff = True


class SpecialistUserFactory(UserFactory):
    email = factory.Sequence(lambda n: f"specialist{n}@itrix.example")
    role = User.Role.SPECIALIST
    team_role = User.TeamRole.SPECIALIST


class ViewerUserFactory(UserFactory):
    email = factory.Sequence(lambda n: f"viewer{n}@itrix.example")
    role = User.Role.VIEWER
    team_role = User.TeamRole.MEDIA_CONTACT
