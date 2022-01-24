from uuid import uuid4

import factory

from license_manager.apps.api.models import BulkEnrollmentJob


class BulkEnrollmentJobFactory(factory.django.DjangoModelFactory):
    """
    Test factory for the `BulkEnrollmentJob` model.
    """
    class Meta:
        model = BulkEnrollmentJob

    uuid = factory.LazyFunction(uuid4)
    enterprise_customer_uuid = factory.LazyFunction(uuid4)
    lms_user_id = factory.Faker('random_int')
