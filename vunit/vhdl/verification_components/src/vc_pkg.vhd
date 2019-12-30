-- This Source Code Form is subject to the terms of the Mozilla Public
-- License, v. 2.0. If a copy of the MPL was not distributed with this file,
-- You can obtain one at http://mozilla.org/MPL/2.0/.
--
-- Copyright (c) 2014-2019, Lars Asplund lars.anders.asplund@gmail.com
--
-- This package contains common functionality for VC designers.

context work.vunit_context;
context work.com_context;

package vc_pkg is
  type std_vc_cfg_t is record
    actor                       : actor_t;
    logger                      : logger_t;
    checker                     : checker_t;
    fail_on_unexpected_msg_type : boolean;
  end record;

  constant null_std_vc_cfg : std_vc_cfg_t := (actor => null_actor, logger => null_logger, checker => null_checker, fail_on_unexpected_msg_type => false);

  -- Creates a standard VC configuration with an actor, a logger, a checker, and the policy for handling unexpected messages
  --
  -- * The actor is the actor provided by the actor parameter unless it's the null_actor. In that case a new actor is created
  -- * The logger is the logger provided by the logger parameter unless it's the null_logger. In that case the default logger is used which must not be the null_logger.
  -- * The checker is the checker provided by the checker parameter unless it's the null_checker. In that case the the default checker is used if the logger is the
  --   default logger. Otherwise a new checker is created based on the provided logger. The default checker must not be the null_checker
  -- * The policy for handling unexpected messages is according to the fail_on_unexpected_msg_type parameter.
  impure function create_std_vc_cfg(
    default_logger              : logger_t;
    default_checker             : checker_t;
    actor                       : actor_t := null_actor;
    logger                      : logger_t := null_logger;
    checker                     : checker_t := null_checker;
    fail_on_unexpected_msg_type : boolean := true
  ) return std_vc_cfg_t;

  -- These functions extracts the different parts of a standard VC configuration
  function get_actor(std_vc_cfg : std_vc_cfg_t) return actor_t;
  function get_logger(std_vc_cfg : std_vc_cfg_t) return logger_t;
  function get_checker(std_vc_cfg : std_vc_cfg_t) return checker_t;
  function fail_on_unexpected_msg_type(std_vc_cfg : std_vc_cfg_t) return boolean;

end package;

package body vc_pkg is
  constant vc_logger : logger_t := get_logger("vunit_lib:vc_pkg");
  constant vc_checker : checker_t := new_checker(vc_logger);

  impure function create_std_vc_cfg(
    default_logger              : logger_t;
    default_checker             : checker_t;
    actor                       : actor_t := null_actor;
    logger                      : logger_t := null_logger;
    checker                     : checker_t := null_checker;
    fail_on_unexpected_msg_type : boolean := true
  ) return std_vc_cfg_t is
    variable result : std_vc_cfg_t;
  begin
    check(vc_checker, default_logger /= null_logger, "A default logger must be provided");
    check(vc_checker, default_checker /= null_checker, "A default checker must be provided");

    result.actor                       := actor when actor /= null_actor else new_actor;
    result.logger                      := logger when logger /= null_logger else default_logger;
    result.fail_on_unexpected_msg_type := fail_on_unexpected_msg_type;

    if checker = null_checker then
      if logger = default_logger then
        result.checker := default_checker;
      else
        result.checker := new_checker(logger);
      end if;
    else
      result.checker := checker;
    end if;

    return result;
  end;

  function get_actor(std_vc_cfg : std_vc_cfg_t) return actor_t is
  begin
    return std_vc_cfg.actor;
  end;

  function get_logger(std_vc_cfg : std_vc_cfg_t) return logger_t is
  begin
    return std_vc_cfg.logger;
  end;

  function get_checker(std_vc_cfg : std_vc_cfg_t) return checker_t is
  begin
    return std_vc_cfg.checker;
  end;

  function fail_on_unexpected_msg_type(std_vc_cfg : std_vc_cfg_t) return boolean is
  begin
    return std_vc_cfg.fail_on_unexpected_msg_type;
  end;

end package body;
