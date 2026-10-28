"""Explicit environment selection; local disk is only a cache in R2 mode."""
from backend.storage.local import LocalStorage
from backend.storage.signing import Signer, R2Signer


def media_storage(settings):
    if settings.storage_mode == 'r2':
        from backend.storage.r2 import R2Storage
        return R2Storage(settings)
    return LocalStorage(settings.storage_root)


def media_signer(store):
    return R2Signer(store) if store.mode == 'r2' else Signer(store.root)


def result_store(store):
    if store.mode == 'r2':
        from backend.storage.result_store import R2ResultStore
        return R2ResultStore(store)
    from backend.worker.runner import ResultStore
    return ResultStore(store.root)
