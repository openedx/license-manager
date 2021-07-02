from license_manager.apps.subscriptions.models import PlanType
from django.db import migrations


def generate_email_templates(apps, schema_editor):
    activation_plaintext_email = """
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
"""
    activation_html_email="""
{% load i18n %}
{% get_current_language as LANGUAGE_CODE %}
{% get_current_language_bidi as LANGUAGE_BIDI %}
<!DOCTYPE html>
<html lang="{{ LANGUAGE_CODE|default:"en" }}" dir="{{ LANGUAGE_BIDI|yesno:"rtl,ltr" }}">
<head>
  <meta http-equiv="Content-Type" content="text/html; charset=UTF-8">
  <meta name="viewport" content="initial-scale=1.0">
  <!-- So that mobile webkit will display zoomed in -->
  <meta name="format-detection" content="telephone=no">
  <!-- disable auto telephone linking in iOS -->
  <style>
    @import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;500;700&family=Roboto+Mono&display=swap');
  </style>
  <!-- Hack for outlook 2010, which wants to render everything in Times New Roman -->
  <!--[if mso]>
  <style type="text/css">
    body, table, td {font-family: 'Inter', 'Helvetica Neue', Arial, sans-serif !important;}
  </style>
  <![endif]-->
</head>
<body>
  <div bgcolor="#fbfaf9" style="margin: 0; padding: 0; min-width: 100%;">
    <!--[if (gte mso 9)|(IE)]>
    <table role="presentation" width="600" align="center" cellpadding="0" cellspacing="0" border="0">
      <tr>
        <td>
          <![endif]-->
          <!-- CONTENT -->
          <table class="content" role="presentation" align="center" cellpadding="0" cellspacing="0" bgcolor="#fbfaf9" border="0" width="100%" style="
            font-family: 'Inter', 'Helvetica Neue', Arial, sans-serif;
            font-size: 1em;
            line-height: 1.5;
            max-width: 600px;
            padding: 0 20px;
            ">
            <tr>
              <!-- HEADER -->
              <td class="header" style="
                padding: 20px;
                ">
                {% block header %}
                <table role="presentation" width="100%" align="left" border="0" cellpadding="0" cellspacing="0">
                  <tr>
                    <td width="70">
                      <img src="https://edx-cdn.org/v3/prod/logo.png" height="40" width="auto" />
                    </td>
                  </tr>
                </table>
                {% endblock %}
              </td>
            </tr>
            <tr>
              <!-- MAIN -->
              <td class="main" bgcolor="#ffffff" style="
                padding: 30px 20px;
                box-shadow: 0 1px 5px rgba(0,0,0,0.25);
                ">
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
              </td>
            </tr>
            <tr>
              <!-- FOOTER -->
              <td class="footer" style="padding: 20px;">
                <table role="presentation" width="100%" align="left" border="0" cellpadding="0" cellspacing="0">
                  {% if not HIDE_EMAIL_FOOTER_MARKETING %}
                  <tr>
                    <td style="padding-bottom: 20px;">
                      <!-- SOCIAL -->
                      <table role="presentation" align="{{ LANGUAGE_BIDI|yesno:"right,left" }}" border="0" border="0" cellpadding="0" cellspacing="0" width="210">
                  <tr>
                    {% if SOCIAL_MEDIA_FOOTER_URLS.linkedin %}
                    <td height="32" width="42">
                      <a href="{{ SOCIAL_MEDIA_FOOTER_URLS.linkedin|safe }}">
                      <img src="https://media.sailthru.com/595/1k1/8/o/599f354ec70cb.png"
                        width="32" height="32" alt="{% filter force_escape %}{% blocktrans %}LinkedIn{% endblocktrans %}{% endfilter %}"/>
                      </a>
                    </td>
                    {% endif %}
                    {% if SOCIAL_MEDIA_FOOTER_URLS.twitter %}
                    <td height="32" width="42">
                      <a href="{{ SOCIAL_MEDIA_FOOTER_URLS.twitter|safe }}">
                      <img src="https://media.sailthru.com/595/1k1/8/o/599f354d9c26e.png"
                        width="32" height="32" alt="{% filter force_escape %}{% blocktrans %}Twitter{% endblocktrans %}{% endfilter %}"/>
                      </a>
                    </td>
                    {% endif %}
                    {% if SOCIAL_MEDIA_FOOTER_URLS.facebook %}
                    <td height="32" width="42">
                      <a href="{{ SOCIAL_MEDIA_FOOTER_URLS.facebook|safe }}">
                      <img src="https://media.sailthru.com/595/1k1/8/o/599f355052c8e.png"
                        width="32" height="32" alt="{% filter force_escape %}{% blocktrans %}Facebook{% endblocktrans %}{% endfilter %}"/>
                      </a>
                    </td>
                    {% endif %}
                    {% if SOCIAL_MEDIA_FOOTER_URLS.reddit %}
                    <td height="32" width="42">
                      <a href="{{ SOCIAL_MEDIA_FOOTER_URLS.reddit|safe }}">
                      <img src="https://media.sailthru.com/595/1k1/8/o/599f354e326b9.png"
                        width="32" height="32" alt="{% filter force_escape %}{% blocktrans %}Reddit{% endblocktrans %}{% endfilter %}"/>
                      </a>
                    </td>
                    {% endif %}
                  </tr>
                </table>
              </td>
            </tr>
            <tr>
              <!-- APP BUTTONS -->
              <td style="padding-bottom: 20px;">
                {% if MOBILE_STORE_URLS.apple %}
                <a href="{{ MOBILE_STORE_URLS.apple|safe }}" style="text-decoration: none">
                <img src="https://media.sailthru.com/595/1k1/6/2/5931cfbba391b.png"
                alt="{% trans "Download the iOS app on the Apple Store" as tmsg %}{{ tmsg | force_escape }}"
                width="136" height="50" style="margin-{{ LANGUAGE_BIDI|yesno:"left,right" }}: 10px"/>
                </a>
                {% endif %}
                {% if MOBILE_STORE_URLS.google %}
                <a href="{{ MOBILE_STORE_URLS.google|safe }}" style="text-decoration: none">
                <img src="https://media.sailthru.com/595/1k1/6/2/5931cf879a033.png"
                alt="{% trans "Download the Android app on the Google Play Store" as tmsg %}{{ tmsg | force_escape }}"
                width="136" height="50"/>
                </a>
                {% endif %}
              </td>
            </tr>
            {% endif %}
            <tr>
              <!-- COPYRIGHT -->
              <td>
                &copy; {% now "Y" %} edX, {% trans "All rights reserved" as tmsg %}{{ tmsg | force_escape }}
              </td>
            </tr>
          </table>
        </td>
      </tr>
    </table>
    <!--[if (gte mso 9)|(IE)]>
    </td>
    </tr>
    </table>
    <![endif]-->
  </div>
</body>
</html>
"""
    reminder_plaintext_email="""
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
        """
    reminder_html_email="""
{% load i18n %}
{% get_current_language as LANGUAGE_CODE %}
{% get_current_language_bidi as LANGUAGE_BIDI %}
<!DOCTYPE html>
<html lang="{{ LANGUAGE_CODE|default:"en" }}" dir="{{ LANGUAGE_BIDI|yesno:"rtl,ltr" }}">
<head>
  <meta http-equiv="Content-Type" content="text/html; charset=UTF-8">
  <meta name="viewport" content="initial-scale=1.0">
  <!-- So that mobile webkit will display zoomed in -->
  <meta name="format-detection" content="telephone=no">
  <!-- disable auto telephone linking in iOS -->
  <style>
    @import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;500;700&family=Roboto+Mono&display=swap');
  </style>
  <!-- Hack for outlook 2010, which wants to render everything in Times New Roman -->
  <!--[if mso]>
  <style type="text/css">
    body, table, td {font-family: 'Inter', 'Helvetica Neue', Arial, sans-serif !important;}
  </style>
  <![endif]-->
</head>
<body>
  <div bgcolor="#fbfaf9" style="margin: 0; padding: 0; min-width: 100%;">
    <!--[if (gte mso 9)|(IE)]>
    <table role="presentation" width="600" align="center" cellpadding="0" cellspacing="0" border="0">
      <tr>
        <td>
          <![endif]-->
          <!-- CONTENT -->
          <table class="content" role="presentation" align="center" cellpadding="0" cellspacing="0" bgcolor="#fbfaf9" border="0" width="100%" style="
            font-family: 'Inter', 'Helvetica Neue', Arial, sans-serif;
            font-size: 1em;
            line-height: 1.5;
            max-width: 600px;
            padding: 0 20px;
            ">
            <tr>
              <!-- HEADER -->
              <td class="header" style="
                padding: 20px;
                ">
                {% block header %}
                <table role="presentation" width="100%" align="left" border="0" cellpadding="0" cellspacing="0">
                  <tr>
                    <td width="70">
                      <img src="https://edx-cdn.org/v3/prod/logo.png" height="40" width="auto" />
                    </td>
                  </tr>
                </table>
                {% endblock %}
              </td>
            </tr>
            <tr>
              <!-- MAIN -->
              <td class="main" bgcolor="#ffffff" style="
                padding: 30px 20px;
                box-shadow: 0 1px 5px rgba(0,0,0,0.25);
                ">
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
              </td>
            </tr>
            <tr>
              <!-- FOOTER -->
              <td class="footer" style="padding: 20px;">
                <table role="presentation" width="100%" align="left" border="0" cellpadding="0" cellspacing="0">
                  {% if not HIDE_EMAIL_FOOTER_MARKETING %}
                  <tr>
                    <td style="padding-bottom: 20px;">
                      <!-- SOCIAL -->
                      <table role="presentation" align="{{ LANGUAGE_BIDI|yesno:"right,left" }}" border="0" border="0" cellpadding="0" cellspacing="0" width="210">
                  <tr>
                    {% if SOCIAL_MEDIA_FOOTER_URLS.linkedin %}
                    <td height="32" width="42">
                      <a href="{{ SOCIAL_MEDIA_FOOTER_URLS.linkedin|safe }}">
                      <img src="https://media.sailthru.com/595/1k1/8/o/599f354ec70cb.png"
                        width="32" height="32" alt="{% filter force_escape %}{% blocktrans %}LinkedIn{% endblocktrans %}{% endfilter %}"/>
                      </a>
                    </td>
                    {% endif %}
                    {% if SOCIAL_MEDIA_FOOTER_URLS.twitter %}
                    <td height="32" width="42">
                      <a href="{{ SOCIAL_MEDIA_FOOTER_URLS.twitter|safe }}">
                      <img src="https://media.sailthru.com/595/1k1/8/o/599f354d9c26e.png"
                        width="32" height="32" alt="{% filter force_escape %}{% blocktrans %}Twitter{% endblocktrans %}{% endfilter %}"/>
                      </a>
                    </td>
                    {% endif %}
                    {% if SOCIAL_MEDIA_FOOTER_URLS.facebook %}
                    <td height="32" width="42">
                      <a href="{{ SOCIAL_MEDIA_FOOTER_URLS.facebook|safe }}">
                      <img src="https://media.sailthru.com/595/1k1/8/o/599f355052c8e.png"
                        width="32" height="32" alt="{% filter force_escape %}{% blocktrans %}Facebook{% endblocktrans %}{% endfilter %}"/>
                      </a>
                    </td>
                    {% endif %}
                    {% if SOCIAL_MEDIA_FOOTER_URLS.reddit %}
                    <td height="32" width="42">
                      <a href="{{ SOCIAL_MEDIA_FOOTER_URLS.reddit|safe }}">
                      <img src="https://media.sailthru.com/595/1k1/8/o/599f354e326b9.png"
                        width="32" height="32" alt="{% filter force_escape %}{% blocktrans %}Reddit{% endblocktrans %}{% endfilter %}"/>
                      </a>
                    </td>
                    {% endif %}
                  </tr>
                </table>
              </td>
            </tr>
            <tr>
              <!-- APP BUTTONS -->
              <td style="padding-bottom: 20px;">
                {% if MOBILE_STORE_URLS.apple %}
                <a href="{{ MOBILE_STORE_URLS.apple|safe }}" style="text-decoration: none">
                <img src="https://media.sailthru.com/595/1k1/6/2/5931cfbba391b.png"
                alt="{% trans "Download the iOS app on the Apple Store" as tmsg %}{{ tmsg | force_escape }}"
                width="136" height="50" style="margin-{{ LANGUAGE_BIDI|yesno:"left,right" }}: 10px"/>
                </a>
                {% endif %}
                {% if MOBILE_STORE_URLS.google %}
                <a href="{{ MOBILE_STORE_URLS.google|safe }}" style="text-decoration: none">
                <img src="https://media.sailthru.com/595/1k1/6/2/5931cf879a033.png"
                alt="{% trans "Download the Android app on the Google Play Store" as tmsg %}{{ tmsg | force_escape }}"
                width="136" height="50"/>
                </a>
                {% endif %}
              </td>
            </tr>
            {% endif %}
            <tr>
              <!-- COPYRIGHT -->
              <td>
                &copy; {% now "Y" %} edX, {% trans "All rights reserved" as tmsg %}{{ tmsg | force_escape }}
              </td>
            </tr>
          </table>
        </td>
      </tr>
    </table>
    <!--[if (gte mso 9)|(IE)]>
    </td>
    </tr>
    </table>
    <![endif]-->
  </div>
</body>
</html>
        """
    onboarding_plaintext_email="""
{% load i18n %}

{% trans "Welcome to edX Subscriptions!" %}

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
        """
    onboarding_html_email="""
{% load i18n %}
{% load static %}
{% get_current_language as LANGUAGE_CODE %}
{% get_current_language_bidi as LANGUAGE_BIDI %}
<!DOCTYPE html>
<html lang="{{ LANGUAGE_CODE|default:"en" }}" dir="{{ LANGUAGE_BIDI|yesno:"rtl,ltr" }}">
<head>
  <meta http-equiv="Content-Type" content="text/html; charset=UTF-8">
  <meta name="viewport" content="initial-scale=1.0">
  <!-- So that mobile webkit will display zoomed in -->
  <meta name="format-detection" content="telephone=no">
  <!-- disable auto telephone linking in iOS -->
  <style>
    @import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;500;700&family=Roboto+Mono&display=swap');
  </style>
  <!-- Hack for outlook 2010, which wants to render everything in Times New Roman -->
  <!--[if mso]>
  <style type="text/css">
    body, table, td {font-family: 'Inter', 'Helvetica Neue', Arial, sans-serif !important;}
  </style>
  <![endif]-->
</head>
<body>
  <div bgcolor="#fbfaf9" style="margin: 0; padding: 0; min-width: 100%;">
    <!--[if (gte mso 9)|(IE)]>
    <table role="presentation" width="600" align="center" cellpadding="0" cellspacing="0" border="0">
      <tr>
        <td>
          <![endif]-->
          <!-- CONTENT -->
          <table class="content" role="presentation" align="center" cellpadding="0" cellspacing="0" bgcolor="#fbfaf9" border="0" width="100%" style="
            font-family: 'Inter', 'Helvetica Neue', Arial, sans-serif;
            font-size: 1em;
            line-height: 1.5;
            max-width: 600px;
            padding: 0 20px;
            ">
            <tr>
              <!-- HEADER -->
              <td class="header" style="
                padding: 20px;
                ">
                {% block header %}
                <table role="presentation" width="100%" align="left" border="0" cellpadding="0" cellspacing="0">
                  <tr>
                    <td width="70">
                      <img src="https://edx-cdn.org/v3/prod/logo.png" height="40" width="auto" />
                    </td>
                  </tr>
                </table>
                {% endblock %}
              </td>
            </tr>
            <tr>
              <!-- MAIN -->
              <td class="main" bgcolor="#ffffff" style="
                padding: 30px 20px;
                box-shadow: 0 1px 5px rgba(0,0,0,0.25);
                ">
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
              </td>
            </tr>
            <tr>
              <!-- FOOTER -->
              <td class="footer" style="padding: 20px;">
                <table role="presentation" width="100%" align="left" border="0" cellpadding="0" cellspacing="0">
                  {% if not HIDE_EMAIL_FOOTER_MARKETING %}
                  <tr>
                    <td style="padding-bottom: 20px;">
                      <!-- SOCIAL -->
                      <table role="presentation" align="{{ LANGUAGE_BIDI|yesno:"right,left" }}" border="0" border="0" cellpadding="0" cellspacing="0" width="210">
                  <tr>
                    {% if SOCIAL_MEDIA_FOOTER_URLS.linkedin %}
                    <td height="32" width="42">
                      <a href="{{ SOCIAL_MEDIA_FOOTER_URLS.linkedin|safe }}">
                      <img src="https://media.sailthru.com/595/1k1/8/o/599f354ec70cb.png"
                        width="32" height="32" alt="{% filter force_escape %}{% blocktrans %}LinkedIn{% endblocktrans %}{% endfilter %}"/>
                      </a>
                    </td>
                    {% endif %}
                    {% if SOCIAL_MEDIA_FOOTER_URLS.twitter %}
                    <td height="32" width="42">
                      <a href="{{ SOCIAL_MEDIA_FOOTER_URLS.twitter|safe }}">
                      <img src="https://media.sailthru.com/595/1k1/8/o/599f354d9c26e.png"
                        width="32" height="32" alt="{% filter force_escape %}{% blocktrans %}Twitter{% endblocktrans %}{% endfilter %}"/>
                      </a>
                    </td>
                    {% endif %}
                    {% if SOCIAL_MEDIA_FOOTER_URLS.facebook %}
                    <td height="32" width="42">
                      <a href="{{ SOCIAL_MEDIA_FOOTER_URLS.facebook|safe }}">
                      <img src="https://media.sailthru.com/595/1k1/8/o/599f355052c8e.png"
                        width="32" height="32" alt="{% filter force_escape %}{% blocktrans %}Facebook{% endblocktrans %}{% endfilter %}"/>
                      </a>
                    </td>
                    {% endif %}
                    {% if SOCIAL_MEDIA_FOOTER_URLS.reddit %}
                    <td height="32" width="42">
                      <a href="{{ SOCIAL_MEDIA_FOOTER_URLS.reddit|safe }}">
                      <img src="https://media.sailthru.com/595/1k1/8/o/599f354e326b9.png"
                        width="32" height="32" alt="{% filter force_escape %}{% blocktrans %}Reddit{% endblocktrans %}{% endfilter %}"/>
                      </a>
                    </td>
                    {% endif %}
                  </tr>
                </table>
              </td>
            </tr>
            <tr>
              <!-- APP BUTTONS -->
              <td style="padding-bottom: 20px;">
                {% if MOBILE_STORE_URLS.apple %}
                <a href="{{ MOBILE_STORE_URLS.apple|safe }}" style="text-decoration: none">
                <img src="https://media.sailthru.com/595/1k1/6/2/5931cfbba391b.png"
                alt="{% trans "Download the iOS app on the Apple Store" as tmsg %}{{ tmsg | force_escape }}"
                width="136" height="50" style="margin-{{ LANGUAGE_BIDI|yesno:"left,right" }}: 10px"/>
                </a>
                {% endif %}
                {% if MOBILE_STORE_URLS.google %}
                <a href="{{ MOBILE_STORE_URLS.google|safe }}" style="text-decoration: none">
                <img src="https://media.sailthru.com/595/1k1/6/2/5931cf879a033.png"
                alt="{% trans "Download the Android app on the Google Play Store" as tmsg %}{{ tmsg | force_escape }}"
                width="136" height="50"/>
                </a>
                {% endif %}
              </td>
            </tr>
            {% endif %}
            <tr>
              <!-- COPYRIGHT -->
              <td>
                &copy; {% now "Y" %} edX, {% trans "All rights reserved" as tmsg %}{{ tmsg | force_escape }}
              </td>
            </tr>
          </table>
        </td>
      </tr>
    </table>
    <!--[if (gte mso 9)|(IE)]>
    </td>
    </tr>
    </table>
    <![endif]-->
  </div>
</body>
</html>
        """

    revocation_plaintext_email="""
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
    revocation_html_email="""
{% load i18n %}
{% get_current_language as LANGUAGE_CODE %}
{% get_current_language_bidi as LANGUAGE_BIDI %}
<!DOCTYPE html>
<html lang="{{ LANGUAGE_CODE|default:"en" }}" dir="{{ LANGUAGE_BIDI|yesno:"rtl,ltr" }}">
<head>
  <meta http-equiv="Content-Type" content="text/html; charset=UTF-8">
  <meta name="viewport" content="initial-scale=1.0">
  <!-- So that mobile webkit will display zoomed in -->
  <meta name="format-detection" content="telephone=no">
  <!-- disable auto telephone linking in iOS -->
  <style>
    @import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;500;700&family=Roboto+Mono&display=swap');
  </style>
  <!-- Hack for outlook 2010, which wants to render everything in Times New Roman -->
  <!--[if mso]>
  <style type="text/css">
    body, table, td {font-family: 'Inter', 'Helvetica Neue', Arial, sans-serif !important;}
  </style>
  <![endif]-->
