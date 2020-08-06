import bleach
from rest_framework import serializers

from license_manager.apps.email_templates.constants import (
    EMAIL_TEMPLATE_BODY_MAP,
    OFFER_ASSIGNMENT_EMAIL_SUBJECT_LIMIT,
    OFFER_ASSIGNMENT_EMAIL_TEMPLATE_FIELD_LIMIT,
)
from license_manager.apps.email_templates.models import EmailTemplate
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


class EmailTemplateSerializer(serializers.ModelSerializer):
    enterprise_customer = serializers.UUIDField(read_only=True)
    email_body = serializers.SerializerMethodField()

    class Meta:
        model = EmailTemplate
        fields = '__all__'

    def validate_email_greeting(self, value):
        if len(value) > OFFER_ASSIGNMENT_EMAIL_TEMPLATE_FIELD_LIMIT:
            raise serializers.ValidationError(
                'Email greeting must be {} characters or less'.format(OFFER_ASSIGNMENT_EMAIL_TEMPLATE_FIELD_LIMIT)
            )
        return value

    def validate_email_closing(self, value):
        if len(value) > OFFER_ASSIGNMENT_EMAIL_TEMPLATE_FIELD_LIMIT:
            raise serializers.ValidationError(
                'Email closing must be {} characters or less'.format(OFFER_ASSIGNMENT_EMAIL_TEMPLATE_FIELD_LIMIT)
            )
        return value

    def validate_email_subject(self, value):
        if len(value) > OFFER_ASSIGNMENT_EMAIL_SUBJECT_LIMIT:
            raise serializers.ValidationError(
                'Email subject must be {} characters or less'.format(OFFER_ASSIGNMENT_EMAIL_SUBJECT_LIMIT)
            )
        return value

    def create(self, validated_data):
        enterprise_customer = self.context['view'].kwargs.get('enterprise_customer')
        email_type = validated_data['email_type']

        instance = EmailTemplate.objects.create(
            name=validated_data['name'],
            enterprise_customer=enterprise_customer,
            email_type=email_type,
            email_subject=bleach.clean(validated_data['email_subject']),
            email_greeting=bleach.clean(validated_data.get('email_greeting', '')),
            email_closing=bleach.clean(validated_data.get('email_closing', '')),
        )

        # deactivate old templates for enterprise for this specific email type
        EmailTemplate.objects.filter(
            enterprise_customer=enterprise_customer,
            email_type=email_type,
        ).exclude(pk=instance.pk).update(active=False)

        return instance

    def get_email_body(self, obj):
        return EMAIL_TEMPLATE_BODY_MAP[obj.email_type]
