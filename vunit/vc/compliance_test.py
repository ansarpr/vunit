# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this file,
# You can obtain one at http://mozilla.org/MPL/2.0/.
#
# Copyright (c) 2014-2019, Lars Asplund lars.anders.asplund@gmail.com

"""
Module for generating a compliance test for a VUnit verification component
"""

import argparse
import sys
import re
import logging
from os import makedirs
from os.path import exists, join, dirname, isdir
from re import subn, MULTILINE, IGNORECASE, DOTALL
from string import Template
from vunit.vhdl_parser import (
    VHDLDesignFile,
    VHDLFunctionSpecification,
    find_closing_delimiter,
    remove_comments,
    VHDLRecordType,
)

LOGGER = logging.getLogger(__name__)


class ComplianceTest(object):
    """
    Represents the compliance test for a VUnit verification component.

    :param vc_lib: The :class:`.Library` containing the verification component and its interface.
    :param vc_name: The name of the verification component entity.
    :param vci_name: The name of the verification component interface package."""

    def __init__(self, vc_lib, vc_name, vci_name):
        try:
            self.vc_facade = vc_lib.get_entity(vc_name)
        except KeyError:
            LOGGER.error("Failed to find VC %s", vc_name)
            sys.exit(1)

        self.vc_code = self._validate_vc(self.vc_facade.source_file.name)
        if not self.vc_code:
            sys.exit(1)

        self.vc_entity = self.vc_code.entities[0]
        self.vc_handle_t = self.vc_entity.generics[0].subtype_indication.type_mark

        try:
            self.vci_facade = vc_lib.package(vci_name)
        except KeyError:
            LOGGER.error("Failed to find VCI %s", vci_name)
            sys.exit(1)

        _, self.vc_constructor = self._validate_vci(
            self.vci_facade.source_file.name, self.vc_handle_t
        )

        if not self.vc_constructor:
            sys.exit(1)

    @classmethod
    def _validate_vc(cls, vc_source_file_name):
        """Validates the existence and contents of the verification component."""

        with open(vc_source_file_name) as fptr:
            vc_code = VHDLDesignFile.parse(fptr.read())

            if len(vc_code.entities) != 1:
                LOGGER.error("%s must contain a single VC entity", vc_source_file_name)
                return None

            vc_entity = vc_code.entities[0]

            if not (
                (len(vc_entity.generics) == 1)
                and (len(vc_entity.generics[0].identifier_list) == 1)
            ):
                LOGGER.error("%s must have a single generic", vc_entity.identifier)
                return None

            return vc_code

    @classmethod
    def _validate_vci(cls, vci_source_file_name, vc_handle_t):
        """Validates the existence and contents of the verification component interface."""

        def create_messages(required_parameter_types, expected_default_value):
            messages = [
                "Failed to find constructor function starting with new_",
                "Found constructor function starting with new_ but not with the correct return type %s"
                % (vc_handle_t),
            ]

            for parameter_name, parameter_type in required_parameter_types.items():
                messages.append(
                    "Found constructor function but the %s parameter is missing"
                    % (parameter_name)
                )
                messages.append(
                    "Found constructor function but the %s parameter is not of type %s"
                    % (parameter_name, parameter_type)
                )
                messages.append(
                    "Found constructor function but %s is the only allowed default value for the %s parameter"
                    % (expected_default_value[parameter_name], parameter_name)
                )

            return messages

        def get_constructor(code):
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
            message_idx = 0
            for func in VHDLFunctionSpecification.find(code):
                if not func.identifier.startswith("new_"):
                    continue
                message_idx = max(message_idx, 1)

                if func.return_type_mark != vc_handle_t:
                    continue
                message_idx = max(message_idx, 2)

                parameters = {}
                for parameter in func.parameter_list:
                    for identifier in parameter.identifier_list:
                        parameters[identifier] = parameter

                step = 3
                parameters_missing_default_value = set()
                for parameter_name, parameter_type in required_parameter_types.items():
                    if parameter_name not in parameters:
                        break
                    message_idx = max(message_idx, step)
                    step += 1

                    if (
                        parameters[parameter_name].subtype_indication.type_mark
                        != parameter_type
                    ):
                        break
                    message_idx = max(message_idx, step)
                    step += 1

                    if not parameters[parameter_name].init_value:
                        parameters_missing_default_value.add(parameter_name)
                    elif expected_default_value[parameter_name] and (
                        parameters[parameter_name].init_value
                        != expected_default_value[parameter_name]
                    ):
                        break
                    message_idx = max(message_idx, step)
                    step += 1

                if step == len(messages) + 1:
                    for parameter_name in parameters_missing_default_value:
                        LOGGER.warning(
                            "%s parameter in %s is missing a default value",
                            parameter_name,
                            func.identifier,
                        )
                    return func

            LOGGER.error(messages[message_idx])
            return None

        def valid_vc_handle_t(code, vc_handle_t):
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

        with open(vci_source_file_name) as fptr:
            code = remove_comments(fptr.read())
            vci_code = VHDLDesignFile.parse(code)
            if len(vci_code.packages) != 1:
                LOGGER.error(
                    "%s must contain a single VCI package", vci_source_file_name
                )
                return None, None

            vc_constructor = get_constructor(code)
            if not valid_vc_handle_t(code, vc_handle_t):
                vc_constructor = None

            return vci_code.packages[0], vc_constructor

    def add_vhdl_testbench(self, vc_test_lib, test_dir, template_path=None):
        """
        Adds a VHDL compliance testbench

        :param vc_test_lib: The name of the library to which the testbench is added.
        :param test_dir: The name of the directory where the testbench file is stored.
        :param template_path: Path to testbench template file. If None, a default template is used.

        :returns: The :class:`.SourceFile` for the added testbench.

        :example:

        .. code-block:: python

           root = dirname(__file__)
           prj.add_vhdl_testbench("test_lib", join(root, "test"), join(root, ".vc", "vc_template.vhd")

        """

        try:
            vc_test_lib.test_bench("tb_%s_compliance" % self.vc_entity.identifier)
            raise RuntimeError(
                "tb_%s_compliance already exists in %s"
                % (self.vc_entity.identifier, vc_test_lib.name)
            )
        except KeyError:
            pass

        if not exists(test_dir):
            makedirs(test_dir)

        tb_path = join(test_dir, "tb_%s_compliance.vhd" % self.vc_entity.identifier)
        with open(tb_path, "w") as fptr:
            testbench_code = self.create_vhdl_testbench(template_path)
            if not testbench_code:
                return None
            fptr.write(testbench_code)

        tb_file = vc_test_lib.add_source_file(tb_path)
        testbench = vc_test_lib.test_bench(
            "tb_%s_compliance" % self.vc_entity.identifier
        )
        test = testbench.test("Test that the actor can be customised")
        test.set_generic("use_custom_actor", True)

        test = testbench.test("Test unexpected message handling")
        test.add_config(
            name="accept_unexpected_msg_type",
            generics=dict(
                fail_on_unexpected_msg_type=False,
                use_custom_logger=True,
                use_custom_actor=True,
            ),
        )
        test.add_config(
            name="fail_unexpected_msg_type_with_null_checker",
            generics=dict(
                fail_on_unexpected_msg_type=True,
                use_custom_logger=True,
                use_custom_actor=True,
            ),
        )
        test.add_config(
            name="fail_unexpected_msg_type_with_custom_checker",
            generics=dict(
                fail_on_unexpected_msg_type=True,
                use_custom_logger=True,
                use_custom_checker=True,
                use_custom_actor=True,
            ),
        )

        return tb_file

    @classmethod
    def create_vhdl_testbench_template(cls, vc_lib_name, vc_path, vci_path):
        """
        Creates a template for a compliance testbench.

        :param vc_lib_name: Name of the library containing the verification component and its interface.
        :param vc_path: Path to the file containing the verification component entity.
        :param vci_path: Path to the file containing the verification component interface package.

        :returns: The template string and the name of the verification component entity.
        """

        def create_context_items(code):
            library_names = set(["std", "work", "vunit_lib", vc_lib_name])

            context_refs = set(["vunit_lib.vunit_context", "vunit_lib.com_context"])
            package_refs = set(
                [
                    "vunit_lib.sync_pkg.all",
                    "%s.%s.all" % (vc_lib_name, vci_package.identifier),
                ]
            )

            for ref in code.references:
                if ref.is_package_reference() or ref.is_context_reference():
                    library_names.add(ref.library_name)

                    library_name = (
                        ref.library_name if ref.library_name != "work" else vc_lib_name
                    )

                    if ref.is_context_reference():
                        context_refs.add("%s.%s" % (library_name, ref.design_unit_name))

                    if ref.is_package_reference():
                        package_refs.add(
                            "%s.%s.%s"
                            % (library_name, ref.design_unit_name, ref.name_within)
                        )

            context_items = ""
            for library in sorted(library_names):
                if library not in ["std", "work"]:
                    context_items += "library %s;\n" % library

            for context_ref in sorted(context_refs):
                context_items += "context %s;\n" % context_ref

            for package_ref in sorted(package_refs):
                context_items += "use %s;\n" % package_ref

            return context_items

        def create_constructor(vc_entity, vc_handle_t, vc_constructor):
            unspecified_parameters = []
            for parameter in vc_constructor.parameter_list:
                if not parameter.init_value:
                    unspecified_parameters += parameter.identifier_list

            constructor = (
                "  -- TODO: Specify a value for all listed parameters. Keep all parameters on separate lines\n"
                if unspecified_parameters
                else ""
            )
            constructor += "  constant %s : %s := %s" % (
                vc_entity.generics[0].identifier_list[0],
                vc_handle_t,
                vc_constructor.identifier,
            )

            if not unspecified_parameters:
                constructor += ";\n"
            else:
                constructor += "(\n"
                for parameter in unspecified_parameters:
                    if parameter in ["actor", "logger", "checker"]:
                        continue
                    constructor += "    %s => ,\n" % parameter
                constructor = constructor[:-2] + "\n  );\n"

            return constructor

        def create_signal_declarations_and_vc_instantiation(vc_entity, vc_lib_name):
            signal_declarations = (
                "  -- TODO: Constrain any unconstrained signal connecting to the DUT.\n"
                if vc_entity.ports
                else ""
            )
            port_mappings = ""
            for port in vc_entity.ports:
                if (port.mode != "out") and port.init_value:
                    for identifier in port.identifier_list:
                        port_mappings += "      %s => open,\n" % identifier
                else:
                    signal_declarations += "  signal %s : %s;\n" % (
                        ", ".join(port.identifier_list),
                        port.subtype_indication,
                    )
                    for identifier in port.identifier_list:
                        port_mappings += "      %s => %s,\n" % (identifier, identifier,)

            vc_instantiation = """  -- DO NOT modify the VC instantiation.
  vc_inst: entity %s.%s
    generic map(%s)""" % (
                vc_lib_name,
                vc_entity.identifier,
                vc_entity.generics[0].identifier_list[0],
            )

            if len(vc_entity.ports) > 0:
                vc_instantiation = (
                    vc_instantiation
                    + """
    port map(
"""
                )

                vc_instantiation += port_mappings[:-2] + "\n    );\n"
            else:
                vc_instantiation += ";\n"

            return signal_declarations, vc_instantiation

        vc_code = cls._validate_vc(vc_path)
        vc_entity = vc_code.entities[0]
        vc_handle_t = vc_entity.generics[0].subtype_indication.type_mark
        vci_package, vc_constructor = cls._validate_vci(vci_path, vc_handle_t)
        if (not vci_package) or (not vc_constructor):
            return None, None

        (
            signal_declarations,
            vc_instantiation,
        ) = create_signal_declarations_and_vc_instantiation(vc_entity, vc_lib_name)

        tb_template = Template(
            """-- Read the TODOs to complete this template.

${context_items}
entity tb_${vc_name}_compliance is
  generic(
    runner_cfg : string);
end entity;

architecture tb of tb_${vc_name}_compliance is

${constructor}
${signal_declarations}
begin
  -- DO NOT modify the test runner process.
  test_runner : process
  begin
    test_runner_setup(runner, runner_cfg);
    test_runner_cleanup(runner);
  end process test_runner;

${vc_instantiation}
end architecture;
"""
        )

        return (
            tb_template.substitute(
                context_items=create_context_items(vc_code),
                vc_name=vc_entity.identifier,
                constructor=create_constructor(vc_entity, vc_handle_t, vc_constructor),
                signal_declarations=signal_declarations,
                vc_instantiation=vc_instantiation,
            ),
            vc_entity.identifier,
        )

    def create_vhdl_testbench(self, template_path=None):
        """
        Creates a VHDL compliance testbench.

        :param template_path: Path to template file. If None, a default template is assumed.

        :returns: The testbench code as a string.
        """

        def update_architecture_declarations(code):
            _constructor_call_start_re = re.compile(
                r"\bconstant\s+{vc_handle_name}\s*:\s*{vc_handle_t}\s*:=\s*{vc_constructor_name}".format(
                    vc_handle_name=self.vc_entity.generics[0].identifier_list[0],
                    vc_handle_t=self.vc_handle_t,
                    vc_constructor_name=self.vc_constructor.identifier,
                ),
                MULTILINE | IGNORECASE | DOTALL,
            )

            constructor_call_start = _constructor_call_start_re.search(code)
            if not constructor_call_start:
                raise RuntimeError(
                    "Failed to find call to %s in template_path %s"
                    % (self.vc_constructor.identifier, template_path)
                )

            parameter_start_re = re.compile(r"\s*\(", MULTILINE | IGNORECASE | DOTALL)
            parameter_start = parameter_start_re.match(
                code[constructor_call_start.end() :]
            )

            if parameter_start:
                closing_parenthesis_pos = find_closing_delimiter(
                    "\\(",
                    "\\)",
                    code[constructor_call_start.end() + parameter_start.end() :],
                )

                specified_parameters = (
                    code[
                        constructor_call_start.end()
                        + parameter_start.end() : constructor_call_start.end()
                        + parameter_start.end()
                        + closing_parenthesis_pos
                        - 1
                    ].strip()
                    + ","
                )

            else:
                specified_parameters = ""

            _constructor_call_end_re = re.compile(
                r"\s*;", MULTILINE | IGNORECASE | DOTALL
            )
            if parameter_start:
                search_start = (
                    constructor_call_start.end()
                    + parameter_start.end()
                    + closing_parenthesis_pos
                )
                constructor_call_end_match = _constructor_call_end_re.match(
                    code[search_start:]
                )
            else:
                search_start = constructor_call_start.end()
                constructor_call_end_match = _constructor_call_end_re.match(
                    code[search_start:]
                )

            if not constructor_call_end_match:
                raise RuntimeError(
                    "Missing trailing semicolon for %s in template_path %s"
                    % (self.vc_constructor.identifier, template_path)
                )

            constructor_call_end = search_start + constructor_call_end_match.end()

            default_values = {}
            for parameter in self.vc_constructor.parameter_list:
                for identifier in parameter.identifier_list:
                    default_values[identifier] = parameter.init_value

            architecture_declarations = """\
constant custom_actor : actor_t := new_actor("vc", inbox_size => 1);
  constant custom_logger : logger_t := get_logger("vc");
  constant custom_checker : checker_t := new_checker(get_logger("vc_check"));

  impure function create_handle return {vc_handle_t} is
    variable handle : {vc_handle_t};
    variable logger : logger_t := {default_logger};
    variable actor : actor_t := {default_actor};
    variable checker : checker_t := {default_checker};
  begin
    if use_custom_logger then
      logger := custom_logger;
    end if;

    if use_custom_actor then
      actor := custom_actor;
    end if;

    if use_custom_checker then
      checker := custom_checker;
    end if;

    return {vc_constructor_name}(
      {specified_parameters}
      logger => logger,
      actor => actor,
      checker => checker,
      fail_on_unexpected_msg_type => fail_on_unexpected_msg_type);
  end;

  constant {vc_handle_name} : {vc_handle_t} := create_handle;
  constant unexpected_msg : msg_type_t := new_msg_type("unexpected msg");
""".format(
                vc_handle_t=self.vc_handle_t,
                vc_constructor_name=self.vc_constructor.identifier,
                specified_parameters=specified_parameters,
                vc_handle_name=self.vc_entity.generics[0].identifier_list[0],
                default_logger=default_values["logger"]
                if default_values["logger"]
                else 'get_logger("vc_logger")',
                default_actor=default_values["actor"]
                if default_values["actor"]
                else 'new_actor("vc_actor")',
                default_checker=default_values["checker"]
                if default_values["checker"]
                else 'new_checker("vc_checker")',
            )

            return (
                code[: constructor_call_start.start()]
                + architecture_declarations
                + code[constructor_call_end:]
            )

        def update_test_runner(code):
            _test_runner_re = re.compile(
                r"\btest_runner\s*:\s*process.*?end\s+process\s+test_runner\s*;",
                # r"\btest_runner\s*:\s*process",
                MULTILINE | IGNORECASE | DOTALL,
            )

            new_test_runner = """\
test_runner : process
  variable t_start : time;
  variable msg : msg_t;
  variable error_logger : logger_t;
begin
  test_runner_setup(runner, runner_cfg);

  while test_suite loop

    if run("Test that sync interface is supported") then
      t_start := now;
      wait_for_time(net, as_sync({vc_handle_name}), 1 ns);
      wait_for_time(net, as_sync({vc_handle_name}), 2 ns);
      wait_for_time(net, as_sync({vc_handle_name}), 3 ns);
      check_equal(now - t_start, 0 ns);
      t_start := now;
      wait_until_idle(net, as_sync({vc_handle_name}));
      check_equal(now - t_start, 6 ns);

    elsif run("Test that the actor can be customised") then
      t_start := now;
      wait_for_time(net, as_sync({vc_handle_name}), 1 ns);
      wait_for_time(net, as_sync({vc_handle_name}), 2 ns);
      check_equal(now - t_start, 0 ns);
      wait_for_time(net, as_sync({vc_handle_name}), 3 ns);
      check_equal(now - t_start, 1 ns);
      wait_until_idle(net, as_sync({vc_handle_name}));
      check_equal(now - t_start, 6 ns);

    elsif run("Test unexpected message handling") then
      if use_custom_checker then
        error_logger := get_logger(custom_checker);
      else
        error_logger := custom_logger;
      end if;
      mock(error_logger, failure);
      msg := new_msg(unexpected_msg);
      send(net, custom_actor, msg);
      wait for 1 ns;
      if fail_on_unexpected_msg_type then
        check_only_log(error_logger, "Got unexpected message unexpected msg", failure);
      else
        check_no_log;
      end if;
      unmock(error_logger);
    end if;

  end loop;

  test_runner_cleanup(runner);
end process test_runner;""".format(
                vc_handle_name=self.vc_entity.generics[0].identifier_list[0]
            )

            code, num_found_test_runners = subn(
                _test_runner_re, new_test_runner, code, 1
            )
            if not num_found_test_runners:
                raise RuntimeError(
                    "Failed to find test runner in template_path %s" % template_path
                )

            return code

        def update_generics(code):
            _runner_cfg_re = re.compile(
                r"\brunner_cfg\s*:\s*string", MULTILINE | IGNORECASE | DOTALL
            )

            new_generics = """use_custom_logger : boolean := false;
    use_custom_checker : boolean := false;
    use_custom_actor : boolean := false;
    fail_on_unexpected_msg_type : boolean := true;
    runner_cfg : string"""

            code, num_found_runner_cfg = subn(_runner_cfg_re, new_generics, code, 1)
            if not num_found_runner_cfg:
                raise RuntimeError(
                    "Failed to find runner_cfg generic in template_path %s"
                    % template_path
                )

            return code

        if template_path:
            with open(template_path) as fptr:
                template_code = fptr.read().lower()
        else:
            template_code, _ = self.create_vhdl_testbench_template(
                self.vc_facade.library,
                self.vc_facade.source_file.name,
                self.vci_facade.source_file.name,
            )
            if not template_code:
                return None
            template_code = template_code.lower()

        design_file = VHDLDesignFile.parse(template_code)
        if (
            design_file.entities[0].identifier
            != "tb_%s_compliance" % self.vc_facade.name
        ):
            raise RuntimeError(
                "%s is not a template_path for %s"
                % (template_path, self.vc_facade.name)
            )

        tb_code = update_architecture_declarations(template_code)
        tb_code = update_test_runner(tb_code)
        tb_code = update_generics(tb_code)

        return remove_comments(tb_code)


