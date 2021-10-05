import random
import string
from datetime import timedelta
from uuid import uuid4

import factory
from faker import Faker

from license_manager.apps.core.models import User
from license_manager.apps.subscriptions.constants import (
    SALESFORCE_ID_LENGTH,
    UNASSIGNED,
)
from license_manager.apps.subscriptions.models import (
    CustomerAgreement,
    License,
    PlanType,
    SubscriptionPlan,
    SubscriptionPlanRenewal,
)
from license_manager.apps.subscriptions.utils import localized_utcnow


USER_PASSWORD = 'password'

FAKER = Faker()


def get_random_salesforce_id():
    """
    Returns a random alpha-numeric string of the correct length for a salesforce opportunity id.
    """
    return ''.join(random.choice(string.ascii_uppercase + string.ascii_lowercase + string.digits)
                   for _ in range(SALESFORCE_ID_LENGTH))


class CustomerAgreementFactory(factory.django.DjangoModelFactory):
    """
    Test factory for the `CustomerAgreement` model.

    Creates a customer agreement with randomized data
    """
    class Meta:
        model = CustomerAgreement
        # Perform a `get_or_create` when an agreement already exists with the same unique identifiers
        django_get_or_create = ('enterprise_customer_uuid', 'enterprise_customer_slug', 'enterprise_customer_name',)

    uuid = factory.LazyFunction(uuid4)
    enterprise_customer_uuid = factory.LazyFunction(uuid4)
    enterprise_customer_slug = factory.Faker('slug')
    default_enterprise_catalog_uuid = factory.LazyFunction(uuid4)
    enterprise_customer_name = factory.LazyAttribute(lambda x: FAKER.company())


class PlanTypeFactory(factory.django.DjangoModelFactory):
    """
    Test factory for the `PlanType` model.
    """
    label = 'Test'
    description = 'Internal edX subscription testing'
    is_paid_subscription = False
    ns_id_required = False
    sf_id_required = False
    internal_use_only = True

    class Meta:
        model = PlanType


class SubscriptionPlanFactory(factory.django.DjangoModelFactory):
    """
    Test factory for the `SubscriptionPlan` model.

    Creates a subscription purchased and starting today by default.
    """
    class Meta:
        model = SubscriptionPlan

    # Make the title sufficiently random to avoid violating
    # the unique constraint on (customer_agreement, title)
    title = factory.LazyAttribute(lambda p: '{} {}'.format(FAKER.word(), random.randint(0, 1000000)))
    uuid = factory.LazyFunction(uuid4)
    is_active = True
    start_date = localized_utcnow()
    # Make the subscription expire in roughly a year and a day
    expiration_date = localized_utcnow() + timedelta(days=366)
    expiration_processed = False
    customer_agreement = factory.SubFactory(CustomerAgreementFactory)
    enterprise_catalog_uuid = factory.LazyFunction(uuid4)
    netsuite_product_id = factory.Faker('random_int')
    salesforce_opportunity_id = factory.LazyFunction(get_random_salesforce_id)
    # By default, all the subscription plans created are Test type,
    # though this can be overridden to test others
    plan_type_id = 4
    can_freeze_unused_licenses = False


class SubscriptionPlanRenewalFactory(factory.django.DjangoModelFactory):
    """
    Test factory for the `SubscriptionPlanRenewal` model.

    Creates a subscription plan renewal with randomized data
    """
    class Meta:
        model = SubscriptionPlanRenewal

    prior_subscription_plan = factory.SubFactory(SubscriptionPlanFactory)
    salesforce_opportunity_id = factory.LazyFunction(get_random_salesforce_id)
    number_of_licenses = 5
    effective_date = localized_utcnow() + timedelta(days=366)
    renewed_expiration_date = effective_date + timedelta(days=366)
    processed = False


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
    revoked_date = None


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
