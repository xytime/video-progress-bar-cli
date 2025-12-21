rm -rf build/ dist/           
find . -name "*.egg-info" -type d -exec rm -rf {} + 2>/dev/null
pip install -e .              
