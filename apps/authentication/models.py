"""
Custom user model.

Two role concepts coexist, by design:

* ``role`` — the **permission role** from Backend v3:
  ADMIN / ASSESSMENT / SPECIALIST / VIEWER. This drives every permission class.
* ``team_role`` — the **display label** the dashboard shows
  (e.g. "Admin", "Success Team", "Technical Review Team"). This is what
  ``itrix-dashboard``'s ``SessionUser.role`` renders. Keeping them separate means we
  can have many friendly team functions while permissions stay on a small, auditable
  set of four.

Login is by **email** (there is no username); the dashboard posts ``{email, password}``.
"""

from __future__ import annotations

from django.contrib.auth.models import AbstractBaseUser, BaseUserManager, PermissionsMixin
from django.db import models

from apps.core.models import BaseModel


class UserManager(BaseUserManager):
    """Manager for the email-based custom user."""

    use_in_migrations = True

    def _create_user(self, email: str, password: str | None, **extra):
        if not email:
            raise ValueError("Users must have an email address.")
        email = self.normalize_email(email).lower()
        user = self.model(email=email, **extra)
        user.set_password(password)
        user.save(using=self._db)
        return user

    def create_user(self, email: str, password: str | None = None, **extra):
        extra.setdefault("is_staff", False)
        extra.setdefault("is_superuser", False)
        extra.setdefault("role", User.Role.VIEWER)
        return self._create_user(email, password, **extra)

    def create_superuser(self, email: str, password: str | None = None, **extra):
        extra.setdefault("is_staff", True)
        extra.setdefault("is_superuser", True)
        extra.setdefault("is_active", True)
        extra.setdefault("role", User.Role.ADMIN)
        extra.setdefault("team_role", User.TeamRole.ADMIN)
        if extra.get("is_staff") is not True:
            raise ValueError("Superuser must have is_staff=True.")
        if extra.get("is_superuser") is not True:
            raise ValueError("Superuser must have is_superuser=True.")
        return self._create_user(email, password, **extra)


class User(AbstractBaseUser, PermissionsMixin, BaseModel):
    """A member of the internal iTrix / IWL team."""

    class Role(models.TextChoices):
        """Permission roles (Backend v3)."""

        ADMIN = "ADMIN", "Admin"
        ASSESSMENT = "ASSESSMENT", "Assessment"
        SPECIALIST = "SPECIALIST", "Specialist"
        VIEWER = "VIEWER", "Viewer"

    class TeamRole(models.TextChoices):
        """Display labels shown in the dashboard (Surface 2)."""

        ADMIN = "Admin", "Admin"
        ASSESSMENT_TEAM = "Assessment Team", "Assessment Team"
        TECHNICAL_REVIEW = "Technical Review Team", "Technical Review Team"
        EXPERT_CONCIERGE = "Expert Concierge", "Expert Concierge"
        SUCCESS_TEAM = "Success Team", "Success Team"
        SPECIALIST = "Specialist", "Specialist"
        MEDIA_CONTACT = "Media Contact", "Media Contact"

    email = models.EmailField(unique=True, db_index=True)
    name = models.CharField(max_length=150, blank=True)
    role = models.CharField(
        max_length=20,
        choices=Role.choices,
        default=Role.VIEWER,
        help_text="Permission role (drives access control).",
    )
    team_role = models.CharField(
        max_length=40,
        choices=TeamRole.choices,
        default=TeamRole.ASSESSMENT_TEAM,
        help_text="Display label shown to the team in the dashboard.",
    )
    avatar_url = models.URLField(blank=True, default="")

    is_active = models.BooleanField(default=True)
    is_staff = models.BooleanField(
        default=False, help_text="Can access the Django admin."
    )

    objects = UserManager()

    USERNAME_FIELD = "email"
    REQUIRED_FIELDS = ["name"]

    class Meta:
        ordering = ["name", "email"]
        verbose_name = "Team member"
        verbose_name_plural = "Team members"

    def __str__(self) -> str:
        return f"{self.name or self.email} <{self.email}>"

    # ── Convenience ──────────────────────────────────────────────────────────
    @property
    def display_name(self) -> str:
        return self.name or self.email.split("@")[0]

    @property
    def is_admin_role(self) -> bool:
        return self.role == self.Role.ADMIN

    def save(self, *args, **kwargs):
        if self.email:
            self.email = self.email.lower()
        super().save(*args, **kwargs)
