-- This Source Code Form is subject to the terms of the Mozilla Public
-- License, v. 2.0. If a copy of the MPL was not distributed with this file,
-- You can obtain one at http://mozilla.org/MPL/2.0/.
--
-- Copyright (c) 2014-2019, Lars Asplund lars.anders.asplund@gmail.com
-- Author Slawomir Siluk slaweksiluk@gazeta.pl
library ieee;
use ieee.std_logic_1164.all;

use work.queue_pkg.all;
use work.logger_pkg.all;
use work.checker_pkg.all;
use work.memory_pkg.all;
use work.sync_pkg.all;
use work.vc_pkg.all;
context work.com_context;

package wishbone_pkg is

  type wishbone_slave_t is record
    ack_high_probability   : real range 0.0 to 1.0;
    stall_high_probability : real range 0.0 to 1.0;
    -- Private
    p_std_vc_cfg           : std_vc_cfg_t;
    p_ack_actor            : actor_t;
    p_memory               : memory_t;
  end record;

  constant wishbone_slave_logger : logger_t := get_logger("vunit_lib:wishbone_slave_pkg");
  constant wishbone_slave_checker : checker_t := new_checker(wishbone_slave_logger);

  impure function new_wishbone_slave(
    memory                      : memory_t;
    ack_high_probability        : real      := 1.0;
    stall_high_probability      : real      := 0.0;
    logger                      : logger_t  := wishbone_slave_logger;
    actor                       : actor_t   := null_actor;
    checker                     : checker_t := null_checker;
    fail_on_unexpected_msg_type : boolean   := true
  ) return wishbone_slave_t;

  impure function as_sync(slave : wishbone_slave_t) return sync_handle_t;

end package;

package body wishbone_pkg is

  impure function new_wishbone_slave(
    memory                      : memory_t;
    ack_high_probability        : real      := 1.0;
    stall_high_probability      : real      := 0.0;
    logger                      : logger_t  := wishbone_slave_logger;
    actor                       : actor_t   := null_actor;
    checker                     : checker_t := null_checker;
    fail_on_unexpected_msg_type : boolean   := true
  ) return wishbone_slave_t is
    constant p_std_vc_cfg : std_vc_cfg_t := create_std_vc_cfg(
      wishbone_slave_logger, wishbone_slave_checker, actor, logger, checker, fail_on_unexpected_msg_type
    );

  begin
    return (p_std_vc_cfg => p_std_vc_cfg,
            p_ack_actor => new_actor,
            p_memory => to_vc_interface(memory, logger),
            ack_high_probability => ack_high_probability,
            stall_high_probability => stall_high_probability
        );
  end;

  impure function as_sync(slave : wishbone_slave_t) return sync_handle_t is
  begin
    return get_actor(slave.p_std_vc_cfg);
  end;

end package body;
