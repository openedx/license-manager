import mock

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
        self.license.user_email = self.email_recipient_list[0]
        self.license.save()

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
            self.license.subscription_plan,
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

    @mock.patch('license_manager.apps.subscriptions.emails.mail.get_connection')
    def test_send_reminder_email_failure_no_remind_date_update(self, mock_get_connection):
        """
        Tests that when sending the remind email fails, last_remind_date is not updated
        """
        mock_get_connection.send_messages.side_effect = Exception('Test Exception')
        emails.send_reminder_emails(
            self.custom_template_text,
            [self.license.user_email],
            self.license.subscription_plan,
        )
        # Verify no messages were sent
        self.assertEqual(len(mail.outbox), 0)
        # Verify the 'last_remind_date' was not updated
        assert_last_remind_date_correct([self.license], False)
