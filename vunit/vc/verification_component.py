# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this file,
# You can obtain one at http://mozilla.org/MPL/2.0/.
#
# Copyright (c) 2014-2019, Lars Asplund lars.anders.asplund@gmail.com

"""VerificationComponent class."""

import sys
import re
from os import makedirs
from os.path import exists, join
from re import subn, MULTILINE, IGNORECASE, DOTALL
from string import Template
from vunit.vhdl_parser import (
    VHDLDesignFile,
    find_closing_delimiter,
    remove_comments,
)
from vunit.vc.verification_component_interface import (
    VerificationComponentInterface,
    create_context_items,
    LOGGER,
)


class VerificationComponent:
    """Represents a Verification Component (VC)."""

    @classmethod
    def find(cls, vc_lib, vc_name, vci):
        """ Finds the specified VC if present.

        :param vc_lib: Library object containing the VC.
        :param vc_name: Name of VC entity.
        :param vci: A VerificationComponentInterface object representing the VCI used by the VC.

        :returns: A VerificationComponent object.
        """

        if not vci:
            LOGGER.error("No VCI provided")
            sys.exit(1)

        try:
            vc_facade = vc_lib.get_entity(vc_name)
        except KeyError:
            LOGGER.error("Failed to find VC %s", vc_name)
            sys.exit(1)

        vc_code = cls.validate(vc_facade.source_file.name)
        if not vc_code:
            sys.exit(1)

        vc_entity = vc_code.entities[0]
        vc_handle_t = vc_entity.generics[0].subtype_indication.type_mark

        if vc_handle_t != vci.vc_constructor.return_type_mark:
            LOGGER.error(
                "VC handle (%s) doesn't match that of the VCI (%s)",
                vc_handle_t,
                vci.vc_constructor.return_type_mark,
            )
            sys.exit(1)

        return cls(vc_facade, vc_code, vc_entity, vc_handle_t, vci)

    def __init__(self, vc_facade, vc_code, vc_entity, vc_handle_t, vci):
        self.vc_facade = vc_facade
        self.vc_code = vc_code
        self.vc_entity = vc_entity
        self.vc_handle_t = vc_handle_t
        self.vci = vci

    @staticmethod
    def validate(vc_source_file_name):
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

    @staticmethod
    def create_vhdl_testbench_template(vc_lib_name, vc_path, vci_path):
        """
        Creates a template for a VC compliance testbench.

        :param vc_lib_name: Name of the library containing the verification component and its interface.
        :param vc_path: Path to the file containing the verification component entity.
        :param vci_path: Path to the file containing the verification component interface package.

        :returns: The template string and the name of the verification component entity.
        """

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

        vc_code = VerificationComponent.validate(vc_path)
        vc_entity = vc_code.entities[0]
        vc_handle_t = vc_entity.generics[0].subtype_indication.type_mark
        vci_code, vc_constructor = VerificationComponentInterface.validate(
            vci_path, vc_handle_t
        )
        if (not vci_code) or (not vc_constructor):
            return None, None

        (
            signal_declarations,
            vc_instantiation,
        ) = create_signal_declarations_and_vc_instantiation(vc_entity, vc_lib_name)

        initial_package_refs = set(
            [
                "vunit_lib.sync_pkg.all",
                "%s.%s.all" % (vc_lib_name, vci_code.packages[0].identifier),
            ]
        )
        context_items = create_context_items(
            vc_code,
            vc_lib_name,
            initial_library_names=set(["std", "work", "vunit_lib", vc_lib_name]),
            initial_context_refs=set(
                ["vunit_lib.vunit_context", "vunit_lib.com_context"]
            ),
            initial_package_refs=initial_package_refs,
        )

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
                context_items=context_items,
                vc_name=vc_entity.identifier,
                constructor=create_constructor(vc_entity, vc_handle_t, vc_constructor),
                signal_declarations=signal_declarations,
                vc_instantiation=vc_instantiation,
            ),
            vc_entity.identifier,
        )

    def create_vhdl_testbench(self, template_path=None):
        """
        Creates a VHDL VC compliance testbench.

        :param template_path: Path to template file. If None, a default template is assumed.

        :returns: The testbench code as a string.
        """

        def update_architecture_declarations(code):
            _constructor_call_start_re = re.compile(
                r"\bconstant\s+{vc_handle_name}\s*:\s*{vc_handle_t}\s*:=\s*{vc_constructor_name}".format(
                    vc_handle_name=self.vc_entity.generics[0].identifier_list[0],
                    vc_handle_t=self.vc_handle_t,
                    vc_constructor_name=self.vci.vc_constructor.identifier,
                ),
                MULTILINE | IGNORECASE | DOTALL,
            )

            constructor_call_start = _constructor_call_start_re.search(code)
            if not constructor_call_start:
                raise RuntimeError(
                    "Failed to find call to %s in template_path %s"
                    % (self.vci.vc_constructor.identifier, template_path)
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
                    % (self.vci.vc_constructor.identifier, template_path)
                )

            constructor_call_end = search_start + constructor_call_end_match.end()

            default_values = {}
            for parameter in self.vci.vc_constructor.parameter_list:
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
                vc_constructor_name=self.vci.vc_constructor.identifier,
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
                self.vci.vci_facade.source_file.name,
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
