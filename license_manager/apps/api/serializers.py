from django.core.validators import MinLengthValidator
from rest_framework import serializers
from rest_framework.fields import SerializerMethodField

from license_manager.apps.subscriptions.constants import (
    ACTIVATED,
    ASSIGNED,
    REVOKED,
    SALESFORCE_ID_LENGTH,
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

    prior_subscription_plan_start_date = serializers.UUIDField(source='prior_subscription_plan.start_date')
    renewed_subscription_plan_start_date = serializers.UUIDField(source='renewed_subscription_plan.start_date')

    class Meta:
        model = SubscriptionPlanRenewal
        fields = [
            'prior_subscription_plan_id',
            'prior_subscription_plan_start_date',
            'renewed_subscription_plan_id',
            'renewed_subscription_plan_start_date',
        ]


class SubscriptionPlanSerializer(serializers.ModelSerializer):
    """
    Serializer for the `SubscriptionPlan` model.
    """
    licenses = serializers.SerializerMethodField()
    revocations = serializers.SerializerMethodField()
    prior_renewals = SubscriptionPlanRenewalSerializer(many=True)

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
            'prior_renewals',
            'is_locked_for_renewal_processing',
            'should_auto_apply_licenses'
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

        total_count = 0
        for status, count_for_status in count_by_status.items():
            if status != REVOKED:
                total_count += count_for_status

        count_by_status['total'] = total_count
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
    subscriptions = SerializerMethodField()
    subscription_for_auto_applied_licenses = serializers.SerializerMethodField()

    class Meta:
        model = CustomerAgreement
        fields = [
            'uuid',
            'enterprise_customer_uuid',
            'enterprise_customer_slug',
            'default_enterprise_catalog_uuid',
            'subscriptions',
            'disable_expiration_notifications',
            'net_days_until_expiration',
            'subscription_for_auto_applied_licenses'
        ]

    @property
    def serialize_active_plans_only(self):
        return self.context.get('active_plans_only', True)

    def get_subscriptions(self, obj):
        """
        Returns a serialized dictionary of all or active-only plans in this agreement.
        """
        plans = obj.subscriptions.all()

        if self.serialize_active_plans_only:
            plans = [plan for plan in plans if plan.is_active]

        serializer = SubscriptionPlanSerializer(plans, many=True)
        return serializer.data

    def get_subscription_for_auto_applied_licenses(self, obj):
        subscription_plan = obj.auto_applicable_subscription
        return subscription_plan.uuid if subscription_plan else None


class LicenseSerializer(serializers.ModelSerializer):
    """
    Serializer for the `License` model.
    """

    subscription_plan_uuid = serializers.UUIDField(source='subscription_plan_id')

    class Meta:
        model = License
        fields = [
            'uuid',
            'status',
            'user_email',
            'activation_date',
            'last_remind_date',
            'subscription_plan_uuid',
            'revoked_date',
            'activation_key',
        ]


class StaffLicenseSerializer(serializers.ModelSerializer):
    """
    Serializer for the ``License`` model that is usable by views
    that are restricted to staff/admin users.
    """

    subscription_plan_title = serializers.CharField(source='subscription_plan.title')
    subscription_plan_expiration_date = serializers.DateTimeField(source='subscription_plan.expiration_date')

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


# Action Serializers
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


class CustomTextWithMultipleEmailsSerializer(MultipleEmailsSerializer, CustomTextSerializer):  # pylint: disable=abstract-method
    """
    Serializer for specifying custom text to use in a license management email for multiple user_emails
    """
    class Meta:
        fields = MultipleEmailsSerializer.Meta.fields + CustomTextSerializer.Meta.fields


class MultipleOrSingleEmailSerializer(serializers.Serializer):  # pylint: disable=abstract-method
    """
    Serializer for specifying multiple or single email

    Requires that valid emails are submitted.
    """
    user_email = serializers.EmailField(
        allow_blank=True,
        required=False,
        write_only=True,
    )

    user_emails = serializers.ListField(
        child=serializers.EmailField(
            allow_blank=True,
            write_only=True,
        ),
        allow_empty=True,
        required=False,
    )

    class Meta:
        fields = [
            'user_email',
            'user_emails',
        ]


class CustomTextWithMultipleOrSingleEmailSerializer(MultipleOrSingleEmailSerializer, CustomTextSerializer):  # pylint: disable=abstract-method
    """
    Serializer for specifying custom text to use in a license management email for
    either multiple user_emails or a single email.
    """
    class Meta:
        fields = MultipleOrSingleEmailSerializer.Meta.fields + CustomTextSerializer.Meta.fields


class LicenseAdminBulkActionSerializer(serializers.Serializer):  # pylint: disable=abstract-method
    """
    Serializer for license admin bulk actions.

    Takes either a list of user_emails or a list of filters, but not both.
    """

    user_emails = serializers.ListField(
        child=serializers.EmailField(
            allow_blank=False,
            write_only=True,
        ),
        allow_empty=False,
        required=False,
    )

    filters = serializers.ListField(
        child=serializers.DictField(),
        allow_empty=False,
        required=False
    )

    class Meta:
        fields = ['user_emails', 'filters']

    def _validate_filters(self, filters):
        """
        Validate filters that were passed in. Only user_email and status filters are supported.
        """

        if not filters:
            return

        supported_filters = ['user_email', 'status_in']

        for fltr in filters:
            filter_name = fltr.get('name')
            filter_value = fltr.get('filter_value')

            if filter_name not in supported_filters:
                raise serializers.ValidationError(f'Malformed filters, supported filters are {supported_filters}.')

            if filter_name == 'user_email' and not isinstance(filter_value, str):
                raise serializers.ValidationError('Malformed filters, user_email must be a string.')

            if filter_name == 'status_in' and not isinstance(filter_value, list) \
                    and not all(isinstance(s, str) for s in filter_value):
                raise serializers.ValidationError('Malformed filters, status_in must be a list of strings.')

    def validate(self, attrs):
        user_emails = attrs.get('user_emails')
        filters = attrs.get('filters')

        if not (user_emails or filters):
            raise serializers.ValidationError('Either user_emails or filters must be provided.')

        if user_emails and filters:
            raise serializers.ValidationError('Either user_emails or filters must be provided, but not both.')

        self._validate_filters(filters)
        return super().validate(attrs)


class LicenseAdminRemindActionSerializer(  # pylint: disable=abstract-method
    LicenseAdminBulkActionSerializer,
    CustomTextSerializer
):
    """
    Serializer for the license admin remind action.
    """

    class Meta:
        fields = LicenseAdminBulkActionSerializer.Meta.fields + CustomTextSerializer.Meta.fields


class LicenseAdminAssignActionSerializer(CustomTextWithMultipleEmailsSerializer):  # pylint: disable=abstract-method
    """
    Serializer for the license admin assign action.
    """

    notify_users = serializers.BooleanField(required=False)
    user_sfids = serializers.ListField(
        child=serializers.CharField(
            allow_blank=True,
            allow_null=True,
            write_only=True,
            validators=[MinLengthValidator(SALESFORCE_ID_LENGTH)]
        ),
        allow_empty=False,
        required=False,
        error_messages={"empty": "No Salesforce Ids provided."}
    )

    class Meta:
        fields = CustomTextWithMultipleEmailsSerializer.Meta.fields + [
            'notify_users',
        ]

    def validate(self, attrs):
        user_emails = attrs.get('user_emails')
        user_sfids = attrs.get('user_sfids')

        if user_sfids:
            # if saleforce ids list is present then its length must be equal to number of user emails
            if len(user_emails) != len(user_sfids):
                raise serializers.ValidationError(
                    'Number of Salesforce IDs did not match number of provided user emails.'
                )

        return super().validate(attrs)


class EnterpriseEnrollmentWithLicenseSubsidyQueryParamsSerializer(serializers.Serializer):  # pylint: disable=abstract-method
    """
    Serializer for the enterprise enrollment with license subsidy query params
    """

    enterprise_customer_uuid = serializers.UUIDField(
        required=True,
        help_text='The UUID of the associated enterprise customer',
    )
    enroll_all = serializers.BooleanField(
        required=False,
        help_text='A boolean indicating whether to enroll all learners or not',
    )
    subscription_uuid = serializers.UUIDField(
        required=False,
        help_text='The UUID of the subscription',
    )

    class Meta:
        fields = [
            'enterprise_customer_uuid',
            'enroll_all',
            'subscription_uuid',
        ]


class EnterpriseEnrollmentWithLicenseSubsidyRequestSerializer(serializers.Serializer):  # pylint: disable=abstract-method
    """
    Serializer for the enterprise enrollment with license subsidy request
    """

    emails = serializers.ListField(
        child=serializers.EmailField(
            allow_blank=False,
        ),
        allow_empty=False,
        required=True,
        help_text='an array of learners\' emails',
    )
    course_run_keys = serializers.ListField(
        child=serializers.CharField(
            allow_blank=False,
            write_only=True,
        ),
        allow_empty=False,
        required=True,
        help_text='an array of course run keys',
    )
    notify = serializers.BooleanField(
        required=True,
        help_text='a boolean indicating whether to notify learners or not',
    )

    class Meta:
        fields = [
            'emails',
            'course_run_keys',
            'notify',
        ]