def main():
    """Parses the command line arguments and acts accordingly."""

    def create_template(args):
        template_code, vc_name = ComplianceTest.create_vhdl_testbench_template(
            args.vc_lib_name, args.vc_path, args.vci_path
        )
        if not template_code or not vc_name:
            sys.exit(1)

        if not args.output_path:
            output_dir = join(dirname(args.vc_path), ".vc")
            if not exists(output_dir):
                makedirs(output_dir)

            output_path = join(output_dir, "tb_%s_compliance_template.vhd" % vc_name)
        elif isdir(args.output_path):
            output_path = join(
                args.output_path, "tb_%s_compliance_template.vhd" % vc_name
            )
        else:
            output_path = args.output_path

        with open(output_path, "w") as output_file:
            output_file.write(template_code)

    parser = argparse.ArgumentParser(description="Compliance test tool")
    subparsers = parser.add_subparsers(dest="subparser_name", help="sub-command help")

    parser_create = subparsers.add_parser(
        "create", help="Creates a compliance test template"
    )
    parser_create.add_argument(
        "-l",
        "--vc-lib-name",
        help="Name of library hosting the VC and the VCI (default: vc_lib)",
        default="vc_lib",
    )
    parser_create.add_argument(
        "-o",
        "--output-path",
        help="Path to the template  (default: ./compliance_test/tb_<VC name>_compliance_template.vhd)",
    )
    parser_create.add_argument("vc_path", help="Path to file containing the VC entity")
    parser_create.add_argument(
        "vci_path", help="Path to file containing the VCI package"
    )

    args = parser.parse_args(sys.argv[1:])

    logging.basicConfig(format="%(levelname)s: %(message)s")

    if args.subparser_name == "create":
        create_template(args)


if __name__ == "__main__":
    main()
