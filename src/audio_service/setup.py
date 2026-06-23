from setuptools import find_packages, setup
import os
from glob import glob

package_name = 'audio_service'

setup(
    name=package_name,
    version="0.3.38",
    packages=find_packages(exclude=['test']),
    data_files=[
        # ('share/' + package_name + '/launch', ['audio_service/launch/asr_sentence_launch.py']),
        ('share/' + package_name + '/launch', glob('audio_service/launch/*.py')),
        ('share/ament_index/resource_index/packages', ['resource/' + package_name]),
        ('share/' + package_name, ['package.xml']),
        (os.path.join('share', package_name, 'msg'), glob('msg/*.msg')),
    ],
    install_requires=['setuptools'],
    zip_safe=True,
    maintainer='ubuntu',
    maintainer_email='han.li@ubtrobot.com',
    description='TODO: Package description',
    license='TODO: License declaration',
    entry_points={
        'console_scripts': [
            'tk_audio_publisher = audio_service.tk_audio_publisher:main',
            'tk_audio_process = audio_service.tk_audio_process:main',
            'tk_asr_text_publisher = audio_service.tk_asr_text_publisher:main',
        ],
    },
)