</head>
<body>
  <div bgcolor="#fbfaf9" style="margin: 0; padding: 0; min-width: 100%;">
    <!--[if (gte mso 9)|(IE)]>
    <table role="presentation" width="600" align="center" cellpadding="0" cellspacing="0" border="0">
      <tr>
        <td>
          <![endif]-->
          <!-- CONTENT -->
          <table class="content" role="presentation" align="center" cellpadding="0" cellspacing="0" bgcolor="#fbfaf9" border="0" width="100%" style="
            font-family: 'Inter', 'Helvetica Neue', Arial, sans-serif;
            font-size: 1em;
            line-height: 1.5;
            max-width: 600px;
            padding: 0 20px;
            ">
            <tr>
              <!-- HEADER -->
              <td class="header" style="
                padding: 20px;
                ">
                {% block header %}
                <table role="presentation" width="100%" align="left" border="0" cellpadding="0" cellspacing="0">
                  <tr>
                    <td width="70">
                      <img src="https://edx-cdn.org/v3/prod/logo.png" height="40" width="auto" />
                    </td>
                  </tr>
                </table>
                {% endblock %}
              </td>
            </tr>
            <tr>
              <!-- MAIN -->
              <td class="main" bgcolor="#ffffff" style="
                padding: 30px 20px;
                box-shadow: 0 1px 5px rgba(0,0,0,0.25);
                ">
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
              </td>
            </tr>
            <tr>
              <!-- FOOTER -->
              <td class="footer" style="padding: 20px;">
                <table role="presentation" width="100%" align="left" border="0" cellpadding="0" cellspacing="0">
                  {% if not HIDE_EMAIL_FOOTER_MARKETING %}
                  <tr>
                    <td style="padding-bottom: 20px;">
                      <!-- SOCIAL -->
                      <table role="presentation" align="{{ LANGUAGE_BIDI|yesno:"right,left" }}" border="0" border="0" cellpadding="0" cellspacing="0" width="210">
                  <tr>
                    {% if SOCIAL_MEDIA_FOOTER_URLS.linkedin %}
                    <td height="32" width="42">
                      <a href="{{ SOCIAL_MEDIA_FOOTER_URLS.linkedin|safe }}">
                      <img src="https://media.sailthru.com/595/1k1/8/o/599f354ec70cb.png"
                        width="32" height="32" alt="{% filter force_escape %}{% blocktrans %}LinkedIn{% endblocktrans %}{% endfilter %}"/>
                      </a>
                    </td>
                    {% endif %}
                    {% if SOCIAL_MEDIA_FOOTER_URLS.twitter %}
                    <td height="32" width="42">
                      <a href="{{ SOCIAL_MEDIA_FOOTER_URLS.twitter|safe }}">
                      <img src="https://media.sailthru.com/595/1k1/8/o/599f354d9c26e.png"
                        width="32" height="32" alt="{% filter force_escape %}{% blocktrans %}Twitter{% endblocktrans %}{% endfilter %}"/>
                      </a>
                    </td>
                    {% endif %}
                    {% if SOCIAL_MEDIA_FOOTER_URLS.facebook %}
                    <td height="32" width="42">
                      <a href="{{ SOCIAL_MEDIA_FOOTER_URLS.facebook|safe }}">
                      <img src="https://media.sailthru.com/595/1k1/8/o/599f355052c8e.png"
                        width="32" height="32" alt="{% filter force_escape %}{% blocktrans %}Facebook{% endblocktrans %}{% endfilter %}"/>
                      </a>
                    </td>
                    {% endif %}
                    {% if SOCIAL_MEDIA_FOOTER_URLS.reddit %}
                    <td height="32" width="42">
                      <a href="{{ SOCIAL_MEDIA_FOOTER_URLS.reddit|safe }}">
                      <img src="https://media.sailthru.com/595/1k1/8/o/599f354e326b9.png"
                        width="32" height="32" alt="{% filter force_escape %}{% blocktrans %}Reddit{% endblocktrans %}{% endfilter %}"/>
                      </a>
                    </td>
                    {% endif %}
                  </tr>
                </table>
              </td>
            </tr>
            <tr>
              <!-- APP BUTTONS -->
              <td style="padding-bottom: 20px;">
                {% if MOBILE_STORE_URLS.apple %}
                <a href="{{ MOBILE_STORE_URLS.apple|safe }}" style="text-decoration: none">
                <img src="https://media.sailthru.com/595/1k1/6/2/5931cfbba391b.png"
                alt="{% trans "Download the iOS app on the Apple Store" as tmsg %}{{ tmsg | force_escape }}"
                width="136" height="50" style="margin-{{ LANGUAGE_BIDI|yesno:"left,right" }}: 10px"/>
                </a>
                {% endif %}
                {% if MOBILE_STORE_URLS.google %}
                <a href="{{ MOBILE_STORE_URLS.google|safe }}" style="text-decoration: none">
                <img src="https://media.sailthru.com/595/1k1/6/2/5931cf879a033.png"
                alt="{% trans "Download the Android app on the Google Play Store" as tmsg %}{{ tmsg | force_escape }}"
                width="136" height="50"/>
                </a>
                {% endif %}
              </td>
            </tr>
            {% endif %}
            <tr>
              <!-- COPYRIGHT -->
              <td>
                &copy; {% now "Y" %} edX, {% trans "All rights reserved" as tmsg %}{{ tmsg | force_escape }}
              </td>
            </tr>
          </table>
        </td>
      </tr>
    </table>
    <!--[if (gte mso 9)|(IE)]>
    </td>
    </tr>
    </table>
    <![endif]-->
  </div>
