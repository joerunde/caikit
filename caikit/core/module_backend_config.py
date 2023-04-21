# Copyright The Caikit Authors
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

# Standard
from typing import List
import threading

# First Party
import alog

# Local
from .module import MODULE_BACKEND_REGISTRY
from .module_backends.backend_types import MODULE_BACKEND_CLASSES, MODULE_BACKEND_TYPES
from .module_backends.base import BackendBase
from .toolkit.errors import error_handler
from caikit.config import get_config

log = alog.use_channel("BACKENDS")
error = error_handler.get(log)

_CONFIGURED_BACKENDS = {}
_BACKEND_START_LOCKS = {}


def start_backends() -> None:
    """This function kicks off the `start` functions for configured backends
    Returns:
        None
    """
    for backend_type, backend in _CONFIGURED_BACKENDS.items():
        with _BACKEND_START_LOCKS[backend_type]:
            if not backend.is_started:
                backend.start()


def get_backend(backend_type: str) -> BackendBase:
    """Get the configured instance of the given backend type. If not configured,
    a ValueError is raised
    """
    error.value_check(
        "<COR82987857E>",
        backend_type in _CONFIGURED_BACKENDS,
        "Cannot fetch unconfigured backend [%s]",
        backend_type,
    )
    backend = _CONFIGURED_BACKENDS[backend_type]
    if not backend.is_started:
        with _BACKEND_START_LOCKS[backend_type]:
            if not backend.is_started:
                backend.start()
    return backend


def get_configured_backends() -> List[str]:
    """This function exposes the list of configured backends for downstream
    checks
    """
    # NOTE: Return a copy to avoid accidentally mutating the global
    return list(_CONFIGURED_BACKENDS.keys())


def backend_configure():
    """Configure the backend environment

    NOTE: This function is NOT thread safe!
    """
    config_object = get_config().module_backends

    log.debug3("Full Config: %s", config_object)

    # Determine the priority list of enabled backends
    #
    # NOTE: All backends are held in UPPERCASE, but this is not canonical for
    #   yaml or function arguments, so we allow lowercase names in the config
    #   and coerce them to upper here
    backend_priority = config_object.priority or []
    error.type_check("<COR46006487E>", list, backend_priority=backend_priority)

    # Check if disable_local is set
    disable_local_backend = config_object.disable_local or False

    # Add local at the end of priority by default
    # TODO: Should we remove LOCAL from priority if it is disabled?
    if not disable_local_backend and (
        MODULE_BACKEND_TYPES.LOCAL not in backend_priority
    ):
        log.debug3("Adding fallback priority to [%s]", MODULE_BACKEND_TYPES.LOCAL)
        backend_priority.append(MODULE_BACKEND_TYPES.LOCAL)
    backend_priority = [backend.upper() for backend in backend_priority]

    for i, backend in enumerate(backend_priority):
        error.value_check(
            "<COR72281596E>",
            backend in MODULE_BACKEND_TYPES,
            "Invalid backend [{}] found at backend_priority index [{}]",
            backend,
            i,
        )
    log.debug2("Backend Priority: %s", backend_priority)

    # Iterate through the config objects for each enabled backend in order and
    # do the actual config
    backend_configs = {
        key.lower(): val for key, val in config_object.get("configs", {}).items()
    }
    for backend in backend_priority:
        log.debug("Configuring backend [%s]", backend)
        backend_config = backend_configs.get(backend.lower(), {})
        log.debug3("Backend [%s] config: %s", backend, backend_config)

        if (
            backend in get_configured_backends()
            and backend != MODULE_BACKEND_TYPES.LOCAL
        ):
            error("<COR64618509E>", AssertionError(f"{backend} already configured"))

        config_class = MODULE_BACKEND_CLASSES.get(backend)

        # NOTE: since all backends needs to be derived from BackendBase, they all
        # support configuration. as input
        if config_class is not None:
            log.debug2("Performing config for [%s]", backend)
            config_class_obj = config_class(backend_config)

            # Add configuration to backends as per individual module requirements
            _configure_backend_overrides(backend, config_class_obj)

        # NOTE: Configured backends holds the object of backend classes that are based
        # on BaseBackend
        # The start operation of the backend needs to be performed separately
        _CONFIGURED_BACKENDS[backend] = config_class_obj
        _BACKEND_START_LOCKS[backend] = threading.Lock()

    log.debug2("All configured backends: %s", _CONFIGURED_BACKENDS)


## Implementation Details ######################################################

# The global map of configured backends
_CONFIGURED_BACKENDS = {}


# Thread-safe lock for each backend to ensure that starting is not performed
# multiple times on any given backend
_BACKEND_START_LOCKS = {}


def _configure_backend_overrides(backend: str, config_class_obj: object):
    """Function to go over all the modules registered in the MODULE_BACKEND_REGISTRY
    for a particular backend and configure their backend overrides

    Args:
        backend: str
            Name of the backend to select from registry
        config_class_obj: object
            Initialized object of Backend module. This object should
            implement the `register_config` function which will be
            used to merge / iteratively configure the backend
    """
    # Go through all the modules registered with particular backend
    for module_id, module_type_mapping in MODULE_BACKEND_REGISTRY.items():
        if backend in module_type_mapping:
            # check if it contains any special config
            config = module_type_mapping[backend].backend_config_override
            error.type_check("<COR61136899E>", dict, config=config)
            if len(config) != 0:
                # TODO: Add a check here to see if the backend has already started
                config_class_obj.register_config(config)
            else:
                log.debug2(
                    f"No backend overrides configured for {module_id} module and {backend} backend"
                )
