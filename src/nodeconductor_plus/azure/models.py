from django.db import models

from nodeconductor.structure import models as structure_models


class AzureService(structure_models.Service):
    projects = models.ManyToManyField(
        structure_models.Project, related_name='azure_services', through='AzureServiceProjectLink')


class AzureServiceProjectLink(structure_models.ServiceProjectLink):
    service = models.ForeignKey(AzureService)

    cloud_service_name = models.CharField(max_length=255, blank=True)

    def get_backend(self):
        return super(AzureServiceProjectLink, self).get_backend(
            cloud_service_name=self.cloud_service_name)


class Image(structure_models.ServiceProperty):
    pass


class Location(structure_models.ServiceProperty):
    pass


class VirtualMachine(structure_models.VirtualMachineMixin, structure_models.Resource):
    service_project_link = models.ForeignKey(
        AzureServiceProjectLink, related_name='virtualmachines', on_delete=models.PROTECT)

    external_ips = models.GenericIPAddressField(null=True, blank=True, protocol='IPv4')
    internal_ips = models.GenericIPAddressField(null=True, blank=True, protocol='IPv4')
