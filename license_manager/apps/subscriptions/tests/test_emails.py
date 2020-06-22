from django.core import mail
from django.test import TestCase

from license_manager.apps.subscriptions import constants, emails
from license_manager.apps.subscriptions.constants import ASSIGNED
from license_manager.apps.subscriptions.tests.utils import (
    assert_last_remind_date_correct,
    make_test_email_data,
)


class EmailTests(TestCase):
    def setUp(self):
        super().setUp()
        test_email_data = make_test_email_data()
        self.subscription_plan = test_email_data['subscription_plan']
        self.custom_template_text = test_email_data['custom_template_text']
        self.email_recipient_list = test_email_data['email_recipient_list']

        self.license = test_email_data['license']
        self.license.status = ASSIGNED
        self.license.subscription_plan = self.subscription_plan
        self.license.user_email = self.email_recipient_list[0]

    def test_send_activation_emails(self):
        """
        Tests that activation emails are correctly sent.
        """
        emails.send_activation_emails(
            self.custom_template_text,
            self.email_recipient_list,
            self.subscription_plan,
        )
        self.assertEqual(
            len(mail.outbox),
            len(self.email_recipient_list)
        )
        # Verify the contents of the first message
        message = mail.outbox[0]
        self.assertEqual(message.subject, constants.LICENSE_ACTIVATION_EMAIL_SUBJECT)
        self.assertFalse('Reminder' in message.body)

    def test_send_reminder_emails(self):
        """
        Tests that reminder emails are correctly sent.
        """
        user_emails = [self.license.user_email]
        emails.send_reminder_emails(
            self.custom_template_text,
            user_emails,
            self.subscription_plan,
        )
        self.assertEqual(
            len(mail.outbox),
            len(user_emails)
        )
        # Verify the contents of the first message
        message = mail.outbox[0]
        self.assertEqual(message.subject, constants.LICENSE_REMINDER_EMAIL_SUBJECT)
        # Verify that 'Reminder' does show up for the reminder case
        self.assertTrue('Reminder' in message.body)
        # Verify the 'last_remind_date' of all licenses have been updated
        assert_last_remind_date_correct([self.license], True)
