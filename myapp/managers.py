from django.contrib.auth.base_user import BaseUserManager


class CustomUserManager(BaseUserManager):
    """
    Manager for CustomUser where email is the unique identifier
    instead of a separate username.

    Emails are not case-sensitive in UEnvision: they are saved in lowercase
    (CustomUser.save) and looked up without caring about case, so Juan@UE.edu.ph
    and juan@ue.edu.ph are the same account.
    """

    @classmethod
    def normalize_email(cls, email):
        return str(email or "").strip().lower()

    def get_by_natural_key(self, username):
        # Log in (ModelBackend) and createsuperuser look accounts up here.
        email = str(username or "").strip()
        try:
            return self.get(email=email.lower())
        except self.model.DoesNotExist:
            # an account saved before emails were lowercased (two accounts that differ only
            # by case are left as they are by migration 0017; the exact match wins then)
            matches = list(self.filter(email__iexact=email)[:2])
            if len(matches) == 1:
                return matches[0]
            exact = [u for u in matches if u.email == email]
            if exact:
                return exact[0]
            raise

    def create_user(self, email, password=None, **extra_fields):
        if not email:
            raise ValueError("Users must have an email address")
        email = self.normalize_email(email)
        user = self.model(email=email, **extra_fields)
        user.set_password(password)  # hashes the password (PBKDF2 by default)
        user.save(using=self._db)
        return user

    def create_superuser(self, email, password=None, **extra_fields):
        extra_fields.setdefault("is_staff", True)
        extra_fields.setdefault("is_superuser", True)
        extra_fields.setdefault("is_active", True)
        extra_fields.setdefault("role", "administrator")

        if extra_fields.get("is_staff") is not True:
            raise ValueError("Superuser must have is_staff=True")
        if extra_fields.get("is_superuser") is not True:
            raise ValueError("Superuser must have is_superuser=True")

        return self.create_user(email, password, **extra_fields)