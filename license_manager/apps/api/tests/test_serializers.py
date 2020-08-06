"""
Tests for the license-manager API serializers.
"""
from uuid import uuid4

import ddt
from django.test import TestCase
from mock import Mock
from rest_framework.exceptions import ErrorDetail

from license_manager.apps.api.serializers import EmailTemplateSerializer
from license_manager.apps.email_templates.constants import (
    OFFER_ASSIGNMENT_EMAIL_SUBJECT_LIMIT,
    OFFER_ASSIGNMENT_EMAIL_TEMPLATE_FIELD_LIMIT,
)
from license_manager.apps.email_templates.models import EmailTemplate
from license_manager.apps.email_templates.tests.factories import (
    EmailTemplateFactory,
)


@ddt.ddt
class EmailTemplateSerializerTests(TestCase):
    """
    Validate the behavior of email template serializer.
    """
    def setUp(self):
        """
        Setup an instance of EmailTemplateSerializer with appropriate data.
        """
        super().setUp()
        self.serializer = EmailTemplateSerializer()

    @ddt.data(
        (
            {
                'email_type': EmailTemplate.ASSIGN,
                'email_subject': 'Test subject',
            },
            {'name': [ErrorDetail('This field is required.', 'required')]},
        ),
        (
            {
                'name': 'Test Email Template',
                'email_type': EmailTemplate.ASSIGN,
            },
            {'email_subject': [ErrorDetail('This field is required.', 'required')]},
        ),
        (
            {
                'name': 'Test Email Template',
                'email_subject': 'Test subject',
            },
            {'email_type': [ErrorDetail('This field is required.', 'required')]},
        ),
    )
    @ddt.unpack
    def test_required_field_validations(self, data, expected_errors):
        """
        Validate that serializer validates all required fields are present.
        """
        serializer = EmailTemplateSerializer(data=data)

        assert not serializer.is_valid()
        assert serializer.errors == expected_errors

    @ddt.data(
        (
            {
                'name': 'Test Name',
                'email_type': EmailTemplate.ASSIGN,
                'email_subject': 'S' * (OFFER_ASSIGNMENT_EMAIL_SUBJECT_LIMIT + 1),
                'email_greeting': 'G' * (OFFER_ASSIGNMENT_EMAIL_TEMPLATE_FIELD_LIMIT + 1),
                'email_closing': 'C' * (OFFER_ASSIGNMENT_EMAIL_TEMPLATE_FIELD_LIMIT + 1),
            },
            {
                'email_subject': [
                    ErrorDetail(
                        'Email subject must be {} characters or less'.format(OFFER_ASSIGNMENT_EMAIL_SUBJECT_LIMIT),
                        'invalid',
                    )
                ],
                'email_greeting': [
                    ErrorDetail(
                        'Email greeting must be {} characters or less'.format(
                            OFFER_ASSIGNMENT_EMAIL_TEMPLATE_FIELD_LIMIT
                        ),
                        'invalid',
                    )
                ],
                'email_closing': [
                    ErrorDetail(
                        'Email closing must be {} characters or less'.format(
                            OFFER_ASSIGNMENT_EMAIL_TEMPLATE_FIELD_LIMIT
                        ),
                        'invalid',
                    )
                ],
            },
        ),
    )
    @ddt.unpack
    def test_field_validations(self, data, expected_errors):
        """
        Validate that serializer data is properly validated and in case of errors,
        readable error messages are displayed.
        """
        serializer = EmailTemplateSerializer(data=data)

        assert not serializer.is_valid()
        assert serializer.errors == expected_errors

    @staticmethod
    def test_validate_create():
        """
        Validate that new instance is created if validations are successful.
        """
        enterprise_customer_uuid = uuid4()

        EmailTemplateFactory(
            enterprise_customer=enterprise_customer_uuid,
            email_type=EmailTemplate.ASSIGN,
        )
        data = {
            'name': 'Test Name',
            'email_type': EmailTemplate.ASSIGN,
            'email_subject': 'SUBJECT',
            'email_greeting': 'GREETING',
            'email_closing': 'CLOSING',
        }
        serializer = EmailTemplateSerializer(
            data=data,
            context={'view': Mock(kwargs={'enterprise_customer': enterprise_customer_uuid})},
        )

        assert serializer.is_valid()
        serializer.create(serializer.validated_data)

        # Validate the new record after saving.
        assert EmailTemplate.objects.filter(
            enterprise_customer=enterprise_customer_uuid,
            email_type=EmailTemplate.ASSIGN,
            active=True,
        ).count() == 1

        # Validate the existing record is not active.
        assert EmailTemplate.objects.filter(
            enterprise_customer=enterprise_customer_uuid,
            email_type=EmailTemplate.ASSIGN,
            active=False,
        ).count() == 1
