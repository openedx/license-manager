from datetime import date, timedelta
from unittest import TestCase

import ddt
from pytest import mark

from license_manager.apps.subscriptions.forms import SubscriptionPlanForm
from license_manager.apps.subscriptions.models import SubscriptionPlan
from license_manager.apps.subscriptions.tests.utils import (
    make_bound_subscription_form,
)


@mark.django_db
@ddt.ddt
class TestSubscriptionPlanForm(TestCase):
    """
    Unit tests for the SubscriptionPlanForm
    """
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
        form = make_bound_subscription_form(num_licenses=num_licenses)
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
        form = make_bound_subscription_form(expiration_date=expiration_date)
        assert form.is_valid() is is_valid
