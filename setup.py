#!/usr/bin/env python
from setuptools import setup, find_packages


dev_requires = [
    'Sphinx==1.2.2'
]

tests_require = [
    'factory_boy==2.4.1',
    'mock==1.0.1',
    'mock-django==0.6.6',
    'six>=1.7.3',
    'sqlalchemy>=1.0.12',
]

install_requires = [
    'nodeconductor>0.109.0',
    'html5lib<0.99999999',  # Transient dependency for nodeconductor_paypal
    # Consider moving nodeconductor_plus.plans to nodeconductor_paypal
    'nodeconductor_paypal>0.3.5',
]

setup(
    name='nodeconductor-plus',
    version='0.2.0',
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
        'test': tests_require,
        'dev': dev_requires,
    },
    entry_points={
        'nodeconductor_extensions': (
            'insights = nodeconductor_plus.insights.extension:InsightsExtension',
            'plans = nodeconductor_plus.plans.extension:PlansExtension',
            'premium_support = nodeconductor_plus.premium_support.extension:SupportExtension',
        ),
    },
    tests_require=tests_require,
    include_package_data=True,
    classifiers=[
        'Framework :: Django',
        'Intended Audience :: Developers',
        'Intended Audience :: System Administrators',
        'Operating System :: OS Independent',
        'License :: OSI Approved :: MIT License',
    ],
)
