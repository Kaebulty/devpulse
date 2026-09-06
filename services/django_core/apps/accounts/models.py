from django.contrib.auth.models import AbstractUser
from django.db import models


class User(AbstractUser):
    class Role(models.TextChoices):
        ADMIN = "ADMIN", "Admin"
        DEVELOPER = "DEVELOPER", "Developer"

    role = models.CharField(max_length=20, choices=Role.choices, default=Role.DEVELOPER)

    @property
    def is_admin(self) -> bool:
        return self.role == self.Role.ADMIN
