pip3 install --upgrade setuptools wheel twine
python3 setup.py sdist bdist_wheel
python3 -m twine upload -u __token__ -p $TOKEN dist/*
