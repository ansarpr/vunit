# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this file,
# You can obtain one at http://mozilla.org/MPL/2.0/.
#
# Copyright (c) 2014-2019, Lars Asplund lars.anders.asplund@gmail.com

"""VerificationComponentInterface class."""

import sys
import re
import logging
from os import makedirs
from os.path import exists, join
from string import Template
from vunit.vhdl_parser import (
    VHDLDesignFile,
    VHDLFunctionSpecification,
    remove_comments,
    VHDLRecordType,
)

LOGGER = logging.getLogger(__name__)


def create_context_items(
    code, lib_name, initial_library_names, initial_context_refs, initial_package_refs
):
    """Creates a VHDL snippet with context items found in the provided code and the initial_ arguments."""
    for ref in code.references:
        if ref.is_package_reference() or ref.is_context_reference():
            initial_library_names.add(ref.library_name)

            library_name = ref.library_name if ref.library_name != "work" else lib_name

            if ref.is_context_reference():
                initial_context_refs.add("%s.%s" % (library_name, ref.design_unit_name))

            if ref.is_package_reference():
                initial_package_refs.add(
                    "%s.%s.%s" % (library_name, ref.design_unit_name, ref.name_within)
                )

    context_items = ""
    for library in sorted(initial_library_names):
        if library not in ["std", "work"]:
            context_items += "library %s;\n" % library

    for context_ref in sorted(initial_context_refs):
        context_items += "context %s;\n" % context_ref

    for package_ref in sorted(initial_package_refs):
        context_items += "use %s;\n" % package_ref

    return context_items


