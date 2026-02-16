"""Tests for in-memory cache service."""

import time
import pytest
from app.services.cache import CacheService


def test_set_and_get():
    cache = CacheService(default_ttl=60)
    cache.set("key1", {"price": 100.5})
    result = cache.get("key1")
    assert result == {"price": 100.5}


def test_get_missing_key():
    cache = CacheService(default_ttl=60)
    assert cache.get("nonexistent") is None


def test_ttl_expiry():
    cache = CacheService(default_ttl=1)
    cache.set("key1", "value1")
    assert cache.get("key1") == "value1"
    time.sleep(1.1)
    assert cache.get("key1") is None


def test_custom_ttl():
    cache = CacheService(default_ttl=60)
    cache.set("key1", "value1", ttl=1)
    assert cache.get("key1") == "value1"
    time.sleep(1.1)
    assert cache.get("key1") is None


def test_delete():
    cache = CacheService(default_ttl=60)
    cache.set("key1", "value1")
    cache.delete("key1")
    assert cache.get("key1") is None


def test_clear():
    cache = CacheService(default_ttl=60)
    cache.set("key1", "v1")
    cache.set("key2", "v2")
    cache.clear()
    assert cache.get("key1") is None
    assert cache.get("key2") is None
