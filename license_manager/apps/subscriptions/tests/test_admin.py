# pylint: disable=redefined-outer-name
import pytest
from django.contrib.admin.sites import AdminSite
from django.test import RequestFactory

from license_manager.apps.subscriptions.admin import SubscriptionPlanAdmin
from license_manager.apps.subscriptions.models import SubscriptionPlan
from license_manager.apps.subscriptions.tests.factories import PlanTypeFactory, UserFactory
from license_manager.apps.subscriptions.tests.utils import (
    make_bound_subscription_form,
)


@pytest.mark.django_db
def test_licenses_subscription_creation():
    """
    Verify that creating a SubscriptionPlan creates its associated Licenses after it is created.
    """
    subscription_admin = SubscriptionPlanAdmin(SubscriptionPlan, AdminSite())
    request = RequestFactory()
    request.user = UserFactory()
    plan_type = PlanTypeFactory()
    num_licenses = 5
    form = make_bound_subscription_form(num_licenses=num_licenses,plan_type=plan_type)
    obj = form.save()  # Get the object returned from saving the form to save to the database
    assert obj.licenses.count() == 0  # Verify no Licenses have been created yet
    change = False
    subscription_admin.save_model(request, obj, form, change)
    assert obj.licenses.count() == num_licenses
