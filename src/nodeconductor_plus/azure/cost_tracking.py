from django.contrib.contenttypes.models import ContentType

from nodeconductor.cost_tracking import CostTrackingBackend
from nodeconductor.cost_tracking.models import DefaultPriceListItem

from .backend import SizeQueryset
from . import models


class AzureCostTrackingBackend(CostTrackingBackend):

    @classmethod
    def get_default_price_list_items(cls):
        ct = ContentType.objects.get_for_model(models.VirtualMachine)
        for size in SizeQueryset():
            yield DefaultPriceListItem(
                resource_content_type=ct,
                item_type='size',
                key=size.pk,
                value=size.price)

    @classmethod
    def get_monthly_cost_estimate(cls, resource):
        backend = resource.get_backend()
        return backend.get_monthly_cost_estimate(resource)
