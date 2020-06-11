from rest_framework import serializers

from license_manager.apps.subscriptions.models import License, SubscriptionPlan


class SubscriptionPlanSerializer(serializers.ModelSerializer):
    """
    Serializer for the `SubscriptionPlan` model.
    """
    licenses = serializers.SerializerMethodField()

    class Meta:
        model = SubscriptionPlan
        fields = [
            'title',
            'uuid',
            'purchase_date',
            'start_date',
            'expiration_date',
            'enterprise_customer_uuid',
            'enterprise_catalog_uuid',
            'is_active',
            'licenses',
        ]

    def get_licenses(self, obj):
        return {
            'total': obj.num_licenses,
            'allocated': obj.num_allocated_licenses,
        }


class LicenseSerializer(serializers.ModelSerializer):
    """
    Serializer for the `License` model.
    """
    class Meta:
        model = License
        fields = [
            'uuid',
            'status',
            'user_email',
            'activation_date',
            'last_remind_date',
        ]


class CustomTextSerializer(serializers.ModelSerializer):
    """
    Serializer for specifying custom text to use in license management emails.

    It's a bit of a hack for it to be a model serializer, but it makes the connection to the license model in the views
    cleaner.
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
        model = License
        fields = [
            'greeting',
            'closing',
        ]


class LicenseEmailSerializer(CustomTextSerializer):
    """
    Serializer that takes custom text and allows additionally specifying a user_email for license management.

    Requires that a valid, non-empty email is submitted.
    """
    user_email = serializers.EmailField(
        allow_blank=False,
        required=True,
        write_only=True,
    )

    class Meta(CustomTextSerializer.Meta):
        fields = CustomTextSerializer.Meta.fields + [
            'user_email',
        ]
