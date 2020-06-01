from datetime import date, timedelta
from unittest import TestCase

import ddt
from faker import Factory as FakerFactory
from pytest import mark

from license_manager.apps.subscriptions.forms import SubscriptionPlanForm
from license_manager.apps.subscriptions.models import SubscriptionPlan


faker = FakerFactory.create()


@mark.django_db
@ddt.ddt
class TestSubscriptionPlanForm(TestCase):
    """
    Unit tests for the SubscriptionPlanForm
    """
    @staticmethod
    def _make_bound_form(
        purchase_date=date.today(),
        start_date=date.today(),
        expiration_date=date.today() + timedelta(days=366),
        enterprise_customer_uuid=faker.uuid4(),
        enterprise_catalog_uuid=faker.uuid4(),
        num_licenses=0,
        is_active=False
    ):
        """
        Builds a bound SubscriptionPlanForm
        """
        form_data = {
            'purchase_date': purchase_date,
            'start_date': start_date,
            'expiration_date': expiration_date,
            'enterprise_customer_uuid': enterprise_customer_uuid,
            'enterprise_catalog_uuid': enterprise_catalog_uuid,
            'num_licenses': num_licenses,
            'is_active': is_active
        }
        return SubscriptionPlanForm(form_data)

    @ddt.data(
        (0, True),     # Minimum value for num_licenses
        (1000, True),  # Maximum value for num_licenses
        (-1, False),   # Validation fails when num_licenses is decreased
        (1001, False)  # Validation fails when num_licenses is greater than the maximum value
    )
    @ddt.unpack
    def test_num_licenses(self, num_licenses, is_valid):
        """
        Test to check validation conditions for the num_licenses field
        """
        form = self._make_bound_form(num_licenses=num_licenses)
        assert form.is_valid() is is_valid

    @ddt.data(
        (date.today() - timedelta(days=1), False),  # Validation fails when expiration is before start_date
        (date.today(), False),                      # Validation fails when expiration_date is start_date
        (date.today() + timedelta(days=365), True)  # Validation passes when expiration_date is 1 year after start_date
    )
    @ddt.unpack
    def test_expiration_date(self, expiration_date, is_valid):
        """
        Test to check validation conditions for the expiration_date field
        """
        form = self._make_bound_form(expiration_date=expiration_date)
        assert form.is_valid() is is_valid

    @ddt.data(
        0,    # Create no Licenses
        1,    # Create a single License
        1000  # Create the maximum number of Licenses possible
    )
    def test_save_increase_num_licenses(self, num_licenses):
        """
        Test to check that increase_num_licenses is called with num_licenses
        """
        form = self._make_bound_form(num_licenses=num_licenses)
        subscription_plan = form.save()
        assert SubscriptionPlan.objects.get(uuid=subscription_plan.uuid).num_licenses == num_licenses
