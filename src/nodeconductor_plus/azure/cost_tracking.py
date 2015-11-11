from . import models
from nodeconductor.cost_tracking import CostTrackingBackend


class AzureCostTrackingBackend(CostTrackingBackend):

    @classmethod
    def get_monthly_cost_estimate(cls, resource):
        backend = resource.get_backend()
        return backend.get_monthly_cost_estimate(resource)