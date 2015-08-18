from . import views


def register_in(router):
    router.register(r'azure', views.AzureServiceViewSet, base_name='azure')
    router.register(r'azure-images', views.ImageViewSet, base_name='azure-image')
    router.register(r'azure-locations', views.LocationViewSet, base_name='azure-location')
    router.register(r'azure-virtualmachines', views.VirtualMachineViewSet, base_name='azure-virtualmachine')
    router.register(r'azure-service-project-link',
                    views.AzureServiceProjectLinkViewSet, base_name='azure-spl')