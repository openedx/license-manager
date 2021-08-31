from django.conf import settings
from rest_framework import serializers

from license_manager.apps.subscriptions.constants import (
    ACTIVATED,
    ASSIGNED,
    EXPOSE_LICENSE_ACTIVATION_KEY_OVER_API,
)
from license_manager.apps.subscriptions.models import (
    CustomerAgreement,
    License,
    SubscriptionPlan,
    SubscriptionPlanRenewal,
)


class SubscriptionPlanRenewalSerializer(serializers.ModelSerializer):
    """
    Serializer for the `SubscriptionPlanRenewal` model.
    """
    prior_subscription_plan_start_date = serializers.SerializerMethodField()
    renewed_subscription_plan_start_date = serializers.SerializerMethodField()

    class Meta:
        model = SubscriptionPlanRenewal
        fields = [
            'prior_subscription_plan_id',
            'prior_subscription_plan_start_date',
            'renewed_subscription_plan_id',
            'renewed_subscription_plan_start_date',
        ]

    def get_prior_subscription_plan_start_date(self, obj):
        return obj.prior_subscription_plan.start_date

    def get_renewed_subscription_plan_start_date(self, obj):
        return obj.renewed_subscription_plan.start_date


class SubscriptionPlanSerializer(serializers.ModelSerializer):
    """
    Serializer for the `SubscriptionPlan` model.
    """
    licenses = serializers.SerializerMethodField()
    revocations = serializers.SerializerMethodField()
    prior_renewals = SubscriptionPlanRenewalSerializer(many=True)
    is_locked_for_renewal_processing = serializers.SerializerMethodField()

    class Meta:
        model = SubscriptionPlan
        fields = [
            'title',
            'uuid',
            'start_date',
            'expiration_date',
            'enterprise_customer_uuid',
            'enterprise_catalog_uuid',
            'is_active',
            'is_revocation_cap_enabled',
            'licenses',
            'revocations',
            'days_until_expiration',
            'days_until_expiration_including_renewals',
            'prior_renewals'
            'is_locked_for_renewal_processing',
        ]

    def get_licenses(self, obj):
        """
        Returns the number of licenses that are currently
        associated with the plan (obj), assigned or activated in the plan,
        or revoked in the plan.

        Returns a dictionary with keys 'activated', 'allocated', 'assigned',
        'revoked', 'total', and 'unassigned'.  Note that 'total' does not include
        revoked licenses in its count - see the docstring of `num_licenses()` for
        more details.
        """
        count_by_status = obj.license_count_by_status()
        count_by_status['total'] = obj.num_licenses
        count_by_status['allocated'] = count_by_status[ASSIGNED] + count_by_status[ACTIVATED]
        return count_by_status

    def get_revocations(self, obj):
        """
        If the revocation cap is enabled for the plan (obj),
        returns a count of the number of revocations ever applied
        and how many are remaining before the cap is reached.

        If the revocation cap is not enabled for the plan, returns null.
        """
        if not obj.is_revocation_cap_enabled:
            return None

        return {
            'applied': obj.num_revocations_applied,
            'remaining': obj.num_revocations_remaining,
        }


class CustomerAgreementSerializer(serializers.ModelSerializer):
    """
    Serializer for the `CustomerAgreement` model.
    """
    subscriptions = SubscriptionPlanSerializer(many=True)

    class Meta:
        model = CustomerAgreement
        fields = [
            'uuid',
            'enterprise_customer_uuid',
            'enterprise_customer_slug',
            'default_enterprise_catalog_uuid',
            'ordered_subscription_plan_expirations',
            'subscriptions',
            'disable_expiration_notifications',
            'net_days_until_expiration',
        ]


class LicenseSerializer(serializers.ModelSerializer):
    """
    Serializer for the `License` model.
    """
    subscription_plan = SubscriptionPlanSerializer(read_only=True)

    class Meta:
        model = License
        fields = [
            'uuid',
            'status',
            'user_email',
            'activation_date',
            'last_remind_date',
            'subscription_plan',
        ]
        if settings.FEATURES[EXPOSE_LICENSE_ACTIVATION_KEY_OVER_API]:
            fields.append('activation_key')


class StaffLicenseSerializer(serializers.ModelSerializer):
    """
    Serializer for the ``License`` model that is usable by views
    that are restricted to staff/admin users.
    """
    subscription_plan_title = serializers.SerializerMethodField()
    subscription_plan_expiration_date = serializers.SerializerMethodField()

    class Meta:
        model = License
        fields = [
            'status',
            'assigned_date',
            'activation_date',
            'revoked_date',
            'last_remind_date',
            'subscription_plan_title',
            'subscription_plan_expiration_date',
            'activation_link',
        ]

    def get_subscription_plan_title(self, obj):
        return obj.subscription_plan.title

    def get_subscription_plan_expiration_date(self, obj):
        return obj.subscription_plan.expiration_date


class SingleEmailSerializer(serializers.Serializer):  # pylint: disable=abstract-method
    """
    Serializer for specifying a single email

    Requires that a valid, non-empty email is submitted.
    """
    user_email = serializers.EmailField(
        allow_blank=False,
        required=True,
        write_only=True,
    )

    class Meta:
        fields = [
            'user_email',
        ]


class MultipleEmailsSerializer(serializers.Serializer):  # pylint: disable=abstract-method
    """
    Serializer for specifying multiple emails

    Requires that a list of valid, non-empty emails are submitted.
    """
    user_emails = serializers.ListField(
        child=serializers.EmailField(
            allow_blank=False,
            write_only=True,
        ),
        allow_empty=False,
    )

    class Meta:
        fields = [
            'user_emails',
        ]


class CustomTextSerializer(serializers.Serializer):  # pylint: disable=abstract-method
    """
    Serializer for specifying custom text to use in license management emails.
    """
    greeting = serializers.CharField(
        allow_blank=True,
        required=False,
        write_only=True,
    )
    closing = serializers.CharField(
        allow_blank=True,
        required=False,
        write_only=True,
    )

    class Meta:
        fields = [
            'greeting',
            'closing',
        ]


class CustomTextWithSingleEmailSerializer(SingleEmailSerializer, CustomTextSerializer):  # pylint: disable=abstract-method
    """
    Serializer for specifying custom text to use in a license management email for a single user_email
    """
    class Meta:
        fields = SingleEmailSerializer.Meta.fields + CustomTextSerializer.Meta.fields


class CustomTextWithMultipleEmailsSerializer(MultipleEmailsSerializer, CustomTextSerializer):  # pylint: disable=abstract-method
    """
    Serializer for specifying custom text to use in a license management email for multiple user_emails
    """
    class Meta:
        fields = MultipleEmailsSerializer.Meta.fields + CustomTextSerializer.Meta.fields
