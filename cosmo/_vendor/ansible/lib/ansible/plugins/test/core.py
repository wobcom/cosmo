# (c) 2012, Jeroen Hoekx <jeroen@hoekx.be>
#
# This file is part of Ansible
#
# Ansible is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.
#
# Ansible is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with Ansible.  If not, see <http://www.gnu.org/licenses/>.

from __future__ import annotations

import operator as py_operator

from cosmo._vendor.ansible.lib.ansible.module_utils.compat.version import (
    LooseVersion,
    StrictVersion,
)

from cosmo._vendor.ansible.lib.ansible.utils.version import SemanticVersion

try:
    from packaging.version import Version as PEP440Version

    HAS_PACKAGING = True
except ImportError:
    HAS_PACKAGING = False


def version_compare(value, version, operator="eq", strict=None, version_type=None):
    """Perform a version comparison on a value"""
    op_map = {
        "==": "eq",
        "=": "eq",
        "eq": "eq",
        "<": "lt",
        "lt": "lt",
        "<=": "le",
        "le": "le",
        ">": "gt",
        "gt": "gt",
        ">=": "ge",
        "ge": "ge",
        "!=": "ne",
        "<>": "ne",
        "ne": "ne",
    }

    type_map = {
        "loose": LooseVersion,
        "strict": StrictVersion,
        "semver": SemanticVersion,
        "semantic": SemanticVersion,
        "pep440": PEP440Version,
    }

    if strict is not None and version_type is not None:
        raise Exception("Cannot specify both 'strict' and 'version_type'")

    if not value:
        raise Exception("Input version value cannot be empty")

    if not version:
        raise Exception("Version parameter to compare against cannot be empty")

    if version_type == "pep440" and not HAS_PACKAGING:
        raise Exception(
            "The pep440 version_type requires the Python 'packaging' library"
        )

    Version = LooseVersion
    if strict:
        Version = StrictVersion
    elif version_type:
        try:
            Version = type_map[version_type]
        except KeyError:
            raise Exception(
                "Invalid version type (%s). Must be one of %s"
                % (version_type, ", ".join(map(repr, type_map)))
            )

    if operator in op_map:
        operator = op_map[operator]
    else:
        raise Exception(
            "Invalid operator type (%s). Must be one of %s"
            % (operator, ", ".join(map(repr, op_map)))
        )

    try:
        method = getattr(py_operator, operator)
        return method(Version(str(value)), Version(str(version)))
    except Exception as e:
        raise Exception("Version comparison failed: %s" % str(e))
