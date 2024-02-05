"""
Helper to generate assignment input
CSVs of fake email data.
"""
import csv
import math

import click

DEFAULT_EMAIL_TEMPLATE = 'testuser+{}@example.com'


def generate_multi_plan_input(
    subscription_plan_identifiers, number_in_plan,
    email_template, filename, subscription_plan_fieldname='university_name',
):
    total = len(subscription_plan_identifiers) * sum(number_in_plan)
    order_mag = math.ceil(math.log(total, 10))

    with open(filename, 'w') as file_out:
        fieldnames = ['email', subscription_plan_fieldname]
        writer = csv.DictWriter(file_out, fieldnames)
        writer.writeheader()

        # This offset helps us generate emails
        # that are unique across all sub plan identifiers that we iterate.
        offset = 0
        for plan_id, num_emails_for_plan in zip(subscription_plan_identifiers, number_in_plan):
            for index in range(offset, offset + num_emails_for_plan):
                email = email_template.format(
                    str(index).zfill(order_mag)
                )
                writer.writerow({'email': email, subscription_plan_fieldname: plan_id})
            offset = index + 1


@click.command
@click.option(
    '--subscription-plan-identifier', '-s',
    multiple=True,
    help='One or more subscription plan identifier, comma-separated. Could be a uuid or an external name.',
)
@click.option(
    '--subscription-plan-fieldname', '-n',
    help='Name of output field corresponding to subscription plans',
    default='university_name',
    show_default=True,
)
@click.option(
    '--number-in-plan', '-n',
    multiple=True,
    help='One or more: Number of emails to generate in each plan.',
    show_default=True,
)
@click.option(
    '--email-template',
    default=DEFAULT_EMAIL_TEMPLATE,
    help='Optional python string template to use for email address generation, must take exactly one argument',
)
@click.option(
    '--filename',
    help='Where to write the generated file.',
)
def run(
    subscription_plan_identifier, subscription_plan_fieldname, number_in_plan,
    email_template, filename,
):
    number_in_plan = [int(s) for s in number_in_plan]
    generate_multi_plan_input(
        subscription_plan_identifier, number_in_plan, email_template,
        filename, subscription_plan_fieldname,
    )


if __name__ == '__main__':
    run()
