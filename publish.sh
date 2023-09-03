pip3 install --upgrade build twine
python3 -m build
#python3 -m twine upload dist/*
python3 -m twine upload --repository testpypi dist/*