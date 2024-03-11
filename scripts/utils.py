# needed for email validation
import django
from rest_framework import serializers

EMAIL_FIELD = serializers.EmailField()


def is_valid_email(email):
    try:
        EMAIL_FIELD.run_validators(email)
        return True
    except Exception:
        return False
