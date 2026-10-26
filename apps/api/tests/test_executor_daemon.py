import pytest

from lava.executor import load_key, provision_key


def test_key_provisioning_is_private_and_never_overwrites(tmp_path):
    path = tmp_path / "executor.key"
    provision_key(path)
    original = load_key(path)
    assert len(original) == 32
    with pytest.raises(FileExistsError):
        provision_key(path)
    assert load_key(path) == original
    path.chmod(0o644)
    with pytest.raises(PermissionError):
        load_key(path)


def test_key_symlink_is_rejected(tmp_path):
    target = tmp_path / "key"
    provision_key(target)
    link = tmp_path / "link"
    link.symlink_to(target)
    with pytest.raises(OSError):
        load_key(link)
