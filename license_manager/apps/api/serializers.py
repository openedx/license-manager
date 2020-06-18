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
            'revoked_date',
        ]


class SingleEmailSerializer(serializers.ModelSerializer):
    """
    Serializer for specifying a single email

    It's a bit of a hack for it to be a model serializer, but it makes the connection to the license model in the views
    cleaner.

    Requires that a valid, non-empty email is submitted.
    """
    user_email = serializers.EmailField(
        allow_blank=False,
        required=True,
        write_only=True,
    )

    class Meta:
        model = License
        fields = [
            'user_email',
        ]


class MultipleEmailsSerializer(serializers.ModelSerializer):
    """
    Serializer for specifying multiple emails

    It's a bit of a hack for it to be a model serializer, but it makes the connection to the license model in the views
    cleaner.

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
        model = License
        fields = [
            'user_emails',
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


def combine_serializers(*serializers_to_compose):
    """
    Function for combining multiple serializers into a single serializer
    This allows for having multiple base serializers that don't inherit from each other and eliminates the need
    to have additional serializers that serve to just compose other serializers

    Instead the serializer definition is composed in `views` via using this function:
    e.g. combine_serializers(MultipleEmailsSerializer, CustomTextSerializer)

    Limitations: the Meta model can only be set to a single model class here it is set to the License Model
    serializers.ModelSerializer is assumed to be inherited in the serializers being combined because of the previously
    mentioned hacky trick of using serializers.ModelSerializer to make the connection to the license model in the views
    cleaner.
    """
    class CombinedSerializer(*serializers_to_compose):
        class Meta:
            model = License
            fields = []
            for x in serializers_to_compose:
                fields = fields + x.Meta.fields
    return CombinedSerializer
