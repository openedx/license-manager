import random
import string
from datetime import date, timedelta
from uuid import uuid4

import factory

from license_manager.apps.core.models import User
from license_manager.apps.subscriptions.constants import (
    SALESFORCE_ID_LENGTH,
    UNASSIGNED,
)
from license_manager.apps.subscriptions.models import License, SubscriptionPlan


USER_PASSWORD = 'password'


def get_random_salesforce_id():
    """
    Returns a random alpha-numeric string of the correct length for a salesforce opportunity id.
    """
    return ''.join(random.choice(string.ascii_uppercase + string.ascii_lowercase + string.digits)
                   for _ in range(SALESFORCE_ID_LENGTH))


class SubscriptionPlanFactory(factory.django.DjangoModelFactory):
    """
    Test factory for the `SubscriptionPlan` model.

    Creates a subscription purchased and starting today by default.
    """
    class Meta:
        model = SubscriptionPlan

    title = factory.Faker('word')
    uuid = factory.LazyFunction(uuid4)
    start_date = date.today()
    # Make the subscription expire in roughly a year and a day
    expiration_date = date.today() + timedelta(days=366)
    enterprise_customer_uuid = factory.LazyFunction(uuid4)
    enterprise_catalog_uuid = factory.LazyFunction(uuid4)
    netsuite_product_id = factory.Faker('random_int')
    salesforce_opportunity_id = factory.LazyFunction(get_random_salesforce_id)


class LicenseFactory(factory.django.DjangoModelFactory):
    """
    Test factory for the `License` model.

    Creates an unassigned license by default.
    """
    class Meta:
        model = License

    uuid = factory.LazyFunction(uuid4)
    activation_key = factory.LazyFunction(uuid4)
    status = UNASSIGNED
    subscription_plan = factory.SubFactory(SubscriptionPlanFactory)


class UserFactory(factory.django.DjangoModelFactory):
    """
    Test factory for the `User` model.
    """
    username = factory.Faker('user_name')
    password = factory.PostGenerationMethodCall('set_password', USER_PASSWORD)
    email = factory.Faker('email')
    first_name = factory.Faker('first_name')
    last_name = factory.Faker('last_name')
    is_active = True
    is_staff = False
    is_superuser = False

    class Meta:
        model = User
