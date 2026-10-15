import re

def test_package_id_examples():
    pattern = r"[A-Za-z][A-Za-z0-9_]*(\.[A-Za-z][A-Za-z0-9_]*){1,}"
    assert re.fullmatch(pattern, "com.mamun.myapp")
    assert not re.fullmatch(pattern, "myapp")
    assert not re.fullmatch(pattern, "com..bad")
