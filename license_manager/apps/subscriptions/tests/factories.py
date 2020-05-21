from datetime import date
from uuid import uuid4

import factory
from factory.faker import faker

from license_manager.apps.subscriptions.constants import UNASSIGNED
from license_manager.apps.subscriptions.models import License, SubscriptionPlan


class SubscriptionPlanFactory(factory.DjangoModelFactory):
    """
    Test factory for the `SubscriptionPlan` model.

    Creates a subscription purchased and starting today by default.
    """
    class Meta:
        model = SubscriptionPlan

    uuid = factory.LazyFunction(uuid4)
    purchase_date = date.today()
    start_date = date.today()
    expiration_date = date.max
    enterprise_customer_uuid = factory.LazyFunction(uuid4)
    enterprise_catalog_uuid = factory.LazyFunction(uuid4)


class LicenseFactory(factory.DjangoModelFactory):
    """
    Test factory for the `License` model.

    Creates an unassigned license by default.
    """
    class Meta:
        model = License

    uuid = factory.LazyFunction(uuid4)
    status = UNASSIGNED
    subscription_plan = factory.SubFactory(SubscriptionPlanFactory)
