-- This Source Code Form is subject to the terms of the Mozilla Public
-- License, v. 2.0. If a copy of the MPL was not distributed with this file,
-- You can obtain one at http://mozilla.org/MPL/2.0/.
--
-- Copyright (c) 2014-2019, Lars Asplund lars.anders.asplund@gmail.com

library vunit_lib;
context vunit_lib.vunit_context;
context vunit_lib.com_context;
context vunit_lib.vc_context;

package vc_not_supporting_sync_pkg is
  type vc_not_supporting_sync_handle_t is record
    p_std_vc_cfg : std_vc_cfg_t;
  end record;

  constant vc_not_supporting_sync_logger : logger_t := get_logger("vc_not_supporting_sync");
  constant vc_not_supporting_sync_checker : checker_t := new_checker(vc_not_supporting_sync_logger);

  impure function new_vc_not_supporting_sync(
    logger : logger_t := vc_not_supporting_sync_logger;
    actor : actor_t := null_actor;
    checker : checker_t := null_checker;
    fail_on_unexpected_msg_type : boolean := true
  ) return vc_not_supporting_sync_handle_t;

  impure function as_sync(
    vc_h : vc_not_supporting_sync_handle_t
  ) return sync_handle_t;

end package;

package body vc_not_supporting_sync_pkg is
  impure function new_vc_not_supporting_sync(
    logger : logger_t := vc_not_supporting_sync_logger;
    actor : actor_t := null_actor;
    checker : checker_t := null_checker;
    fail_on_unexpected_msg_type : boolean := true
  ) return vc_not_supporting_sync_handle_t is
    constant p_std_vc_cfg : std_vc_cfg_t := create_std_vc_cfg(
      vc_not_supporting_sync_logger, vc_not_supporting_sync_checker, actor, logger, checker, fail_on_unexpected_msg_type
    );
  begin
    return (p_std_vc_cfg => p_std_vc_cfg);
  end;

  impure function as_sync(
    vc_h : vc_not_supporting_sync_handle_t
  ) return sync_handle_t is
  begin
    return get_actor(vc_h.p_std_vc_cfg);
  end;

end package body;

