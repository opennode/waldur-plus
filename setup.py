#!/usr/bin/env python
import sys
from setuptools import setup, find_packages


dev_requires = [
    'Sphinx==1.2.2'
]

tests_requires = [
    'factory_boy==2.4.1',
    'mock==1.0.1',
    'mock-django==0.6.6',
    'six>=1.7.3',
    'django-celery==3.1.16',
]

install_requires = [
    'apache-libcloud>=0.20.0',
    # Consider moving nodeconductor_plus.plans to nodeconductor_paypal
    'nodeconductor_paypal>=0.3.0',
    'nodeconductor>0.89.0',
    'python-digitalocean>=1.5',
    'python-gitlab>=0.9',
]

# RPM installation does not need oslo, cliff and stevedore libs -
# they are required only for installation with setuptools
try:
    action = sys.argv[1]
except IndexError:
    pass
else:
    if action in ['develop', 'install', 'test']:
        install_requires += [
            'cliff==1.7.0',
            'oslo.config==1.4.0',
            'oslo.i18n==1.0.0',
            'oslo.utils==1.0.0',
            'stevedore==1.0.0',
        ]
    # handle the case when plugins are installed in develop mode
    if action in ['develop']:
        install_requires += tests_require


setup(
    name='nodeconductor-plus',
    version='0.1.0',
    author='OpenNode Team',
    author_email='info@opennodecloud.com',
    url='http://nodeconductor.com',
    description='NodeConductor Plus is an extension of NodeConductor with extra features',
    long_description=open('README.rst').read(),
    package_dir={'': 'src'},
    packages=find_packages('src', exclude=["*.tests", "*.tests.*", "tests.*", "tests"]),
    install_requires=install_requires,
    zip_safe=False,
    extras_require={
        'test': tests_requires,
        'dev': dev_requires,
    },
    entry_points={
        'nodeconductor_extensions': (
            'aws = nodeconductor_plus.aws.extension:AWSExtension',
            'azure = nodeconductor_plus.azure.extension:AzureExtension',
            'digitalocean = nodeconductor_plus.digitalocean.extension:DigitalOceanExtension',
            'gitlab = nodeconductor_plus.gitlab.extension:GitLabExtension',
            'insights = nodeconductor_plus.insights.extension:InsightsExtension',
            'nodeconductor_auth = nodeconductor_plus.nodeconductor_auth.extension:AuthExtension',
            'plans = nodeconductor_plus.plans.extension:PlansExtension',
            'premium_support = nodeconductor_plus.premium_support.extension:SupportExtension',
        ),
    },
    tests_require=tests_requires,
    include_package_data=True,
    classifiers=[
        'Framework :: Django',
        'Intended Audience :: Developers',
        'Intended Audience :: System Administrators',
        'Operating System :: OS Independent',
        'License :: Other/Proprietary License',
    ],
)
