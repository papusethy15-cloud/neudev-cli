from setuptools import setup, find_packages

setup(
    name="neudev",
    version="1.0.0",
    description="NeuDev - Advanced AI Coding Agent powered by Ollama",
    author="NeuDev",
    packages=find_packages(),
    python_requires=">=3.10",
    install_requires=[
        "ollama>=0.4.0",
        "rich>=14.0.0",
        "prompt_toolkit>=3.0.0",
    ],
    entry_points={
        "console_scripts": [
            "neu=neudev.cli:main",
        ],
    },
    classifiers=[
        "Programming Language :: Python :: 3",
        "License :: OSI Approved :: MIT License",
        "Operating System :: OS Independent",
    ],
)
