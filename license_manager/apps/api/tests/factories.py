import random
import string
from datetime import timedelta
from uuid import uuid4

import factory
from faker import Faker

from license_manager.apps.api.models import (
    BulkEnrollmentJob,
)

from license_manager.apps.subscriptions.utils import localized_utcnow


class BulkEnrollmentJobFactory(factory.django.DjangoModelFactory):
    """
    Test factory for the `BulkEnrollmentJob` model.
    """
    class Meta:
        model = BulkEnrollmentJob

    uuid = factory.LazyFunction(uuid4)
    enterprise_customer_uuid = factory.LazyFunction(uuid4)
    lms_user_id = factory.Faker('random_int')