from celery import shared_task
from django.conf import settings
from django.contrib.auth import get_user_model
from django.contrib.auth.tokens import default_token_generator
from django.core.mail import send_mail
from django.template.loader import render_to_string


@shared_task(name='nodeconductor.nodeconductor_auth.send_activation_email')
def send_activation_email(user_uuid):
    subject = 'Account activation on NodeConductor'
    template_name = 'nodeconductor_auth/activation_email_body.txt'

    user = get_user_model().objects.get(uuid=user_uuid, is_active=False)

    token = default_token_generator.make_token(user)
    url_template = settings.NODECONDUCTOR.get('USER_ACTIVATION_URL_TEMPLATE')
    url = url_template.format(token=token, user_uuid=user_uuid)
    context = {'activation_url': url}

    body = render_to_string(template_name, context)
    send_mail(subject, body, settings.DEFAULT_FROM_EMAIL, [user.email])
