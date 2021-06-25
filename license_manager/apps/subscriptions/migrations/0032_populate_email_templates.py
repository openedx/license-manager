from license_manager.apps.subscriptions.models import PlanType
from django.db import migrations


def generate_email_templates(apps, schema_editor):
    SubscriptionPlanTemplate = apps.get_model("subscriptions", "PlanEmailTemplates")
    PlanType = apps.get_model('subscriptions', 'PlanType')

    standard_plan = PlanType.objects.filter(id=1).get()
    SubscriptionPlanTemplate.objects.get_or_create(
        subject_line='Start your edX Subscription',
        template_type='activation',
        plan_type=standard_plan,
        plaintext_template="""
{% load i18n %}

{{ TEMPLATE_GREETING }}

{% with enterprise_text=ENTERPRISE_NAME|add:" has partnered with edX to give you an unlimited subscription to learn on edX!" %}
    {% trans enterprise_text %}
    {% trans " Take the best courses in the most in-demand subject areas and upskill for a new career opportunity." %}
    {% trans " Earn a professional certificate, start a program or just learn for fun." %}
{% endwith %}

{% trans "Activate Your License " %}{{ LICENSE_ACTIVATION_LINK }}

{% trans "About edX" %}

{% trans "Since 2012, edX has been committed to increasing access to high-quality education for everyone, everywhere. By harnessing the transformative power of education through online learning, edX empowers learners to unlock their potential and become changemakers." %}

{% trans "We are excited to welcome you to our growing community of over 35 million users and 15 thousand instructors from 160 partner universities and organizations." %}

{{ TEMPLATE_CLOSING }}
        """,
        html_template="""
{% extends "email/email_base.html" %}
{% load i18n %}
{% block body %}
    <!-- Message Body -->
    <p>
        {% filter force_escape %}
            {{ TEMPLATE_GREETING }}
        {% endfilter %}
    </p>
    <p>
        {% with enterprise_text=ENTERPRISE_NAME|add:" has partnered with edX to give you an unlimited subscription to learn on edX!" %}
            {% trans enterprise_text %}
            {% trans "Take the best courses in the most in-demand subject areas and upskill for a new career opportunity." %}
            {% trans "Earn a professional certificate, start a program or just learn for fun." %}
        {% endwith %}
    </p>
    <p>
        <a href="{{ LICENSE_ACTIVATION_LINK }}"
        style="
            color: #ffffff;
            text-decoration: none;
            border-radius: 4px;
            -webkit-border-radius: 4px;
            -moz-border-radius: 4px;
            background-color: #002b2b;
            padding: 12px 50px;
            display: inline-block;
        ">
            {# old email clients require the use of the font tag :( #}
            <font color="#ffffff"><b>{% trans "Activate Your License" %}</b></font>
        </a>
    </p>
    <p>
        <b>{% trans "About edX" %}</b>
    </p>
    <p>
        {% trans "Since 2012, edX has been committed to increasing access to high-quality education for everyone, everywhere. By harnessing the transformative power of education through online learning, edX empowers learners to unlock their potential and become changemakers." %}
    </p>
    <p>
        {% trans "We are excited to welcome you to our growing community of over 35 million users and 15 thousand instructors from 160 partner universities and organizations." %}
    </p>
    <p>
        {% filter force_escape %}
            {{ TEMPLATE_CLOSING }}
        {% endfilter %}
    </p>
    <!-- End Message Body -->
{% endblock body %}
        """,
    )
    SubscriptionPlanTemplate.objects.get_or_create(
        subject_line='Your edX License is pending',
        template_type='reminder',
        plan_type=standard_plan,
        plaintext_template="""
{% load i18n %}

{{ TEMPLATE_GREETING }}

{% with enterprise_text=ENTERPRISE_NAME|add:" partnered with edX to give everyone access to high-quality online courses." %}
    {% trans enterprise_text %}
    {% trans " Start your subscription and browse courses in nearly every subject including Data Analytics, Digital Media, Business & Leadership, Communications, Computer Science and so much more." %}
    {% trans " Courses are taught by experts from the world’s leading universities and corporations." %}
{% endwith %}

{% trans "Start Learning " %}{{ LICENSE_ACTIVATION_LINK }}

{% trans "So you don't have to search for this link, bookmark your learning portal now to have easy access to your subscription in the future: " %}{{ LEARNER_PORTAL_LINK }}

{% trans "My Learning Portal" %}

{{ TEMPLATE_CLOSING }}
        """,
        html_template="""
{% extends "email/email_base.html" %}
{% load i18n %}
{% block body %}
    <!-- Message Body -->
    <p>
        {% filter force_escape %}
            {{ TEMPLATE_GREETING }}
        {% endfilter %}
    </p>
    <p>
        {% with enterprise_text=ENTERPRISE_NAME|add:" partnered with edX to give everyone access to high-quality online courses." %}
            {% trans enterprise_text %}
            {% trans " Start your subscription and browse courses in nearly every subject including Data Analytics, Digital Media, Business & Leadership, Communications, Computer Science and so much more." %}
            {% trans " Courses are taught by experts from the world’s leading universities and corporations." %}
        {% endwith %}
    </p>
    <p>
        <a href="{{ LICENSE_ACTIVATION_LINK }}"
        style="
            color: #ffffff;
            text-decoration: none;
            border-radius: 4px;
            -webkit-border-radius: 4px;
            -moz-border-radius: 4px;
            background-color: #002b2b;
            padding: 12px 50px;
            display: inline-block;
        ">
            {# old email clients require the use of the font tag :( #}
            <font color="#ffffff"><b>{% trans "Start Learning" %}</b></font>
        </a>
    </p>
    <p>
        {% trans "So you don't have to search for this link, bookmark your learning portal now to have easy access to your subscription in the future: " %}
    </p>
    <p>
        <a href="{{ LEARNER_PORTAL_LINK }}"
        style="
            color: #0d7d4d;
            text-decoration: none;
            border-radius: 4px;
            background-color: #ffffff;
            border: 3px solid #0d7d4d;
            display: inline-block;
            padding: 12px 50px;
        ">
            <font color="#0d7d4d"><b>{% trans "My Learning Portal" %}</b></font>
        </a>
    </p>
    <p>
        {% filter force_escape %}
            {{ TEMPLATE_CLOSING }}
        {% endfilter %}
    </p>
    <!-- End Message Body -->
{% endblock body %}
        """,
    )
    SubscriptionPlanTemplate.objects.get_or_create(
        subject_line='Welcome to edX Subscriptions!',
        template_type='onboarding',
        plan_type=standard_plan,
        plaintext_template="""
{% blocktrans trimmed %}
On behalf of edX, we're excited to have you join our global community of over 35 million learners! Your edX
subscription is a special benefit for you through your affiliation with {{ ENTERPRISE_NAME }}.
{% endblocktrans %}

{% trans "Get started learning on edX now by following the steps below:" %}

{% trans "1. Bookmark your Learner Portal" %}
{% blocktrans trimmed %}
Your {{ ENTERPRISE_NAME }} Learner Portal is your home base to see all of the courses included in your
{{ ENTERPRISE_NAME }} subscription catalog. This link is unique for {{ ENTERPRISE_NAME }} subscribers so be sure to add
it to your bookmarks!
{% endblocktrans %}
{% trans "Your Learner Portal: " %}{{ LICENSE_ACTIVATION_LINK }}

{% trans "2. Find a course" %}
{% blocktrans trimmed %}
Click "Find a Course" above the banner. You can search for subjects, course names, and content providers. Once you find
the right course, click "Enroll". You can even save courses you are interested in for later.
{% endblocktrans %}

{% trans "3. Enroll and start your journey" %}
{% blocktrans trimmed %}
The edX learner support team is available to answer any questions. Use the great information at our Help Center
({{ HELP_CENTER_URL }}), or use info@edx.org to contact us.
{% endblocktrans %}

{% trans "We hope you love learning on edX!" %}

        """,
        html_template="""
{% extends "email/email_base.html" %}
{% load i18n %}
{% load static %}
{% block body %}
    <!-- Message Body -->
    <h2>
        {% trans "Welcome to edX Subscriptions!" %}
    </h2>
    <p>
        {% trans "On behalf of edX, we're excited to have you join our global community of over 35 million learners!" %}
        {% blocktrans %}
            Your edX subscription is a special benefit for you through your affiliation with {{ ENTERPRISE_NAME }}.
        {% endblocktrans %}
    </p>
    <p>
        {% trans "Get started learning on edX now by following the steps below:" %}
    </p>
    <table>
        <tr>
            <td>
                <img src="{% static 'img/edX_Icon_CGvirtualproctor_2.png' %}"
                     alt=""
                     height="100"
                     width="100"
                >
            </td>
            <td style="padding-left: 20px">
                <h3>
                    {% trans "1. Bookmark your Learner Portal" %}
                </h3>
                <p>
                    {% blocktrans trimmed %}
                        Your {{ ENTERPRISE_NAME }} Learner Portal is your home base to see all of the courses included
                        in your {{ ENTERPRISE_NAME }} subscription catalog. This link is unique for
                        {{ ENTERPRISE_NAME }} subscribers so be sure to add it to your bookmarks!
                    {% endblocktrans %}
                </p>
            </td>
        </tr>
        <tr>
            <td>
                <!-- Empty column to force button alignment with second column -->
            </td>
            <td style="padding-left: 20px">
                <p>
                    <a href="{{ LEARNER_PORTAL_LINK|safe }}"
                    style="
                        color: #ffffff;
                        text-decoration: none;
                        border-radius: 4px;
                        -webkit-border-radius: 4px;
                        -moz-border-radius: 4px;
                        background-color: #002b2b;
                        padding: 12px 50px;
                        display: inline-block;
                    ">
                        {# old email clients require the use of the font tag :( #}
                        <font color="#ffffff"><b>{% trans "Your Learner Portal" %}</b></font>
                    </a>
                </p>
            </td>
        </tr>
        <tr>
            <td>
                <img src="{% static 'img/edX_Icon_1000courses.png' %}"
                     alt=""
                     height="100"
                     width="100"
                >
            </td>
            <td style="padding-left: 20px">
                <h3>
                    {% trans "2. Find a course" %}
                </h3>
                <p>
                    {% blocktrans trimmed %}
                        Click "Find a Course" above the banner. You can search for subjects, course names, and content
                        providers. Once you find the right course, click "Enroll". You can even save courses you are
                        interested in for later.
                    {% endblocktrans %}
                </p>
            </td>
        </tr>
        <tr>
            <td>
                <img src="{% static 'img/edX_Icon_LearningNeuroscience.png' %}"
                     alt=""
                     height="100"
                     width="100"
                >
            </td>
            <td style="padding-left: 20px">
                <h3>
                    {% trans "3. Enroll and start your journey" %}
                </h3>
                <p>
                    {% blocktrans trimmed %}
                        The edX learner support team is available to answer any questions. Use the great information at
                        our <a href="{{ HELP_CENTER_URL|safe }}">Help Center</a>, or use
                        <a href="mailto:info@edx.org">info@edx.org</a> to contact us.
                    {% endblocktrans %}
                </p>
            </td>
        </tr>
    </table>
    <hr style="margin: 20px 0;" />
    <p>
        {% trans "We hope you love learning on edX!" %}
    </p>
    <!-- End Message Body -->
{% endblock body %}
        """,
    )
    oce_plan = PlanType.objects.filter(id=2).get()
    SubscriptionPlanTemplate.objects.get_or_create(
        subject_line='Start your edX Subscription',
        template_type='activation',
        plan_type=oce_plan,
        plaintext_template="""
{% load i18n %}

{{ TEMPLATE_GREETING }}

{% with enterprise_text=ENTERPRISE_NAME|add:" has partnered with edX to give you an unlimited subscription to learn on edX!" %}
    {% trans enterprise_text %}
    {% trans " Take the best courses in the most in-demand subject areas and upskill for a new career opportunity." %}
    {% trans " Earn a professional certificate, start a program or just learn for fun." %}
{% endwith %}

{% trans "Activate Your License " %}{{ LICENSE_ACTIVATION_LINK }}

{% trans "About edX" %}

{% trans "Since 2012, edX has been committed to increasing access to high-quality education for everyone, everywhere. By harnessing the transformative power of education through online learning, edX empowers learners to unlock their potential and become changemakers." %}

{% trans "We are excited to welcome you to our growing community of over 35 million users and 15 thousand instructors from 160 partner universities and organizations." %}

{{ TEMPLATE_CLOSING }}
        """,
        html_template="""
        {% extends "email/email_base.html" %}
{% load i18n %}
{% block body %}
    <!-- Message Body -->
    <p>
        {% filter force_escape %}
            {{ TEMPLATE_GREETING }}
        {% endfilter %}
    </p>
    <p>
        {% with enterprise_text=ENTERPRISE_NAME|add:" has partnered with edX to give you an unlimited subscription to learn on edX!" %}
            {% trans enterprise_text %}
            {% trans "Take the best courses in the most in-demand subject areas and upskill for a new career opportunity." %}
            {% trans "Earn a professional certificate, start a program or just learn for fun." %}
        {% endwith %}
    </p>
    <p>
        <a href="{{ LICENSE_ACTIVATION_LINK }}"
        style="
            color: #ffffff;
            text-decoration: none;
            border-radius: 4px;
            -webkit-border-radius: 4px;
            -moz-border-radius: 4px;
            background-color: #002b2b;
            padding: 12px 50px;
            display: inline-block;
        ">
            {# old email clients require the use of the font tag :( #}
            <font color="#ffffff"><b>{% trans "Activate Your License" %}</b></font>
        </a>
    </p>
    <p>
        <b>{% trans "About edX" %}</b>
    </p>
    <p>
        {% trans "Since 2012, edX has been committed to increasing access to high-quality education for everyone, everywhere. By harnessing the transformative power of education through online learning, edX empowers learners to unlock their potential and become changemakers." %}
    </p>
    <p>
        {% trans "We are excited to welcome you to our growing community of over 35 million users and 15 thousand instructors from 160 partner universities and organizations." %}
    </p>
    <p>
        {% filter force_escape %}
            {{ TEMPLATE_CLOSING }}
        {% endfilter %}
    </p>
    <!-- End Message Body -->
{% endblock body %}
        """,
    )
    SubscriptionPlanTemplate.objects.get_or_create(
        subject_line='Your edX License is pending',
        template_type='reminder',
        plan_type=oce_plan,
        plaintext_template="""
{% load i18n %}

{{ TEMPLATE_GREETING }}

{% with enterprise_text=ENTERPRISE_NAME|add:" partnered with edX to give everyone access to high-quality online courses." %}
    {% trans enterprise_text %}
    {% trans " Start your subscription and browse courses in nearly every subject including Data Analytics, Digital Media, Business & Leadership, Communications, Computer Science and so much more." %}
    {% trans " Courses are taught by experts from the world’s leading universities and corporations." %}
{% endwith %}

{% trans "Start Learning " %}{{ LICENSE_ACTIVATION_LINK }}

{% trans "So you don't have to search for this link, bookmark your learning portal now to have easy access to your subscription in the future: " %}{{ LEARNER_PORTAL_LINK }}

{% trans "My Learning Portal" %}

{{ TEMPLATE_CLOSING }}
        """,
        html_template="""
{% extends "email/email_base.html" %}
{% load i18n %}
{% block body %}
    <!-- Message Body -->
    <p>
        {% filter force_escape %}
            {{ TEMPLATE_GREETING }}
        {% endfilter %}
    </p>
    <p>
        {% with enterprise_text=ENTERPRISE_NAME|add:" partnered with edX to give everyone access to high-quality online courses." %}
            {% trans enterprise_text %}
            {% trans " Start your subscription and browse courses in nearly every subject including Data Analytics, Digital Media, Business & Leadership, Communications, Computer Science and so much more." %}
            {% trans " Courses are taught by experts from the world’s leading universities and corporations." %}
        {% endwith %}
    </p>
    <p>
        <a href="{{ LICENSE_ACTIVATION_LINK }}"
        style="
            color: #ffffff;
            text-decoration: none;
            border-radius: 4px;
            -webkit-border-radius: 4px;
            -moz-border-radius: 4px;
            background-color: #002b2b;
            padding: 12px 50px;
            display: inline-block;
        ">
            {# old email clients require the use of the font tag :( #}
            <font color="#ffffff"><b>{% trans "Start Learning" %}</b></font>
        </a>
    </p>
    <p>
        {% trans "So you don't have to search for this link, bookmark your learning portal now to have easy access to your subscription in the future: " %}
    </p>
    <p>
        <a href="{{ LEARNER_PORTAL_LINK }}"
        style="
            color: #0d7d4d;
            text-decoration: none;
            border-radius: 4px;
            background-color: #ffffff;
            border: 3px solid #0d7d4d;
            display: inline-block;
            padding: 12px 50px;
        ">
            <font color="#0d7d4d"><b>{% trans "My Learning Portal" %}</b></font>
        </a>
    </p>
    <p>
        {% filter force_escape %}
            {{ TEMPLATE_CLOSING }}
        {% endfilter %}
    </p>
    <!-- End Message Body -->
{% endblock body %}
        """,
    )
    SubscriptionPlanTemplate.objects.get_or_create(
        subject_line='Welcome to edX Subscriptions!',
        template_type='onboarding',
        plan_type=oce_plan,
        plaintext_template="""
{% blocktrans trimmed %}
On behalf of edX, we're excited to have you join our global community of over 35 million learners! Your edX
subscription is a special benefit for you through your affiliation with {{ ENTERPRISE_NAME }}.
{% endblocktrans %}

{% trans "Get started learning on edX now by following the steps below:" %}

{% trans "1. Bookmark your Learner Portal" %}
{% blocktrans trimmed %}
Your {{ ENTERPRISE_NAME }} Learner Portal is your home base to see all of the courses included in your
{{ ENTERPRISE_NAME }} subscription catalog. This link is unique for {{ ENTERPRISE_NAME }} subscribers so be sure to add
it to your bookmarks!
{% endblocktrans %}
{% trans "Your Learner Portal: " %}{{ LICENSE_ACTIVATION_LINK }}

{% trans "2. Find a course" %}
{% blocktrans trimmed %}
Click "Find a Course" above the banner. You can search for subjects, course names, and content providers. Once you find
the right course, click "Enroll". You can even save courses you are interested in for later.
{% endblocktrans %}

{% trans "3. Enroll and start your journey" %}
{% blocktrans trimmed %}
The edX learner support team is available to answer any questions. Use the great information at our Help Center
({{ HELP_CENTER_URL }}), or use info@edx.org to contact us.
{% endblocktrans %}

{% trans "We hope you love learning on edX!" %}

        """,
        html_template="""
{% extends "email/email_base.html" %}
{% load i18n %}
{% load static %}
{% block body %}
    <!-- Message Body -->
    <h2>
        {% trans "Welcome to edX Subscriptions!" %}
    </h2>
    <p>
        {% trans "On behalf of edX, we're excited to have you join our global community of over 35 million learners!" %}
        {% blocktrans %}
            Your edX subscription is a special benefit for you through your affiliation with {{ ENTERPRISE_NAME }}.
        {% endblocktrans %}
    </p>
    <p>
        {% trans "Get started learning on edX now by following the steps below:" %}
    </p>
    <table>
        <tr>
            <td>
                <img src="{% static 'img/edX_Icon_CGvirtualproctor_2.png' %}"
                     alt=""
                     height="100"
                     width="100"
                >
            </td>
            <td style="padding-left: 20px">
                <h3>
                    {% trans "1. Bookmark your Learner Portal" %}
                </h3>
                <p>
                    {% blocktrans trimmed %}
                        Your {{ ENTERPRISE_NAME }} Learner Portal is your home base to see all of the courses included
                        in your {{ ENTERPRISE_NAME }} subscription catalog. This link is unique for
                        {{ ENTERPRISE_NAME }} subscribers so be sure to add it to your bookmarks!
                    {% endblocktrans %}
                </p>
            </td>
        </tr>
        <tr>
            <td>
                <!-- Empty column to force button alignment with second column -->
            </td>
            <td style="padding-left: 20px">
                <p>
                    <a href="{{ LEARNER_PORTAL_LINK|safe }}"
                    style="
                        color: #ffffff;
                        text-decoration: none;
                        border-radius: 4px;
                        -webkit-border-radius: 4px;
                        -moz-border-radius: 4px;
                        background-color: #002b2b;
                        padding: 12px 50px;
                        display: inline-block;
                    ">
                        {# old email clients require the use of the font tag :( #}
                        <font color="#ffffff"><b>{% trans "Your Learner Portal" %}</b></font>
                    </a>
                </p>
            </td>
        </tr>
        <tr>
            <td>
                <img src="{% static 'img/edX_Icon_1000courses.png' %}"
                     alt=""
                     height="100"
                     width="100"
                >
            </td>
            <td style="padding-left: 20px">
                <h3>
                    {% trans "2. Find a course" %}
                </h3>
                <p>
                    {% blocktrans trimmed %}
                        Click "Find a Course" above the banner. You can search for subjects, course names, and content
                        providers. Once you find the right course, click "Enroll". You can even save courses you are
                        interested in for later.
                    {% endblocktrans %}
                </p>
            </td>
        </tr>
        <tr>
            <td>
                <img src="{% static 'img/edX_Icon_LearningNeuroscience.png' %}"
                     alt=""
                     height="100"
                     width="100"
                >
            </td>
            <td style="padding-left: 20px">
                <h3>
                    {% trans "3. Enroll and start your journey" %}
                </h3>
                <p>
                    {% blocktrans trimmed %}
                        The edX learner support team is available to answer any questions. Use the great information at
                        our <a href="{{ HELP_CENTER_URL|safe }}">Help Center</a>, or use
                        <a href="mailto:info@edx.org">info@edx.org</a> to contact us.
                    {% endblocktrans %}
                </p>
            </td>
        </tr>
    </table>
    <hr style="margin: 20px 0;" />
    <p>
        {% trans "We hope you love learning on edX!" %}
    </p>
    <!-- End Message Body -->
{% endblock body %}
        """,
    )
    trials_plan = PlanType.objects.filter(id=3).get()
    SubscriptionPlanTemplate.objects.get_or_create(
        subject_line='Start your edX Subscription',
        template_type='activation',
        plan_type=trials_plan,
        plaintext_template="""
{% load i18n %}

{{ TEMPLATE_GREETING }}

{% with enterprise_text=ENTERPRISE_NAME|add:" has partnered with edX to give you an unlimited subscription to learn on edX!" %}
    {% trans enterprise_text %}
    {% trans " Take the best courses in the most in-demand subject areas and upskill for a new career opportunity." %}
    {% trans " Earn a professional certificate, start a program or just learn for fun." %}
{% endwith %}

{% trans "Activate Your License " %}{{ LICENSE_ACTIVATION_LINK }}

{% trans "About edX" %}

{% trans "Since 2012, edX has been committed to increasing access to high-quality education for everyone, everywhere. By harnessing the transformative power of education through online learning, edX empowers learners to unlock their potential and become changemakers." %}

{% trans "We are excited to welcome you to our growing community of over 35 million users and 15 thousand instructors from 160 partner universities and organizations." %}

{{ TEMPLATE_CLOSING }}
        """,
        html_template="""
        {% extends "email/email_base.html" %}
{% load i18n %}
{% block body %}
    <!-- Message Body -->
    <p>
        {% filter force_escape %}
            {{ TEMPLATE_GREETING }}
        {% endfilter %}
    </p>
    <p>
        {% with enterprise_text=ENTERPRISE_NAME|add:" has partnered with edX to give you an unlimited subscription to learn on edX!" %}
            {% trans enterprise_text %}
            {% trans "Take the best courses in the most in-demand subject areas and upskill for a new career opportunity." %}
            {% trans "Earn a professional certificate, start a program or just learn for fun." %}
        {% endwith %}
    </p>
    <p>
        <a href="{{ LICENSE_ACTIVATION_LINK }}"
        style="
            color: #ffffff;
            text-decoration: none;
            border-radius: 4px;
            -webkit-border-radius: 4px;
            -moz-border-radius: 4px;
            background-color: #002b2b;
            padding: 12px 50px;
            display: inline-block;
        ">
            {# old email clients require the use of the font tag :( #}
            <font color="#ffffff"><b>{% trans "Activate Your License" %}</b></font>
        </a>
    </p>
    <p>
        <b>{% trans "About edX" %}</b>
    </p>
    <p>
        {% trans "Since 2012, edX has been committed to increasing access to high-quality education for everyone, everywhere. By harnessing the transformative power of education through online learning, edX empowers learners to unlock their potential and become changemakers." %}
    </p>
    <p>
        {% trans "We are excited to welcome you to our growing community of over 35 million users and 15 thousand instructors from 160 partner universities and organizations." %}
    </p>
    <p>
        {% filter force_escape %}
            {{ TEMPLATE_CLOSING }}
        {% endfilter %}
    </p>
    <!-- End Message Body -->
{% endblock body %}
        """,
    )
    SubscriptionPlanTemplate.objects.get_or_create(
        subject_line='Your edX License is pending',
        template_type='reminder',
        plan_type=trials_plan,
        plaintext_template="""
{% load i18n %}

{{ TEMPLATE_GREETING }}

{% with enterprise_text=ENTERPRISE_NAME|add:" partnered with edX to give everyone access to high-quality online courses." %}
    {% trans enterprise_text %}
    {% trans " Start your subscription and browse courses in nearly every subject including Data Analytics, Digital Media, Business & Leadership, Communications, Computer Science and so much more." %}
    {% trans " Courses are taught by experts from the world’s leading universities and corporations." %}
{% endwith %}

{% trans "Start Learning " %}{{ LICENSE_ACTIVATION_LINK }}

{% trans "So you don't have to search for this link, bookmark your learning portal now to have easy access to your subscription in the future: " %}{{ LEARNER_PORTAL_LINK }}

{% trans "My Learning Portal" %}

{{ TEMPLATE_CLOSING }}
        """,
        html_template="""
{% extends "email/email_base.html" %}
{% load i18n %}
{% block body %}
    <!-- Message Body -->
    <p>
        {% filter force_escape %}
            {{ TEMPLATE_GREETING }}
        {% endfilter %}
    </p>
    <p>
        {% with enterprise_text=ENTERPRISE_NAME|add:" partnered with edX to give everyone access to high-quality online courses." %}
            {% trans enterprise_text %}
            {% trans " Start your subscription and browse courses in nearly every subject including Data Analytics, Digital Media, Business & Leadership, Communications, Computer Science and so much more." %}
            {% trans " Courses are taught by experts from the world’s leading universities and corporations." %}
        {% endwith %}
    </p>
    <p>
        <a href="{{ LICENSE_ACTIVATION_LINK }}"
        style="
            color: #ffffff;
            text-decoration: none;
            border-radius: 4px;
            -webkit-border-radius: 4px;
            -moz-border-radius: 4px;
            background-color: #002b2b;
            padding: 12px 50px;
            display: inline-block;
        ">
            {# old email clients require the use of the font tag :( #}
            <font color="#ffffff"><b>{% trans "Start Learning" %}</b></font>
        </a>
    </p>
    <p>
        {% trans "So you don't have to search for this link, bookmark your learning portal now to have easy access to your subscription in the future: " %}
    </p>
    <p>
        <a href="{{ LEARNER_PORTAL_LINK }}"
        style="
            color: #0d7d4d;
            text-decoration: none;
            border-radius: 4px;
            background-color: #ffffff;
            border: 3px solid #0d7d4d;
            display: inline-block;
            padding: 12px 50px;
        ">
            <font color="#0d7d4d"><b>{% trans "My Learning Portal" %}</b></font>
        </a>
    </p>
    <p>
        {% filter force_escape %}
            {{ TEMPLATE_CLOSING }}
        {% endfilter %}
    </p>
    <!-- End Message Body -->
{% endblock body %}
        """,
    )
    SubscriptionPlanTemplate.objects.get_or_create(
        subject_line='Welcome to edX Subscriptions!',
        template_type='onboarding',
        plan_type=trials_plan,
        plaintext_template="""
{% blocktrans trimmed %}
On behalf of edX, we're excited to have you join our global community of over 35 million learners! Your edX
subscription is a special benefit for you through your affiliation with {{ ENTERPRISE_NAME }}.
{% endblocktrans %}

{% trans "Get started learning on edX now by following the steps below:" %}

{% trans "1. Bookmark your Learner Portal" %}
{% blocktrans trimmed %}
Your {{ ENTERPRISE_NAME }} Learner Portal is your home base to see all of the courses included in your
{{ ENTERPRISE_NAME }} subscription catalog. This link is unique for {{ ENTERPRISE_NAME }} subscribers so be sure to add
it to your bookmarks!
{% endblocktrans %}
{% trans "Your Learner Portal: " %}{{ LICENSE_ACTIVATION_LINK }}

{% trans "2. Find a course" %}
{% blocktrans trimmed %}
Click "Find a Course" above the banner. You can search for subjects, course names, and content providers. Once you find
the right course, click "Enroll". You can even save courses you are interested in for later.
{% endblocktrans %}

{% trans "3. Enroll and start your journey" %}
{% blocktrans trimmed %}
The edX learner support team is available to answer any questions. Use the great information at our Help Center
({{ HELP_CENTER_URL }}), or use info@edx.org to contact us.
{% endblocktrans %}

{% trans "We hope you love learning on edX!" %}

        """,
        html_template="""
{% extends "email/email_base.html" %}
{% load i18n %}
{% load static %}
{% block body %}
    <!-- Message Body -->
    <h2>
        {% trans "Welcome to edX Subscriptions!" %}
    </h2>
    <p>
        {% trans "On behalf of edX, we're excited to have you join our global community of over 35 million learners!" %}
        {% blocktrans %}
            Your edX subscription is a special benefit for you through your affiliation with {{ ENTERPRISE_NAME }}.
        {% endblocktrans %}
    </p>
    <p>
        {% trans "Get started learning on edX now by following the steps below:" %}
    </p>
    <table>
        <tr>
            <td>
                <img src="{% static 'img/edX_Icon_CGvirtualproctor_2.png' %}"
                     alt=""
                     height="100"
                     width="100"
                >
            </td>
            <td style="padding-left: 20px">
                <h3>
                    {% trans "1. Bookmark your Learner Portal" %}
                </h3>
                <p>
                    {% blocktrans trimmed %}
                        Your {{ ENTERPRISE_NAME }} Learner Portal is your home base to see all of the courses included
                        in your {{ ENTERPRISE_NAME }} subscription catalog. This link is unique for
                        {{ ENTERPRISE_NAME }} subscribers so be sure to add it to your bookmarks!
                    {% endblocktrans %}
                </p>
            </td>
        </tr>
        <tr>
            <td>
                <!-- Empty column to force button alignment with second column -->
            </td>
            <td style="padding-left: 20px">
                <p>
                    <a href="{{ LEARNER_PORTAL_LINK|safe }}"
                    style="
                        color: #ffffff;
                        text-decoration: none;
                        border-radius: 4px;
                        -webkit-border-radius: 4px;
                        -moz-border-radius: 4px;
                        background-color: #002b2b;
                        padding: 12px 50px;
                        display: inline-block;
                    ">
                        {# old email clients require the use of the font tag :( #}
                        <font color="#ffffff"><b>{% trans "Your Learner Portal" %}</b></font>
                    </a>
                </p>
            </td>
        </tr>
        <tr>
            <td>
                <img src="{% static 'img/edX_Icon_1000courses.png' %}"
                     alt=""
                     height="100"
                     width="100"
                >
            </td>
            <td style="padding-left: 20px">
                <h3>
                    {% trans "2. Find a course" %}
                </h3>
                <p>
                    {% blocktrans trimmed %}
                        Click "Find a Course" above the banner. You can search for subjects, course names, and content
                        providers. Once you find the right course, click "Enroll". You can even save courses you are
                        interested in for later.
                    {% endblocktrans %}
                </p>
            </td>
        </tr>
        <tr>
            <td>
                <img src="{% static 'img/edX_Icon_LearningNeuroscience.png' %}"
                     alt=""
                     height="100"
                     width="100"
                >
            </td>
            <td style="padding-left: 20px">
                <h3>
                    {% trans "3. Enroll and start your journey" %}
                </h3>
                <p>
                    {% blocktrans trimmed %}
                        The edX learner support team is available to answer any questions. Use the great information at
                        our <a href="{{ HELP_CENTER_URL|safe }}">Help Center</a>, or use
                        <a href="mailto:info@edx.org">info@edx.org</a> to contact us.
                    {% endblocktrans %}
                </p>
            </td>
        </tr>
    </table>
    <hr style="margin: 20px 0;" />
    <p>
        {% trans "We hope you love learning on edX!" %}
    </p>
    <!-- End Message Body -->
{% endblock body %}
        """,
    )
    test_plan = PlanType.objects.filter(id=1).get()
    SubscriptionPlanTemplate.objects.get_or_create(
        subject_line='Start your edX Subscription',
        template_type='activation',
        plan_type=test_plan,
        plaintext_template="""
        {% load i18n %}

{{ TEMPLATE_GREETING }}

{% with enterprise_text=ENTERPRISE_NAME|add:" has partnered with edX to give you an unlimited subscription to learn on edX!" %}
    {% trans enterprise_text %}
    {% trans " Take the best courses in the most in-demand subject areas and upskill for a new career opportunity." %}
    {% trans " Earn a professional certificate, start a program or just learn for fun." %}
{% endwith %}

{% trans "Activate Your License " %}{{ LICENSE_ACTIVATION_LINK }}

{% trans "About edX" %}

{% trans "Since 2012, edX has been committed to increasing access to high-quality education for everyone, everywhere. By harnessing the transformative power of education through online learning, edX empowers learners to unlock their potential and become changemakers." %}

{% trans "We are excited to welcome you to our growing community of over 35 million users and 15 thousand instructors from 160 partner universities and organizations." %}

{{ TEMPLATE_CLOSING }}
        """,
        html_template="""
        {% extends "email/email_base.html" %}
{% load i18n %}
{% block body %}
    <!-- Message Body -->
    <p>
        {% filter force_escape %}
            {{ TEMPLATE_GREETING }}
        {% endfilter %}
    </p>
    <p>
        {% with enterprise_text=ENTERPRISE_NAME|add:" has partnered with edX to give you an unlimited subscription to learn on edX!" %}
            {% trans enterprise_text %}
            {% trans "Take the best courses in the most in-demand subject areas and upskill for a new career opportunity." %}
            {% trans "Earn a professional certificate, start a program or just learn for fun." %}
        {% endwith %}
    </p>
    <p>
        <a href="{{ LICENSE_ACTIVATION_LINK }}"
        style="
            color: #ffffff;
            text-decoration: none;
            border-radius: 4px;
            -webkit-border-radius: 4px;
            -moz-border-radius: 4px;
            background-color: #002b2b;
            padding: 12px 50px;
            display: inline-block;
        ">
            {# old email clients require the use of the font tag :( #}
            <font color="#ffffff"><b>{% trans "Activate Your License" %}</b></font>
        </a>
    </p>
    <p>
        <b>{% trans "About edX" %}</b>
    </p>
    <p>
        {% trans "Since 2012, edX has been committed to increasing access to high-quality education for everyone, everywhere. By harnessing the transformative power of education through online learning, edX empowers learners to unlock their potential and become changemakers." %}
    </p>
    <p>
        {% trans "We are excited to welcome you to our growing community of over 35 million users and 15 thousand instructors from 160 partner universities and organizations." %}
    </p>
    <p>
        {% filter force_escape %}
            {{ TEMPLATE_CLOSING }}
        {% endfilter %}
    </p>
    <!-- End Message Body -->
{% endblock body %}
        """,
    )
    SubscriptionPlanTemplate.objects.get_or_create(
        subject_line='Your edX License is pending',
        template_type='reminder',
        plan_type=test_plan,
        plaintext_template="""
{% load i18n %}

{{ TEMPLATE_GREETING }}

{% with enterprise_text=ENTERPRISE_NAME|add:" partnered with edX to give everyone access to high-quality online courses." %}
    {% trans enterprise_text %}
    {% trans " Start your subscription and browse courses in nearly every subject including Data Analytics, Digital Media, Business & Leadership, Communications, Computer Science and so much more." %}
    {% trans " Courses are taught by experts from the world’s leading universities and corporations." %}
{% endwith %}

{% trans "Start Learning " %}{{ LICENSE_ACTIVATION_LINK }}

{% trans "So you don't have to search for this link, bookmark your learning portal now to have easy access to your subscription in the future: " %}{{ LEARNER_PORTAL_LINK }}

{% trans "My Learning Portal" %}

{{ TEMPLATE_CLOSING }}
        """,
        html_template="""
{% extends "email/email_base.html" %}
{% load i18n %}
{% block body %}
    <!-- Message Body -->
    <p>
        {% filter force_escape %}
            {{ TEMPLATE_GREETING }}
        {% endfilter %}
    </p>
    <p>
        {% with enterprise_text=ENTERPRISE_NAME|add:" partnered with edX to give everyone access to high-quality online courses." %}
            {% trans enterprise_text %}
            {% trans " Start your subscription and browse courses in nearly every subject including Data Analytics, Digital Media, Business & Leadership, Communications, Computer Science and so much more." %}
            {% trans " Courses are taught by experts from the world’s leading universities and corporations." %}
        {% endwith %}
    </p>
    <p>
        <a href="{{ LICENSE_ACTIVATION_LINK }}"
        style="
            color: #ffffff;
            text-decoration: none;
            border-radius: 4px;
            -webkit-border-radius: 4px;
            -moz-border-radius: 4px;
            background-color: #002b2b;
            padding: 12px 50px;
            display: inline-block;
        ">
            {# old email clients require the use of the font tag :( #}
            <font color="#ffffff"><b>{% trans "Start Learning" %}</b></font>
        </a>
    </p>
    <p>
        {% trans "So you don't have to search for this link, bookmark your learning portal now to have easy access to your subscription in the future: " %}
    </p>
    <p>
        <a href="{{ LEARNER_PORTAL_LINK }}"
        style="
            color: #0d7d4d;
            text-decoration: none;
            border-radius: 4px;
            background-color: #ffffff;
            border: 3px solid #0d7d4d;
            display: inline-block;
            padding: 12px 50px;
        ">
            <font color="#0d7d4d"><b>{% trans "My Learning Portal" %}</b></font>
        </a>
    </p>
    <p>
        {% filter force_escape %}
            {{ TEMPLATE_CLOSING }}
        {% endfilter %}
    </p>
    <!-- End Message Body -->
{% endblock body %}
        """,
    )
    SubscriptionPlanTemplate.objects.get_or_create(
        subject_line='Welcome to edX Subscriptions!',
        template_type='onboarding',
        plan_type=test_plan,
        plaintext_template="""
{% blocktrans trimmed %}
On behalf of edX, we're excited to have you join our global community of over 35 million learners! Your edX
subscription is a special benefit for you through your affiliation with {{ ENTERPRISE_NAME }}.
{% endblocktrans %}

{% trans "Get started learning on edX now by following the steps below:" %}

{% trans "1. Bookmark your Learner Portal" %}
{% blocktrans trimmed %}
Your {{ ENTERPRISE_NAME }} Learner Portal is your home base to see all of the courses included in your
{{ ENTERPRISE_NAME }} subscription catalog. This link is unique for {{ ENTERPRISE_NAME }} subscribers so be sure to add
it to your bookmarks!
{% endblocktrans %}
{% trans "Your Learner Portal: " %}{{ LICENSE_ACTIVATION_LINK }}

{% trans "2. Find a course" %}
{% blocktrans trimmed %}
Click "Find a Course" above the banner. You can search for subjects, course names, and content providers. Once you find
the right course, click "Enroll". You can even save courses you are interested in for later.
{% endblocktrans %}

{% trans "3. Enroll and start your journey" %}
{% blocktrans trimmed %}
The edX learner support team is available to answer any questions. Use the great information at our Help Center
({{ HELP_CENTER_URL }}), or use info@edx.org to contact us.
{% endblocktrans %}

{% trans "We hope you love learning on edX!" %}

        """,
        html_template="""
{% extends "email/email_base.html" %}
{% load i18n %}
{% load static %}
{% block body %}
    <!-- Message Body -->
    <h2>
        {% trans "Welcome to edX Subscriptions!" %}
    </h2>
    <p>
        {% trans "On behalf of edX, we're excited to have you join our global community of over 35 million learners!" %}
        {% blocktrans %}
            Your edX subscription is a special benefit for you through your affiliation with {{ ENTERPRISE_NAME }}.
        {% endblocktrans %}
    </p>
    <p>
        {% trans "Get started learning on edX now by following the steps below:" %}
    </p>
    <table>
        <tr>
            <td>
                <img src="{% static 'img/edX_Icon_CGvirtualproctor_2.png' %}"
                     alt=""
                     height="100"
                     width="100"
                >
            </td>
            <td style="padding-left: 20px">
                <h3>
                    {% trans "1. Bookmark your Learner Portal" %}
                </h3>
                <p>
                    {% blocktrans trimmed %}
                        Your {{ ENTERPRISE_NAME }} Learner Portal is your home base to see all of the courses included
                        in your {{ ENTERPRISE_NAME }} subscription catalog. This link is unique for
                        {{ ENTERPRISE_NAME }} subscribers so be sure to add it to your bookmarks!
                    {% endblocktrans %}
                </p>
            </td>
        </tr>
        <tr>
            <td>
                <!-- Empty column to force button alignment with second column -->
            </td>
            <td style="padding-left: 20px">
                <p>
                    <a href="{{ LEARNER_PORTAL_LINK|safe }}"
                    style="
                        color: #ffffff;
                        text-decoration: none;
                        border-radius: 4px;
                        -webkit-border-radius: 4px;
                        -moz-border-radius: 4px;
                        background-color: #002b2b;
                        padding: 12px 50px;
                        display: inline-block;
                    ">
                        {# old email clients require the use of the font tag :( #}
                        <font color="#ffffff"><b>{% trans "Your Learner Portal" %}</b></font>
                    </a>
                </p>
            </td>
        </tr>
        <tr>
            <td>
                <img src="{% static 'img/edX_Icon_1000courses.png' %}"
                     alt=""
                     height="100"
                     width="100"
                >
            </td>
            <td style="padding-left: 20px">
                <h3>
                    {% trans "2. Find a course" %}
                </h3>
                <p>
                    {% blocktrans trimmed %}
                        Click "Find a Course" above the banner. You can search for subjects, course names, and content
                        providers. Once you find the right course, click "Enroll". You can even save courses you are
                        interested in for later.
                    {% endblocktrans %}
                </p>
            </td>
        </tr>
        <tr>
            <td>
                <img src="{% static 'img/edX_Icon_LearningNeuroscience.png' %}"
                     alt=""
                     height="100"
                     width="100"
                >
            </td>
            <td style="padding-left: 20px">
                <h3>
                    {% trans "3. Enroll and start your journey" %}
                </h3>
                <p>
                    {% blocktrans trimmed %}
                        The edX learner support team is available to answer any questions. Use the great information at
                        our <a href="{{ HELP_CENTER_URL|safe }}">Help Center</a>, or use
                        <a href="mailto:info@edx.org">info@edx.org</a> to contact us.
                    {% endblocktrans %}
                </p>
            </td>
        </tr>
    </table>
    <hr style="margin: 20px 0;" />
    <p>
        {% trans "We hope you love learning on edX!" %}
    </p>
    <!-- End Message Body -->
{% endblock body %}
        """,
    )
    # REVOCATION CAP
    SubscriptionPlanTemplate.objects.get_or_create(
        subject_line='REVOCATION CAP REACHED: {}',
        template_type='revocation_cap',
        plaintext_template="""
{% load i18n %}

{% trans "Revocation Cap Reached" %}

{% now "F j, Y, h:i a T" as revoke_limit_reached_date %}
{% blocktrans trimmed %}
As of {{ revoke_limit_reached_date }}, {{ ENTERPRISE_NAME }} has used all allotted license revocations
for their subscription plan: {{ SUBSCRIPTION_TITLE }}.
{% endblocktrans %}

{% blocktrans trimmed %}
Having now used {{ NUM_REVOCATIONS_APPLIED }} revocations, this enterprise will be unable to revoke additional activated
licenses from learners, and this feature will be disabled within their administration portal. They will still be able to
revoke and reassign pending licenses that have never been previously activated.
{% endblocktrans %}

{% blocktrans trimmed %}
Please alert Account Management (if applicable) and take appropriate steps to ensure the customer continues to have a positive experience with edX.
{% endblocktrans %}

        """,
        html_template="""
{% extends "email/email_base.html" %}
{% load i18n %}

{% block body %}
    <!-- Message Body -->
    <h1>
        {% trans "Revocation Cap Reached" %}
    </h1>
    <p>
        {% now "F j, Y, h:i a T" as revoke_limit_reached_date %}
        {% blocktrans trimmed %}
        As of {{ revoke_limit_reached_date }}, {{ ENTERPRISE_NAME }} has used all allotted license revocations
        for their subscription plan: {{ SUBSCRIPTION_TITLE }}.
        {% endblocktrans %}
    </p>
    <p>
        {% blocktrans trimmed %}
        Having now used {{ NUM_REVOCATIONS_APPLIED }} revocations, this enterprise will be unable to
        revoke additional activated licenses from learners, and this feature will be disabled within
        their administration portal. They will still be able to revoke and reassign pending licenses
        that have never been previously activated.
        {% endblocktrans %}
    </p>
    <p>
        {% blocktrans trimmed %}
        Please alert Account Management (if applicable) and take appropriate steps to ensure the customer
        continues to have a positive experience with edX.
        {% endblocktrans %}
    </p>
    <!-- End Message Body -->
{% endblock body %}
        """,
    )


class Migration(migrations.Migration):
    dependencies = [
        ('subscriptions', '0031_planemailtemplates'),
    ]

    operations = [
        migrations.RunPython(generate_email_templates),
    ]
