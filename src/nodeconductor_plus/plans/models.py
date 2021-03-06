from __future__ import unicode_literals

import logging

from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models
from django.utils.encoding import python_2_unicode_compatible
from django_fsm import FSMField, transition
from model_utils.models import TimeStampedModel

from nodeconductor.core.models import UuidMixin
from nodeconductor.logging.loggers import LoggableMixin
from nodeconductor.structure import models as structure_models


logger = logging.getLogger(__name__)


@python_2_unicode_compatible
class Plan(UuidMixin, LoggableMixin):
    name = models.CharField(max_length=120)
    price = models.DecimalField(max_digits=12, decimal_places=2)
    is_default = models.BooleanField(default=False)

    def __str__(self):
        return self.name

    def clean(self):
        if self.is_default and Plan.objects.filter(is_default=True).exclude(pk=self.pk).exists():
            raise ValidationError('Cannot create two default plans')

    def get_log_fields(self):
        return 'uuid', 'name'


class PlanQuota(models.Model):
    plan = models.ForeignKey(Plan, related_name='quotas')
    name = models.CharField(max_length=50, choices=[
        (f.name, f.name) for f in structure_models.Customer.get_quotas_fields()])
    value = models.FloatField()

    class Meta:
        unique_together = (('plan', 'name'),)


@python_2_unicode_compatible
class Agreement(UuidMixin, TimeStampedModel, LoggableMixin):
    class Meta:
        ordering = ['-modified']

    class Permissions(object):
        customer_path = 'customer'
        project_path = 'customer__projects'
        project_group_path = 'customer__project_groups'

    class States(object):
        CREATED = 'created'  # agreement has been created in our database, but not yet pushed to backend
        PENDING = 'pending'  # agreement has been pushed to backend, but not yet approved by user
        APPROVED = 'approved'  # agreement has been approved by user but quotas have not been applied
        ACTIVE = 'active'  # appropriate quotas have been applied, other agreements (if any) are cancelled
        CANCELLED = 'cancelled'
        ERRED = 'erred'

        CHOICES = (
            (CREATED, 'Created'),
            (PENDING, 'Pending'),
            (APPROVED, 'Approved'),
            (ACTIVE, 'Active'),
            (CANCELLED, 'Cancelled'),
            (ERRED, 'Erred'),
        )

    user = models.ForeignKey(settings.AUTH_USER_MODEL, null=True)
    plan = models.ForeignKey(Plan)
    customer = models.ForeignKey(structure_models.Customer)
    tax = models.DecimalField(max_digits=9, decimal_places=2, default=0)

    # These values are fetched from backend
    backend_id = models.CharField(max_length=255, blank=True, null=True)

    # Token is used as temporary identifier of billing agreement
    token = models.CharField(max_length=120, blank=True, null=True)
    approval_url = models.URLField(blank=True, null=True)

    state = FSMField(default=States.CREATED,
                     max_length=20,
                     choices=States.CHOICES,
                     help_text="WARNING! Should not be changed manually unless you really know what you are doing.")

    @transition(field=state, source=States.CREATED, target=States.PENDING)
    def set_pending(self, approval_url, token):
        self.approval_url = approval_url
        self.token = token

    @transition(field=state, source=States.PENDING, target=States.APPROVED)
    def set_approved(self):
        pass

    @transition(field=state, source=States.APPROVED, target=States.ACTIVE)
    def set_active(self):
        pass

    @transition(field=state, source=(States.PENDING, States.ACTIVE), target=States.CANCELLED)
    def set_cancelled(self):
        pass

    @transition(field=state, source='*', target=States.ERRED)
    def set_erred(self):
        pass

    def apply_quotas(self):
        for quota in self.plan.quotas.all():
            self.customer.set_quota_limit(quota.name, quota.value)

    @staticmethod
    def apply_default_plan(customer):
        try:
            default_plan = Plan.objects.filter(is_default=True).get()
            agreement = Agreement.objects.create(
                plan=default_plan, customer=customer, state=Agreement.States.ACTIVE)
            agreement.apply_quotas()
            logger.info('Default plan for customer %s has been applied', customer.name)
        except Plan.DoesNotExist:
            logger.warning('Default plan does not exist')

    def __str__(self):
        return 'Agreement for customer %s and plan %s' % (self.customer, self.plan)

    def get_log_fields(self):
        return 'uuid', 'customer', 'name', 'plan'
