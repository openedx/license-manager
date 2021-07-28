from datetime import date, timedelta
from uuid import uuid4

import ddt
from django.test import TestCase
from pytest import mark

from license_manager.apps.subscriptions.constants import (
    MAX_NUM_LICENSES,
    MIN_NUM_LICENSES,
    SubscriptionPlanChangeReasonChoices,
)
from license_manager.apps.subscriptions.forms import SubscriptionPlanForm
from license_manager.apps.subscriptions.models import SubscriptionPlan
from license_manager.apps.subscriptions.tests.factories import (
    PlanTypeFactory,
    SubscriptionPlanFactory,
)
from license_manager.apps.subscriptions.tests.utils import (
    make_bound_subscription_form,
    make_bound_subscription_plan_renewal_form,
)


@mark.django_db
@ddt.ddt
class TestSubscriptionPlanForm(TestCase):
    """
    Unit tests for the SubscriptionPlanForm
    """
    @ddt.data(
        {'num_licenses': MIN_NUM_LICENSES, 'is_valid': True},  # Minimum valid value for num_licenses
        {'num_licenses': MAX_NUM_LICENSES, 'is_valid': True},  # Maximum valid value for num_licenses
        # Validation fails when num_licenses is less than the minimum
        {'num_licenses': MIN_NUM_LICENSES - 1, 'is_valid': False},
        # Validation fails when num_licenses is greater than the maximum value for a non-test subscription
        {'num_licenses': MAX_NUM_LICENSES + 1, 'is_valid': False},
        # A subscription for internal testing passes validation even with more than the max number of licenses
        {'num_licenses': MAX_NUM_LICENSES + 1, 'is_valid': True, 'for_internal_use': True},
    )
    @ddt.unpack
    def test_num_licenses(self, num_licenses, is_valid, for_internal_use=False):
        """
        Test to check validation conditions for the num_licenses field
        """
        plan_type = PlanTypeFactory.create()
        form = make_bound_subscription_form(
            num_licenses=num_licenses, for_internal_use_only=for_internal_use, plan_type=plan_type)
        assert form.is_valid() is is_valid

    @ddt.data(
        {'catalog_uuid': None, 'customer_agreement_has_default_catalog': False, 'is_valid': False},
        {'catalog_uuid': uuid4(), 'customer_agreement_has_default_catalog': False, 'is_valid': True},
        {'catalog_uuid': None, 'customer_agreement_has_default_catalog': True, 'is_valid': True},
        {'catalog_uuid': uuid4(), 'customer_agreement_has_default_catalog': True, 'is_valid': True},
    )
    @ddt.unpack
    def test_catalog_uuid(self, catalog_uuid, customer_agreement_has_default_catalog, is_valid):
        """
        Verify that a subscription form is invalid if it neither specifies a catalog_uuid nor has a customer agreement
        with a default catalog.
        """
        plan_type = PlanTypeFactory.create()
        form = make_bound_subscription_form(
            enterprise_catalog_uuid=catalog_uuid,
            customer_agreement_has_default_catalog=customer_agreement_has_default_catalog,
            plan_type=plan_type,
        )
        assert form.is_valid() is is_valid

    def test_change_reason_is_required(self):
        """
        Verify subscription plan form is invalid if reason for change is None or outside the set of options
        """
        plan_type = PlanTypeFactory.create()
        valid_form = make_bound_subscription_form(
            change_reason=SubscriptionPlanChangeReasonChoices.NEW, plan_type=plan_type)
        assert valid_form.is_valid() is True

        not_valid_form = make_bound_subscription_form(
            change_reason=SubscriptionPlanChangeReasonChoices.NONE, plan_type=plan_type)
        assert not_valid_form.is_valid() is False

        not_valid_form = make_bound_subscription_form(
            change_reason="koala", plan_type=plan_type)
        assert not_valid_form.is_valid() is False

    def test_plan_type_validation(self):
        """
        Verify that the selected plan type has properly associated ids populated
        """
        plan_type_1 = PlanTypeFactory.create(label='Standard Paid', ns_id_required=True, sf_id_required=True)
        valid_standard_paid_form = make_bound_subscription_form(
            plan_type=plan_type_1,
        )
        assert valid_standard_paid_form.is_valid() is True

        invalid_standard_paid_form_1 = make_bound_subscription_form(
            plan_type=plan_type_1,
            salesforce_opportunity_id=None,
        )
        assert invalid_standard_paid_form_1.is_valid() is False

        invalid_standard_paid_form_2 = make_bound_subscription_form(
            plan_type=plan_type_1,
            netsuite_product_id=None,
        )
        assert invalid_standard_paid_form_2.is_valid() is False

        plan_type_2 = PlanTypeFactory.create(label='OCE', sf_id_required=True)
        valid_oce_form = make_bound_subscription_form(
            plan_type=plan_type_2,
            netsuite_product_id=None,
        )
        assert valid_oce_form.is_valid() is True

        invalid_oce_form = make_bound_subscription_form(
            plan_type=plan_type_2,
            salesforce_opportunity_id=None,
        )
        assert invalid_oce_form.is_valid() is False

        plan_type_3 = PlanTypeFactory.create(label='Trials', sf_id_required=True)
        valid_trails_form = make_bound_subscription_form(
            plan_type=plan_type_3,
            netsuite_product_id=None,
        )
        assert valid_trails_form.is_valid() is True

        invalid_trials_form = make_bound_subscription_form(
            plan_type=plan_type_3,
            salesforce_opportunity_id=None,
        )
        assert invalid_trials_form.is_valid() is False

        plan_type_4 = PlanTypeFactory.create()
        valid_test_form = make_bound_subscription_form(
            plan_type=plan_type_4,
            netsuite_product_id=None,
            salesforce_opportunity_id=None,
        )
        assert valid_test_form.is_valid() is True


@mark.django_db
class TestSubscriptionPlanRenewalForm(TestCase):
    """
    Unit tests for the SubscriptionPlanRenewalForm
    """
    def test_valid_start_and_expiration_dates(self):
        prior_subscription_plan = SubscriptionPlanFactory.create()
        form = make_bound_subscription_plan_renewal_form(
            prior_subscription_plan=prior_subscription_plan,
            effective_date=prior_subscription_plan.expiration_date + timedelta(1),
            renewed_expiration_date=prior_subscription_plan.expiration_date + timedelta(366),
        )
        assert form.is_valid()

    def test_invalid_start_date_overlap_current_subscription(self):
        prior_subscription_plan = SubscriptionPlanFactory.create()
        form = make_bound_subscription_plan_renewal_form(
            prior_subscription_plan=prior_subscription_plan,
            effective_date=prior_subscription_plan.expiration_date - timedelta(1),
            renewed_expiration_date=date.today() + timedelta(366),
        )
        assert not form.is_valid()

    def test_invalid_expiration_date_before_start_date(self):
        prior_subscription_plan = SubscriptionPlanFactory.create()
        form = make_bound_subscription_plan_renewal_form(
            prior_subscription_plan=prior_subscription_plan,
            effective_date=prior_subscription_plan.expiration_date + timedelta(366),
            renewed_expiration_date=prior_subscription_plan.expiration_date + timedelta(1),
        )
        assert not form.is_valid()

    def test_invalid_start_date_before_today(self):
        prior_subscription_plan = SubscriptionPlanFactory.create()
        form = make_bound_subscription_plan_renewal_form(
            prior_subscription_plan=prior_subscription_plan,
            effective_date=date.today() - timedelta(1),
            renewed_expiration_date=prior_subscription_plan.expiration_date + timedelta(366),
        )
        assert not form.is_valid()
