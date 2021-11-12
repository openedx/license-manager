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
from license_manager.apps.subscriptions.forms import (
    ProductForm,
    SubscriptionPlanForm,
)
from license_manager.apps.subscriptions.models import SubscriptionPlan
from license_manager.apps.subscriptions.tests.factories import (
    CustomerAgreementFactory,
    PlanTypeFactory,
    SubscriptionPlanFactory,
)
from license_manager.apps.subscriptions.tests.utils import (
    make_bound_customer_agreement_form,
    make_bound_subscription_form,
    make_bound_subscription_plan_renewal_form,
)
from license_manager.apps.subscriptions.utils import localized_utcnow


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
        form = make_bound_subscription_form(
            num_licenses=num_licenses, for_internal_use_only=for_internal_use)
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
        form = make_bound_subscription_form(
            enterprise_catalog_uuid=catalog_uuid,
            customer_agreement_has_default_catalog=customer_agreement_has_default_catalog
        )
        assert form.is_valid() is is_valid

    def test_change_reason_is_required(self):
        """
        Verify subscription plan form is invalid if reason for change is None or outside the set of options
        """
        valid_form = make_bound_subscription_form(
            change_reason=SubscriptionPlanChangeReasonChoices.NEW)
        assert valid_form.is_valid() is True

        not_valid_form = make_bound_subscription_form(
            change_reason=SubscriptionPlanChangeReasonChoices.NONE)
        assert not_valid_form.is_valid() is False

        not_valid_form = make_bound_subscription_form(
            change_reason="koala")
        assert not_valid_form.is_valid() is False


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
            renewed_expiration_date=localized_utcnow() + timedelta(366),
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
            effective_date=localized_utcnow() - timedelta(1),
            renewed_expiration_date=prior_subscription_plan.expiration_date + timedelta(366),
        )
        assert not form.is_valid()


@mark.django_db
class TestCustomerAgreementAdminForm(TestCase):

    def test_populate_subscription_for_auto_applied_licenses_choices(self):
        customer_agreement = CustomerAgreementFactory()
        active_subscription_plan = SubscriptionPlanFactory(customer_agreement=customer_agreement)
        SubscriptionPlanFactory(customer_agreement=customer_agreement, is_active=False)

        form = make_bound_customer_agreement_form(
            customer_agreement=customer_agreement,
            subscription_for_auto_applied_licenses=None
        )

        field = form.fields['subscription_for_auto_applied_licenses']
        choices = field.choices
        self.assertEqual(len(choices), 2)
        self.assertEqual(choices[0], ('', '------'))
        self.assertEqual(choices[1], (active_subscription_plan.uuid, active_subscription_plan.title))
        self.assertEqual(field.initial, ('', '------'))

    def test_populate_subscription_for_auto_applied_licenses_choices_initial_choice(self):
        customer_agreement = CustomerAgreementFactory()
        current_sub_for_auto_applied_licenses = SubscriptionPlanFactory(
            customer_agreement=customer_agreement,
            should_auto_apply_licenses=True
        )
        SubscriptionPlanFactory(customer_agreement=customer_agreement, is_active=False)

        form = make_bound_customer_agreement_form(
            customer_agreement=customer_agreement,
            subscription_for_auto_applied_licenses=None
        )

        field = form.fields['subscription_for_auto_applied_licenses']
        choices = field.choices
        self.assertEqual(len(choices), 2)
        self.assertEqual(choices[0], ('', '------'))
        self.assertEqual(choices[1], (current_sub_for_auto_applied_licenses.uuid, current_sub_for_auto_applied_licenses.title))
        self.assertEqual(field.initial, (current_sub_for_auto_applied_licenses.uuid, current_sub_for_auto_applied_licenses.title))

    def test_populate_subscription_for_auto_applied_licenses_plans_outside_agreement_not_included(self):
        customer_agreement_1 = CustomerAgreementFactory()
        customer_agreement_2 = CustomerAgreementFactory()

        sub_for_customer_agreement_1 = SubscriptionPlanFactory(
            customer_agreement=customer_agreement_1,
            should_auto_apply_licenses=False
        )
        SubscriptionPlanFactory(customer_agreement=customer_agreement_2, should_auto_apply_licenses=True)

        form = make_bound_customer_agreement_form(
            customer_agreement=customer_agreement_1,
            subscription_for_auto_applied_licenses=None
        )

        field = form.fields['subscription_for_auto_applied_licenses']
        choices = field.choices
        self.assertEqual(len(choices), 2)
        self.assertEqual(choices[0], ('', '------'))
        self.assertEqual(choices[1], (sub_for_customer_agreement_1.uuid, sub_for_customer_agreement_1.title))
        self.assertEqual(field.initial, choices[0], ('', '------'))


@mark.django_db
@ddt.ddt
class TestProductAdminForm(TestCase):

    @ddt.data(
        {'ns_id_required': True, 'ns_id': '', 'is_valid': False},
        {'ns_id_required': True, 'ns_id': '1', 'is_valid': True},
        {'ns_id_required': False, 'ns_id': '', 'is_valid': True},
        {'ns_id_required': False, 'ns_id': '1', 'is_valid': True},
    )
    @ddt.unpack
    def test_ns_id_validation(self, ns_id_required, ns_id, is_valid):
        plan_type = PlanTypeFactory.create(ns_id_required=ns_id_required)
        form_data = {
            'name': 'Product A',
            'description': 'Product A description',
            'netsuite_id': ns_id,
            'plan_type': plan_type.id,
        }
        product_form = ProductForm(form_data)
        assert product_form.is_valid() is is_valid