class VerificationComponentInterface:
    """Represents a Verification Component Interface (VCI)."""

    @classmethod
    def find(cls, vc_lib, vci_name, vc_handle_t):
        """ Finds the specified VCI if present.

        :param vc_lib: Library object containing the VCI.
        :param vci_name: Name of VCI package.
        :param vc_handle_t: Name of VC handle type.

        :returns: A VerificationComponentInterface object.
        """

        try:
            vci_facade = vc_lib.package(vci_name)
        except KeyError:
            LOGGER.error("Failed to find VCI %s", vci_name)
            sys.exit(1)

        _, vc_constructor = cls.validate(vci_facade.source_file.name, vc_handle_t)
        if not vc_constructor:
            sys.exit(1)

        return cls(vci_facade, vc_constructor)

    @classmethod
    def validate(cls, vci_source_file_name, vc_handle_t):
        """Validates the existence and contents of the verification component interface."""

        with open(vci_source_file_name) as fptr:
            code = remove_comments(fptr.read())
            vci_code = VHDLDesignFile.parse(code)
            if len(vci_code.packages) != 1:
                LOGGER.error(
                    "%s must contain a single VCI package", vci_source_file_name
                )
                return None, None

            vc_constructor = cls._validate_constructor(code, vc_handle_t)
            if not cls._validate_handle(code, vc_handle_t):
                vc_constructor = None

            return vci_code, vc_constructor

    def __init__(self, vci_facade, vc_constructor):
        self.vci_facade = vci_facade
        self.vc_constructor = vc_constructor

    @staticmethod
    def _validate_constructor(code, vc_handle_t):
        """Validates the existence and format of the verification component constructor."""

        def create_messages(required_parameter_types, expected_default_value):
            messages = [
                "Failed to find a constructor function%s for %s starting with new_",
                "Found constructor function %s but not with the correct return type %s",
            ]

            for parameter_name, parameter_type in required_parameter_types.items():
                messages.append(
                    "Found constructor function %s for %s but the {} parameter is missing".format(
                        parameter_name
                    )
                )
                messages.append(
                    "Found constructor function %s for %s but the {} parameter is not of type {}".format(
                        parameter_name, parameter_type
                    )
                )
                messages.append(
                    "Found constructor function %s for %s but {} is the only allowed default "
                    "value for the {} parameter".format(
                        expected_default_value[parameter_name], parameter_name
                    )
                )

            return messages

        def log_error_message(function_score, messages):
            high_score = 0
            best_function = ""
            for function_name, score in function_score.items():
                if score > high_score:
                    high_score = score
                    best_function = function_name

            error_msg = messages[high_score] % (best_function, vc_handle_t)
            LOGGER.error(error_msg)

        required_parameter_types = dict(
            logger="logger_t",
            actor="actor_t",
            checker="checker_t",
            fail_on_unexpected_msg_type="boolean",
        )

        expected_default_value = dict(
            logger=None,
            actor="null_actor",
            checker="null_checker",
            fail_on_unexpected_msg_type=None,
        )

        messages = create_messages(required_parameter_types, expected_default_value)

        function_score = {}
        for func in VHDLFunctionSpecification.find(code):
            function_score[func.identifier] = 0

            if not func.identifier.startswith("new_"):
                continue
            function_score[func.identifier] += 1

            if func.return_type_mark != vc_handle_t:
                continue
            function_score[func.identifier] += 1

            parameters = {}
            for parameter in func.parameter_list:
                for identifier in parameter.identifier_list:
                    parameters[identifier] = parameter

            parameters_missing_default_value = set()
            for parameter_name, parameter_type in required_parameter_types.items():
                if parameter_name not in parameters:
                    break
                function_score[func.identifier] += 1

                if (
                    parameters[parameter_name].subtype_indication.type_mark
                    != parameter_type
                ):
                    break
                function_score[func.identifier] += 1

                if not parameters[parameter_name].init_value:
                    parameters_missing_default_value.add(parameter_name)
                elif expected_default_value[parameter_name] and (
                    parameters[parameter_name].init_value
                    != expected_default_value[parameter_name]
                ):
                    break
                function_score[func.identifier] += 1

            if function_score[func.identifier] == len(messages):
                for parameter_name in parameters_missing_default_value:
                    LOGGER.warning(
                        "%s parameter in %s is missing a default value",
                        parameter_name,
                        func.identifier,
                    )
                return func

        log_error_message(function_score, messages)

        return None

    @staticmethod
    def _validate_handle(code, vc_handle_t):
        """Validates the existence and format of the verification component handle type."""

        handle_is_valid = True
        for record in VHDLRecordType.find(code):
            if record.identifier == vc_handle_t:
                for element in record.elements:
                    for parameter_name in element.identifier_list:
                        if not parameter_name.lower().startswith("p_"):
                            handle_is_valid = False
                            LOGGER.error(
                                "%s in %s doesn't start with p_",
                                parameter_name,
                                vc_handle_t,
                            )
                return handle_is_valid

        LOGGER.error(
            "Failed to find %s record", vc_handle_t,
        )
        return False

    @classmethod
    def create_vhdl_testbench_template(cls, vci_lib_name, vci_path, vc_handle_t):
        """
        Creates a template for a VCI compliance testbench.

        :param vc_lib_name: Name of the library containing the verification component interface.
        :param vci_path: Path to the file containing the verification component interface package.
        :param vc_handle_t: Name of the VC handle type returned by the VC constructor.

        :returns: The template code as a string and the name of the verification component entity.
        """
        vci_code, vc_constructor = cls.validate(vci_path, vc_handle_t)

        initial_library_names = set(["std", "work", "vunit_lib", vci_lib_name])
        initial_context_refs = set(["vunit_lib.vunit_context", "vunit_lib.com_context"])
        initial_package_refs = set(
            [
                "vunit_lib.vc_pkg.all",
                "%s.%s.all" % (vci_lib_name, vci_code.packages[0].identifier),
            ]
        )
        context_items = create_context_items(
            vci_code,
            vci_lib_name,
            initial_library_names,
            initial_context_refs,
            initial_package_refs,
        )

        unspecified_parameters = [
            parameter
            for parameter in vc_constructor.parameter_list
            if not parameter.init_value
        ]
        if unspecified_parameters:
            constant_declarations = ""
            for parameter in unspecified_parameters:
                constant_declarations += "    constant %s : %s := ;\n" % (
                    ", ".join(parameter.identifier_list),
                    parameter.subtype_indication.type_mark,
                )
        else:
            constant_declarations = "\n"

        tb_template = Template(
            """-- Read the TODOs to complete this template.

${context_items}
entity tb_${vci_name}_compliance is
  generic(
    runner_cfg : string);
end entity;

architecture tb of tb_${vci_name}_compliance is
begin
  test_runner : process
    -- TODO: Specify a value for all listed constants.
    ${constant_declarations}

    -- DO NOT modify this line and the lines below.
  begin
    test_runner_setup(runner, runner_cfg);
    test_runner_cleanup(runner);
  end process test_runner;
end architecture;
"""
        )

        template_code = tb_template.substitute(
            context_items=context_items,
            vci_name=vci_code.packages[0].identifier,
            constant_declarations=constant_declarations,
        )

        return (
            template_code,
            vci_code.packages[0].identifier,
        )

    def create_vhdl_testbench(self, template_path=None):
        """
        Creates a VHDL VCI compliance testbench.

        :param template_path: Path to template file. If None, a default template is assumed.

        :returns: The testbench code as a string.
        """
        if not template_path:
            template_code, _ = self.create_vhdl_testbench_template(
                self.vci_facade.library,
                self.vci_facade.source_file.name,
                self.vc_constructor.return_type_mark,
            )
        else:
            with open(template_path) as fptr:
                template_code = fptr.read()

        test_runner_body_pattern = re.compile(
            r"\s+-- DO NOT modify this line and the lines below."
        )
        match = test_runner_body_pattern.search(template_code)
        if not match:
            LOGGER.error("Failed to find body of test_runner in template code.")
            return None

        unspecified_parameters = [
            parameter
            for parameter in self.vc_constructor.parameter_list
            if not parameter.init_value
        ]

        def create_handle_assignment(
            handle_name,
            actor=None,
            logger=None,
            checker=None,
            fail_on_unexpected_msg_type=True,
        ):

            handle_assignment = "        %s := %s(\n" % (
                handle_name,
                self.vc_constructor.identifier,
            )
            for parameter in unspecified_parameters:
                for identifier in parameter.identifier_list:
                    handle_assignment += "          %s => %s,\n" % (
                        identifier,
                        identifier,
                    )
            for formal, actual in dict(
                actor=actor,
                logger=logger,
                checker=checker,
                fail_on_unexpected_msg_type=fail_on_unexpected_msg_type,
            ).items():
                if actual:
                    handle_assignment += "          %s => %s,\n" % (formal, actual)

            handle_assignment = handle_assignment[:-2] + "\n        );"

            return handle_assignment

        tb_code = Template(
            template_code[: match.start()]
            + """
    constant actor1 : actor_t := new_actor;
    constant logger1 : logger_t := get_logger("logger1");
    constant checker_logger1 : logger_t := get_logger("checker1");
    constant checker1 : checker_t := new_checker(checker_logger1);

    constant actor2 : actor_t := new_actor;
    constant logger2 : logger_t := get_logger("logger2");
    constant checker_logger2 : logger_t := get_logger("checker2");
    constant checker2 : checker_t := new_checker(checker_logger2);

    variable handle1, handle2 : ${vc_handle_t};
    variable std_cfg1, std_cfg2 : std_cfg_t;
  begin
    test_runner_setup(runner, runner_cfg);

    while test_suite loop
      if run("Test standard configuration") then
${handle1}
        std_cfg1 := get_std_cfg(handle1);

        check(get_actor(std_cfg1) = actor1, "Failed to configure actor with ${vc_constructor_name}");
        check(get_logger(std_cfg1) = logger1, "Failed to configure logger with ${vc_constructor_name}");
        check(get_checker(std_cfg1) = checker1, "Failed to configure checker with ${vc_constructor_name}");
        check(fail_on_unexpected_msg_type(std_cfg1),
        "Failed to configure fail_on_unexpected_msg_type = true with ${vc_constructor_name}");

${handle2}
        std_cfg1 := get_std_cfg(handle1);

        check(fail_on_unexpected_msg_type(std_cfg1) = false,
        "Failed to configure fail_on_unexpected_msg_type = false with ${vc_constructor_name}");

      elsif run("Test handle independence") then
${handle1}
${handle3}

        std_cfg1 := get_std_cfg(handle1);
        std_cfg2 := get_std_cfg(handle2);
        check(get_actor(std_cfg1) /= get_actor(std_cfg2),
        "Actor shared between handles created by ${vc_constructor_name}");
        check(get_logger(std_cfg1) /= get_logger(std_cfg2),
        "Logger shared between handles created by ${vc_constructor_name}");
        check(get_checker(std_cfg1) /= get_checker(std_cfg2),
        "Checker shared between handles created by ${vc_constructor_name}");
        check(fail_on_unexpected_msg_type(std_cfg1) /= fail_on_unexpected_msg_type(std_cfg2),
        "fail_on_unexpected_msg_type shared between handles created by ${vc_constructor_name}");

      elsif run("Test default logger") then
${handle4}
        std_cfg1 := get_std_cfg(handle1);
        check(get_logger(std_cfg1) /= null_logger, "No valid default logger created by ${vc_constructor_name}");

${handle5}
        std_cfg1 := get_std_cfg(handle1);
        check(get_logger(std_cfg1) /= null_logger, "No valid default logger created by ${vc_constructor_name}");

      elsif run("Test default checker") then
${handle6}
        std_cfg1 := get_std_cfg(handle1);
        check(get_checker(std_cfg1) /= null_checker, "No valid default checker created by ${vc_constructor_name}");

${handle7}
        std_cfg1 := get_std_cfg(handle1);
        check(get_checker(std_cfg1) /= null_checker, "No valid default checker created by ${vc_constructor_name}");

${handle8}
        std_cfg1 := get_std_cfg(handle1);
        check(get_checker(std_cfg1) /= null_checker, "No valid default checker created by ${vc_constructor_name}");
        check(get_logger(get_checker(std_cfg1)) = logger1,
        "Default checker not based on logger provided to ${vc_constructor_name}");

      end if;
    end loop;

    test_runner_cleanup(runner);
  end process test_runner;
end architecture;
"""
        )

        testbench_code = tb_code.substitute(
            vc_handle_t=self.vc_constructor.return_type_mark,
            vc_constructor_name=self.vc_constructor.identifier,
            handle1=create_handle_assignment(
                "handle1",
                actor="actor1",
                logger="logger1",
                checker="checker1",
                fail_on_unexpected_msg_type="true",
            ),
            handle2=create_handle_assignment(
                "handle1",
                actor="actor1",
                logger="logger1",
                checker="checker1",
                fail_on_unexpected_msg_type="false",
            ),
            handle3=create_handle_assignment(
                "handle2",
                actor="actor2",
                logger="logger2",
                checker="checker2",
                fail_on_unexpected_msg_type="false",
            ),
            handle4=create_handle_assignment(
                "handle1",
                actor="actor1",
                checker="checker1",
                fail_on_unexpected_msg_type="true",
            ),
            handle5=create_handle_assignment(
                "handle1",
                actor="actor1",
                logger="null_logger",
                checker="checker1",
                fail_on_unexpected_msg_type="true",
            ),
            handle6=create_handle_assignment(
                "handle1", actor="actor1", fail_on_unexpected_msg_type="true",
            ),
            handle7=create_handle_assignment(
                "handle1",
                actor="actor1",
                checker="null_checker",
                fail_on_unexpected_msg_type="true",
            ),
            handle8=create_handle_assignment(
                "handle1",
                actor="actor1",
                logger="logger1",
                fail_on_unexpected_msg_type="true",
            ),
        )

        return testbench_code

    def add_vhdl_testbench(self, vci_test_lib, test_dir, template_path=None):
        """
        Adds a VHDL compliance testbench

        :param vci_test_lib: The name of the library to which the testbench is added.
        :param test_dir: The name of the directory where the testbench file is stored.
        :param template_path: Path to testbench template file. If None, a default template is used.

        :returns: The :class:`.SourceFile` for the added testbench.

        :example:

        .. code-block:: python

           root = dirname(__file__)
           prj.add_vhdl_testbench("test_lib", join(root, "test"), join(root, ".vc", "vc_template.vhd")

        """

        try:
            vci_test_lib.test_bench("tb_%s_compliance" % self.vci_facade.name)
            raise RuntimeError(
                "tb_%s_compliance already exists in %s"
                % (self.vci_facade.name, vci_test_lib.name)
            )
        except KeyError:
            pass

        if not exists(test_dir):
            makedirs(test_dir)

        tb_path = join(test_dir, "tb_%s_compliance.vhd" % self.vci_facade.name)
        with open(tb_path, "w") as fptr:
            testbench_code = self.create_vhdl_testbench(template_path)
            if not testbench_code:
                return None
            fptr.write(testbench_code)

        tb_file = vci_test_lib.add_source_file(tb_path)

        return tb_file
