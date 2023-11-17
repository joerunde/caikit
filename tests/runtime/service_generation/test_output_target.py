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
"""
Tests for the
- output_field data model for runtime training APIs
- model saver plugins that populate that field
"""
# Third Party
import pytest

# Local
from caikit.core.data_model import DataBase
from caikit.core.model_management import LocalModelSaver
from caikit.runtime.service_generation.output_target import make_output_target_message
import caikit

#
# def test_local_saver_plugin():
#     plugin = LocalModelSaverPlugin(config={}, instance_name="_test")
#
#     # Should have output target type `PathReference`
#     assert plugin.get_output_target_type() == PathReference
#
#     # Field name should be "path_reference" (target type lower snake cased)
#     assert plugin.get_field_name() == "path_reference"
#
#     # Model saver is the local path one
#     assert plugin.get_model_saver_class() == LocalModelSaver
#
#     # Can construct a `LocalPathModelSaver` with a `PathReference`
#     saver = plugin.make_model_saver(PathReference(path="foo"))
#     assert isinstance(saver, LocalModelSaver)
#
#
# def test_local_saver_plugin_validates_target_type():
#     plugin = LocalModelSaverPlugin(config={}, instance_name="_test")
#     with pytest.raises(
#         TypeError, match="variable `target` has type `str` .* not in .*PathReference"
#     ):
#         plugin.make_model_saver(target="/some/path")
#
#
# @pytest.fixture
# def plugin_factory():
#     fct = ModelSaverPluginFactory("TestFactory")
#     fct.register(LocalModelSaverPlugin)
#     yield fct


# TODO: add fixture like `reset_stream_source_types`


def test_output_target_message_class():
    output_target_class = make_output_target_message()

    # Inherits from DataBase
    assert issubclass(output_target_class, DataBase)

    # Should have one `oneof`
    assert len(output_target_class.get_proto_class().DESCRIPTOR.oneofs) == 1
    oneof = output_target_class.get_proto_class().DESCRIPTOR.oneofs[0]

    # For now: only has the `local` field. Can add more test model savers for more
    assert len(oneof.fields) == 1

    assert hasattr(output_target_class, "local")


def test_output_targets_can_be_used_to_build_model_savers():
    output_target_class = make_output_target_message()

    target_field = output_target_class(local="foo")

    saver = caikit.core.make_model_saver(target_field.output_target)

    assert isinstance(saver, LocalModelSaver)
