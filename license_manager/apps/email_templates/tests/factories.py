import random
from uuid import uuid4

import factory

from license_manager.apps.email_templates.models import EmailTemplate


EMAIL_TEMPLATE_TYPES = [EmailTemplate.ASSIGN, EmailTemplate.REMIND, EmailTemplate.REVOKE]


def get_random_email_type():
    """
    Returns a random email type from EmailTemplate.EMAIL_TEMPLATE_TYPES.
    """
    return random.choice(EmailTemplate.EMAIL_TEMPLATE_TYPES)


class EmailTemplateFactory(factory.DjangoModelFactory):
    """
    Test factory for the `EmailTemplate` model.
    """
    class Meta:
        model = EmailTemplate

    name = factory.Faker('sentence', nb_words=4)
    enterprise_customer = factory.LazyFunction(uuid4)
    email_type = factory.LazyFunction(get_random_email_type)
    email_subject = factory.Faker('sentence', nb_words=5)
    email_greeting = factory.Faker('sentence', nb_words=5)
    email_closing = factory.Faker('sentence', nb_words=5)
    active = True
