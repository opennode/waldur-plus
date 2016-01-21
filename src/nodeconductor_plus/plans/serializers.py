from rest_framework import serializers

from nodeconductor.core.signals import pre_serializer_fields
from . import models
from nodeconductor.structure.serializers import CustomerSerializer


def get_plan_for_customer(serializer, customer):
    if 'plans' not in serializer.context:
        agreements = models.Agreement.objects\
            .filter(state=models.Agreement.States.ACTIVE)\
            .select_related('plan')
        if isinstance(serializer.instance, list):
            agreements = agreements.filter(customer__in=serializer.instance)
        else:
            agreements = agreements.filter(customer=serializer.instance)
        plans = {}
        for agreement in agreements:
            plans[agreement.customer_id] = agreement.plan
        serializer.context['plans'] = plans

    plan = serializer.context['plans'].get(customer.id)
    if plan:
        serializer = PlanSerializer(instance=plan, context=serializer.context)
        return serializer.data


def add_plan_for_customer(sender, fields, **kwargs):
    fields['plan'] = serializers.SerializerMethodField()
    setattr(sender, 'get_plan', get_plan_for_customer)


pre_serializer_fields.connect(
    add_plan_for_customer,
    sender=CustomerSerializer
)


class PlanSerializer(serializers.HyperlinkedModelSerializer):

    quotas = serializers.SerializerMethodField()

    class Meta:
        model = models.Plan
        fields = ('url', 'uuid', 'name', 'price', 'quotas')
        extra_kwargs = {
            'url': {'lookup_field': 'uuid'},
        }

    def get_quotas(self, obj):
        return obj.quotas.values('name', 'value')


class AgreementSerializer(serializers.HyperlinkedModelSerializer):
    customer_name = serializers.ReadOnlyField(source='customer.name')
    plan_name = serializers.ReadOnlyField(source='plan.name')
    plan_price = serializers.ReadOnlyField(source='plan.price')
    quotas = serializers.SerializerMethodField()

    class Meta:
        model = models.Agreement
        fields = ('url', 'uuid', 'state', 'created', 'modified', 'approval_url',
                  'user', 'customer', 'customer_name', 'plan', 'plan_name', 'plan_price', 'quotas')
        read_only_fields = ('state', 'user', 'approval_url')
        extra_kwargs = {
            'url': {'lookup_field': 'uuid'},
            'customer': {'lookup_field': 'uuid'},
            'plan': {'lookup_field': 'uuid'},
            'user': {'lookup_field': 'uuid'},
        }

    def get_quotas(self, obj):
        return obj.plan.quotas.values('name', 'value')

    def get_fields(self):
        fields = super(AgreementSerializer, self).get_fields()
        fields['customer'].required = True
        fields['plan'].required = True
        return fields

    def create(self, validated_data):
        try:
            validated_data['user'] = self.context['request'].user
        except AttributeError:
            raise AttributeError('AgreementSerializer have to be initialized with `request` in context')
        return super(AgreementSerializer, self).create(validated_data)