</body>
</html>
        """,


    PlanEmailTemplates = apps.get_model("subscriptions", "PlanEmailTemplates")
    PlanType = apps.get_model('subscriptions', 'PlanType')

    # Standard Paid    
    standard_plan = PlanType.objects.filter(id=1).get()
    PlanEmailTemplates.objects.get_or_create(
        subject_line='Start your edX Subscription',
        template_type='activation',
        plan_type=standard_plan,
        plaintext_template=activation_plaintext_email,
        html_template=activation_html_email,
    )
    PlanEmailTemplates.objects.get_or_create(
        subject_line='Your edX License is pending',
        template_type='reminder',
        plan_type=standard_plan,
        plaintext_template=reminder_plaintext_email,
        html_template=reminder_html_email,
    )
    PlanEmailTemplates.objects.get_or_create(
        subject_line='Welcome to edX Subscriptions!',
        template_type='onboarding',
        plan_type=standard_plan,
        plaintext_template=onboarding_plaintext_email, 
        html_template=onboarding_html_email,
    )
    # OCE
    oce_plan = PlanType.objects.filter(id=2).get()
    PlanEmailTemplates.objects.get_or_create(
        subject_line='Start your edX Subscription',
        template_type='activation',
        plan_type=oce_plan,
        plaintext_template=activation_plaintext_email,
        html_template=activation_html_email,
    )
    PlanEmailTemplates.objects.get_or_create(
        subject_line='Your edX License is pending',
        template_type='reminder',
        plan_type=oce_plan,
        plaintext_template=reminder_plaintext_email,
        html_template=reminder_html_email,
    )
    PlanEmailTemplates.objects.get_or_create(
        subject_line='Welcome to edX Subscriptions!',
        template_type='onboarding',
        plan_type=oce_plan,
        plaintext_template=onboarding_plaintext_email, 
        html_template=onboarding_html_email, 
    )
    # Trials
    trials_plan = PlanType.objects.filter(id=3).get()
    PlanEmailTemplates.objects.get_or_create(
        subject_line='Start your edX Subscription',
        template_type='activation',
        plan_type=trials_plan,
        plaintext_template=activation_plaintext_email,
        html_template=activation_html_email,
    )
    PlanEmailTemplates.objects.get_or_create(
        subject_line='Your edX License is pending',
        template_type='reminder',
        plan_type=trials_plan,
        plaintext_template=reminder_plaintext_email,
        html_template=reminder_html_email, 
    )
    PlanEmailTemplates.objects.get_or_create(
        subject_line='Welcome to edX Subscriptions!',
        template_type='onboarding',
        plan_type=trials_plan,
        plaintext_template=onboarding_plaintext_email, 
        html_template=onboarding_html_email, 
    )
    # Test
    test_plan = PlanType.objects.filter(id=4).get()
    PlanEmailTemplates.objects.get_or_create(
        subject_line='Start your edX Subscription',
        template_type='activation',
        plan_type=test_plan,
        plaintext_template=activation_plaintext_email,
        html_template=activation_html_email,
    )
    PlanEmailTemplates.objects.get_or_create(
        subject_line='Your edX License is pending',
        template_type='reminder',
        plan_type=test_plan,
        plaintext_template=reminder_plaintext_email,
        html_template=reminder_html_email,
    )
    PlanEmailTemplates.objects.get_or_create(
        subject_line='Welcome to edX Subscriptions!',
        template_type='onboarding',
        plan_type=test_plan,
        plaintext_template=onboarding_plaintext_email, 
        html_template=onboarding_html_email, 
    )
    # Revocation Cap
    PlanEmailTemplates.objects.get_or_create(
        subject_line='REVOCATION CAP REACHED: {}',
        template_type='revocation_cap',
        plaintext_template=revocation_plaintext_email, 
        html_template=revocation_html_email, 
    )

def depopulate_table(apps, schema_editor):
    PlanEmailTemplates = apps.get_model("subscriptions", "PlanEmailTemplates")
    PlanEmailTemplates.objects.all().delete()

class Migration(migrations.Migration):
    dependencies = [
        ('subscriptions', '0031_planemailtemplates'),
    ]

    operations = [
        migrations.RunPython(generate_email_templates, depopulate_table),
    ]
