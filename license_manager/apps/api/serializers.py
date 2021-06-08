from django.conf import settings
from rest_framework import serializers

from license_manager.apps.subscriptions.constants import (
    EXPOSE_LICENSE_ACTIVATION_KEY_OVER_API,
)
from license_manager.apps.subscriptions.models import (
    CustomerAgreement,
    License,
    SubscriptionPlan,
)


class SubscriptionPlanSerializer(serializers.ModelSerializer):
    """
    Serializer for the `SubscriptionPlan` model.
    """
    licenses = serializers.SerializerMethodField()
    revocations = serializers.SerializerMethodField()

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
            'licenses',
            'revocations',
            'days_until_expiration',
            'days_until_expiration_including_renewals',
        ]

    def get_licenses(self, obj):
        return {
            'total': obj.num_licenses,
            'allocated': obj.num_allocated_licenses,
        }

    def get_revocations(self, obj):
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
